# -*- coding: utf-8 -*-
"""
candlestick.py — ローソク足パターン検知
=========================================
包み足、はらみ足、カラカサ、明けの明星、赤三兵、
流星、宵の明星、黒三兵、三羽烏、出来高急増、窓開け、
十字線、たくり線、首吊り線、窓埋め、三空、ピンバー、
下放れ二本立ち、トウバ、リバーサル・デーを
コンテキストフィルタ付きで自動検出する。（合計24種）
"""

from typing import List, Dict, Any
import pandas as pd
import numpy as np


# ══════════════════════════════════════════════════════════════════════════════
# ユーティリティ
# ══════════════════════════════════════════════════════════════════════════════
def _body(row) -> float:
    """実体の長さ（符号付き: 正=陽線, 負=陰線）"""
    return row["close"] - row["open"]


def _body_abs(row) -> float:
    return abs(_body(row))


def _upper_shadow(row) -> float:
    return row["high"] - max(row["open"], row["close"])


def _lower_shadow(row) -> float:
    return min(row["open"], row["close"]) - row["low"]


def _is_bullish(row) -> bool:
    return row["close"] > row["open"]


def _is_bearish(row) -> bool:
    return row["close"] < row["open"]


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


def _trend_direction(df: pd.DataFrame, idx: int, lookback: int = 10) -> str:
    """直近 lookback 日間のトレンド方向 → "up" / "down" / "sideways" """
    if idx < lookback:
        return "sideways"
    closes = df["close"].iloc[idx - lookback:idx].values
    if len(closes) < 2:
        return "sideways"
    slope = np.polyfit(range(len(closes)), closes, 1)[0]
    avg_price = np.mean(closes)
    if avg_price == 0:
        return "sideways"
    normalized_slope = slope / avg_price * 100  # %/day
    if normalized_slope > 0.1:
        return "up"
    elif normalized_slope < -0.1:
        return "down"
    return "sideways"


