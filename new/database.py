# -*- coding: utf-8 -*-
"""
database.py — SQLite データベース管理
=====================================
daily_ohlcv テーブルの作成、UPSERT、バルクインサート、
銘柄マスター CSV の読み込みを行う。
"""

import csv
import sqlite3
import logging
from typing import List, Dict, Any, Optional

import pandas as pd

from config import DB_PATH, UNIVERSE_CSV_PATH, BULK_INSERT_SIZE

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# DB 初期化
# ══════════════════════════════════════════════════════════════════════════════
_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS daily_ohlcv (
    symbol   TEXT    NOT NULL,
    date     TEXT    NOT NULL,
    open     REAL    NOT NULL,
    high     REAL    NOT NULL,
    low      REAL    NOT NULL,
    close    REAL    NOT NULL,
    volume   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS universe (
    code        TEXT    PRIMARY KEY,
    name        TEXT    NOT NULL DEFAULT '',
    market      TEXT    NOT NULL DEFAULT '',
    sector_33   TEXT    NOT NULL DEFAULT '',
    sector_17   TEXT    NOT NULL DEFAULT '',
    scale       TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol ON daily_ohlcv(symbol);
CREATE INDEX IF NOT EXISTS idx_ohlcv_date   ON daily_ohlcv(date);
"""


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    """DB を初期化し、接続を返す"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_CREATE_TABLES_SQL)
    conn.commit()
    logger.info(f"DB初期化完了: {db_path}")
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# UPSERT（バルク）
# ══════════════════════════════════════════════════════════════════════════════
_UPSERT_SQL = """
INSERT INTO daily_ohlcv (symbol, date, open, high, low, close, volume)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(symbol, date) DO UPDATE SET
    open   = excluded.open,
    high   = excluded.high,
    low    = excluded.low,
    close  = excluded.close,
    volume = excluded.volume
"""


def upsert_daily(conn: sqlite3.Connection, records: List[Dict[str, Any]]):
    """
    OHLCV レコードのリストを UPSERT する。
    BULK_INSERT_SIZE 件ごとにコミットする。
    """
    if not records:
        return
    cursor = conn.cursor()
    for i in range(0, len(records), BULK_INSERT_SIZE):
        batch = records[i:i + BULK_INSERT_SIZE]
        rows = [
            (r["symbol"], r["date"],
             r["open"], r["high"], r["low"], r["close"], r["volume"])
            for r in batch
        ]
        cursor.executemany(_UPSERT_SQL, rows)
        conn.commit()
    logger.info(f"UPSERT完了: {len(records)} 件")


# ══════════════════════════════════════════════════════════════════════════════
# データ取得
# ══════════════════════════════════════════════════════════════════════════════
def get_daily(
    conn: sqlite3.Connection,
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """指定銘柄の日足データを DataFrame で返す"""
    query = "SELECT date, open, high, low, close, volume FROM daily_ohlcv WHERE symbol = ?"
    params: list = [symbol]
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date"
    df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    return df


def get_all_symbols(conn: sqlite3.Connection) -> List[str]:
    """DB に登録済みの全銘柄コードを返す"""
    cursor = conn.execute("SELECT DISTINCT symbol FROM daily_ohlcv ORDER BY symbol")
    return [row[0] for row in cursor.fetchall()]


# ══════════════════════════════════════════════════════════════════════════════
# 銘柄マスター CSV 読み込み
# ══════════════════════════════════════════════════════════════════════════════
def load_universe_csv(
    conn: sqlite3.Connection,
    csv_path: str = UNIVERSE_CSV_PATH,
) -> List[Dict[str, str]]:
    """
    data_j.csv を読み込み、universe テーブルに登録する。
    CSV カラム: 日付,コード,銘柄名,市場・商品区分,33業種コード,33業種区分,
                17業種コード,17業種区分,規模コード,規模区分
    ETF・ETN・PRO Market は除外し、内国株式のみを対象とする。
    返り値: [{"code": "1301", "name": "極洋", "market": "プライム", ...}, ...]
    """
    symbols = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            market = row.get("市場・商品区分", "")
            # ETF/ETN、PRO Market は除外（内国株式のみ対象）
            if "ETF" in market or "ETN" in market or "PRO" in market:
                continue
            code = row.get("コード", "").strip()
            name = row.get("銘柄名", "").strip()
            sector_33 = row.get("33業種区分", "").strip()
            sector_17 = row.get("17業種区分", "").strip()
            scale = row.get("規模区分", "").strip()
            if not code:
                continue
            symbols.append({
                "code": code,
                "name": name,
                "market": market,
                "sector_33": sector_33,
                "sector_17": sector_17,
                "scale": scale,
            })

    # DB に UPSERT
    cursor = conn.cursor()
    upsert_sql = """
    INSERT INTO universe (code, name, market, sector_33, sector_17, scale)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(code) DO UPDATE SET
        name      = excluded.name,
        market    = excluded.market,
        sector_33 = excluded.sector_33,
        sector_17 = excluded.sector_17,
        scale     = excluded.scale
    """
    rows = [(s["code"], s["name"], s["market"], s["sector_33"], s["sector_17"], s["scale"])
            for s in symbols]
    cursor.executemany(upsert_sql, rows)
    conn.commit()
    logger.info(f"銘柄マスター読み込み完了: {len(symbols)} 銘柄")
    return symbols


def get_universe(conn: sqlite3.Connection) -> pd.DataFrame:
    """universe テーブルの全件を DataFrame で返す"""
    return pd.read_sql_query("SELECT * FROM universe ORDER BY code", conn)
