# -*- coding: utf-8 -*-
"""
history_fetcher.py — yfinance を使った過去データ一括取得
========================================================
kabuStation API には過去データの取得 API がないため、
yfinance を利用して過去 N 年分の日足 OHLCV を取得し DB に保存する。
"""

import datetime
import logging
import sqlite3
from typing import List, Dict, Any, Optional, Callable

import yfinance as yf
import pandas as pd

from database import upsert_daily

logger = logging.getLogger(__name__)

# yfinance の東証ティッカー末尾
_TSE_SUFFIX = ".T"

# バッチサイズ（yfinance は複数銘柄一括取得可能）
_BATCH_SIZE = 50


def _to_yf_ticker(code: str) -> str:
    """銘柄コード → yfinance ティッカー（例: 7203 → 7203.T）"""
    return f"{code}{_TSE_SUFFIX}"


def fetch_history_single(
    code: str,
    years: int = 2,
) -> pd.DataFrame:
    """
    1銘柄の過去日足データを yfinance から取得する。

    Args:
        code: 銘柄コード（例: "7203"）
        years: 取得期間（年数）

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    ticker = _to_yf_ticker(code)
    end = datetime.date.today()
    start = end - datetime.timedelta(days=years * 365)

    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return pd.DataFrame()

        # カラム名正規化（yfinance は MultiIndex になる場合がある）
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df.index.name = "date"
        return df[["open", "high", "low", "close", "volume"]]

    except Exception as e:
        logger.warning(f"yfinance 取得失敗: {code} → {e}")
        return pd.DataFrame()


def fetch_history_batch(
    symbols: List[Dict[str, str]],
    conn: sqlite3.Connection,
    years: int = 2,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    """
    全銘柄の過去データをバッチ取得し、DB に UPSERT する。

    Args:
        symbols: [{"code": "1301", ...}, ...]
        conn: DB 接続
        years: 取得期間（年数）
        progress_cb: (current_batch, total_batches, status_msg) コールバック

    Returns:
        {"total": N, "success": M, "failed": K, "skipped": S}
    """
    total = len(symbols)
    success = 0
    failed = 0
    skipped = 0

    end = datetime.date.today()
    start = end - datetime.timedelta(days=years * 365)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    # バッチに分割
    batches = []
    for i in range(0, total, _BATCH_SIZE):
        batches.append(symbols[i:i + _BATCH_SIZE])

    total_batches = len(batches)
    logger.info(
        f"過去データ取得開始: {total} 銘柄, {total_batches} バッチ, "
        f"期間={start_str}〜{end_str}"
    )

    for batch_idx, batch in enumerate(batches):
        codes = [s["code"] for s in batch]
        tickers = [_to_yf_ticker(c) for c in codes]
        ticker_str = " ".join(tickers)

        if progress_cb:
            progress_cb(
                batch_idx + 1, total_batches,
                f"バッチ {batch_idx + 1}/{total_batches} ({len(codes)} 銘柄)"
            )

        try:
            # yfinance 一括取得
            data = yf.download(
                ticker_str,
                start=start_str,
                end=end_str,
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
            )

            if data.empty:
                skipped += len(codes)
                continue

            # 各銘柄のデータを抽出して UPSERT
            for code, ticker in zip(codes, tickers):
                try:
                    if len(codes) == 1:
                        # 1銘柄の場合は MultiIndex なし
                        df = data.copy()
                    else:
                        if ticker not in data.columns.get_level_values(0):
                            skipped += 1
                            continue
                        df = data[ticker].copy()

                    # NaN 行を除去
                    df = df.dropna(subset=["Close"] if "Close" in df.columns else ["close"])
                    if df.empty:
                        skipped += 1
                        continue

                    # カラム名正規化
                    df = df.rename(columns={
                        "Open": "open", "High": "high", "Low": "low",
                        "Close": "close", "Volume": "volume",
                    })

                    # OHLCV レコードに変換
                    records = []
                    for date_idx, row in df.iterrows():
                        date_str = pd.Timestamp(date_idx).strftime("%Y-%m-%d")
                        records.append({
                            "symbol": code,
                            "date": date_str,
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": int(row.get("volume", 0)),
                        })

                    if records:
                        upsert_daily(conn, records)
                        success += 1
                    else:
                        skipped += 1

                except Exception as e:
                    failed += 1
                    logger.warning(f"変換/保存失敗: {code} → {e}")

        except Exception as e:
            failed += len(codes)
            logger.error(f"バッチ取得失敗: {e}")

        logger.info(
            f"過去データ進捗: バッチ {batch_idx + 1}/{total_batches} 完了 "
            f"(成功={success}, スキップ={skipped}, 失敗={failed})"
        )

    result = {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "period": f"{start_str}〜{end_str}",
    }
    logger.info(f"過去データ取得完了: {result}")
    return result
