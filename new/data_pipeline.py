# -*- coding: utf-8 -*-
"""
data_pipeline.py — データ取得パイプライン
==========================================
全銘柄の日足データを kabuStation API から取得し、DB に UPSERT する。
実行時刻 (Texec) に応じたデータ範囲決定ロジックを実装。
"""

import datetime
import logging
import sqlite3
from typing import List, Dict, Any, Optional, Tuple

from config import MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE
from kabu_api import get_board, extract_ohlcv, unregister_all, kabus_get_token
from database import upsert_daily, load_universe_csv

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 営業日判定ユーティリティ
# ══════════════════════════════════════════════════════════════════════════════
def _is_business_day(dt: datetime.date) -> bool:
    """簡易営業日判定（土日を除外）。祝日は考慮しない。"""
    return dt.weekday() < 5  # 0=月 ~ 4=金


def _prev_business_day(dt: datetime.date) -> datetime.date:
    """直前の営業日を返す"""
    d = dt - datetime.timedelta(days=1)
    while not _is_business_day(d):
        d -= datetime.timedelta(days=1)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# 実行時刻に基づくデータ対象日の決定
# ══════════════════════════════════════════════════════════════════════════════
def determine_target_date(
    now: Optional[datetime.datetime] = None,
) -> str:
    """
    実行時刻 Texec に応じてデータ取得対象の最終日を決定する。
    - 15:00 以降 → 当日分まで（終値確定）
    - 15:00 前  → 直前営業日まで
    返り値: "YYYY-MM-DD" 形式の文字列
    """
    if now is None:
        now = datetime.datetime.now()
    today = now.date()

    if now.hour >= MARKET_CLOSE_HOUR and now.minute >= MARKET_CLOSE_MINUTE:
        # 大引け後 → 当日が営業日なら当日、そうでなければ直前営業日
        if _is_business_day(today):
            target = today
        else:
            target = _prev_business_day(today)
    else:
        # 取引時間中 or 市場開始前 → 直前営業日
        target = _prev_business_day(today)

    return target.strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════════════
# 日次データ更新バッチ
# ══════════════════════════════════════════════════════════════════════════════
def run_daily_update(
    conn: sqlite3.Connection,
    token: str,
    symbols: Optional[List[Dict[str, str]]] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    全銘柄（or 指定銘柄）の板情報を取得し、DB に UPSERT する。

    Args:
        conn: DB 接続
        token: kabuStation API トークン
        symbols: [{"code": "1301", ...}, ...] 省略時は universe テーブルから取得
        progress_callback: (current, total, symbol) を受け取るコールバック

    Returns:
        {"total": N, "success": M, "failed": K, "skipped": S}
    """
    if symbols is None:
        symbols = load_universe_csv(conn)

    target_date = determine_target_date()
    total = len(symbols)
    success = 0
    failed = 0
    skipped = 0
    token_refreshed = 0
    records_buffer: List[Dict[str, Any]] = []
    register_count = 0          # board 呼び出しカウント（登録数管理）
    REGISTER_LIMIT = 40         # 50 件上限の手前で解除

    logger.info(f"日次データ更新開始: {total} 銘柄, 対象日={target_date}")

    # 開始前に全銘柄登録解除
    unregister_all(token)

    for i, sym in enumerate(symbols):
        code = sym["code"]
        try:
            # 登録数が上限に近づいたら全解除
            if register_count >= REGISTER_LIMIT:
                unregister_all(token)
                register_count = 0

            board = get_board(code, token)
            register_count += 1

            # 401 エラー（トークン無効化）→ トークン再取得してリトライ
            if isinstance(board, dict) and board.get("_status") == 401:
                logger.warning(f"トークン無効化検出 ({code}) → トークン再取得")
                try:
                    token = kabus_get_token()
                    token_refreshed += 1
                    unregister_all(token)
                    register_count = 0
                    board = get_board(code, token)
                    register_count += 1
                except Exception as te:
                    logger.error(f"トークン再取得失敗: {te}")
                    failed += 1
                    continue

            if not board or board.get("_status"):
                skipped += 1
                logger.debug(f"スキップ（データ無し）: {code}")
                continue

            record = extract_ohlcv(board, code, target_date)
            if record is None:
                skipped += 1
                continue

            records_buffer.append(record)
            success += 1

            # バルクUPSERT
            if len(records_buffer) >= 100:
                upsert_daily(conn, records_buffer)
                records_buffer.clear()

        except Exception as e:
            failed += 1
            logger.error(f"取得失敗: {code} → {e}")

        # 進捗ログ（100件ごと）
        if (i + 1) % 100 == 0 or (i + 1) == total:
            logger.info(
                f"進捗: {i + 1}/{total} "
                f"(成功={success}, スキップ={skipped}, 失敗={failed})"
            )

        if progress_callback:
            progress_callback(i + 1, total, code)

    # 残りを書き込み
    if records_buffer:
        upsert_daily(conn, records_buffer)

    result = {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "token_refreshed": token_refreshed,
        "target_date": target_date,
    }
    logger.info(f"日次データ更新完了: {result}")
    return result