# ══════════════════════════════════════════════════════════════════════════════
# パターン検出
# ══════════════════════════════════════════════════════════════════════════════
def detect_all_patterns(
    df: pd.DataFrame,
    timeframe: str = "daily",
) -> List[Dict[str, Any]]:
    """
    全ローソク足パターンを一括検出する。
    df: DatetimeIndex, open/high/low/close/volume カラム必須。
    """
    signals: List[Dict[str, Any]] = []
    if len(df) < 4:
        return signals

    atr = _atr(df)
    vol_ma20 = df["volume"].rolling(20, min_periods=1).mean()

    for i in range(2, len(df)):
        date = df.index[i]
        r0 = df.iloc[i]       # 当日
        r1 = df.iloc[i - 1]   # 前日
        r2 = df.iloc[i - 2]   # 2日前

        body0 = _body(r0)
        body1 = _body(r1)
        ba0 = _body_abs(r0)
        ba1 = _body_abs(r1)
        ba2 = _body_abs(r2)
        us0 = _upper_shadow(r0)
        ls0 = _lower_shadow(r0)
        us1 = _upper_shadow(r1)
        ls1 = _lower_shadow(r1)
        atr_val = atr.iloc[i] if not pd.isna(atr.iloc[i]) else 1.0
        trend = _trend_direction(df, i)

        # ===== 良いシグナル =====

        # 1. 包み足（陽の包み線） — 下落トレンドの底値圏
        if (_is_bearish(r1) and _is_bullish(r0)
                and r0["open"] < r1["close"] and r0["close"] > r1["open"]
                and trend == "down"):
            signals.append({
                "name": "包み足（陽線）",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "前日陰線を当日陽線が完全に包み込み — 強気反転",
            })

        # 2. はらみ足（陰の陽はらみ）
        if (_is_bearish(r1) and ba1 > atr_val * 0.5
                and _is_bullish(r0) and ba0 < ba1 * 0.5
                and r0["open"] > r1["close"] and r0["close"] < r1["open"]
                and trend == "down"):
            signals.append({
                "name": "はらみ足（陽はらみ）",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "大陰線の実体内に小陽線が収まる — 売り圧力枯渇",
            })

        # 3. カラカサ / ハンマー
        if (ba0 > 0 and ls0 >= ba0 * 2 and us0 < ba0 * 0.3
                and trend == "down"):
            signals.append({
                "name": "カラカサ / ハンマー",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "長い下ヒゲ＋小実体 — 底打ちシグナル",
            })

        # 4. 明けの明星 (Morning Star)
        if (i >= 2
                and _is_bearish(r2) and ba2 > atr_val * 0.5
                and ba1 < atr_val * 0.3
                and _is_bullish(r0) and ba0 > atr_val * 0.5
                and r0["close"] > (r2["open"] + r2["close"]) / 2
                and trend == "down"):
            signals.append({
                "name": "明けの明星",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "大陰線→小実体→大陽線 — 劇的な強気反転",
            })

        # 5. 赤三兵 (Three White Soldiers)
        if (i >= 2
                and _is_bullish(r2) and _is_bullish(r1) and _is_bullish(r0)
                and r1["open"] >= r2["open"] and r1["open"] <= r2["close"]
                and r0["open"] >= r1["open"] and r0["open"] <= r1["close"]
                and r0["close"] > r1["close"] > r2["close"]
                and us0 < ba0 * 0.3 and us1 < ba1 * 0.3):
            signals.append({
                "name": "赤三兵",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "3日連続の陽線（短いヒゲ）— 強力な上昇トレンド",
            })

        # 6. 出来高急増（陽線）
        if (r0["volume"] >= vol_ma20.iloc[i] * 2
                and _is_bullish(r0) and ba0 > atr_val * 0.3):
            signals.append({
                "name": "出来高急増（陽線）",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": f"出来高が20日平均の{r0['volume']/vol_ma20.iloc[i]:.1f}倍（陽線）— 買い集め",
            })

        # 7. 窓開け上昇（ギャップアップ）
        if r0["low"] > r1["high"]:
            gap = (r0["low"] - r1["high"]) / r1["close"] * 100
            if gap > 0.5:  # 0.5%以上のギャップ
                signals.append({
                    "name": "窓開け上昇（ギャップアップ）",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"前日高値を上回る位置から寄付き（ギャップ +{gap:.1f}%）",
                })

        # 8. たくり線
        if (trend == "down"
                and ls0 >= atr_val * 1.5
                and ba0 < atr_val * 0.3
                and us0 < ba0 * 0.5 if ba0 > 0 else us0 < atr_val * 0.1):
            signals.append({
                "name": "たくり線",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "下落トレンドで非常に長い下ヒゲ＋極小実体 — 反転示唆",
            })

        # 9. 三空叩き込み
        if (i >= 3 and trend == "down"):
            r3 = df.iloc[i - 3]
            if (r3["low"] > r2["high"]  # 窓1: r3→r2
                    and r2["low"] > r1["high"]  # 窓2: r2→r1
                    and r1["low"] > r0["high"]  # 窓3: r1→r0
                    and _is_bearish(r2) and _is_bearish(r1)):
                signals.append({
                    "name": "三空叩き込み",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "3連続の窓開け下落 — 売り枯渇で底打ち示唆",
                })

        # 10. ピンバー (強気) — 下ヒゲが実体の3倍以上
        if (ba0 > 0 and ls0 >= ba0 * 3 and us0 < ba0 * 0.5
                and trend != "up"):
            signals.append({
                "name": "ピンバー（反転・買い）",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "極めて長い下ヒゲ — 強力な買い支え・反転シグナル",
            })

        # 11. リバーサル・デー（外側日・強気）
        if (r0["high"] > r1["high"] and r0["low"] < r1["low"]
                and _is_bullish(r0) and _is_bearish(r1)
                and trend == "down"):
            signals.append({
                "name": "リバーサル・デー（強気）",
                "type": "bullish",
                "timeframe": timeframe,
                "date": date,
                "detail": "前日の高安を包み込み陽線引け — 外側日反転",
            })

        # ===== 悪いシグナル =====

        # 12. 包み足（陰の包み線） — 上昇トレンドの天井圏
        if (_is_bullish(r1) and _is_bearish(r0)
                and r0["open"] > r1["close"] and r0["close"] < r1["open"]
                and trend == "up"):
            signals.append({
                "name": "包み足（陰線）",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "前日陽線を当日陰線が完全に飲み込み — 弱気反転",
            })

        # 13. 流星
        if (ba0 > 0 and us0 >= ba0 * 2 and ls0 < ba0 * 0.3
                and trend == "up"):
            signals.append({
                "name": "流星",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "長い上ヒゲ＋小実体 — 天井打ちシグナル",
            })

        # 14. 宵の明星 (Evening Star)
        if (i >= 2
                and _is_bullish(r2) and ba2 > atr_val * 0.5
                and ba1 < atr_val * 0.3
                and _is_bearish(r0) and ba0 > atr_val * 0.5
                and r0["close"] < (r2["open"] + r2["close"]) / 2
                and trend == "up"):
            signals.append({
                "name": "宵の明星",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "大陽線→小実体→大陰線 — 弱気反転パターン",
            })

        # 15. 黒三兵 (Three Black Crows)
        if (i >= 2
                and _is_bearish(r2) and _is_bearish(r1) and _is_bearish(r0)
                and r1["open"] <= r2["open"] and r1["open"] >= r2["close"]
                and r0["open"] <= r1["open"] and r0["open"] >= r1["close"]
                and r0["close"] < r1["close"] < r2["close"]
                and ls0 < _body_abs(r0) * 0.3 and ls1 < _body_abs(r1) * 0.3):
            signals.append({
                "name": "黒三兵",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "3日連続の大陰線 — 急落トレンドの継続",
            })

        # 16. 三羽烏 / 高値圏の小実体群
        if (i >= 3 and trend == "up"):
            last3 = df.iloc[i - 2:i + 1]
            if all(_body_abs(last3.iloc[j]) < atr_val * 0.3 for j in range(3)):
                highs = [last3.iloc[j]["high"] for j in range(3)]
                if highs[0] >= highs[1] >= highs[2]:
                    signals.append({
                        "name": "三羽烏（小実体群）",
                        "type": "bearish",
                        "timeframe": timeframe,
                        "date": date,
                        "detail": "高値圏で小実体が滞留＋上値切り下げ — 買い枯渇",
                    })

        # 17. 出来高急増（陰線）
        if (r0["volume"] >= vol_ma20.iloc[i] * 2
                and _is_bearish(r0) and ba0 > atr_val * 0.3):
            signals.append({
                "name": "出来高急増（陰線）",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": f"出来高が20日平均の{r0['volume']/vol_ma20.iloc[i]:.1f}倍（陰線）— 投げ売り",
            })

        # 18. 窓開け下落（ギャップダウン）
        if r0["high"] < r1["low"]:
            gap = (r1["low"] - r0["high"]) / r1["close"] * 100
            if gap > 0.5:
                signals.append({
                    "name": "窓開け下落（ギャップダウン）",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"前日安値を下回る位置から寄付き（ギャップ -{gap:.1f}%）",
                })

        # 19. 十字線（転換暗示）
        if ba0 < atr_val * 0.05 and (us0 + ls0) > atr_val * 0.3:
            sig_type = "bearish" if trend == "up" else "bullish" if trend == "down" else None
            if sig_type:
                signals.append({
                    "name": f"十字線（{'天井' if sig_type == 'bearish' else '底値'}圏）",
                    "type": sig_type,
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"始値≒終値、長いヒゲ — {trend}トレンドの転換を暗示",
                })

        # 20. 首吊り線
        if (trend == "up"
                and ls0 >= atr_val * 1.5
                and ba0 < atr_val * 0.3
                and us0 < ba0 * 0.5 if ba0 > 0 else us0 < atr_val * 0.1):
            signals.append({
                "name": "首吊り線",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "上昇トレンドで長い下ヒゲ＋極小実体 — 天井示唆",
            })

        # 21. 窓埋め（上昇ギャップ後の反落）
        if (i >= 3 and r1["low"] > r2["high"]):  # r1-r2 間にギャップあり
            if r0["low"] < r2["high"]:  # 当日の安値がギャップを埋める
                signals.append({
                    "name": "窓埋め（上昇後）",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "上昇ギャップが埋められた — 上昇の否定・戻り売り",
                })

        # 22. 三空踏み上げ
        if (i >= 3 and trend == "up"):
            r3 = df.iloc[i - 3]
            if (r2["low"] > r3["high"]  # 窓1
                    and r1["low"] > r2["high"]  # 窓2
                    and r0["low"] > r1["high"]  # 窓3
                    and _is_bullish(r2) and _is_bullish(r1)):
                signals.append({
                    "name": "三空踏み上げ",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "3連続の窓開け上昇 — 買い過熱で天井示唆",
                })

        # 23. ピンバー (弱気) — 上ヒゲが実体の3倍以上
        if (ba0 > 0 and us0 >= ba0 * 3 and ls0 < ba0 * 0.5
                and trend != "down"):
            signals.append({
                "name": "ピンバー（反転・売り）",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "極めて長い上ヒゲ — 強力な売り圧力・天井シグナル",
            })

        # 24. 下放れ二本立ち
        if (i >= 2 and trend == "down"):
            if (r1["high"] < r2["low"]  # r2→r1 間にギャップ
                    and _is_bearish(r1) and _is_bearish(r0)
                    and abs(r0["close"] - r1["close"]) < atr_val * 0.2):
                signals.append({
                    "name": "下放れ二本立ち",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "窓開け後に陰線が2本並ぶ — 売り加速",
                })

        # 25. トウバ（墓石）
        if (trend == "up"
                and us0 >= atr_val * 1.0
                and ba0 < atr_val * 0.05
                and ls0 < atr_val * 0.05):
            signals.append({
                "name": "トウバ（墓石十字線）",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "始値＝終値＝安値、長い上ヒゲ — 上昇否定の天井パターン",
            })

        # 26. リバーサル・デー（外側日・弱気）
        if (r0["high"] > r1["high"] and r0["low"] < r1["low"]
                and _is_bearish(r0) and _is_bullish(r1)
                and trend == "up"):
            signals.append({
                "name": "リバーサル・デー（弱気）",
                "type": "bearish",
                "timeframe": timeframe,
                "date": date,
                "detail": "前日の高安を包み込み陰線引け — 外側日反転",
            })

    return signals
