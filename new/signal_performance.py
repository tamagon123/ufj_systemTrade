# -*- coding: utf-8 -*-
"""
signal_performance.py — シグナル後パフォーマンス分析
=====================================================
各シグナル発生後の N 日後騰落率、勝率、期待値、
簡易シャープレシオを算出する。
"""

import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 分析する将来期間（日数）
FORWARD_PERIODS = [1, 3, 5, 10, 20]


def analyze_signal_performance(
    df: pd.DataFrame,
    signals: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    シグナルごとのパフォーマンス統計を算出する。

    Args:
        df: 日足データ (DatetimeIndex, close カラム必須)
        signals: detect_ma_signals / detect_all_patterns の出力リスト

    Returns:
        {
            "ゴールデンクロス (短期/中期)": {
                "count": 5,
                "win_rate_5d": 0.6,
                "avg_return_5d": 0.023,
                "expected_value": 0.15,
                "sharpe_ratio": 0.45,
                "returns": {1: 0.005, 3: 0.012, 5: 0.023, 10: 0.035, 20: 0.041},
            },
            ...
        }
    """
    if df.empty or not signals:
        return {}

    close = df["close"]

    # シグナルを名前でグループ化
    grouped: Dict[str, List[Dict]] = {}
    for sig in signals:
        name = sig["name"]
        if name not in grouped:
            grouped[name] = []
        grouped[name].append(sig)

    results: Dict[str, Dict[str, Any]] = {}

    for name, sig_list in grouped.items():
        # このシグナルの方向性を取得
        sig_type = sig_list[0]["type"]  # bullish or bearish

        all_returns: Dict[int, List[float]] = {p: [] for p in FORWARD_PERIODS}

        for sig in sig_list:
            sig_date = sig["date"]
            if sig_date not in df.index:
                continue

            idx = df.index.get_loc(sig_date)
            if not isinstance(idx, int):
                idx = int(idx) if isinstance(idx, np.integer) else 0
            base_price = close.iloc[idx]
            if base_price <= 0:
                continue

            for period in FORWARD_PERIODS:
                future_idx = idx + period
                if future_idx < len(df):
                    future_price = close.iloc[future_idx]
                    ret = (future_price - base_price) / base_price
                    all_returns[period].append(ret)

        # 最も代表的な期間（5日）をベースに統計計算
        base_period = 5
        returns_5d = all_returns.get(base_period, [])

        if len(returns_5d) < 1:
            continue

        returns_arr = np.array(returns_5d)

        # 勝率: bullish は正のリターン, bearish は負のリターンを「勝ち」とする
        if sig_type == "bullish":
            wins = np.sum(returns_arr > 0)
        else:
            wins = np.sum(returns_arr < 0)
        win_rate = wins / len(returns_arr) if len(returns_arr) > 0 else 0

        # 方向性を考慮したリターン
        directional_returns = returns_arr if sig_type == "bullish" else -returns_arr

        # 平均利益 / 平均損失
        gains = directional_returns[directional_returns > 0]
        losses = directional_returns[directional_returns <= 0]
        avg_gain = float(np.mean(gains)) if len(gains) > 0 else 0.0
        avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0

        # 期待値 = (勝率 × 平均利益) - (敗率 × 平均損失)
        loss_rate = 1 - win_rate
        expected_value = (win_rate * avg_gain) - (loss_rate * avg_loss)

        # 簡易シャープレシオ = 平均リターン / 標準偏差
        mean_ret = float(np.mean(directional_returns))
        std_ret = float(np.std(directional_returns)) if len(directional_returns) > 1 else 1.0
        sharpe = mean_ret / std_ret if std_ret > 0 else 0.0

        # 最大利益/損失
        max_gain = float(np.max(directional_returns)) if len(directional_returns) > 0 else 0.0
        max_loss = float(np.min(directional_returns)) if len(directional_returns) > 0 else 0.0

        # 各期間の平均リターン
        avg_returns = {}
        for period in FORWARD_PERIODS:
            rets = all_returns[period]
            if rets:
                if sig_type == "bullish":
                    avg_returns[period] = float(np.mean(rets))
                else:
                    avg_returns[period] = float(np.mean([-r for r in rets]))
            else:
                avg_returns[period] = None

        results[name] = {
            "count": len(returns_5d),
            "type": sig_type,
            "win_rate": round(win_rate, 3),
            "avg_return_5d": round(float(np.mean(returns_arr)), 4),
            "expected_value": round(expected_value, 4),
            "sharpe_ratio": round(sharpe, 2),
            "max_gain": round(max_gain, 4),
            "max_loss": round(max_loss, 4),
            "avg_gain": round(avg_gain, 4),
            "avg_loss": round(avg_loss, 4),
            "returns": avg_returns,
        }

    return results


def format_performance_text(perf: Dict[str, Any]) -> str:
    """
    パフォーマンス統計を表示用テキストに変換する。

    Args:
        perf: analyze_signal_performance の1シグナル分の結果

    Returns:
        表示用テキスト（例: "勝率62% | 期待値+0.15% | SR 0.45"）
    """
    if not perf:
        return ""

    wr = perf.get("win_rate", 0)
    ev = perf.get("expected_value", 0)
    sr = perf.get("sharpe_ratio", 0)
    count = perf.get("count", 0)
    ret_5d = perf.get("avg_return_5d", 0)

    ev_sign = "+" if ev >= 0 else ""
    ret_sign = "+" if ret_5d >= 0 else ""

    return (
        f"  📈 {count}回発生 | 勝率{wr:.0%} | "
        f"5日後{ret_sign}{ret_5d:.1%} | "
        f"期待値{ev_sign}{ev:.2%} | SR{sr:.2f}"
    )
