"""
HFT_main.py — 高頻度取引（HFT）システム
=========================================
KabuステーションAPI + WebSocket + asyncio による
低遅延アルゴリズム取引エンジン＋tkinter GUI

設計書: KabuステーションAPI HFTツール開発.txt
"""

import asyncio
import json
import os
import sys
import time
import csv
import statistics
import threading
import queue
import logging
import traceback
import requests
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

# ---------------------------------------------------------------------------
# .env 読み込み（main.py と同じパターン）
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))


def _load_dotenv(path: str = ".env") -> None:
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                key, val = k.strip(), v.strip()
                if not key:
                    continue
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                os.environ.setdefault(key, val)
    except Exception:
        return


_load_dotenv(os.path.join(_BASE_DIR, ".env"))

# ---------------------------------------------------------------------------
# 定数 / 設定
# ---------------------------------------------------------------------------
JST = timezone(timedelta(hours=9))

KABUS_API_BASE_URL = os.environ.get("KABUS_API_BASE_URL", "http://localhost:18080")
KABUS_API_PASSWORD = (os.environ.get("KABUS_API_PASSWORD") or "").strip()
KABUS_EXCHANGE = int(os.environ.get("KABUS_EXCHANGE", "1"))
REQUEST_TIMEOUT_SECONDS = 10

# WebSocket URL（KabuステーションAPIの仕様）
WS_URL = f"ws://localhost:{KABUS_API_BASE_URL.split(':')[-1]}/kabusapi/websocket"
# localhost:18080 → ポート 18080
_api_port = KABUS_API_BASE_URL.rstrip("/").split(":")[-1]
WS_URL = f"ws://localhost:{_api_port}/kabusapi/websocket"

# HFT ログディレクトリ
HFT_LOG_DIR = os.path.join(_BASE_DIR, "HFT")

# スロットル制御（秒間5件の制限 → 安全マージンで4件）
MAX_ORDERS_PER_SECOND = 4

# OBI 履歴保持ティック数
OBI_HISTORY_SIZE = 50

# デフォルト設定値（GUIで変更可能）
DEFAULT_ENTRY_SIGMA = 2.5
DEFAULT_EXIT_SIGMA = 2.0
DEFAULT_TIME_DECAY = 30.0

# 最小OBI履歴（判定開始に必要なティック数）
MIN_OBI_HISTORY = 20

# ---------------------------------------------------------------------------
# ロガー設定
# ---------------------------------------------------------------------------
os.makedirs(HFT_LOG_DIR, exist_ok=True)

logger = logging.getLogger("HFT")
logger.setLevel(logging.DEBUG)

