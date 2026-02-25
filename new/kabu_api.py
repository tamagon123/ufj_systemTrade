# -*- coding: utf-8 -*-
"""
kabu_api.py — kabuStation API ラッパー
======================================
トークン取得、レートリミット、指数バックオフ付きリトライ、
板情報（4 本値）取得を提供する。
"""

import json
import time
import logging
import threading
from typing import Optional, Tuple, Dict, Any, List

import requests

from config import (
    KABUS_API_BASE_URL,
    KABUS_API_PASSWORD,
    KABUS_EXCHANGE,
    REQUEST_TIMEOUT,
    RATE_LIMIT_PER_SEC,
    MAX_RETRIES,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# レートリミッタ（トークンバケット）
# ══════════════════════════════════════════════════════════════════════════════
class RateLimiter:
    """秒間 N 件のリクエストに制限するトークンバケット"""

    def __init__(self, max_per_second: int = RATE_LIMIT_PER_SEC):
        self.max_per_second = max_per_second
        self.timestamps: List[float] = []
        self._lock = threading.Lock()

    def wait(self):
        """必要に応じてスリープし、レートを遵守する"""
        with self._lock:
            now = time.time()
            # 1 秒以上前のタイムスタンプを除去
            self.timestamps = [t for t in self.timestamps if now - t < 1.0]
            if len(self.timestamps) >= self.max_per_second:
                sleep_time = 1.0 - (now - self.timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self.timestamps.append(time.time())


_rate_limiter = RateLimiter()

# ══════════════════════════════════════════════════════════════════════════════
# 汎用 API リクエスト
# ══════════════════════════════════════════════════════════════════════════════
def kabus_api_request(
    method: str,
    path: str,
    token: Optional[str] = None,
    body: Optional[Dict[str, Any]] = None,
    rate_limit: bool = True,
) -> Tuple[int, Any]:
    """kabuStation REST API 汎用ラッパー（リトライ付き）"""
    url = f"{KABUS_API_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-KEY"] = token

    for attempt in range(1, MAX_RETRIES + 1):
        if rate_limit:
            _rate_limiter.wait()
        try:
            if method.upper() in {"POST", "PUT"}:
                resp = requests.request(
                    method.upper(), url, headers=headers,
                    data=json.dumps(body or {}),
                    timeout=REQUEST_TIMEOUT,
                )
            else:
                resp = requests.request(
                    method.upper(), url, headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
            try:
                payload = resp.json() if resp.text else {}
            except Exception:
                payload = {"raw": resp.text}
            if resp.status_code == 200:
                return resp.status_code, payload
            # 4xx（認証エラー等）はリトライしない
            if 400 <= resp.status_code < 500:
                logger.warning(f"API {resp.status_code}: {method} {path} → {payload}")
                return resp.status_code, payload
            # 5xx → リトライ
            logger.warning(
                f"API {resp.status_code} (attempt {attempt}/{MAX_RETRIES}): "
                f"{method} {path}"
            )
        except Exception as e:
            logger.error(
                f"API error (attempt {attempt}/{MAX_RETRIES}): "
                f"{method} {path} → {e}"
            )
            payload = {"error": str(e)}

        # 指数バックオフ
        if attempt < MAX_RETRIES:
            backoff = 2 ** (attempt - 1)
            time.sleep(backoff)

    return 0, payload


# ══════════════════════════════════════════════════════════════════════════════
# トークン取得
# ══════════════════════════════════════════════════════════════════════════════
def kabus_get_token() -> str:
    """APIトークンを取得する"""
    if not KABUS_API_PASSWORD:
        raise RuntimeError("KABUS_API_PASSWORD が設定されていません")
    status, payload = kabus_api_request(
        "POST", "/kabusapi/token",
        body={"APIPassword": KABUS_API_PASSWORD},
        rate_limit=False,
    )
    if status != 200:
        raise RuntimeError(f"トークン取得失敗: {status} {payload}")
    token = payload.get("Token") or payload.get("token")
    if not token:
        raise RuntimeError(f"トークンがレスポンスに含まれていません: {payload}")
    logger.info("APIトークン取得成功")
    return token


# ══════════════════════════════════════════════════════════════════════════════
# 板情報（4 本値）取得
# ══════════════════════════════════════════════════════════════════════════════
def get_board(symbol: str, token: str, exchange: int = KABUS_EXCHANGE) -> Dict[str, Any]:
    """
    板情報を取得し、OHLCV を含む辞書を返す。
    取得できない場合は空辞書を返す。
    401 エラー時は {"_status": 401} を返し、呼び出し側でトークン再取得可能にする。
    """
    path = f"/kabusapi/board/{symbol}@{exchange}"
    status, data = kabus_api_request("GET", path, token=token)
    if status == 401:
        return {"_status": 401}
    if status != 200 or not data:
        return {}
    return data


def get_symbol_info(symbol: str, token: str, exchange: int = KABUS_EXCHANGE) -> Dict[str, Any]:
    """銘柄情報を取得する"""
    path = f"/kabusapi/symbol/{symbol}@{exchange}"
    status, data = kabus_api_request("GET", path, token=token)
    if status != 200:
        return {}
    return data


def unregister_all(token: str) -> bool:
    """
    全銘柄の登録を解除する。
    /board/ は自動的にシンボルを Push 配信対象に登録するため、
    上限（50件）に達する前に解除が必要。
    """
    status, data = kabus_api_request(
        "PUT", "/kabusapi/unregister/all",
        token=token, rate_limit=False,
    )
    if status == 200:
        logger.debug("全銘柄登録解除完了")
        return True
    logger.warning(f"登録解除失敗: {status} {data}")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 4 本値抽出ユーティリティ
# ══════════════════════════════════════════════════════════════════════════════
def extract_ohlcv(board: Dict[str, Any], symbol: str, date_str: str) -> Optional[Dict[str, Any]]:
    """
    board レスポンスから日足 OHLCV レコードを抽出する。
    必要なフィールドが揃わない場合は None を返す。
    """
    try:
        o = board.get("OpeningPrice", 0)
        h = board.get("HighPrice", 0)
        l = board.get("LowPrice", 0)
        c = board.get("CurrentPrice") or board.get("PreviousClose", 0)
        v = board.get("TradingVolume", 0)
        # 0 の場合は取得不可
        if not all([o, h, l, c]):
            return None
        return {
            "symbol": symbol,
            "date": date_str,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": int(v),
        }
    except Exception as e:
        logger.error(f"extract_ohlcv error: {symbol} → {e}")
        return None
