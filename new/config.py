# -*- coding: utf-8 -*-
"""
config.py — システム設定・定数定義
==================================
環境変数（new/.env）から API 接続情報を読み込み、
移動平均線パラメータ・レートリミット・DB パスなどの定数を一元管理する。
"""

import os
import sys

# ---------------------------------------------------------------------------
# ベースディレクトリ（new/ フォルダ自体）
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# .env 読み込み（簡易パーサー — python-dotenv 不要）
# ---------------------------------------------------------------------------
def _load_dotenv(path: str = ".env"):
    """KEY=VALUE 形式の .env ファイルを os.environ に読み込む"""
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key:
                os.environ.setdefault(key, value)

_load_dotenv(os.path.join(BASE_DIR, ".env"))

# ---------------------------------------------------------------------------
# kabuStation API 接続設定
# ---------------------------------------------------------------------------
KABUS_API_BASE_URL = os.environ.get("KABUS_API_BASE_URL", "http://localhost:18080")
KABUS_API_PASSWORD = os.environ.get("KABUS_API_PASSWORD", "")
KABUS_EXCHANGE     = int(os.environ.get("KABUS_EXCHANGE", "1"))   # 1=東証
REQUEST_TIMEOUT    = int(os.environ.get("REQUEST_TIMEOUT", "10"))  # 秒

# ---------------------------------------------------------------------------
# レートリミット
# ---------------------------------------------------------------------------
RATE_LIMIT_PER_SEC = int(os.environ.get("RATE_LIMIT_PER_SEC", "5"))
MAX_RETRIES        = int(os.environ.get("MAX_RETRIES", "3"))

# ---------------------------------------------------------------------------
# データベース
# ---------------------------------------------------------------------------
DB_PATH = os.path.join(BASE_DIR, "market_data.db")
BULK_INSERT_SIZE = 100   # バルクUPSERT ごとの件数

# ---------------------------------------------------------------------------
# 銘柄マスターCSV
# ---------------------------------------------------------------------------
UNIVERSE_CSV_PATH = os.path.join(BASE_DIR, "data_j.csv")

# ---------------------------------------------------------------------------
# 移動平均線パラメータ（デフォルト値）
# ---------------------------------------------------------------------------
MA_PARAMS = {
    "daily": {
        "short":  int(os.environ.get("MA_DAILY_SHORT",  "5")),
        "medium": int(os.environ.get("MA_DAILY_MEDIUM", "25")),
        "long":   int(os.environ.get("MA_DAILY_LONG",   "75")),
    },
    "weekly": {
        "short":  int(os.environ.get("MA_WEEKLY_SHORT",  "13")),
        "medium": int(os.environ.get("MA_WEEKLY_MEDIUM", "26")),
        "long":   int(os.environ.get("MA_WEEKLY_LONG",   "52")),
    },
    "monthly": {
        "short":  int(os.environ.get("MA_MONTHLY_SHORT",  "6")),
        "medium": int(os.environ.get("MA_MONTHLY_MEDIUM", "12")),
        "long":   int(os.environ.get("MA_MONTHLY_LONG",   "24")),
    },
}

# ---------------------------------------------------------------------------
# 取引時間
# ---------------------------------------------------------------------------
MARKET_CLOSE_HOUR   = 15   # 大引け 15:00
MARKET_CLOSE_MINUTE = 0

# ---------------------------------------------------------------------------
# 価格帯別出来高
# ---------------------------------------------------------------------------
VOLUME_PROFILE_BINS = int(os.environ.get("VOLUME_PROFILE_BINS", "50"))

# ---------------------------------------------------------------------------
# ログ
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