_today_str = datetime.now(JST).strftime("%Y%m%d")
_log_file = os.path.join(HFT_LOG_DIR, f"hft_system_{_today_str}.log")
_fh = logging.FileHandler(_log_file, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
_fh.setFormatter(_fmt)
_ch.setFormatter(_fmt)
logger.addHandler(_fh)
logger.addHandler(_ch)

# ---------------------------------------------------------------------------
# CSV ログ
# ---------------------------------------------------------------------------
TRADE_LOG_FIELDS = [
    "datetime", "action", "symbol", "price", "qty",
    "order_type", "obi", "cvd", "micro_price", "pnl", "status", "detail",
]

SIGNAL_LOG_FIELDS = [
    "datetime", "symbol", "current_price", "obi", "cvd",
    "micro_price", "threshold", "signal_type",
]


def _ensure_csv(filepath: str, fieldnames: List[str]) -> None:
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()


def append_trade_log(row: Dict[str, Any]) -> None:
    today = datetime.now(JST).strftime("%Y%m%d")
    fp = os.path.join(HFT_LOG_DIR, f"hft_trades_{today}.csv")
    _ensure_csv(fp, TRADE_LOG_FIELDS)
    with open(fp, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_LOG_FIELDS, extrasaction="ignore")
        w.writerow(row)


def append_signal_log(row: Dict[str, Any]) -> None:
    today = datetime.now(JST).strftime("%Y%m%d")
    fp = os.path.join(HFT_LOG_DIR, f"hft_signals_{today}.csv")
    _ensure_csv(fp, SIGNAL_LOG_FIELDS)
    with open(fp, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SIGNAL_LOG_FIELDS, extrasaction="ignore")
        w.writerow(row)


# ---------------------------------------------------------------------------
# KabuStation API（main.py と同じパターン）
# ---------------------------------------------------------------------------
def kabus_api_request(
    method: str,
    path: str,
    token: Optional[str] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Any]:
    """KabuStation API 汎用ラッパー"""
    url = f"{KABUS_API_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-KEY"] = token
    try:
        if method.upper() in {"POST", "PUT"}:
            resp = requests.request(
                method.upper(), url, headers=headers,
                data=json.dumps(body or {}), timeout=REQUEST_TIMEOUT_SECONDS,
            )
        else:
            resp = requests.request(
                method.upper(), url, headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        try:
            payload = resp.json() if resp.text else {}
        except Exception:
            payload = {"raw": resp.text}
        return resp.status_code, payload
    except Exception as e:
        logger.error(f"API request error: {method} {path} → {e}")
        return 0, {"error": str(e)}


def kabus_get_token() -> str:
    """APIトークン取得"""
    if not KABUS_API_PASSWORD:
        raise RuntimeError("KABUS_API_PASSWORD が設定されていません")
    status, payload = kabus_api_request(
        "POST", "/kabusapi/token", body={"APIPassword": KABUS_API_PASSWORD}
    )
    if status != 200:
        raise RuntimeError(f"トークン取得失敗: {status} {payload}")
    token = payload.get("Token") or payload.get("token")
    if not token:
        raise RuntimeError(f"トークンがレスポンスに含まれていません: {payload}")
    return token


def kabus_register_symbols(token: str, symbols: List[str]) -> Tuple[int, Any]:
    """PUSH配信用に銘柄を登録"""
    symbol_list = [
        {"Symbol": sym, "Exchange": KABUS_EXCHANGE} for sym in symbols
    ]
    return kabus_api_request(
        "PUT", "/kabusapi/register", token=token,
        body={"Symbols": symbol_list}
    )


def kabus_unregister_all(token: str) -> Tuple[int, Any]:
    """登録銘柄を全解除"""
    return kabus_api_request("PUT", "/kabusapi/unregister/all", token=token)


def kabus_get_board(symbol: str, token: str) -> Tuple[int, Any]:
    """板情報取得"""
    return kabus_api_request(
        "GET", f"/kabusapi/board/{symbol}@{KABUS_EXCHANGE}", token=token
    )


def kabus_send_order(token: str, order: Dict[str, Any]) -> Tuple[int, Any]:
    """注文発注"""
    return kabus_api_request("POST", "/kabusapi/sendorder", token=token, body=order)


def kabus_get_positions(
    token: str, product: int = 0, symbol: str = ""
) -> Tuple[int, Any]:
    """建玉一覧取得"""
    params = [f"product={product}", "addinfo=true"]
    if symbol:
        params.append(f"symbol={symbol}")
    qs = "&".join(params)
    return kabus_api_request("GET", f"/kabusapi/positions?{qs}", token=token)


def kabus_cancel_order(
    token: str, order_id: str, password: str = ""
) -> Tuple[int, Any]:
    """注文取消"""
    body: Dict[str, Any] = {"OrderId": order_id}
    if password:
        body["Password"] = password
    return kabus_api_request("PUT", "/kabusapi/cancelorder", token=token, body=body)


def kabus_get_symbol_info(symbol: str, token: str) -> Tuple[int, Any]:
    """銘柄情報取得"""
    return kabus_api_request(
        "GET", f"/kabusapi/symbol/{symbol}@{KABUS_EXCHANGE}", token=token
    )


# ---------------------------------------------------------------------------
# 呼値（ティックサイズ）変換
# ---------------------------------------------------------------------------
def snap_to_tick(price: float, direction: str = "up") -> float:
    """日本株の呼値（ティックサイズ）に丸める。

    Args:
        price: 元の価格
        direction: "up" = 切り上げ（買い指値用）, "down" = 切り下げ（売り指値用）
    Returns:
        呼値に適合した価格
    """
    import math
    # 東証の呼値テーブル (2024年〜)
    tick_table = [
        (3000,    1),
        (5000,    5),
        (30000,   10),
        (50000,   50),
        (300000,  100),
        (500000,  500),
        (3000000, 1000),
        (5000000, 5000),
        (30000000, 10000),
        (50000000, 50000),
        (float('inf'), 100000),
    ]
    tick = 1
    for threshold, t in tick_table:
        if price < threshold:
            tick = t
            break

    if direction == "up":
        return math.ceil(price / tick) * tick
    else:
        return math.floor(price / tick) * tick


# ---------------------------------------------------------------------------
# 注文ビルダー（main.py と同じパターン）
# ---------------------------------------------------------------------------
def build_margin_new_order(
    symbol: str, side: str, qty: int,
    order_type: str = "market", limit_price: Optional[float] = None,
    margin_trade_type: int = 3,
) -> Dict[str, Any]:
    """信用新規注文"""
    obj: Dict[str, Any] = {
        "Symbol": str(symbol),
        "Exchange": KABUS_EXCHANGE,
        "SecurityType": 1,
        "Side": "2" if side == "buy" else "1",
        "CashMargin": 2,
        "MarginTradeType": int(margin_trade_type),
        "DelivType": 0,
        "AccountType": 4,
        "Qty": int(qty),
        "ExpireDay": 0,
    }
    if order_type == "market":
        obj["FrontOrderType"] = 10
        obj["Price"] = 0
    else:
        obj["FrontOrderType"] = 20
        obj["Price"] = float(limit_price or 0)
    return obj


def build_margin_close_order(
    symbol: str, side: str, qty: int,
    order_type: str = "market", limit_price: Optional[float] = None,
    margin_trade_type: int = 3,
) -> Dict[str, Any]:
    """信用返済注文"""
    obj: Dict[str, Any] = {
        "Symbol": str(symbol),
        "Exchange": KABUS_EXCHANGE,
        "SecurityType": 1,
        "Side": "2" if side == "buy" else "1",  # 買い返済=売建の返済
        "CashMargin": 3,
        "MarginTradeType": int(margin_trade_type),
        "DelivType": 2,
        "FundType": "AA",
        "AccountType": 4,
        "Qty": int(qty),
        "ClosePositionOrder": 0,
        "ExpireDay": 0,
    }
    if order_type == "market":
        obj["FrontOrderType"] = 10
        obj["Price"] = 0
    else:
        obj["FrontOrderType"] = 20
        obj["Price"] = float(limit_price or 0)
    return obj


# ---------------------------------------------------------------------------
# スロットル制御 (Token Bucket)
# ---------------------------------------------------------------------------
class OrderThrottle:
    """秒間発注数を制限するトークンバケツ"""

    def __init__(self, max_per_second: int = MAX_ORDERS_PER_SECOND):
        self.max_per_second = max_per_second
        self.timestamps: List[float] = []
        self._lock = threading.Lock()

    def can_send(self) -> bool:
        now = time.time()
        with self._lock:
            self.timestamps = [t for t in self.timestamps if now - t < 1.0]
            return len(self.timestamps) < self.max_per_second

    def record(self) -> None:
        with self._lock:
            self.timestamps.append(time.time())


throttle = OrderThrottle()


# ---------------------------------------------------------------------------
# システム状態管理
# ---------------------------------------------------------------------------
class PositionInfo:
    """保有ポジション情報"""

    def __init__(self, symbol: str, side: str, qty: int,
                 entry_price: float, entry_time: float):
        self.symbol = symbol
        self.side = side          # "buy" or "sell"
        self.qty = qty
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.current_price = entry_price
        self.unrealized_pnl = 0.0

    def update_price(self, price: float) -> None:
        self.current_price = price
        if self.side == "buy":
            self.unrealized_pnl = (price - self.entry_price) * self.qty
        else:
            self.unrealized_pnl = (self.entry_price - price) * self.qty


class SystemState:
    """HFTシステム全体の状態"""

    def __init__(self):
        self.mode = "MONITORING"  # MONITORING / TRADING
        self.paused = False
        self.connected = False
        self.token: Optional[str] = None

        # 監視対象銘柄
        self.target_symbols: List[str] = []
        self.order_qty = 100  # デフォルトロット
        self.order_type = "limit"  # "limit" or "market"（デフォルト: 指値）
        self.limit_pct = 1.0  # 指値の乖離率（%）
        self.target_profit = 500   # 目標利益（円） 0 = 無効
        self.target_loss = -300    # 目標損失（円、負値） 0 = 無効
        self.trade_side = "both"   # "buy_only", "sell_only", "both"
        
        # 戦略パラメータ
        self.entry_sigma = DEFAULT_ENTRY_SIGMA
        self.exit_sigma = DEFAULT_EXIT_SIGMA
        self.time_decay = DEFAULT_TIME_DECAY
        
        self.margin_type = 3  # 1=制度信用, 3=一般信用(デイトレ)

        # 各銘柄のOBI履歴・CVD
        self.obi_history: Dict[str, deque] = {}
        self.cvd: Dict[str, float] = {}
        self.last_prices: Dict[str, float] = {}
        self.symbol_names: Dict[str, str] = {}

        # アクティブポジション（1銘柄排他）
        self.position: Optional[PositionInfo] = None

        # 統計
        self.total_trades = 0
        self.total_pnl = 0.0
        self.tick_count = 0

        # ロック
        self._lock = threading.Lock()

    def init_symbol(self, symbol: str) -> None:
        """銘柄のトラッキング初期化"""
        if symbol not in self.obi_history:
            self.obi_history[symbol] = deque(maxlen=OBI_HISTORY_SIZE)
        if symbol not in self.cvd:
            self.cvd[symbol] = 0.0

    def reset_symbol(self, symbol: str) -> None:
        """銘柄のCVDをリセット"""
        self.cvd[symbol] = 0.0
        if symbol in self.obi_history:
            self.obi_history[symbol].clear()

    def clear_all(self) -> None:
        """全銘柄データをクリア"""
        self.obi_history.clear()
        self.cvd.clear()
        self.last_prices.clear()


state = SystemState()

# GUI → エンジン通信用キュー
gui_to_engine_queue: queue.Queue = queue.Queue()
# エンジン → GUI 通信用キュー
engine_to_gui_queue: queue.Queue = queue.Queue()

# asyncio ループへの参照（外部スレッドからのタスク投入用）
_async_loop: Optional[asyncio.AbstractEventLoop] = None


# ---------------------------------------------------------------------------
# HFT アルゴリズムコア
# ---------------------------------------------------------------------------
def compute_obi(buy_qty: float, sell_qty: float) -> float:
    """オーダーブック・インバランス"""
    total = buy_qty + sell_qty
    if total == 0:
        return 0.0
    return (buy_qty - sell_qty) / total


def compute_micro_price(
    bid_price: float, ask_price: float,
    buy_qty: float, sell_qty: float,
) -> float:
    """マイクロプライス（板厚み加重平均による真の価格）"""
    total = buy_qty + sell_qty
    if total == 0:
        return (bid_price + ask_price) / 2.0
    return (buy_qty * ask_price + sell_qty * bid_price) / total


async def process_tick(
    symbol: str,
    current_price: float,
    bid_price: float, ask_price: float,
    buy_qty: float, sell_qty: float,
) -> None:
    """メイン HFT シグナル処理"""
    global state

    if state.paused:
        return

    state.tick_count += 1
    state.last_prices[symbol] = current_price
    state.init_symbol(symbol)

    # 1. OBI 計算
    obi = compute_obi(buy_qty, sell_qty)
    state.obi_history[symbol].append(obi)

    # 2. CVD 更新
    state.cvd[symbol] += (buy_qty - sell_qty)

    # 履歴が不十分ならスキップ
    if len(state.obi_history[symbol]) < MIN_OBI_HISTORY:
        return

    # 3. 動的閾値 (使用するパラメータは State から取得)
    hist = list(state.obi_history[symbol])
    obi_mean = statistics.mean(hist)
    obi_std = statistics.stdev(hist) if len(hist) > 1 else 0.0
    
    buy_entry_threshold = obi_mean + (state.entry_sigma * obi_std)
    sell_entry_threshold = obi_mean - (state.entry_sigma * obi_std)

    # 4. マイクロプライス
    micro_price = compute_micro_price(bid_price, ask_price, buy_qty, sell_qty)

    # ---------- MONITORING モード ----------
    if state.mode == "MONITORING":
        # 買いエントリー判定
        can_buy = state.trade_side in ("buy_only", "both")
        if can_buy and obi > buy_entry_threshold and state.cvd[symbol] > 0:
            logger.info(
                f"[買いシグナル検知] {symbol} | OBI: {obi:.3f} "
                f"(閾値: {buy_entry_threshold:.3f}) | MicroPrice: {micro_price:.1f}"
            )
            append_signal_log({
                "datetime": datetime.now(JST).isoformat(),
                "symbol": symbol,
                "current_price": current_price,
                "obi": f"{obi:.4f}",
                "cvd": f"{state.cvd[symbol]:.0f}",
                "micro_price": f"{micro_price:.1f}",
                "threshold": f"{buy_entry_threshold:.4f}",
                "signal_type": "ENTRY_BUY",
            })
            await _execute_entry(symbol, current_price, obi, micro_price, ask_price, "buy")

        # 売りエントリー判定
        can_sell = state.trade_side in ("sell_only", "both")
        if can_sell and obi < sell_entry_threshold and state.cvd[symbol] < 0:
            logger.info(
                f"[売りシグナル検知] {symbol} | OBI: {obi:.3f} "
                f"(閾値: {sell_entry_threshold:.3f}) | MicroPrice: {micro_price:.1f}"
            )
            append_signal_log({
                "datetime": datetime.now(JST).isoformat(),
                "symbol": symbol,
                "current_price": current_price,
                "obi": f"{obi:.4f}",
                "cvd": f"{state.cvd[symbol]:.0f}",
                "micro_price": f"{micro_price:.1f}",
                "threshold": f"{sell_entry_threshold:.4f}",
                "signal_type": "ENTRY_SELL",
            })
            # 売りエントリー時は bid_price を参照（売れる価格）
            await _execute_entry(symbol, current_price, obi, micro_price, bid_price, "sell")

    # ---------- TRADING モード ----------
    elif state.mode == "TRADING":
        if state.position is None or state.position.symbol != symbol:
            return

        state.position.update_price(current_price)
        elapsed = time.time() - state.position.entry_time

        # 時間経過による撤退ライン変更
        
        # --- 買いポジションの場合 ---
        if state.position.side == "buy":
            exit_threshold = obi_mean - (state.exit_sigma * obi_std)
            if elapsed > state.time_decay:
                exit_threshold = obi_mean  # 閾値を緩和
            
            if obi < exit_threshold:
                logger.info(
                    f"[買い返済シグナル] {symbol} | 経過: {elapsed:.1f}秒 | "
                    f"OBI: {obi:.3f} (撤退閾値: {exit_threshold:.3f})"
                )
                append_signal_log({
                    "datetime": datetime.now(JST).isoformat(),
                    "symbol": symbol,
                    "current_price": current_price,
                    "obi": f"{obi:.4f}",
                    "cvd": f"{state.cvd[symbol]:.0f}",
                    "micro_price": f"{micro_price:.1f}",
                    "threshold": f"{exit_threshold:.4f}",
                    "signal_type": "EXIT_BUY",
                })
                await _execute_exit(symbol, current_price, "signal")

        # --- 売りポジションの場合 ---
        elif state.position.side == "sell":
            exit_threshold = obi_mean + (state.exit_sigma * obi_std)
            if elapsed > state.time_decay:
                exit_threshold = obi_mean  # 閾値を緩和

            if obi > exit_threshold:
                logger.info(
                    f"[売り返済シグナル] {symbol} | 経過: {elapsed:.1f}秒 | "
                    f"OBI: {obi:.3f} (撤退閾値: {exit_threshold:.3f})"
                )
                append_signal_log({
                    "datetime": datetime.now(JST).isoformat(),
                    "symbol": symbol,
                    "current_price": current_price,
                    "obi": f"{obi:.4f}",
                    "cvd": f"{state.cvd[symbol]:.0f}",
                    "micro_price": f"{micro_price:.1f}",
                    "threshold": f"{exit_threshold:.4f}",
                    "signal_type": "EXIT_SELL",
                })
                await _execute_exit(symbol, current_price, "signal")

        # ---------- P&L 自動イグジット ----------
        elif state.position is not None:
            pnl = state.position.unrealized_pnl
            if state.target_profit > 0 and pnl >= state.target_profit:
                logger.info(
                    f"[利確自動イグジット] {symbol} | P&L: {pnl:+,.0f}円 "
                    f"(目標: {state.target_profit:+,.0f}円)"
                )
                await _execute_exit(symbol, current_price, "auto_profit")
            elif state.target_loss < 0 and pnl <= state.target_loss:
                logger.info(
                    f"[損切自動イグジット] {symbol} | P&L: {pnl:+,.0f}円 "
                    f"(目標: {state.target_loss:+,.0f}円)"
                )
                await _execute_exit(symbol, current_price, "auto_loss")

    # GUIへステータス通知（5ティックごと）
    if state.tick_count % 5 == 0:
        _push_status_to_gui()


async def _execute_entry(
    symbol: str, price: float, obi: float, micro_price: float, board_price: float, side: str = "buy"
) -> None:
    """エントリー注文を発注 (side: "buy" or "sell")"""
    global state

    if not throttle.can_send():
        logger.warning(f"スロットル制限: {symbol} への発注を見送りました")
        return

    if state.token is None:
        logger.error("トークンがありません")
        return

    qty = state.order_qty
    order_type = state.order_type  # GUI設定に従う
    m_type = state.margin_type     # 信用区分

    if order_type == "limit":
        # 買い → 現在価格 + N% の指値（呼値切り上げ）
        # 売り → 現在価格 - N% の指値（呼値切り下げ）
        if side == "buy":
            raw_limit = price * (1.0 + state.limit_pct / 100.0)
            limit_price = snap_to_tick(raw_limit, "up")
        else:
            raw_limit = price * (1.0 - state.limit_pct / 100.0)
            limit_price = snap_to_tick(raw_limit, "down")
            
        order = build_margin_new_order(symbol, side, qty, "limit", limit_price, m_type)
    else:
        limit_price = None
        order = build_margin_new_order(symbol, side, qty, "market", margin_trade_type=m_type)

    throttle.record()
    price_info = f"指値: {limit_price}" if limit_price else "成行"
    logger.info(f"発注実行: {side.upper()} {symbol} x{qty} @ {price} ({order_type}, {price_info})")

    status_code, result = kabus_send_order(state.token, order)

    if status_code == 200:
        state.mode = "TRADING"
        state.position = PositionInfo(symbol, side, qty, price, time.time())
        logger.info(f">>> TRADING モードへ移行（排他ロック: {symbol} | {side.upper()}）")

        append_trade_log({
            "datetime": datetime.now(JST).isoformat(),
            "action": f"{side.upper()}_ENTRY",
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "order_type": order_type,
            "obi": f"{obi:.4f}",
            "cvd": f"{state.cvd[symbol]:.0f}",
            "micro_price": f"{micro_price:.1f}",
            "pnl": "",
            "status": "OK",
            "detail": json.dumps(result, ensure_ascii=False),
        })
    else:
        logger.error(f"発注失敗: {status_code} {result}")
        append_trade_log({
            "datetime": datetime.now(JST).isoformat(),
            "action": f"{side.upper()}_ENTRY",
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "order_type": order_type,
            "obi": f"{obi:.4f}",
            "cvd": f"{state.cvd[symbol]:.0f}",
            "micro_price": f"{micro_price:.1f}",
            "pnl": "",
            "status": "FAIL",
            "detail": json.dumps(result, ensure_ascii=False),
        })

    _push_status_to_gui()


async def _execute_exit(
    symbol: str, price: float, reason: str = "signal",
) -> None:
    """ポジション返済"""
    global state

    if state.position is None:
        return
    if not throttle.can_send():
        logger.warning(f"スロットル制限: {symbol} の返済を見送り")
        return
    if state.token is None:
        logger.error("トークンがありません")
        return

    pos = state.position
    qty = pos.qty
    close_order_type = state.order_type
    m_type = state.margin_type

    # 返済: 買い建て → 売り返済
    close_side = "sell" if pos.side == "buy" else "buy"
    if close_order_type == "limit":
        # 売り返済 → 呼値切り下げ、買い返済 → 呼値切り上げ
        if close_side == "sell":
            raw_limit = price * (1.0 - state.limit_pct / 100.0)
            limit_price = snap_to_tick(raw_limit, "down")
        else:
            raw_limit = price * (1.0 + state.limit_pct / 100.0)
            limit_price = snap_to_tick(raw_limit, "up")
        order = build_margin_close_order(symbol, close_side, qty, "limit", limit_price, m_type)
    else:
        limit_price = None
        order = build_margin_close_order(symbol, close_side, qty, "market", margin_trade_type=m_type)

    throttle.record()
    price_info = f"指値: {limit_price}" if limit_price else "成行"
    logger.info(f"返済実行: {close_side.upper()} {symbol} x{qty} @ {price} ({close_order_type}, {price_info}, 理由: {reason})")

    status_code, result = kabus_send_order(state.token, order)
    pnl = pos.unrealized_pnl

    if status_code == 200:
        state.total_trades += 1
        state.total_pnl += pnl
        logger.info(f"<<< MONITORING モードへ復帰 | P&L: {pnl:+.0f}円")

        append_trade_log({
            "datetime": datetime.now(JST).isoformat(),
            "action": f"CLOSE_{reason.upper()}",
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "order_type": close_order_type,
            "obi": "",
            "cvd": "",
            "micro_price": "",
            "pnl": f"{pnl:.0f}",
            "status": "OK",
            "detail": json.dumps(result, ensure_ascii=False),
        })
    else:
        logger.error(f"返済失敗: {status_code} {result}")
        append_trade_log({
            "datetime": datetime.now(JST).isoformat(),
            "action": f"CLOSE_{reason.upper()}",
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "order_type": close_order_type,
            "obi": "",
            "cvd": "",
            "micro_price": "",
            "pnl": f"{pnl:.0f}",
            "status": "FAIL",
            "detail": json.dumps(result, ensure_ascii=False),
        })

    # 状態リセット
    state.mode = "MONITORING"
    state.position = None
    state.reset_symbol(symbol)
    _push_status_to_gui()


def execute_manual_close(reason: str = "manual") -> None:
    """GUIスレッドからの手動決済（同期呼び出し）"""
    global state

    if state.position is None:
        logger.warning("手動決済: ポジションがありません")
        return
    if state.token is None:
        logger.error("手動決済: トークンがありません")
        return

    pos = state.position
    close_side = "sell" if pos.side == "buy" else "buy"
    manual_order_type = state.order_type
    m_type = state.margin_type
    
    if manual_order_type == "limit":
        if close_side == "sell":
            raw_limit = pos.current_price * (1.0 - state.limit_pct / 100.0)
            limit_price = snap_to_tick(raw_limit, "down")
        else:
            raw_limit = pos.current_price * (1.0 + state.limit_pct / 100.0)
            limit_price = snap_to_tick(raw_limit, "up")
        order = build_margin_close_order(pos.symbol, close_side, pos.qty, "limit", limit_price, m_type)
    else:
        order = build_margin_close_order(pos.symbol, close_side, pos.qty, "market", margin_trade_type=m_type)

    throttle.record()
    price = pos.current_price
    logger.info(f"手動決済: {close_side.upper()} {pos.symbol} x{pos.qty} @ {price} ({reason})")

    status_code, result = kabus_send_order(state.token, order)
    pnl = pos.unrealized_pnl

    if status_code == 200:
        state.total_trades += 1
        state.total_pnl += pnl
        logger.info(f"手動決済成功 | P&L: {pnl:+.0f}円")
    else:
        logger.error(f"手動決済失敗: {status_code} {result}")

    append_trade_log({
        "datetime": datetime.now(JST).isoformat(),
        "action": f"CLOSE_{reason.upper()}",
        "symbol": pos.symbol,
        "price": price,
        "qty": pos.qty,
        "order_type": manual_order_type,
        "obi": "", "cvd": "", "micro_price": "",
        "pnl": f"{pnl:.0f}",
        "status": "OK" if status_code == 200 else "FAIL",
        "detail": json.dumps(result, ensure_ascii=False),
    })

    state.mode = "MONITORING"
    state.position = None
    _push_status_to_gui()


def _push_status_to_gui() -> None:
    """現在のステータスをGUIキューに送信"""
    pos = state.position
    info = {
        "type": "status",
        "mode": state.mode,
        "paused": state.paused,
        "connected": state.connected,
        "tick_count": state.tick_count,
        "symbols": list(state.target_symbols),
        "total_trades": state.total_trades,
        "total_pnl": state.total_pnl,
        "qty": state.order_qty,
    }
    if pos:
        info["position"] = {
            "symbol": pos.symbol,
            "side": pos.side,
            "qty": pos.qty,
            "entry_price": pos.entry_price,
            "current_price": pos.current_price,
            "pnl": pos.unrealized_pnl,
            "elapsed": time.time() - pos.entry_time,
        }
    else:
        info["position"] = None

    try:
        engine_to_gui_queue.put_nowait(info)
    except queue.Full:
        pass


# ---------------------------------------------------------------------------
# WebSocket ストリーム (asyncio)
# ---------------------------------------------------------------------------
async def websocket_stream() -> None:
    """WebSocketからの非同期データ受信ループ"""
    global state

    try:
        import websockets
    except ImportError:
        logger.error("websockets ライブラリが見つかりません。pip install websockets を実行してください。")
        return

    while True:
        try:
            logger.info(f"WebSocket接続中... {WS_URL}")
            async with websockets.connect(WS_URL, ping_timeout=None) as ws:
                state.connected = True
                logger.info("WebSocket 接続確立")
                _push_status_to_gui()

                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        data = json.loads(message)

                        symbol = str(data.get("Symbol", ""))
                        current_price = data.get("CurrentPrice")

                        sell1 = data.get("Sell1", {}) or {}
                        buy1 = data.get("Buy1", {}) or {}

                        ask_price = sell1.get("Price", 0) or 0
                        sell_qty = sell1.get("Qty", 0) or 0
                        bid_price = buy1.get("Price", 0) or 0
                        buy_qty = buy1.get("Qty", 0) or 0

                        if (
                            symbol in state.target_symbols
                            and current_price
                            and ask_price
                            and bid_price
                        ):
                            await process_tick(
                                symbol, current_price,
                                bid_price, ask_price,
                                buy_qty, sell_qty,
                            )

                    except asyncio.TimeoutError:
                        # ハートビートタイムアウト → 再接続
                        logger.warning("WebSocket タイムアウト（30秒）→ 再接続")
                        break
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.error(f"Tick処理エラー: {e}")
                        await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"WebSocket接続エラー: {e}")

        state.connected = False
        _push_status_to_gui()
        logger.info("3秒後に再接続...")
        await asyncio.sleep(3)


async def command_processor() -> None:
    """GUIからのコマンドを非同期で処理"""
    global state

    while True:
        try:
            cmd = gui_to_engine_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.1)
            continue

        cmd_type = cmd.get("type", "")

        if cmd_type == "register_symbols":
            symbols = cmd.get("symbols", [])
            state.target_symbols = symbols
            state.clear_all()
            for sym in symbols:
                state.init_symbol(sym)
            # API に登録
            if state.token and symbols:
                try:
                    kabus_unregister_all(state.token)
                    st, res = kabus_register_symbols(state.token, symbols)
                    if st == 200:
                        logger.info(f"銘柄登録完了: {symbols}")
                        # 銘柄名を取得
                        for sym in symbols:
                            try:
                                _, info = kabus_get_symbol_info(sym, state.token)
                                name = info.get("DisplayName", info.get("SymbolName", sym))
                                state.symbol_names[sym] = name
                            except Exception:
                                state.symbol_names[sym] = sym
                    else:
                        logger.error(f"銘柄登録失敗: {st} {res}")
                except Exception as e:
                    logger.error(f"銘柄登録エラー: {e}")
            _push_status_to_gui()

        elif cmd_type == "set_qty":
            state.order_qty = int(cmd.get("qty", 100))
            logger.info(f"ロット変更: {state.order_qty}")
            _push_status_to_gui()

        elif cmd_type == "pause":
            state.paused = True
            logger.info("システム一時停止")
            _push_status_to_gui()

        elif cmd_type == "resume":
            state.paused = False
            logger.info("システム再開")
            _push_status_to_gui()

        elif cmd_type == "set_order_type":
            ot = cmd.get("order_type", "limit")
            state.order_type = ot
            logger.info(f"注文方式変更: {ot.upper()}")
            _push_status_to_gui()

        elif cmd_type == "set_targets":
            tp = cmd.get("target_profit", 0)
            tl = cmd.get("target_loss", 0)
            state.target_profit = tp
            state.target_loss = tl
            logger.info(f"目標設定変更: 利確={tp:+,}円 / 損切={tl:+,}円")
            _push_status_to_gui()
            
        elif cmd_type == "set_trade_side":
            ts = cmd.get("trade_side", "both")
            state.trade_side = ts
            logger.info(f"売買区分変更: {ts.upper()}")
            _push_status_to_gui()

        elif cmd_type == "set_strategy_params":
            state.entry_sigma = float(cmd.get("entry_sigma", DEFAULT_ENTRY_SIGMA))
            state.exit_sigma = float(cmd.get("exit_sigma", DEFAULT_EXIT_SIGMA))
            state.time_decay = float(cmd.get("time_decay", DEFAULT_TIME_DECAY))
            logger.info(
                f"戦略変更: Entry={state.entry_sigma}σ / Exit={state.exit_sigma}σ / Decay={state.time_decay}s"
            )
            _push_status_to_gui()
            
        elif cmd_type == "set_margin_type":
            mt = int(cmd.get("margin_type", 3))
            state.margin_type = mt
            m_text = "一般信用(デイトレ)" if mt == 3 else "制度信用"
            logger.info(f"信用区分変更: {m_text}")
            _push_status_to_gui()

        elif cmd_type == "manual_close_profit":
            execute_manual_close("take_profit")

        elif cmd_type == "manual_close_loss":
            execute_manual_close("stop_loss")


async def async_main() -> None:
    """asyncio メインエントリ"""
    global _async_loop
    _async_loop = asyncio.get_event_loop()

    # トークン取得
    try:
        state.token = kabus_get_token()
        logger.info("APIトークン取得成功")
    except Exception as e:
        logger.error(f"トークン取得失敗: {e}")
        state.token = None

    _push_status_to_gui()

    # WebSocketストリームとコマンドプロセッサを並行実行
    await asyncio.gather(
        websocket_stream(),
        command_processor(),
    )


# ---------------------------------------------------------------------------
# tkinter GUI
# ---------------------------------------------------------------------------
def start_gui() -> None:
    """メインスレッドでtkinter GUIを起動"""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("HFT トレーディングシステム")
    root.geometry("700x1000")
    root.resizable(True, True)

    # カラーテーマ
    BG = "#1e1e2e"
    FG = "#cdd6f4"
    ACCENT = "#89b4fa"
    GREEN = "#a6e3a1"
    RED = "#f38ba8"
    YELLOW = "#f9e2af"
    SURFACE = "#313244"
    BORDER = "#45475a"

    root.configure(bg=BG)

    # フォント
    FONT = ("Yu Gothic UI", 10)
    FONT_BOLD = ("Yu Gothic UI", 10, "bold")
    FONT_TITLE = ("Yu Gothic UI", 14, "bold")
    FONT_MONO = ("Consolas", 10)

    # スタイルヘルパー
    def styled_label(parent, text="", **kw):
        return tk.Label(parent, text=text, bg=BG, fg=FG, font=FONT, anchor="w", **kw)

    def styled_frame(parent, **kw):
        return tk.Frame(parent, bg=BG, **kw)

    def styled_button(parent, text, command, bg_color=SURFACE, fg_color=FG, **kw):
        return tk.Button(
            parent, text=text, command=command,
            bg=bg_color, fg=fg_color, font=FONT_BOLD,
            activebackground=ACCENT, activeforeground="#000",
            relief="flat", bd=0, padx=12, pady=4, cursor="hand2", **kw
        )

    # ====== ヘッダー ======
    header = styled_frame(root)
    header.pack(fill="x", padx=12, pady=(12, 4))

    tk.Label(
        header, text="⚡ HFT トレーディングシステム",
        bg=BG, fg=ACCENT, font=FONT_TITLE, anchor="w",
    ).pack(side="left")

    # ====== 接続ステータス ======
    status_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    status_frame.pack(fill="x", padx=12, pady=4)

    sv_mode = tk.StringVar(value="モード: MONITORING")
    sv_connection = tk.StringVar(value="接続: 未接続")
    sv_ticks = tk.StringVar(value="受信ティック: 0")
    sv_symbols = tk.StringVar(value="監視銘柄: なし")

    status_inner = styled_frame(status_frame)
    status_inner.pack(fill="x", padx=8, pady=6)

    lbl_mode = tk.Label(status_inner, textvariable=sv_mode, bg=BG, fg=GREEN, font=FONT_BOLD, anchor="w")
    lbl_mode.grid(row=0, column=0, sticky="w", padx=4)

    lbl_conn = tk.Label(status_inner, textvariable=sv_connection, bg=BG, fg=RED, font=FONT, anchor="w")
    lbl_conn.grid(row=0, column=1, sticky="w", padx=16)

    tk.Label(status_inner, textvariable=sv_ticks, bg=BG, fg=FG, font=FONT, anchor="w").grid(
        row=1, column=0, sticky="w", padx=4
    )
    tk.Label(status_inner, textvariable=sv_symbols, bg=BG, fg=FG, font=FONT, anchor="w").grid(
        row=1, column=1, sticky="w", padx=16, columnspan=2
    )

    # ====== ポジション表示 ======
    pos_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    pos_frame.pack(fill="x", padx=12, pady=4)

    tk.Label(pos_frame, text="■ ポジション", bg=BG, fg=YELLOW, font=FONT_BOLD, anchor="w").pack(
        fill="x", padx=8, pady=(6, 2)
    )

    sv_pos = tk.StringVar(value="ポジションなし")
    sv_pnl = tk.StringVar(value="")
    sv_elapsed = tk.StringVar(value="")
    sv_stats = tk.StringVar(value="取引回数: 0 | 累計P&L: 0円")

    pos_inner = styled_frame(pos_frame)
    pos_inner.pack(fill="x", padx=8, pady=(0, 6))

    lbl_pos = tk.Label(pos_inner, textvariable=sv_pos, bg=BG, fg=FG, font=FONT_MONO, anchor="w")
    lbl_pos.pack(fill="x")
    lbl_pnl = tk.Label(pos_inner, textvariable=sv_pnl, bg=BG, fg=FG, font=FONT_BOLD, anchor="w")
    lbl_pnl.pack(fill="x")
    tk.Label(pos_inner, textvariable=sv_elapsed, bg=BG, fg=FG, font=FONT, anchor="w").pack(fill="x")
    tk.Label(pos_inner, textvariable=sv_stats, bg=BG, fg=FG, font=FONT, anchor="w").pack(fill="x")

    # ====== 銘柄登録 ======
    sym_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    sym_frame.pack(fill="x", padx=12, pady=4)

    tk.Label(sym_frame, text="■ 銘柄登録（最大20銘柄）", bg=BG, fg=YELLOW, font=FONT_BOLD, anchor="w").pack(
        fill="x", padx=8, pady=(6, 2)
    )

    sym_entry_frame = styled_frame(sym_frame)
    sym_entry_frame.pack(fill="x", padx=8, pady=(0, 6))

    SYMBOLS_PER_ROW = 5
    MAX_SYMBOLS = 20
    sym_entries: List[tk.Entry] = []
    for i in range(MAX_SYMBOLS):
        row_idx = i // SYMBOLS_PER_ROW
        col_idx = i % SYMBOLS_PER_ROW
        tk.Label(sym_entry_frame, text=f"{i+1}:", bg=BG, fg=FG, font=FONT).grid(
            row=row_idx, column=col_idx*2, padx=(8, 2), pady=2
        )
        e = tk.Entry(sym_entry_frame, width=8, font=FONT_MONO, bg=SURFACE, fg=FG,
                     insertbackground=FG, relief="flat", bd=2)
        e.grid(row=row_idx, column=col_idx*2+1, padx=(0, 4), pady=2)
        sym_entries.append(e)

    def on_register_symbols():
        symbols = []
        for e in sym_entries:
            val = e.get().strip().upper()
            if val and len(val) >= 4:
                symbols.append(val)
        if not symbols:
            messagebox.showwarning("警告", "銘柄コードを1つ以上入力してください")
            return
        gui_to_engine_queue.put({"type": "register_symbols", "symbols": symbols})
        logger.info(f"GUI: 銘柄登録要求 → {symbols}")

    sym_btn_frame = styled_frame(sym_frame)
    sym_btn_frame.pack(fill="x", padx=8, pady=(0, 6))
    styled_button(sym_btn_frame, "登録", on_register_symbols, bg_color=ACCENT, fg_color="#000").pack(
        side="left", padx=(8, 0)
    )

    # ====== ロット設定 + 注文方式 ======
    lot_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    lot_frame.pack(fill="x", padx=12, pady=4)

    tk.Label(lot_frame, text="■ 注文設定", bg=BG, fg=YELLOW, font=FONT_BOLD, anchor="w").pack(
        fill="x", padx=8, pady=(6, 2)
    )

    lot_inner = styled_frame(lot_frame)
    lot_inner.pack(fill="x", padx=8, pady=(0, 4))

    tk.Label(lot_inner, text="ロット（株数）:", bg=BG, fg=FG, font=FONT).pack(side="left")

    lot_var = tk.StringVar(value="100")
    lot_spin = tk.Spinbox(
        lot_inner, from_=100, to=10000, increment=100,
        textvariable=lot_var, width=8, font=FONT_MONO,
        bg=SURFACE, fg=FG, buttonbackground=SURFACE,
        relief="flat", bd=2,
    )
    lot_spin.pack(side="left", padx=8)

    def on_set_qty():
        try:
            qty = int(lot_var.get())
            if qty <= 0:
                raise ValueError
            gui_to_engine_queue.put({"type": "set_qty", "qty": qty})
        except ValueError:
            messagebox.showwarning("警告", "有効な数量を入力してください")

    styled_button(lot_inner, "反映", on_set_qty).pack(side="left", padx=4)

    # --- 注文方式ラジオボタン ---
    otype_inner = styled_frame(lot_frame)
    otype_inner.pack(fill="x", padx=8, pady=(0, 6))

    tk.Label(otype_inner, text="注文方式:", bg=BG, fg=FG, font=FONT).pack(side="left")

    order_type_var = tk.StringVar(value="limit")  # デフォルト: 指値

    def on_order_type_change():
        gui_to_engine_queue.put({"type": "set_order_type", "order_type": order_type_var.get()})

    tk.Radiobutton(
        otype_inner, text="指値（±1%）", variable=order_type_var, value="limit",
        command=on_order_type_change,
        bg=BG, fg=FG, font=FONT, selectcolor=SURFACE,
        activebackground=BG, activeforeground=ACCENT,
        indicatoron=True, bd=0, highlightthickness=0,
    ).pack(side="left", padx=(8, 4))

    tk.Radiobutton(
        otype_inner, text="成行", variable=order_type_var, value="market",
        command=on_order_type_change,
        bg=BG, fg=FG, font=FONT, selectcolor=SURFACE,
        activebackground=BG, activeforeground=ACCENT,
        indicatoron=True, bd=0, highlightthickness=0,
    ).pack(side="left", padx=4)

    # --- 売買区分ラジオボタン ---
    tside_inner = styled_frame(lot_frame)
    tside_inner.pack(fill="x", padx=8, pady=(0, 6))

    tk.Label(tside_inner, text="売買区分:", bg=BG, fg=FG, font=FONT).pack(side="left")

    tside_var = tk.StringVar(value="both")  # デフォルト: 両方

    def on_trade_side_change():
        gui_to_engine_queue.put({"type": "set_trade_side", "trade_side": tside_var.get()})

    tk.Radiobutton(
        tside_inner, text="両方", variable=tside_var, value="both",
        command=on_trade_side_change,
        bg=BG, fg=FG, font=FONT, selectcolor=SURFACE,
        activebackground=BG, activeforeground=ACCENT,
        indicatoron=True, bd=0, highlightthickness=0,
    ).pack(side="left", padx=(8, 4))

    tk.Radiobutton(
        tside_inner, text="買いのみ", variable=tside_var, value="buy_only",
        command=on_trade_side_change,
        bg=BG, fg=FG, font=FONT, selectcolor=SURFACE,
        activebackground=BG, activeforeground=ACCENT,
        indicatoron=True, bd=0, highlightthickness=0,
    ).pack(side="left", padx=4)

    tk.Radiobutton(
        tside_inner, text="売りのみ", variable=tside_var, value="sell_only",
        command=on_trade_side_change,
        bg=BG, fg=FG, font=FONT, selectcolor=SURFACE,
        activebackground=BG, activeforeground=ACCENT,
        indicatoron=True, bd=0, highlightthickness=0,
    ).pack(side="left", padx=4)

    # --- 信用区分ラジオボタン ---
    mtype_inner = styled_frame(lot_frame)
    mtype_inner.pack(fill="x", padx=8, pady=(0, 6))

    tk.Label(mtype_inner, text="信用区分:", bg=BG, fg=FG, font=FONT).pack(side="left")

    mtype_var = tk.IntVar(value=3)  # デフォルト: デイトレ(3)

    def on_margin_type_change():
        gui_to_engine_queue.put({"type": "set_margin_type", "margin_type": mtype_var.get()})

    tk.Radiobutton(
        mtype_inner, text="デイトレ(一般)", variable=mtype_var, value=3,
        command=on_margin_type_change,
        bg=BG, fg=FG, font=FONT, selectcolor=SURFACE,
        activebackground=BG, activeforeground=ACCENT,
        indicatoron=True, bd=0, highlightthickness=0,
    ).pack(side="left", padx=(8, 4))

    tk.Radiobutton(
        mtype_inner, text="制度信用", variable=mtype_var, value=1,
        command=on_margin_type_change,
        bg=BG, fg=FG, font=FONT, selectcolor=SURFACE,
        activebackground=BG, activeforeground=ACCENT,
        indicatoron=True, bd=0, highlightthickness=0,
    ).pack(side="left", padx=4)

    # ====== 目標利益・損切設定 ======
    target_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    target_frame.pack(fill="x", padx=12, pady=4)

    tk.Label(target_frame, text="■ 自動イグジット（P&L目標）", bg=BG, fg=YELLOW, font=FONT_BOLD, anchor="w").pack(
        fill="x", padx=8, pady=(6, 2)
    )

    target_inner = styled_frame(target_frame)
    target_inner.pack(fill="x", padx=8, pady=(0, 6))

    tk.Label(target_inner, text="利確（円）:", bg=BG, fg=GREEN, font=FONT).pack(side="left")
    tp_var = tk.StringVar(value="500")
    tk.Spinbox(
        target_inner, from_=0, to=100000, increment=100,
        textvariable=tp_var, width=7, font=FONT_MONO,
        bg=SURFACE, fg=FG, buttonbackground=SURFACE, relief="flat", bd=2,
    ).pack(side="left", padx=(4, 12))

    tk.Label(target_inner, text="損切（円）:", bg=BG, fg=RED, font=FONT).pack(side="left")
    tl_var = tk.StringVar(value="300")
    tk.Spinbox(
        target_inner, from_=0, to=100000, increment=100,
        textvariable=tl_var, width=7, font=FONT_MONO,
        bg=SURFACE, fg=FG, buttonbackground=SURFACE, relief="flat", bd=2,
    ).pack(side="left", padx=(4, 8))

    tk.Label(target_inner, text="(0=無効)", bg=BG, fg=FG, font=FONT).pack(side="left", padx=(0, 8))

    def on_set_targets():
        try:
            tp = int(tp_var.get())
            tl = int(tl_var.get())
            if tp < 0 or tl < 0:
                raise ValueError
            gui_to_engine_queue.put({
                "type": "set_targets",
                "target_profit": tp,
                "target_loss": -tl,  # 内部は負値で保持
            })
        except ValueError:
            messagebox.showwarning("警告", "有効な数値を入力してください")

    styled_button(target_inner, "反映", on_set_targets).pack(side="left", padx=4)

    # ====== 戦略パラメータ設定 ======
    strat_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    strat_frame.pack(fill="x", padx=12, pady=4)

    tk.Label(strat_frame, text="■ アルゴリズム設定", bg=BG, fg=YELLOW, font=FONT_BOLD, anchor="w").pack(
        fill="x", padx=8, pady=(6, 2)
    )

    strat_inner = styled_frame(strat_frame)
    strat_inner.pack(fill="x", padx=8, pady=(0, 6))

    # Entry Sigma
    tk.Label(strat_inner, text="Entry(σ):", bg=BG, fg=FG, font=FONT).pack(side="left")
    entry_sigma_var = tk.StringVar(value=str(DEFAULT_ENTRY_SIGMA))
    tk.Spinbox(
        strat_inner, from_=0.5, to=5.0, increment=0.1, format="%.1f",
        textvariable=entry_sigma_var, width=4, font=FONT_MONO,
        bg=SURFACE, fg=FG, buttonbackground=SURFACE, relief="flat", bd=2,
    ).pack(side="left", padx=(2, 6))

    # Exit Sigma
    tk.Label(strat_inner, text="Exit(σ):", bg=BG, fg=FG, font=FONT).pack(side="left")
    exit_sigma_var = tk.StringVar(value=str(DEFAULT_EXIT_SIGMA))
    tk.Spinbox(
        strat_inner, from_=0.1, to=5.0, increment=0.1, format="%.1f",
        textvariable=exit_sigma_var, width=4, font=FONT_MONO,
        bg=SURFACE, fg=FG, buttonbackground=SURFACE, relief="flat", bd=2,
    ).pack(side="left", padx=(2, 6))

    # Time Decay
    tk.Label(strat_inner, text="Decay(s):", bg=BG, fg=FG, font=FONT).pack(side="left")
    decay_var = tk.StringVar(value=str(DEFAULT_TIME_DECAY))
    tk.Spinbox(
        strat_inner, from_=5.0, to=300.0, increment=5.0, format="%.0f",
        textvariable=decay_var, width=4, font=FONT_MONO,
        bg=SURFACE, fg=FG, buttonbackground=SURFACE, relief="flat", bd=2,
    ).pack(side="left", padx=(2, 6))

    def on_set_strategy():
        try:
            es = float(entry_sigma_var.get())
            xs = float(exit_sigma_var.get())
            td = float(decay_var.get())
            gui_to_engine_queue.put({
                "type": "set_strategy_params",
                "entry_sigma": es,
                "exit_sigma": xs,
                "time_decay": td,
            })
        except ValueError:
            messagebox.showwarning("警告", "有効な数値を入力してください")

    styled_button(strat_inner, "反映", on_set_strategy).pack(side="left", padx=4)

    # ====== コントロールボタン ======
    ctrl_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    ctrl_frame.pack(fill="x", padx=12, pady=4)

    ctrl_inner = styled_frame(ctrl_frame)
    ctrl_inner.pack(fill="x", padx=8, pady=6)

    sv_pause_btn = tk.StringVar(value="⏸ 一時停止")

    def on_toggle_pause():
        if state.paused:
            gui_to_engine_queue.put({"type": "resume"})
            sv_pause_btn.set("⏸ 一時停止")
        else:
            gui_to_engine_queue.put({"type": "pause"})
            sv_pause_btn.set("▶ 再開")

    tk.Button(
        ctrl_inner, textvariable=sv_pause_btn, command=on_toggle_pause,
        bg=YELLOW, fg="#000", font=FONT_BOLD, relief="flat", bd=0,
        padx=16, pady=6, cursor="hand2",
    ).pack(side="left", padx=4)

    def on_take_profit():
        if state.position is None:
            messagebox.showinfo("情報", "ポジションがありません")
            return
        if messagebox.askyesno("利確確認", f"ポジション({state.position.symbol})を利確しますか？"):
            gui_to_engine_queue.put({"type": "manual_close_profit"})

    def on_stop_loss():
        if state.position is None:
            messagebox.showinfo("情報", "ポジションがありません")
            return
        if messagebox.askyesno("損切確認", f"ポジション({state.position.symbol})を損切しますか？"):
            gui_to_engine_queue.put({"type": "manual_close_loss"})

    styled_button(ctrl_inner, "💰 利確（成行）", on_take_profit, bg_color=GREEN, fg_color="#000").pack(
        side="left", padx=4
    )
    styled_button(ctrl_inner, "🛑 損切（成行）", on_stop_loss, bg_color=RED, fg_color="#000").pack(
        side="left", padx=4
    )

    # ====== ログ表示 ======
    log_frame = styled_frame(root, highlightbackground=BORDER, highlightthickness=1)
    log_frame.pack(fill="both", expand=True, padx=12, pady=(4, 12))

    tk.Label(log_frame, text="■ システムログ", bg=BG, fg=YELLOW, font=FONT_BOLD, anchor="w").pack(
        fill="x", padx=8, pady=(6, 2)
    )

    log_inner = styled_frame(log_frame)
    log_inner.pack(fill="both", expand=True, padx=8, pady=(0, 6))

    log_sb = tk.Scrollbar(log_inner)
    log_sb.pack(side="right", fill="y")

    log_text = tk.Text(
        log_inner, wrap="word", yscrollcommand=log_sb.set,
        bg=SURFACE, fg=FG, font=FONT_MONO,
        relief="flat", bd=0, state="disabled", height=12,
    )
    log_text.pack(side="left", fill="both", expand=True)
    log_sb.config(command=log_text.yview)

    # ログハンドラー → GUI Text
    class GUILogHandler(logging.Handler):
        def emit(self, record):
            msg = self.format(record) + "\n"
            try:
                log_text.after(0, _append_log, msg)
            except Exception:
                pass

    def _append_log(msg: str):
        log_text.config(state="normal")
        log_text.insert("end", msg)
        # 最大1000行に制限
        lines = int(log_text.index("end-1c").split(".")[0])
        if lines > 1000:
            log_text.delete("1.0", f"{lines - 1000}.0")
        log_text.see("end")
        log_text.config(state="disabled")

    gui_handler = GUILogHandler()
    gui_handler.setLevel(logging.INFO)
    gui_handler.setFormatter(_fmt)
    logger.addHandler(gui_handler)

    # ====== GUI 定期更新 ======
    def poll_status():
        """エンジンからのステータス更新をGUIに反映"""
        try:
            while True:
                info = engine_to_gui_queue.get_nowait()
                if info.get("type") == "status":
                    mode = info.get("mode", "?")
                    paused = info.get("paused", False)
                    connected = info.get("connected", False)

                    mode_text = f"モード: {mode}"
                    if paused:
                        mode_text += " (一時停止中)"
                    sv_mode.set(mode_text)

                    if paused:
                        lbl_mode.config(fg=YELLOW)
                    elif mode == "TRADING":
                        lbl_mode.config(fg=RED)
                    else:
                        lbl_mode.config(fg=GREEN)

                    if connected:
                        sv_connection.set("接続: ✅ 接続中")
                        lbl_conn.config(fg=GREEN)
                    else:
                        sv_connection.set("接続: ❌ 未接続")
                        lbl_conn.config(fg=RED)

                    sv_ticks.set(f"受信ティック: {info.get('tick_count', 0)}")

                    syms = info.get("symbols", [])
                    if syms:
                        sym_names = []
                        for s in syms:
                            name = state.symbol_names.get(s, "")
                            sym_names.append(f"{s}({name})" if name else s)
                        sv_symbols.set(f"監視銘柄: {', '.join(sym_names)}")
                    else:
                        sv_symbols.set("監視銘柄: なし")

                    # ポジション
                    pos = info.get("position")
                    if pos:
                        sv_pos.set(
                            f"{pos['symbol']} | {pos['side'].upper()} x{pos['qty']} "
                            f"| 参入: {pos['entry_price']:.0f} → 現在: {pos['current_price']:.0f}"
                        )
                        pnl_val = pos["pnl"]
                        pnl_str = f"含み損益: {pnl_val:+,.0f}円"
                        sv_pnl.set(pnl_str)
                        lbl_pnl.config(fg=GREEN if pnl_val >= 0 else RED)
                        sv_elapsed.set(f"経過時間: {pos['elapsed']:.0f}秒")
                    else:
                        sv_pos.set("ポジションなし")
                        sv_pnl.set("")
                        lbl_pnl.config(fg=FG)
                        sv_elapsed.set("")

                    sv_stats.set(
                        f"取引回数: {info.get('total_trades', 0)} | "
                        f"累計P&L: {info.get('total_pnl', 0):+,.0f}円"
                    )

        except queue.Empty:
            pass
        except Exception:
            pass

        root.after(200, poll_status)

    poll_status()

    # ウィンドウを閉じるときの処理
    def on_closing():
        if messagebox.askokcancel("終了確認", "HFTシステムを終了しますか？"):
            logger.info("システム終了要求")
            root.destroy()
            os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------
def main():
    logger.info("=" * 50)
    logger.info("HFT トレーディングシステム 起動")
    logger.info(f"API: {KABUS_API_BASE_URL}")
    logger.info(f"WebSocket: {WS_URL}")
    logger.info(f"ログ: {HFT_LOG_DIR}")
    logger.info("=" * 50)

    # asyncio イベントループをバックグラウンドスレッドで起動
    def run_async_loop():
        try:
            asyncio.run(async_main())
        except Exception as e:
            logger.error(f"非同期ループエラー: {e}\n{traceback.format_exc()}")

    engine_thread = threading.Thread(target=run_async_loop, daemon=True)
    engine_thread.start()

    # メインスレッドで GUI を起動
    start_gui()


if __name__ == "__main__":
    main()