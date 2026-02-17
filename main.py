import requests
from bs4 import BeautifulSoup
import datetime
import time
import csv
import os
import random
import json
import threading
import queue
import sys
import getpass
import math
import shutil
import zipfile
import re
import unicodedata
import builtins
from typing import Optional, Tuple, Dict, Any, List

def _load_dotenv(path: str = ".env") -> None:
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip()
                if not key:
                    continue
                if (val.startswith("\"") and val.endswith("\"")) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                os.environ.setdefault(key, val)
    except Exception:
        return


# exe化時にも実行ファイルと同階層を基準にするためのベースディレクトリ
_BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

_load_dotenv(os.path.join(_BASE_DIR, ".env"))

# -----------------------------------------------------------------------------
# 定数・設定値の定義
# -----------------------------------------------------------------------------

# 監視したいキーワード（好材料と思われる単語）
# ここを自分の戦略に合わせて調整します
# TDnetの開示タイトルにこれらの単語が含まれている場合、監視対象に追加されます。
POSITIVE_KEYWORDS = [
    "上方修正",
    "増配",
    "復配",
    "株式分割",
    "自社株", # 自社株買いなど
    "提携",
    "M&A",
    "特別利益",
    "決算"
]

# 除外したいキーワード（悪材料、あるいはノイズと思われる単語）
# ポジティブキーワードが含まれていても、これらが含まれていれば無視します。
NEGATIVE_KEYWORDS = [
    "下方修正",
    "減配",
    "無配",
    "赤字",
    "業績予想の修正（減益",
    "取り下げ",
    "中止",
    "延期",
    "廃止",
    "不適切",
    "不正",
    "事故",
    "漏えい",
    "漏洩",
    "破産",
    "民事再生",
]

# TDnetの適時開示情報閲覧サービスのベースURL
TDNET_BASE_URL = "https://www.release.tdnet.info/inbs/"
# ログ保存用のディレクトリ名
LOG_DIR = os.path.join(_BASE_DIR, "logs")

# TDnetポーリング（定期確認）の基本間隔（秒）
BASE_POLL_SECONDS = 10
# ポーリング間隔の最大値（エラー時などのバックオフ用）
MAX_POLL_SECONDS = 300
# ポーリング間隔にランダム性を持たせるためのジッター（秒）
JITTER_SECONDS = 2
# HTTPリクエストのタイムアウト設定（秒）
REQUEST_TIMEOUT_SECONDS = 10
# TDnetから取得する最大ページ数（通常は1ページ目で十分だが、開示が多い日用）
MAX_PAGES = 20

# リクエストヘッダー（Webサイトへのアクセス時にブラウザのように振る舞うため）
REQUEST_HEADERS = {
    "User-Agent": "tdnet-monitor/1.0",
}

# KabuStation API（auカブコム証券）の接続設定
# 環境変数から取得し、なければデフォルト値を使用
KABUS_API_BASE_URL = os.environ.get("KABUS_API_BASE_URL", "http://localhost:18080")
KABUS_API_PASSWORD = (os.environ.get("KABUS_API_PASSWORD") or "").strip()
KABUS_EXCHANGE = os.environ.get("KABUS_EXCHANGE", "1") # 1: 東証

# 監視中の銘柄に対するポーリング間隔設定
WATCH_POLL_SECONDS = 1 # 場中（取引時間中）の更新間隔
WATCH_POLL_SECONDS_OFF_SESSION = float(os.environ.get("WATCH_POLL_SECONDS_OFF_SESSION", "10")) # 場外の更新間隔
WATCH_WINDOW_SECONDS = 180 # 開示検知から監視を続ける最大時間（秒）

# 早期ストップ条件（値動きがない場合に監視を早めに打ち切る設定）
WATCH_EARLY_STOP_SECONDS = float(os.environ.get("WATCH_EARLY_STOP_SECONDS", "60"))
WATCH_EARLY_STOP_PRICE_PCT = float(os.environ.get("WATCH_EARLY_STOP_PRICE_PCT", "0.2"))
WATCH_EARLY_STOP_VOLUME_MULT_DELTA = float(os.environ.get("WATCH_EARLY_STOP_VOLUME_MULT_DELTA", "0.05"))

# 出来高急増検知のための指数平滑移動平均(EMA)パラメータ
WATCH_VOLRATE_EMA_ALPHA = float(os.environ.get("WATCH_VOLRATE_EMA_ALPHA", "0.2"))
WATCH_VOLRATE_MIN_BASE = float(os.environ.get("WATCH_VOLRATE_MIN_BASE", "1.0"))
WATCH_VOLRATE_WINDOW_SECONDS = float(os.environ.get("WATCH_VOLRATE_WINDOW_SECONDS", "10"))

# 同時に監視する最大銘柄数（API制限回避のため）
WATCH_MAX_SYMBOLS = int(os.environ.get("WATCH_MAX_SYMBOLS", "8"))
# APIレートリミットにかかった場合の待機時間設定
WATCH_RATE_LIMIT_BACKOFF_BASE = float(os.environ.get("WATCH_RATE_LIMIT_BACKOFF_BASE", "5"))
WATCH_RATE_LIMIT_BACKOFF_MAX = float(os.environ.get("WATCH_RATE_LIMIT_BACKOFF_MAX", "60"))

# 自動発注に関する閾値設定
ORDER_MIN_PRICE_PCT = float(os.environ.get("ORDER_MIN_PRICE_PCT", "0.3")) # 最低限必要な価格変動率
ORDER_CONSECUTIVE_HITS = int(os.environ.get("ORDER_CONSECUTIVE_HITS", "2")) # 条件合致が何回続いたら発注するか

# デイトレ向き銘柄フィルタ（流動性とボラティリティのチェック）
ORDER_MIN_BASELINE_VOLUME = float(os.environ.get("ORDER_MIN_BASELINE_VOLUME", "50000")) # ベースライン出来高の最低値（普段から出来高がある銘柄のみ）
ORDER_MIN_PRICE_RANGE_PCT = float(os.environ.get("ORDER_MIN_PRICE_RANGE_PCT", "1.0")) # 監視期間中の最低価格変動幅(%)（継続的な値動きがある銘柄のみ）

# 急騰（Surge）判定の閾値
SURGE_PRICE_PCT = float(os.environ.get("SURGE_PRICE_PCT", "2")) # 価格上昇率(%)
SURGE_VOLUME_MULTIPLIER = float(os.environ.get("SURGE_VOLUME_MULTIPLIER", "2")) # 出来高倍率

# 急落（Crash）判定の閾値
CRASH_PRICE_PCT = float(os.environ.get("CRASH_PRICE_PCT", "2")) # 価格下落率(%)
CRASH_VOLUME_MULTIPLIER = float(os.environ.get("CRASH_VOLUME_MULTIPLIER", "2")) # 出来高倍率

# 寄り付き時間帯だけ閾値を高めにするための設定
OPENING_NOISE_ENABLE = (os.environ.get("OPENING_NOISE_ENABLE") or "1").strip() in {"1", "true", "True"}
OPENING_NOISE_START_HHMM = (os.environ.get("OPENING_NOISE_START_HHMM") or "09:00").strip()
OPENING_NOISE_END_HHMM = (os.environ.get("OPENING_NOISE_END_HHMM") or "09:30").strip()
OPENING_SURGE_PRICE_PCT = float(os.environ.get("OPENING_SURGE_PRICE_PCT", "3"))
OPENING_SURGE_VOLUME_MULTIPLIER = float(os.environ.get("OPENING_SURGE_VOLUME_MULTIPLIER", "4"))
OPENING_CRASH_PRICE_PCT = float(os.environ.get("OPENING_CRASH_PRICE_PCT", "3"))
OPENING_CRASH_VOLUME_MULTIPLIER = float(os.environ.get("OPENING_CRASH_VOLUME_MULTIPLIER", "4"))

# 後場寄り付き時間帯だけ閾値を高めにするための設定
PM_OPENING_NOISE_ENABLE = (os.environ.get("PM_OPENING_NOISE_ENABLE") or "1").strip() in {"1", "true", "True"}
PM_OPENING_NOISE_START_HHMM = (os.environ.get("PM_OPENING_NOISE_START_HHMM") or "12:30").strip()
PM_OPENING_NOISE_END_HHMM = (os.environ.get("PM_OPENING_NOISE_END_HHMM") or "13:00").strip()
PM_OPENING_SURGE_PRICE_PCT = float(os.environ.get("PM_OPENING_SURGE_PRICE_PCT", str(OPENING_SURGE_PRICE_PCT)))
PM_OPENING_SURGE_VOLUME_MULTIPLIER = float(os.environ.get("PM_OPENING_SURGE_VOLUME_MULTIPLIER", str(OPENING_SURGE_VOLUME_MULTIPLIER)))
PM_OPENING_CRASH_PRICE_PCT = float(os.environ.get("PM_OPENING_CRASH_PRICE_PCT", str(OPENING_CRASH_PRICE_PCT)))
PM_OPENING_CRASH_VOLUME_MULTIPLIER = float(os.environ.get("PM_OPENING_CRASH_VOLUME_MULTIPLIER", str(OPENING_CRASH_VOLUME_MULTIPLIER)))

# 寄り付き直後の発注抑止（前場/後場）
OPENING_ORDER_SUPPRESS_ENABLE = (os.environ.get("OPENING_ORDER_SUPPRESS_ENABLE") or "1").strip() in {"1", "true", "True"}
OPENING_ORDER_SUPPRESS_MINUTES = int(os.environ.get("OPENING_ORDER_SUPPRESS_MINUTES", "10"))

# GUIを有効にするかどうか
ENABLE_GUI = (os.environ.get("ENABLE_GUI") or "").strip() in {"1", "true", "True"}

# 起動時に設定入力を促すかどうか
PROMPT_CONFIG = (os.environ.get("PROMPT_CONFIG") or "").strip() in {"1", "true", "True"}

# 注文のデフォルト設定（環境変数から読み込み）
ORDER_MODE = (os.environ.get("ORDER_MODE") or "manual").strip().lower()  # auto: 自動発注 / manual: 手動
ORDER_SIDE_MODE = (os.environ.get("ORDER_SIDE_MODE") or "both").strip().lower()  # both/buy/sell
ORDER_CASH_MARGIN = (os.environ.get("ORDER_CASH_MARGIN") or "cash").strip().lower()  # cash: 現物 / margin: 信用
ORDER_TYPE = (os.environ.get("ORDER_TYPE") or "market").strip().lower()  # market: 成行 / limit_pct: 指値
ORDER_LIMIT_PCT = float(os.environ.get("ORDER_LIMIT_PCT", "1")) # 指値の場合の基準価格からの乖離率
ORDER_QTY = int(os.environ.get("ORDER_QTY", "100")) # 注文数量
ORDER_DRY_RUN = (os.environ.get("ORDER_DRY_RUN") or "1").strip() in {"1", "true", "True"} # Trueなら実際には発注しない
ORDER_CONFIRM = (os.environ.get("ORDER_CONFIRM") or "1").strip() in {"1", "true", "True"} # 発注前に確認ダイアログを出すか
ORDER_VOLUME_MULTIPLIER = float(os.environ.get("ORDER_VOLUME_MULTIPLIER", "3")) # 自動発注トリガーとなる出来高倍率
ORDER_PRICE_MIN = float(os.environ.get("ORDER_PRICE_MIN", "0"))   # 発注対象の株価下限（0=制限なし）
ORDER_PRICE_MAX = float(os.environ.get("ORDER_PRICE_MAX", "0"))   # 発注対象の株価上限（0=制限なし）
ORDER_BASE_VOLUME_MIN = float(os.environ.get("ORDER_BASE_VOLUME_MIN", "0"))  # 発注対象の出来高下限（0=制限なし）

# 自動決済設定
AUTO_EXIT_ENABLE = (os.environ.get("AUTO_EXIT_ENABLE") or "0").strip() in {"1", "true", "True"}
AUTO_EXIT_PROFIT_YEN_PER_100 = float(os.environ.get("AUTO_EXIT_PROFIT_YEN_PER_100", "1000"))
AUTO_EXIT_STOPLOSS_YEN_PER_100 = float(os.environ.get("AUTO_EXIT_STOPLOSS_YEN_PER_100", "500"))
AUTO_EXIT_STAGNATION_SECONDS = float(os.environ.get("AUTO_EXIT_STAGNATION_SECONDS", "120"))
AUTO_EXIT_STAGNATION_PRICE_PCT = float(os.environ.get("AUTO_EXIT_STAGNATION_PRICE_PCT", "0.2"))
AUTO_EXIT_STAGNATION_VOLUME_MULT = float(os.environ.get("AUTO_EXIT_STAGNATION_VOLUME_MULT", "1.05"))
AUTO_EXIT_STAGNATION_HITS = int(os.environ.get("AUTO_EXIT_STAGNATION_HITS", "5"))

# -----------------------------------------------------------------------------
# EDINET API 設定
# -----------------------------------------------------------------------------
# EDINET API v2 のサブスクリプションキー（金融庁サイトで取得）
EDINET_API_KEY = os.environ.get("EDINET_API_KEY", "")
# EDINET APIのベースURL
EDINET_API_BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"
# EDINETポーリング間隔（秒）。TDnetほどリアルタイムではないため長めに設定
EDINET_POLL_SECONDS = int(os.environ.get("EDINET_POLL_SECONDS", "60"))
# EDINET経由で検知した銘柄の監視時間（秒）。ニュースの浸透に時間がかかるため長め
EDINET_WATCH_WINDOW_SECONDS = int(os.environ.get("EDINET_WATCH_WINDOW_SECONDS", "600"))

# EDINET 監視対象の書類種別コード
EDINET_TARGET_DOCTYPES = [
    "150",  # 大量保有報告書
    "160",  # 変更報告書
    "230",  # 公開買付届出書
]

# EDINET 監視対象の提出者キーワード（VIPリスト）
# ここに含まれる名前が提出者名(filerName)に部分一致する場合のみ反応する
EDINET_VIP_KEYWORDS = [
    "光通信",
    "シティインデックス",
    "レオス",
    "ストラテジック",
    "エフィッシモ",
    "野村證券",
    # 特定の個人投資家名なども追加可能
]

EDINET_REQUIRE_VIP = (os.environ.get("EDINET_REQUIRE_VIP") or "0").strip() in {"1", "true", "True"}

# -----------------------------------------------------------------------------
# ニュースモニター設定
# -----------------------------------------------------------------------------
# みんかぶ材料ニュースURL
NEWS_MINKABU_URL = "https://minkabu.jp/news/search?category=stock"
# Yahoo!ファイナンス市況ニュースURL
#----NEWS_YAHOO_URL = "https://finance.yahoo.co.jp/news/market"
NEWS_YAHOO_URL = "https://finance.yahoo.co.jp/news/stocks?vip=on"
# ニュースポーリング間隔（秒）
NEWS_POLL_SECONDS = int(os.environ.get("NEWS_POLL_SECONDS", "45"))
# ニュースで「直近何分まで」を対象にするか（分）
NEWS_LOOKBACK_MINUTES = int(os.environ.get("NEWS_LOOKBACK_MINUTES", "30"))
NEWS_LOOKBACK_SECONDS = int(NEWS_LOOKBACK_MINUTES * 60)
# ニュース由来の銘柄の監視時間（秒）
NEWS_WATCH_WINDOW_SECONDS = int(os.environ.get("NEWS_WATCH_WINDOW_SECONDS", "300"))
# ニュース由来の銘柄の出来高倍率閾値を上げる倍率（ダマシ対策）
NEWS_VOLUME_MULT_FACTOR = float(os.environ.get("NEWS_VOLUME_MULT_FACTOR", "1.5"))
# 略称辞書JSONファイルパス
NEWS_ALIASES_PATH = os.environ.get("NEWS_ALIASES_PATH", os.path.join(_BASE_DIR, "aliases.json"))

# 通常は4桁数字だが、新市場等の 285A のような形式も許容する。
_MANUAL_SYMBOL_RE = re.compile(r"^(?:\d{4}|\d{3}[A-Za-z])$")
# 手動監視銘柄（最大5銘柄）。カンマ区切りで証券コードを指定。GUIからも設定可能。
MANUAL_WATCH_SYMBOLS_STR = os.environ.get("MANUAL_WATCH_SYMBOLS", "")
MANUAL_WATCH_SYMBOLS: List[str] = [
    s.strip().upper()
    for s in MANUAL_WATCH_SYMBOLS_STR.split(",")
    if s.strip() and _MANUAL_SYMBOL_RE.match(s.strip())
][:5]
# 手動監視銘柄の監視ウィンドウ（秒）。非常に長い値を設定して常時監視とする。
MANUAL_WATCH_WINDOW_SECONDS = float(os.environ.get("MANUAL_WATCH_WINDOW_SECONDS", "86400"))

# 11:30〜12:30に検知した材料は12:30にまとめて監視開始する（昼休みバッチ）
LUNCH_BATCH_ENABLE = (os.environ.get("LUNCH_BATCH_ENABLE") or "1").strip() not in {"0", "false", "False"}
LUNCH_BATCH_START_HHMM = (os.environ.get("LUNCH_BATCH_START_HHMM") or "11:30").strip()
LUNCH_BATCH_END_HHMM = (os.environ.get("LUNCH_BATCH_END_HHMM") or "12:30").strip()

# 0:00〜9:00に検知した当日材料は9:00にまとめて監視開始する（朝バッチ）
MORNING_BATCH_ENABLE = (os.environ.get("MORNING_BATCH_ENABLE") or "1").strip() not in {"0", "false", "False"}
MORNING_BATCH_START_HHMM = (os.environ.get("MORNING_BATCH_START_HHMM") or "00:00").strip()
MORNING_BATCH_END_HHMM = (os.environ.get("MORNING_BATCH_END_HHMM") or "09:00").strip()

# 15:30〜24:00は自動でwatchlistへ追加しない（情報収集のみ）
AFTERHOURS_ADD_STOP_ENABLE = (os.environ.get("AFTERHOURS_ADD_STOP_ENABLE") or "1").strip() not in {"0", "false", "False"}
AFTERHOURS_ADD_STOP_START_HHMM = (os.environ.get("AFTERHOURS_ADD_STOP_START_HHMM") or "15:30").strip()
AFTERHOURS_ADD_STOP_END_HHMM = (os.environ.get("AFTERHOURS_ADD_STOP_END_HHMM") or "24:00").strip()

# 特別買/売気配が続く銘柄は監視対象から外す
SPECIAL_QUOTE_REMOVE_STREAK = int(os.environ.get("SPECIAL_QUOTE_REMOVE_STREAK", "3"))

# EDINETコードリストCSVのパス（EDINETコード→証券コード変換用）
EDINET_CODE_LIST_PATH = os.environ.get("EDINET_CODE_LIST_PATH", os.path.join(_BASE_DIR, "EdinetcodeDlInfo.csv"))

# 材料キーワードリスト（ポジティブ/ネガティブ不問、変動が見込まれるもの全て）
VOLATILITY_KEYWORDS = [
    # --- 明確な好材料 ---
    "提携", "協業", "開発", "特許", "受注", "増配", "上方修正", "黒字化", "黒字", "増収", "増益",
    "自社株", "買収", "ＴＯＢ", "TOB", "株式分割", "株主優待",
    # --- 明確な悪材料 ---
    "下方修正", "減配", "減収", "赤字", "訴訟", "行政処分", "不適切", "監理銘柄",
    "上場廃止", "破産", "倒産", "更生法",
    # --- 相場用語（急動意） ---
    "急騰", "急落", "ストップ高", "ストップ安", "大幅高", "大幅安",
    "S高", "S安", "続伸", "続落", "急反発", "急反落", "商い伴い", "動意",
    # --- その他注目 ---
    "大量保有", "レーティング", "目標株価", "観測",
]

# ニュース取得用リクエストヘッダー（一般的なブラウザを模倣）
NEWS_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

def build_help_text() -> str:
    """GUIのヘルプ画面に表示する本文を生成する関数。
    
    Returns:
        str: ヘルプ画面用のテキスト全文。

    Note:
        - アプリの仕様変更時はここを修正してヘルプを最新化します。
    """
    lines = []
    lines.append("TDnet監視 / 自動売買 ヘルプ")
    lines.append("")
    lines.append("■ 概要")
    lines.append("- TDnetの好材料キーワードを監視し、該当銘柄を一定時間ウォッチします。")
    lines.append("- ウォッチ中の銘柄について、板情報から 価格変化率(%) と 出来高倍率 を計算します。")
    lines.append("- 条件に合致するとイベント表示を行い、モードが自動の場合は順張りで発注します。")
    lines.append("")
    lines.append("■ 注文設定")
    lines.append("- モード: 自動/手動")
    lines.append("- 売買: 両方/買いのみ/売りのみ")
    lines.append("- 取引区分: 現物/信用(新規)")
    lines.append("- 注文種類: 成行/指値(±%)")
    lines.append("- 数量(株): 発注株数")
    lines.append("- 出来高倍率: 自動発注トリガの閾値")
    lines.append("- DRY_RUN(テスト): ONで実発注せず内容表示のみ")
    lines.append("- 確認ダイアログ: ONで実行前に確認")
    lines.append("")
    lines.append("■ 手動発注")
    lines.append("- 直近銘柄に対し、価格変化率の符号で買い/売りを決めて発注します。")
    lines.append("  - price_pct>0 なら買い、price_pct<0 なら売り")
    lines.append("")
    lines.append("■ 自動発注（順張り）")
    lines.append("- 条件: モード=自動 かつ 出来高倍率>=閾値 かつ 売買フィルタに合致")
    lines.append("- 多重発注防止: 1銘柄につき自動発注は原則1回に抑止")
    lines.append("")
    lines.append("■ 注意")
    lines.append("- 実運用は必ず小ロット/DRY_RUNで十分に検証してください。")
    return "\n".join(lines)

# CSVログのカラム定義
CSV_FIELDNAMES = [
    "date",
    "time",
    "code",
    "name",
    "title",
    "pdf_url",
    "xbrl_url",
    "place",
]

WATCH_LOG_FIELDNAMES = [
    "datetime",
    "tdnet_key",
    "symbol",
    "source",
    "filer_name",
    "doc_description",
    "status",
    "price",
    "volume",
    "baseline_price",
    "baseline_volume",
    "price_pct",
    "volume_mult",
    "triggered",
]

EVENT_LOG_FIELDNAMES = [
    "datetime",
    "event_type",
    "tdnet_key",
    "symbol",
    "price",
    "volume",
    "baseline_price",
    "baseline_volume",
    "price_pct",
    "volume_mult",
]

EDINET_LOG_FIELDNAMES = [
    "datetime",
    "doc_id",
    "doc_type_code",
    "doc_description",
    "filer_name",
    "edinet_code",
    "sec_code",
    "symbol",
    "vip_keyword",
]

NEWS_LOG_FIELDNAMES = [
    "datetime",
    "source",
    "title",
    "url",
    "symbol",
    "matched_keyword",
    "matched_name",
    "published_ts",
]

ORDER_LOG_FIELDNAMES = [
    "datetime",
    "symbol",
    "side",
    "qty",
    "order_type",
    "limit_price",
    "cash_margin",
    "reason",
    "dry_run",
    "status",
    "result",
    "payload",
]

# 日本標準時のタイムゾーン定義
JST = datetime.timezone(datetime.timedelta(hours=9))

def get_market_phase_jp(now: Optional[datetime.datetime] = None) -> str:
    """現在の日時から、日本の株式市場の状態（開場中、昼休み、閉場）を判定する関数。

    Args:
        now (datetime.datetime, optional): 判定基準とする日時。Noneの場合は現在時刻。

    Returns:
        str: "open" (場中), "lunch" (昼休み), "closed" (場外), "holiday" (休日)
    """
    dt = now or datetime.datetime.now(JST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)

    if dt.weekday() >= 5: # 土日判定
        return "holiday"

    t = dt.timetz()
    # 前場
    if datetime.time(9, 0, tzinfo=JST) <= t < datetime.time(11, 30, tzinfo=JST):
        return "open"
    # 後場
    if datetime.time(12, 30, tzinfo=JST) <= t < datetime.time(15, 30, tzinfo=JST):
        return "open"
    # 昼休み
    if datetime.time(11, 30, tzinfo=JST) <= t < datetime.time(12, 30, tzinfo=JST):
        return "lunch"
    return "closed"

def get_watch_poll_seconds(now: Optional[datetime.datetime] = None) -> float:
    """市場の状態に応じて、適切な監視（ポーリング）間隔を返す関数。

    Args:
        now (datetime.datetime, optional): 判定基準日時。

    Returns:
        float: ポーリング間隔（秒）。場中は短く、場外は長くなる。
    """
    phase = get_market_phase_jp(now)
    if phase == "open":
        return float(WATCH_POLL_SECONDS)
    return float(WATCH_POLL_SECONDS_OFF_SESSION)

def append_csv_log(row: Dict[str, str], date_yyyymmdd: str) -> None:
    """TDnetの開示情報をCSVファイルに追記保存する関数。

    Args:
        row (Dict[str, str]): 保存するデータ（辞書形式）。
        date_yyyymmdd (str): ファイル名に使用する日付文字列。
    """
    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    os.makedirs(date_dir, exist_ok=True)
    log_path = os.path.join(date_dir, f"tdnet_{date_yyyymmdd}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in CSV_FIELDNAMES})

def append_watch_log(row: Dict[str, Any], date_yyyymmdd: str) -> None:
    """監視中の銘柄の詳細なステータス（価格、出来高など）をCSVに保存する関数。
    
    銘柄ごとにサブディレクトリを作成して保存します。
    
    Args:
        row (Dict[str, Any]): 保存するデータ。
        date_yyyymmdd (str): 日付文字列。
    """
    symbol = str(row.get("symbol") or "").strip()
    if not symbol:
        return

    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    watch_dir = os.path.join(date_dir, "watch")
    os.makedirs(watch_dir, exist_ok=True)

    log_path = os.path.join(watch_dir, f"{symbol}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=WATCH_LOG_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in WATCH_LOG_FIELDNAMES})

def append_event_log(row: Dict[str, Any], date_yyyymmdd: str) -> None:
    """急騰・急落などのイベント発生情報をCSVに保存する関数。

    Args:
        row (Dict[str, Any]): イベントデータ。
        date_yyyymmdd (str): 日付文字列。
    """
    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    os.makedirs(date_dir, exist_ok=True)
    log_path = os.path.join(date_dir, f"trade_events_{date_yyyymmdd}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENT_LOG_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in EVENT_LOG_FIELDNAMES})

def append_edinet_log(row: Dict[str, Any], date_yyyymmdd: str) -> None:
    """EDINETの書類情報をCSVに保存する関数。

    Args:
        row (Dict[str, Any]): 書類データ。
        date_yyyymmdd (str): 日付文字列。
    """
    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    os.makedirs(date_dir, exist_ok=True)
    log_path = os.path.join(date_dir, f"edinet_{date_yyyymmdd}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EDINET_LOG_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in EDINET_LOG_FIELDNAMES})

def append_news_log(row: Dict[str, Any], date_yyyymmdd: str) -> None:
    """ニュース情報をCSVに保存する関数。

    Args:
        row (Dict[str, Any]): ニュースデータ。
        date_yyyymmdd (str): 日付文字列。
    """
    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    os.makedirs(date_dir, exist_ok=True)
    log_path = os.path.join(date_dir, f"news_{date_yyyymmdd}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_LOG_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in NEWS_LOG_FIELDNAMES})

def append_order_log(row: Dict[str, Any], date_yyyymmdd: str) -> None:
    """発注の実行ログ（リクエスト内容・APIレスポンス）をCSVに保存する関数。

    Args:
        row (Dict[str, Any]): 発注データ。
        date_yyyymmdd (str): 日付文字列。
    """
    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    os.makedirs(date_dir, exist_ok=True)
    log_path = os.path.join(date_dir, f"order_{date_yyyymmdd}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ORDER_LOG_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in ORDER_LOG_FIELDNAMES})

def make_unique_key(item: Dict[str, str]) -> str:
    """開示情報の重複チェック用ユニークキーを生成する関数。
    
    基本はPDFのURLを使用し、URLがない場合は日時やコードを組み合わせてキーとします。

    Args:
        item (Dict[str, str]): TDnetの開示項目。

    Returns:
        str: ユニークキー文字列。
    """
    pdf_url = (item.get("pdf_url") or "").strip()
    if pdf_url:
        return pdf_url
    return f"{item.get('date','')}_{item.get('time','')}_{item.get('code','')}_{item.get('title','')}"

def load_processed_keys(date_yyyymmdd: str) -> set:
    """指定された日付のログファイルを読み込み、処理済みのユニークキー一覧を取得する関数。
    
    これにより、プログラム再起動時などに同じニュースを重複して検知するのを防ぎます。

    Args:
        date_yyyymmdd (str): 読み込む日付。

    Returns:
        set: 処理済みキーのセット。
    """
    log_path = os.path.join(LOG_DIR, date_yyyymmdd, f"tdnet_{date_yyyymmdd}.csv")
    if not os.path.exists(log_path):
        return set()

    processed = set()
    try:
        with open(log_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                processed.add(make_unique_key(row))
    except Exception:
        return set()

    return processed

def fetch_tdnet_list_html(date_yyyymmdd: str, page: int):
    """TDnetのWebサイトから指定された日付・ページ番号のHTMLを取得する関数。

    Args:
        date_yyyymmdd (str): 取得する日付 (例: "20231001")。
        page (int): ページ番号。

    Returns:
        tuple: (HTMLテキスト, ステータスコード, Retry-After秒数)
    """
    url = f"https://www.release.tdnet.info/inbs/I_list_{page:03d}_{date_yyyymmdd}.html"
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    response.encoding = response.apparent_encoding

    if response.status_code == 404:
        if page == 1:
            print(f"Error: {response.status_code}")
            return [], response.status_code, 0
        return [], response.status_code, 0

    if response.status_code != 200:
        retry_after = 0
        try:
            retry_after = int(response.headers.get("Retry-After", "0"))
        except ValueError:
            retry_after = 0
        return None, response.status_code, retry_after

    return response.text, 200, 0

def normalize_tdnet_code_to_symbol(code: str) -> str:
    """TDnetの証券コード（末尾に0がついている場合がある）を、KabuStation API形式に正規化する関数。
    
    例: "72030" -> "7203"

    Args:
        code (str): 元の証券コード。

    Returns:
        str: 正規化された証券コード。
    """
    c = (code or "").strip()
    if not c:
        return ""

    if len(c) == 5 and c.endswith("0"):
        return c[:-1]
    return c

# -----------------------------------------------------------------------------
# EDINET 関連関数
# -----------------------------------------------------------------------------

def load_edinet_code_map(csv_path: str = "") -> Dict[str, str]:
    """EDINETコードリストCSVを読み込み、EDINETコード→証券コードの変換Mapを返す関数。

    CSVは金融庁EDINETサイトからダウンロードした「EdinetcodeDlInfo.csv」を想定。
    ヘッダー行が2行ある場合にも対応（1行目スキップ）。

    Args:
        csv_path (str): CSVファイルパス。空の場合はEDINET_CODE_LIST_PATHを使用。

    Returns:
        Dict[str, str]: {EDINETコード: 証券コード} の辞書。
    """
    path = csv_path or EDINET_CODE_LIST_PATH
    code_map: Dict[str, str] = {}

    if not os.path.exists(path):
        print(f"[EDINET] コードリストCSVが見つかりません: {path}")
        return code_map

    try:
        last_err: Optional[Exception] = None
        for enc in ("utf-8-sig", "cp932"):
            try:
                tmp_map: Dict[str, str] = {}
                with open(path, "r", encoding=enc, errors="replace") as f:
                    reader = csv.reader(f)
                    header = None
                    edinet_col = None
                    sec_col = None
                    for i, row in enumerate(reader):
                        # 最初の数行でヘッダーを探す
                        if header is None:
                            # 「ＥＤＩＮＥＴコード」または「EDINETコード」を含む行をヘッダーとする
                            joined = "".join(row)
                            if "EDINETコード" in joined or "ＥＤＩＮＥＴコード" in joined or "edinetCode" in joined.lower():
                                header = row
                                # カラムインデックスを特定
                                for ci, cell in enumerate(header):
                                    cell_n = cell.strip().replace("　", "").replace(" ", "")
                                    if "EDINETコード" in cell_n or "ＥＤＩＮＥＴコード" in cell_n:
                                        edinet_col = ci
                                    if "証券コード" in cell_n or "銘柄コード" in cell_n:
                                        sec_col = ci
                                if edinet_col is None or sec_col is None:
                                    edinet_col = 0
                                    sec_col = 6

                        if edinet_col is None or sec_col is None:
                            e_idx = None
                            s_idx = None
                            for ci, cell in enumerate(row):
                                v = (cell or "").strip().strip("\"")
                                if e_idx is None and len(v) == 6 and v.startswith("E") and v[1:].isdigit():
                                    e_idx = ci

                            for ci, cell in enumerate(row):
                                v = (cell or "").strip().strip("\"")
                                if v.isdigit() and (len(v) == 4 or len(v) == 5):
                                    s_idx = ci

                            if e_idx is None or s_idx is None:
                                continue

                            e_code = (row[e_idx] or "").strip().strip("\"")
                            s_code = (row[s_idx] or "").strip().strip("\"")
                        else:
                            if len(row) <= max(edinet_col, sec_col):
                                continue

                            e_code = row[edinet_col].strip().strip("\"")
                            s_code = row[sec_col].strip().strip("\"")

                        if not e_code or not s_code:
                            continue

                        s_code = s_code.replace("-", "").replace(" ", "")
                        if len(s_code) == 5 and s_code.endswith("0"):
                            s_code = s_code[:-1]

                        if len(s_code) == 4 and s_code.isdigit():
                            tmp_map[e_code] = s_code

                if tmp_map:
                    code_map = tmp_map
                    break
            except Exception as e:
                last_err = e
                continue

        if not code_map and last_err is not None:
            raise last_err

        print(f"[EDINET] コードリスト読み込み完了: {len(code_map)} 件")
    except Exception as e:
        print(f"[EDINET] コードリスト読み込みエラー: {e}")

    return code_map


def fetch_edinet_documents(date_str: str) -> Tuple[list, int]:
    """EDINET API v2 から指定日の書類一覧（メタデータ）を取得する関数。

    Args:
        date_str (str): 取得する日付 (YYYY-MM-DD形式)。

    Returns:
        tuple: (書類リスト, HTTPステータスコード)
    """
    if not EDINET_API_KEY:
        return [], 0

    url = f"{EDINET_API_BASE_URL}/documents.json"
    params = {
        "date": date_str,
        "type": 2,
        "Subscription-Key": EDINET_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS + 10)
        if resp.status_code != 200:
            print(f"[EDINET] API error: status={resp.status_code}")
            return [], resp.status_code

        data = resp.json()
        results = data.get("results", [])
        if results is None:
            results = []
        return results, 200

    except requests.exceptions.Timeout:
        print("[EDINET] API timeout")
        return [], 408
    except Exception as e:
        print(f"[EDINET] API error: {e}")
        return [], 0


def filter_edinet_documents(documents: list, edinet_code_map: Dict[str, str]) -> list:
    """EDINET書類一覧を書類種別・提出者名でフィルタリングし、証券コードを付与する関数。

    フィルタ条件:
    1. docTypeCode が EDINET_TARGET_DOCTYPES に含まれる
    2. filerName が EDINET_VIP_KEYWORDS のいずれかに部分一致する

    Args:
        documents (list): EDINET APIから取得した書類メタデータのリスト。
        edinet_code_map (Dict[str, str]): EDINETコード→証券コード変換マップ。

    Returns:
        list: フィルタ条件に合致した書類のリスト（証券コード付き）。
    """
    matched = []

    for doc in documents:
        doc_type = str(doc.get("docTypeCode") or "").strip()
        filer_name = str(doc.get("filerName") or "").strip()
        doc_id = str(doc.get("docID") or "").strip()
        doc_description = str(doc.get("docDescription") or "").strip()
        edinet_code = str(doc.get("edinetCode") or "").strip()
        sec_code_raw = str(doc.get("secCode") or "").strip()

        # 1. 書類種別フィルタ
        if doc_type not in EDINET_TARGET_DOCTYPES:
            continue

        # 2. VIPキーワードフィルタ（提出者名の部分一致）
        matched_keyword = ""
        for kw in EDINET_VIP_KEYWORDS:
            if kw in filer_name:
                matched_keyword = kw
                break

        if EDINET_REQUIRE_VIP and not matched_keyword:
            continue

        # 3. 証券コードの解決
        # まずAPIレスポンスのsecCodeを試す
        symbol = ""
        if sec_code_raw and sec_code_raw != "null":
            sc = sec_code_raw.replace("-", "").replace(" ", "")
            if len(sc) == 5 and sc.endswith("0"):
                sc = sc[:-1]
            if len(sc) == 4 and sc.isdigit():
                symbol = sc

        # secCodeが取れない場合、EDINETコードから変換
        if not symbol and edinet_code:
            symbol = edinet_code_map.get(edinet_code, "")

        # 対象発行会社のEDINETコード（subjectEdinetCode）からも試す
        if not symbol:
            subject_edinet = str(doc.get("subjectEdinetCode") or "").strip()
            if subject_edinet:
                symbol = edinet_code_map.get(subject_edinet, "")

        matched.append({
            "doc_id": doc_id,
            "doc_type_code": doc_type,
            "doc_description": doc_description,
            "filer_name": filer_name,
            "edinet_code": edinet_code,
            "sec_code": sec_code_raw,
            "symbol": symbol,
            "vip_keyword": matched_keyword,
        })

    return matched


def append_edinet_log(row: Dict[str, Any], date_yyyymmdd: str) -> None:
    """EDINET検知情報をCSVファイルに追記保存する関数。

    Args:
        row (Dict[str, Any]): 保存するデータ。
        date_yyyymmdd (str): ファイル名に使用する日付文字列。
    """
    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    os.makedirs(date_dir, exist_ok=True)
    log_path = os.path.join(date_dir, f"edinet_{date_yyyymmdd}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EDINET_LOG_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in EDINET_LOG_FIELDNAMES})


def load_edinet_processed_keys(date_yyyymmdd: str) -> set:
    """指定された日付のEDINETログファイルから処理済みdocIDの一覧を取得する関数。

    Args:
        date_yyyymmdd (str): 読み込む日付。

    Returns:
        set: 処理済みdocIDのセット。
    """
    log_path = os.path.join(LOG_DIR, date_yyyymmdd, f"edinet_{date_yyyymmdd}.csv")
    if not os.path.exists(log_path):
        return set()

    processed = set()
    try:
        with open(log_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                doc_id = (row.get("doc_id") or "").strip()
                if doc_id:
                    processed.add(doc_id)
    except Exception:
        return set()

    return processed


# -----------------------------------------------------------------------------
# ニュースモニター関連関数
# -----------------------------------------------------------------------------

def parse_news_published_ts(text: str, now_dt: Optional[datetime.datetime] = None) -> Optional[float]:
    """ニュース一覧ページ上の時刻文字列から epoch 秒を推定する関数。

    サイトにより「12分前」「2時間前」「2026/02/11 15:04」「15:04」等の表記が混在するため、
    可能な範囲で解釈して epoch 秒に変換する。

    Args:
        text (str): 時刻文字列。
        now_dt (datetime.datetime, optional): 相対時刻の基準。Noneの場合は現在時刻。

    Returns:
        Optional[float]: epoch秒。解釈できない場合はNone。
    """
    s = (text or "").strip()
    if not s:
        return None

    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = now_dt or datetime.datetime.now(jst)

    m = re.search(r"(\d+)\s*分前", s)
    if m:
        mins = int(m.group(1))
        return (now - datetime.timedelta(minutes=mins)).timestamp()

    m = re.search(r"(\d+)\s*時間前", s)
    if m:
        hrs = int(m.group(1))
        return (now - datetime.timedelta(hours=hrs)).timestamp()

    m = re.search(r"(\d+)\s*日前", s)
    if m:
        days = int(m.group(1))
        return (now - datetime.timedelta(days=days)).timestamp()

    # 例: 2026/02/11 15:04
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(s, fmt).replace(tzinfo=jst)
            return dt.timestamp()
        except Exception:
            pass

    # 例: "今日 11:07" or "今日 11:07"（みんかぶ形式）
    m = re.search(r"今日\s*(\d{1,2}):(\d{2})", s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return dt.timestamp()

    # 例: "昨日 15:04"
    m = re.search(r"昨日\s*(\d{1,2}):(\d{2})", s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        dt = (now - datetime.timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        return dt.timestamp()

    # 例: 15:04（当日扱い）
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return dt.timestamp()

    return None


def extract_news_published_ts(a_tag: Any, fallback_dt: Optional[datetime.datetime] = None) -> Optional[float]:
    """記事リンク周辺のHTMLから掲載時刻を推定して epoch 秒を返す関数。"""
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now = fallback_dt or datetime.datetime.now(jst)

    try:
        scope = a_tag
        if hasattr(a_tag, "find_parent"):
            # みんかぶは時刻がタイトルaタグの直上divではなく、同じ<li>内の別<div>にあることが多い。
            # そのため<li>を最優先にスコープとし、見つからなければ広めに辿る。
            parent = a_tag.find_parent("li")
            if parent is None:
                parent = a_tag.find_parent("article")
            if parent is None:
                parent = a_tag.find_parent("div")
            if parent is not None:
                scope = parent

        # <time datetime="..."> を優先
        time_el = scope.find("time") if hasattr(scope, "find") else None
        if time_el is not None:
            dt_attr = (time_el.get("datetime") or "").strip()
            if dt_attr:
                # ISOっぽい形式をざっくり対応
                try:
                    dt_attr2 = dt_attr.replace("Z", "+00:00")
                    dt = datetime.datetime.fromisoformat(dt_attr2)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=jst)
                    else:
                        dt = dt.astimezone(jst)
                    return dt.timestamp()
                except Exception:
                    pass

            txt = time_el.get_text(strip=True)
            ts = parse_news_published_ts(txt, now_dt=now)
            if ts is not None:
                return ts

        # それ以外の時刻っぽいテキスト
        for cand in scope.find_all(["span", "div", "i"], limit=10):
            t = cand.get_text(" ", strip=True)
            if not t:
                continue
            if "前" in t or ":" in t or "/" in t or "-" in t or "今日" in t or "昨日" in t:
                ts = parse_news_published_ts(t, now_dt=now)
                if ts is not None:
                    return ts

        # 最後のフォールバック: 親要素のテキスト全体から時刻っぽい部分を抽出
        all_txt = scope.get_text(" ", strip=True) if hasattr(scope, "get_text") else ""
        if all_txt:
            m = re.search(
                r"(今日\s*\d{1,2}:\d{2}|昨日\s*\d{1,2}:\d{2}|\d+\s*分前|\d+\s*時間前|\d+\s*日前|\d{1,2}:\d{2}|\d{4}[/-]\d{2}[/-]\d{2}\s+\d{1,2}:\d{2})",
                all_txt,
            )
            if m:
                ts = parse_news_published_ts(m.group(1), now_dt=now)
                if ts is not None:
                    return ts
    except Exception:
        return None

    return None


def load_news_aliases(path: str = "") -> Dict[str, str]:
    """手動略称辞書（aliases.json）を読み込む関数。

    Args:
        path (str): JSONファイルパス。空の場合はNEWS_ALIASES_PATHを使用。

    Returns:
        Dict[str, str]: {略称: 証券コード} の辞書。
    """
    fpath = path or NEWS_ALIASES_PATH
    if not os.path.exists(fpath):
        print(f"[NEWS] 略称辞書ファイルが見つかりません: {fpath}")
        return {}

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 空文字の値（メガバンク等）は除外
        result = {k: v for k, v in data.items() if v}
        print(f"[NEWS] 略称辞書読み込み完了: {len(result)} 件")
        return result
    except Exception as e:
        print(f"[NEWS] 略称辞書読み込みエラー: {e}")
        return {}


def build_stock_name_dict(token: Optional[str] = None) -> Dict[str, str]:
    """KabuStation APIの銘柄マスタから略称辞書を自動生成する関数。

    正式名称から法人格（株式会社、ホールディングス、グループ等）を削除して
    略称キーとして登録する。

    Args:
        token (str, optional): KabuStation APIトークン。Noneの場合は空辞書を返す。

    Returns:
        Dict[str, str]: {略称: 証券コード} の辞書。
    """
    if not token:
        return {}

    # 削除対象の法人格・サフィックス
    STRIP_SUFFIXES = [
        "株式会社", "(株)", "（株）", "ホールディングス", "ＨＤ", "HD",
        "グループ", "フィナンシャル・グループ", "フィナンシャルグループ",
        "・", "　",
    ]

    name_dict: Dict[str, str] = {}

    # 主要な市場コード（東証プライム等）の銘柄を取得
    # KabuStation APIの /kabusapi/symbolname/all は存在しないため、
    # 個別取得は非効率。ここでは空辞書を返し、aliases.jsonに依存する。
    # 将来的にAPIが銘柄一覧を返すようになったら拡張可能。
    print("[NEWS] 銘柄名辞書の自動生成はaliases.jsonに依存します")

    return name_dict


def normalize_stock_name(name: str) -> str:
    """正式名称から法人格等を削除して略称を生成する関数。

    Args:
        name (str): 正式名称。

    Returns:
        str: 正規化された略称。
    """
    result = name.strip()
    for suffix in ["株式会社", "(株)", "（株）", "ホールディングス", "ＨＤ", "HD",
                    "グループ", "フィナンシャル・グループ", "フィナンシャルグループ"]:
        result = result.replace(suffix, "")
    result = result.strip("・ 　\t\r\n")
    # 短すぎるものは除外
    if len(result) < 2:
        return ""
    return result


def resolve_symbol_from_title(title: str, name_dict: Dict[str, str]) -> Tuple[str, str]:
    """記事タイトルから略称辞書を使って銘柄コードを特定する関数。

    辞書のキーが長い順にマッチングし、最初にヒットしたものを返す。

    Args:
        title (str): 記事タイトル。
        name_dict (Dict[str, str]): {略称: 証券コード} の辞書。

    Returns:
        Tuple[str, str]: (証券コード, マッチした略称名)。見つからない場合は ("", "")。
    """
    # 長いキーから順にマッチング（短いキーの誤マッチを防ぐ）
    for key in sorted(name_dict.keys(), key=len, reverse=True):
        if key in title:
            return name_dict[key], key
    return "", ""


def load_edinet_company_code_index(path: str) -> List[Tuple[str, str]]:
    """EdinetcodeDlInfo.csv から (会社名, 証券コード) のインデックスを作る（雑一致用）。"""
    if not path or (not os.path.exists(path)):
        return []

    rows: List[Tuple[str, str]] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for r in reader:
                if not r or len(r) < 12:
                    continue
                # col12 (インデックス11) = 証券コード、末尾の0を除去
                sec_raw = (r[11] or "").strip()
                name_jp = (r[6] or "").strip()
                if not sec_raw or not name_jp:
                    continue
                # 末尾の0を除去 (例: 72030 -> 7203)
                sec = sec_raw.rstrip("0")
                if not sec or not sec.isdigit():
                    continue
                rows.append((name_jp, sec))
    except Exception:
        return []

    return rows


def extract_company_fragment_from_yahoo_title(title: str) -> str:
    """Yahooニュースのタイトル先頭から会社名断片を抽出する（EDINET雑一致用）。"""
    t = (title or "").strip()
    if not t:
        return ""
    
    # 全角英数字などを正規化（例: "ＮＸＨ" -> "NXH"）
    t = unicodedata.normalize("NFKC", t).strip()

    # タイトル先頭の「【...】」や「[...]」を（連続していても）除去
    while True:
        t2 = re.sub(r"^[\[【\(（].*?[\]】\)）]", "", t).strip()
        if t2 == t:
            break
        t = t2

    # 指定の区切り文字が含まれる場合は、それ以前を会社名断片として優先採用
    # 例: "加藤製が急騰" -> "加藤製", "Abalance－ストップ安" -> "Abalance"
    cut_seps = ["---", "－", "ー", "、", "が"]
    cut_positions = [t.find(sep) for sep in cut_seps if sep and (sep in t)]
    if cut_positions:
        pos = min(p for p in cut_positions if p >= 0)
        frag = t[:pos].strip()
        if frag:
            frag = re.sub(r"[\[\]【】\(\)（）]", "", frag).strip()
            if frag:
                return frag
    
    # タイトル先頭の空白で区切られた最初の部分を会社名断片として取得
    # 「銘柄名 ニュースタイトル...」の形式を想定
    # まず、「、」「,」「：」「:」「/」「|」「｜」などの区切りで分割
    for sep in ["、", ",", "：", ":", "/", "|", "｜", " "]:
        if sep in t:
            parts = t.split(sep)
            for part in parts:
                frag = part.strip()
                if frag:
                    # 英数字のみの断片は確定させる
                    if re.match(r'^[A-Za-z0-9\-\.]+$', frag):
                        return frag
                    # 英数字や記号のみの断片はスキップ
                    if re.match(r'^[\sA-Za-z0-9\-\.]+$', frag):
                        continue
                    # 2文字以上の日本語/漢字を含む断片を採用
                    if len(frag) >= 2 and re.search(r'[\u4e00-\u9fffぁ-んァ-ン]', frag):
                        # 括弧や記号を除去
                        frag = re.sub(r"[\[\]【】\(\)（）]", "", frag).strip()
                        return frag
    
    # フォールバック: 先頭の数単語を取得
    words = t.split()
    for word in words[:3]:  # 先頭3単語までチェック
        frag = word.strip("【】[]()（）")
        # 英数字や記号のみはスキップ
        if re.match(r'^[\sA-Za-z0-9\-\.]+$', frag):
            continue
        if len(frag) >= 2:
            return frag
    
    return ""


def resolve_symbol_from_edinet_company_fragment(fragment: str, index_rows: List[Tuple[str, str]]) -> Tuple[str, str]:
    """会社名断片からEDINET会社名の部分一致で証券コードを返す（雑一致）。"""
    frag = (fragment or "").strip()
    if not frag or not index_rows:
        return "", ""
    for name_jp, sec in index_rows:
        if frag in name_jp:
            return sec, name_jp
    return "", ""


def get_company_name_from_symbol(symbol: str, index_rows: List[Tuple[str, str]]) -> str:
    """EDINETインデックスから証券コードに対応する会社名を返す。"""
    if not symbol or not index_rows:
        return ""
    sym = str(symbol).strip()
    for name_jp, sec in index_rows:
        if sec == sym:
            return name_jp
    return ""


def notify_watchlist_change(watchlist: Dict[str, Any], edinet_company_index: List[Tuple[str, str]], event_queue: "queue.Queue") -> None:
    """watchlistの変更をGUIに通知する。"""
    if not watchlist:
        try:
            event_queue.put_nowait({"kind": "watch", "count": 0})
            event_queue.put_nowait({"kind": "watching_symbols", "text": "-"})
            event_queue.put_nowait({"kind": "watching_symbols_full", "symbols": []})
        except Exception:
            pass
        return
    
    symbols_info = []
    symbols_full: List[Tuple[str, str]] = []
    for sym in sorted(watchlist.keys()):
        state = watchlist[sym]
        company_name = str(state.get("company_name") or "").strip() or get_company_name_from_symbol(sym, edinet_company_index)
        source = state.get("source", "")
        symbols_full.append((sym, company_name or str(source or "").strip()))
        if company_name:
            symbols_info.append(f"{sym}({company_name[:8]})" if len(company_name) > 8 else f"{sym}({company_name})")
        else:
            symbols_info.append(f"{sym}({source})")
    
    text = ", ".join(symbols_info[:10])  # 最大10銘柄表示
    if len(symbols_info) > 10:
        text += f" ...他{len(symbols_info) - 10}銘柄"
    
    try:
        event_queue.put_nowait({"kind": "watch", "count": len(watchlist)})
        event_queue.put_nowait({"kind": "watching_symbols", "text": text})
        event_queue.put_nowait({"kind": "watching_symbols_full", "symbols": symbols_full})
    except Exception:
        pass


def _parse_hhmm(s: str) -> Tuple[int, int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", (s or "").strip())
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def _in_hhmm_window(now_dt: datetime.datetime, start_hhmm: str, end_hhmm: str) -> bool:
    jst = datetime.timezone(datetime.timedelta(hours=9))
    nd = now_dt.astimezone(jst) if now_dt.tzinfo else now_dt.replace(tzinfo=jst)
    sh, sm = _parse_hhmm(start_hhmm)
    eh, em = _parse_hhmm(end_hhmm)
    start = nd.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = nd.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end <= start:
        return False
    return (start <= nd < end)


def get_surge_crash_thresholds(now_dt: datetime.datetime) -> Tuple[float, float, float, float]:
    if OPENING_NOISE_ENABLE and _in_hhmm_window(now_dt, OPENING_NOISE_START_HHMM, OPENING_NOISE_END_HHMM):
        return (
            float(OPENING_SURGE_PRICE_PCT),
            float(OPENING_SURGE_VOLUME_MULTIPLIER),
            float(OPENING_CRASH_PRICE_PCT),
            float(OPENING_CRASH_VOLUME_MULTIPLIER),
        )
    if PM_OPENING_NOISE_ENABLE and _in_hhmm_window(now_dt, PM_OPENING_NOISE_START_HHMM, PM_OPENING_NOISE_END_HHMM):
        return (
            float(PM_OPENING_SURGE_PRICE_PCT),
            float(PM_OPENING_SURGE_VOLUME_MULTIPLIER),
            float(PM_OPENING_CRASH_PRICE_PCT),
            float(PM_OPENING_CRASH_VOLUME_MULTIPLIER),
        )
    return (
        float(SURGE_PRICE_PCT),
        float(SURGE_VOLUME_MULTIPLIER),
        float(CRASH_PRICE_PCT),
        float(CRASH_VOLUME_MULTIPLIER),
    )


def is_lunch_batch_window(now_dt: datetime.datetime) -> Tuple[bool, float]:
    """今が昼休みバッチの『溜め込み期間』かどうかと、バッチ解放時刻(epoch)を返す。"""
    if not LUNCH_BATCH_ENABLE:
        return False, 0.0

    jst = datetime.timezone(datetime.timedelta(hours=9))
    nd = now_dt.astimezone(jst) if now_dt.tzinfo else now_dt.replace(tzinfo=jst)
    sh, sm = _parse_hhmm(LUNCH_BATCH_START_HHMM)
    eh, em = _parse_hhmm(LUNCH_BATCH_END_HHMM)
    start = nd.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = nd.replace(hour=eh, minute=em, second=0, microsecond=0)
    if end <= start:
        return False, 0.0
    in_window = (start <= nd < end)
    return in_window, end.timestamp()


def detect_special_quote_side(board: Dict[str, Any]) -> str:
    """板情報から特別買/売気配を推定する（取得できなければ空文字）。"""
    # 文字列系フィールドに「特別買」「特別売」が入るパターンを優先
    for k in (
        "CurrentPriceStatus",
        "CurrentPriceChangeStatus",
        "PriceChangeStatus",
        "Status",
        "MarketOrderStatus",
    ):
        v = board.get(k)
        if isinstance(v, str):
            if "特別買" in v:
                return "buy"
            if "特別売" in v:
                return "sell"
            if "特別" in v:
                return "unknown"

    # 数値コードの場合: 実際に特別気配を示す特定コードのみを判定（例: 4=特別売気配、5=特別買気配など）
    for k in ("CurrentPriceStatus", "CurrentPriceChangeStatus", "PriceChangeStatus"):
        v = board.get(k)
        if isinstance(v, (int, float)):
            vi = int(v)
            # 4=特別売気配、5=特別買気配（KabuStation API仕様に準拠）
            if vi == 4:
                return "sell"
            if vi == 5:
                return "buy"

    return ""


def fetch_minkabu_news(name_dict: Dict[str, str], edinet_company_index: Optional[List[Tuple[str, str]]] = None) -> list:
    """みんかぶの材料ニュース一覧をスクレイピングして取得する関数。

    Args:
        name_dict (Dict[str, str]): 略称辞書（タイトルからの銘柄特定用）。

    Returns:
        list: ニュース記事のリスト。各要素は辞書形式。
    """
    results = []
    try:
        jst = datetime.timezone(datetime.timedelta(hours=9))
        now_dt = datetime.datetime.now(jst)
        resp = requests.get(NEWS_MINKABU_URL, headers=NEWS_REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS + 5)
        if resp.status_code != 200:
            print(f"[NEWS][Minkabu] HTTP error: {resp.status_code}")
            return results

        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # みんかぶのニュースリスト要素を探索
        # 複数のセレクタパターンに対応（サイト構造変更への耐性）
        # /news/1234567 のような記事リンクを抽出
        articles = soup.find_all("a", href=lambda h: h and re.search(r"^/news/\d+", str(h)))
        if not articles:
            print(f"[NEWS][Minkabu] no article links found. status={resp.status_code} html_len={len(resp.text)}")
            return results

        skipped_no_ts = 0

        seen_urls = set()
        for a_tag in articles:
            href = a_tag.get("href", "")
            title_text = a_tag.get_text(strip=True)
            if not title_text or not href:
                continue

            # URL正規化
            if href.startswith("/"):
                url = f"https://minkabu.jp{href}"
            elif href.startswith("http"):
                url = href
            else:
                continue

            if url in seen_urls:
                continue
            seen_urls.add(url)

            published_ts = extract_news_published_ts(a_tag, fallback_dt=now_dt)
            if published_ts is None:
                skipped_no_ts += 1
                continue
            if published_ts <= time.time() - NEWS_LOOKBACK_SECONDS:
                continue

            # 優先順位1: URLから銘柄コードを抽出 (/stock/XXXX)
            symbol = ""
            matched_name = ""
            stock_match = re.search(r"/stock/(\d{4})", url)
            if stock_match:
                symbol = stock_match.group(1)
                matched_name = f"(URL:{symbol})"

            # data-stock-code属性からの抽出
            if not symbol:
                parent = a_tag.parent
                if parent:
                    data_code = parent.get("data-stock-code") or parent.get("data-code") or ""
                    if data_code:
                        sc = str(data_code).strip()
                        if len(sc) == 4 and sc.isdigit():
                            symbol = sc
                            matched_name = f"(data-code:{sc})"

            # 優先順位2: キーワード判定
            has_keyword = any(kw in title_text for kw in VOLATILITY_KEYWORDS)
            matched_keyword = ""
            if has_keyword:
                for kw in VOLATILITY_KEYWORDS:
                    if kw in title_text:
                        matched_keyword = kw
                        break

            # 優先順位3: タイトルから略称辞書で銘柄特定
            if not symbol:
                symbol, matched_name = resolve_symbol_from_title(title_text, name_dict)

            # 優先順位4: タイトル先頭（会社名断片）からEDINET会社名で雑一致
            if (not symbol) and edinet_company_index:
                frag = extract_company_fragment_from_yahoo_title(title_text)
                if frag:
                    sym2, matched2 = resolve_symbol_from_edinet_company_fragment(frag, edinet_company_index)
                    if sym2:
                        symbol = sym2
                        matched_name = f"(edinet_name:{matched2})"

            if has_keyword or symbol:
                results.append({
                    "source": "minkabu",
                    "title": title_text,
                    "url": url,
                    "symbol": symbol,
                    "matched_keyword": matched_keyword,
                    "matched_name": matched_name,
                    "published_ts": published_ts,
                })

        if not results:
            print(
                f"[NEWS][Minkabu] fetched_links={len(articles)} skipped_no_ts={skipped_no_ts} results=0 lookback_min={NEWS_LOOKBACK_MINUTES}"
            )

        print(
            f"[NEWS][Minkabu] fetched_links={len(articles)} skipped_no_ts={skipped_no_ts} results={len(results)} lookback_min={NEWS_LOOKBACK_MINUTES}"
        )

    except requests.exceptions.Timeout:
        print("[NEWS][Minkabu] timeout")
    except Exception as e:
        print(f"[NEWS][Minkabu] error: {e}")

    return results


def fetch_yahoo_finance_news(name_dict: Dict[str, str], edinet_company_index: Optional[List[Tuple[str, str]]] = None) -> list:
    """Yahoo!ファイナンスの市況ニュース一覧をスクレイピングして取得する関数。

    Args:
        name_dict (Dict[str, str]): 略称辞書（タイトルからの銘柄特定用）。

    Returns:
        list: ニュース記事のリスト。各要素は辞書形式。
    """
    results = []
    try:
        jst = datetime.timezone(datetime.timedelta(hours=9))
        now_dt = datetime.datetime.now(jst)
        resp = requests.get(NEWS_YAHOO_URL, headers=NEWS_REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS + 5)
        if resp.status_code != 200:
            print(f"[NEWS][Yahoo] HTTP error: {resp.status_code}")
            return results

        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # Yahoo!ファイナンスのニュース（/news/detail/...）リンクを抽出
        articles = soup.find_all("a", href=lambda h: h and "/news/detail/" in str(h))
        if not articles:
            articles = soup.select("a[href*='/news/detail/']")

        seen_urls = set()
        for a_tag in articles:
            href = a_tag.get("href", "")
            # このページはリンクテキストにタイトル + 時刻 + 配信社が混ざるため、まず全文を取得
            title_text = a_tag.get_text(" ", strip=True)

            if not title_text or not href:
                continue

            # URL正規化
            if href.startswith("/"):
                url = f"https://finance.yahoo.co.jp{href}"
            elif href.startswith("http"):
                url = href
            else:
                continue

            if url in seen_urls:
                continue
            seen_urls.add(url)

            published_ts = extract_news_published_ts(a_tag, fallback_dt=now_dt)
            if published_ts is None:
                continue
            if published_ts <= time.time() - NEWS_LOOKBACK_SECONDS:
                continue

            # 優先順位1: 関連銘柄タグからコード抽出 (/quote/XXXX.T)
            symbol = ""
            matched_name = ""
            parent_li = a_tag.find_parent("li")
            search_scope = parent_li if parent_li else a_tag
            quote_links = search_scope.find_all("a", href=lambda h: h and "/quote/" in h)
            for ql in quote_links:
                qhref = ql.get("href", "")
                qm = re.search(r"/quote/(\d{4})\.T", qhref)
                if not qm:
                    qm = re.search(r"/quote/(\d{4})", qhref)
                if qm:
                    symbol = qm.group(1)
                    matched_name = f"(quote:{symbol})"
                    break

            # 優先順位2: キーワード判定
            has_keyword = any(kw in title_text for kw in VOLATILITY_KEYWORDS)
            matched_keyword = ""
            if has_keyword:
                for kw in VOLATILITY_KEYWORDS:
                    if kw in title_text:
                        matched_keyword = kw
                        break

            # 優先順位3: タイトルから略称辞書で銘柄特定
            if not symbol:
                symbol, matched_name = resolve_symbol_from_title(title_text, name_dict)

            # 優先順位4: Yahoo特有のタイトル先頭（会社名断片）からEDINET会社名で雑一致
            if (not symbol) and edinet_company_index:
                frag = extract_company_fragment_from_yahoo_title(title_text)
                if frag:
                    sym2, matched2 = resolve_symbol_from_edinet_company_fragment(frag, edinet_company_index)
                    if sym2:
                        symbol = sym2
                        matched_name = f"(edinet_name:{matched2})"

            if has_keyword or symbol:
                results.append({
                    "source": "yahoo",
                    "title": title_text,
                    "url": url,
                    "symbol": symbol,
                    "matched_keyword": matched_keyword,
                    "matched_name": matched_name,
                    "published_ts": published_ts,
                })

    except requests.exceptions.Timeout:
        print("[NEWS][Yahoo] timeout")
    except Exception as e:
        print(f"[NEWS][Yahoo] error: {e}")

    return results


def append_news_log(row: Dict[str, Any], date_yyyymmdd: str) -> None:
    """ニュース検知情報をCSVファイルに追記保存する関数。

    Args:
        row (Dict[str, Any]): 保存するデータ。
        date_yyyymmdd (str): ファイル名に使用する日付文字列。
    """
    date_dir = os.path.join(LOG_DIR, date_yyyymmdd)
    os.makedirs(date_dir, exist_ok=True)
    log_path = os.path.join(date_dir, f"news_{date_yyyymmdd}.csv")
    file_exists = os.path.exists(log_path)

    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NEWS_LOG_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in NEWS_LOG_FIELDNAMES})


def load_news_processed_keys(date_yyyymmdd: str) -> set:
    """指定された日付のニュースログファイルから処理済みURLの一覧を取得する関数。

    Args:
        date_yyyymmdd (str): 読み込む日付。

    Returns:
        set: 処理済みURLのセット。
    """
    log_path = os.path.join(LOG_DIR, date_yyyymmdd, f"news_{date_yyyymmdd}.csv")
    if not os.path.exists(log_path):
        return set()

    processed = set()
    try:
        with open(log_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get("url") or "").strip()
                if url:
                    processed.add(url)
    except Exception:
        return set()

    return processed


def kabus_api_request(method: str, path: str, token: Optional[str] = None, body: Optional[Dict[str, Any]] = None):
    """KabuStation APIへのHTTPリクエストを実行する汎用ラッパー関数。

    Args:
        method (str): "GET", "POST", "PUT" 等。
        path (str): APIのエンドポイントパス（例: "/kabusapi/board/..."）。
        token (str, optional): APIトークン。
        body (Dict, optional): POST/PUT時のリクエストボディ。

    Returns:
        tuple: (ステータスコード, レスポンスのJSONまたは辞書)
    """
    url = f"{KABUS_API_BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
    }
    if token:
        headers["X-API-KEY"] = token

    timeout = REQUEST_TIMEOUT_SECONDS
    if method.upper() in {"POST", "PUT"}:
        resp = requests.request(method.upper(), url, headers=headers, data=json.dumps(body or {}), timeout=timeout)
    else:
        resp = requests.request(method.upper(), url, headers=headers, timeout=timeout)

    text = resp.text
    try:
        payload = resp.json() if text else {}
    except Exception:
        payload = {"raw": text}

    return resp.status_code, payload

def kabus_get_token() -> str:
    """KabuStation APIを使用するための認証トークンを取得する関数。

    Returns:
        str: 取得したAPIトークン。
    
    Raises:
        RuntimeError: パスワード未設定や取得失敗時。
    """
    if not KABUS_API_PASSWORD:
        raise RuntimeError("KABUS_API_PASSWORD is not set")

    status, payload = kabus_api_request("POST", "/kabusapi/token", token=None, body={"APIPassword": KABUS_API_PASSWORD})
    if status != 200:
        raise RuntimeError(f"token request failed: {status} {payload}")
    token = payload.get("Token") or payload.get("token")
    if not token:
        raise RuntimeError(f"token not found in response: {payload}")
    return token

def kabus_get_board(symbol: str, token: str) -> Tuple[int, Dict[str, Any]]:
    """指定した銘柄の板情報（現在値、気配値など）を取得する関数。

    Args:
        symbol (str): 証券コード。
        token (str): APIトークン。

    Returns:
        tuple: (ステータスコード, 板情報データ)
    """
    status, payload = kabus_api_request("GET", f"/kabusapi/board/{symbol}@{KABUS_EXCHANGE}", token=token)
    return status, payload

def kabus_get_symbol_info(symbol: str, token: str) -> Tuple[int, Any]:
    """指定した銘柄の銘柄情報（銘柄名など）を取得する関数。"""
    status, payload = kabus_api_request("GET", f"/kabusapi/symbol/{symbol}@{KABUS_EXCHANGE}", token=token)
    return status, payload

def kabus_unregister_all(token: str) -> Tuple[int, Dict[str, Any]]:
    """KabuStation APIに登録されている監視銘柄をすべて解除する関数。
    
    PUSH配信の登録枠をクリアするために使用します。

    Args:
        token (str): APIトークン。

    Returns:
        tuple: (ステータスコード, レスポンス)
    """
    status, payload = kabus_api_request("PUT", "/kabusapi/unregister/all", token=token, body={})
    return status, payload

def kabus_send_order(token: str, order: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """注文を発注する関数。

    Args:
        token (str): APIトークン。
        order (Dict[str, Any]): 注文パラメータを含む辞書。

    Returns:
        tuple: (ステータスコード, 注文結果レスポンス)
    """
    status, payload = kabus_api_request("POST", "/kabusapi/sendorder", token=token, body=order)
    return status, payload

def kabus_get_orders(token: str, product: int = 0, order_id: str = "", symbol: str = "", state: str = "", side: str = "", cashmargin: str = "") -> Tuple[int, Any]:
    """注文約定照会API。注文一覧を取得する。
    
    Args:
        token: APIトークン
        product: 商品(0=すべて, 1=現物, 2=信用, 3=先物, 4=OP)
        order_id: 注文番号(指定すると該当注文のみ)
        symbol: 銘柄コード
        state: 状態(1=待機, 2=処理中, 3=処理済, 4=訂正取消送信中, 5=終了)
        side: 売買区分(1=売, 2=買)
        cashmargin: 取引区分(2=新規, 3=返済)
    
    Returns:
        tuple: (ステータスコード, レスポンス)
    """
    params = []
    if product > 0:
        params.append(f"product={int(product)}")
    if order_id:
        params.append(f"id={order_id}")
    if symbol:
        params.append(f"symbol={symbol}")
    if state:
        params.append(f"state={state}")
    if side:
        params.append(f"side={side}")
    if cashmargin:
        params.append(f"cashmargin={cashmargin}")
    qs = "&".join(params) if params else ""
    endpoint = f"/kabusapi/orders?{qs}" if qs else "/kabusapi/orders"
    return kabus_api_request("GET", endpoint, token=token)

def kabus_cancel_order(token: str, order_id: str, password: str) -> Tuple[int, Any]:
    """注文取消API。
    
    Args:
        token: APIトークン
        order_id: 注文番号
        password: 注文パスワード(kabuステーションの注文パスワード)
    
    Returns:
        tuple: (ステータスコード, レスポンス)
    """
    body = {
        "OrderId": order_id,
        "Password": password
    }
    return kabus_api_request("PUT", "/kabusapi/cancelorder", token=token, body=body)

def kabus_get_positions(token: str, product: int = 0, symbol: str = "", side: str = "", addinfo: bool = False) -> Tuple[int, Any]:
    params = [f"product={int(product)}", f"addinfo={'true' if addinfo else 'false'}"]
    if symbol:
        params.append(f"symbol={symbol}")
    if side:
        params.append(f"side={side}")
    qs = "&".join(params)
    return kabus_api_request("GET", f"/kabusapi/positions?{qs}", token=token)

def calc_limit_price(current_price: float, side: str, pct: float) -> float:
    """現在価格と指定した割合（%）に基づいて、指値価格を計算する関数。

    Args:
        current_price (float): 現在価格。
        side (str): "buy" または "sell"。
        pct (float): 乖離率（%）。

    Returns:
        float: 計算された指値価格（小数点第2位以下四捨五入）。
    """
    p = float(current_price)
    rate = float(pct) / 100.0
    if side == "buy":
        v = p * (1.0 - rate)
    else:
        v = p * (1.0 + rate)
    return round(v, 1)

def apply_order_settings(order_settings: Dict[str, Any], cmd: Dict[str, Any]) -> None:
    def _norm(s: Any) -> str:
        return str(s or "").strip().lower()

    def _to_float(v: Any, default: float) -> float:
        try:
            return float(v)
        except Exception:
            return default

    def _to_int(v: Any, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return default

    if "mode" in cmd:
        order_settings["mode"] = _norm(cmd.get("mode")) or order_settings.get("mode")
    if "side_mode" in cmd:
        order_settings["side_mode"] = _norm(cmd.get("side_mode")) or order_settings.get("side_mode")
    if "cash_margin" in cmd:
        order_settings["cash_margin"] = _norm(cmd.get("cash_margin")) or order_settings.get("cash_margin")
    if "order_type" in cmd:
        order_settings["order_type"] = _norm(cmd.get("order_type")) or order_settings.get("order_type")

    if "limit_pct" in cmd:
        order_settings["limit_pct"] = _to_float(cmd.get("limit_pct"), float(order_settings.get("limit_pct") or 0.0))
    if "qty" in cmd:
        order_settings["qty"] = _to_int(cmd.get("qty"), int(order_settings.get("qty") or 0))
    if "dry_run" in cmd:
        order_settings["dry_run"] = bool(cmd.get("dry_run"))
    if "confirm" in cmd:
        order_settings["confirm"] = bool(cmd.get("confirm"))
    if "volume_mult" in cmd:
        order_settings["volume_mult"] = _to_float(cmd.get("volume_mult"), float(order_settings.get("volume_mult") or 0.0))
    if "price_min" in cmd:
        order_settings["price_min"] = _to_float(cmd.get("price_min"), float(order_settings.get("price_min") or 0.0))
    if "price_max" in cmd:
        order_settings["price_max"] = _to_float(cmd.get("price_max"), float(order_settings.get("price_max") or 0.0))
    if "base_volume_min" in cmd:
        order_settings["base_volume_min"] = _to_float(cmd.get("base_volume_min"), float(order_settings.get("base_volume_min") or 0.0))

    if "auto_exit" in cmd:
        order_settings["auto_exit"] = bool(cmd.get("auto_exit"))
    if "profit_yen_per_100" in cmd:
        order_settings["profit_yen_per_100"] = _to_float(cmd.get("profit_yen_per_100"), float(order_settings.get("profit_yen_per_100") or 0.0))
    if "stoploss_yen_per_100" in cmd:
        order_settings["stoploss_yen_per_100"] = _to_float(cmd.get("stoploss_yen_per_100"), float(order_settings.get("stoploss_yen_per_100") or 0.0))
    if "stagnation_seconds" in cmd:
        order_settings["stagnation_seconds"] = _to_float(cmd.get("stagnation_seconds"), float(order_settings.get("stagnation_seconds") or 0.0))
    if "stagnation_price_pct" in cmd:
        order_settings["stagnation_price_pct"] = _to_float(cmd.get("stagnation_price_pct"), float(order_settings.get("stagnation_price_pct") or 0.0))
    if "stagnation_volume_mult" in cmd:
        order_settings["stagnation_volume_mult"] = _to_float(cmd.get("stagnation_volume_mult"), float(order_settings.get("stagnation_volume_mult") or 0.0))
    if "stagnation_hits" in cmd:
        order_settings["stagnation_hits"] = _to_int(cmd.get("stagnation_hits"), int(order_settings.get("stagnation_hits") or 0))

def should_place_side(side_mode: str, side: str) -> bool:
    sm = (side_mode or "").strip().lower()
    sd = (side or "").strip().lower()
    if sm in {"both", "", "all"}:
        return sd in {"buy", "sell"}
    if sm in {"buy", "buy_only", "long"}:
        return sd == "buy"
    if sm in {"sell", "sell_only", "short"}:
        return sd == "sell"
    return False

def decide_side_by_trend(price_pct: float) -> str:
    try:
        v = float(price_pct)
    except Exception:
        return ""
    if v > 0:
        return "buy"
    if v < 0:
        return "sell"
    return ""

def is_opening_order_suppressed(dt: datetime.datetime) -> bool:
    if not OPENING_ORDER_SUPPRESS_ENABLE:
        return False
    mins = int(OPENING_ORDER_SUPPRESS_MINUTES)
    if mins <= 0:
        return False

    jst = datetime.timezone(datetime.timedelta(hours=9))
    nd = dt.astimezone(jst) if dt.tzinfo else dt.replace(tzinfo=jst)

    morning_start = nd.replace(hour=9, minute=0, second=0, microsecond=0)
    morning_end = morning_start + datetime.timedelta(minutes=mins)
    pm_start = nd.replace(hour=12, minute=30, second=0, microsecond=0)
    pm_end = pm_start + datetime.timedelta(minutes=mins)

    return (morning_start <= nd < morning_end) or (pm_start <= nd < pm_end)

def try_place_order(
    token: Optional[str],
    symbol: str,
    side: str,
    current_price: float,
    settings: Dict[str, Any],
    event_queue: "queue.Queue",
    reason: str,
) -> Optional[str]:
    """注文を発注し、成功時は注文IDを返す。
    
    Returns:
        Optional[str]: 注文ID（成功時）、None（失敗時）
    """
    sym = str(symbol or "").strip()
    sd = str(side or "").strip().lower()
    if not sym or sd not in {"buy", "sell"}:
        return None

    is_exit = "auto_exit" in str(reason or "")
    if is_opening_order_suppressed(datetime.datetime.now(JST)) and (not is_exit):
        print(f"[ORDER] 寄り付き直後のため新規発注抑止: {sym} ({reason})")
        try:
            event_queue.put_nowait({"kind": "event", "text": f"寄り抑止 order {sym}", "symbol": sym, "price": current_price})
        except Exception:
            pass
        append_order_log(
            {
                "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                "symbol": sym,
                "side": sd,
                "qty": int(settings.get("qty") or 0),
                "order_type": str(settings.get("order_type") or ""),
                "limit_price": "",
                "cash_margin": str(settings.get("cash_margin") or ""),
                "reason": reason,
                "dry_run": bool(settings.get("dry_run")),
                "status": "",
                "result": "opening_suppressed",
                "payload": "",
            },
            datetime.datetime.now().strftime("%Y%m%d"),
        )
        return

    qty = int(settings.get("qty") or 0)
    if qty <= 0:
        return

    order_type = str(settings.get("order_type") or "market").strip().lower()
    limit_pct = float(settings.get("limit_pct") or 0.0)
    dry_run = bool(settings.get("dry_run"))
    confirm = bool(settings.get("confirm"))
    cash_margin = str(settings.get("cash_margin") or "cash").strip().lower()

    limit_price: Optional[float] = None
    if order_type in {"limit_pct", "limit", "limitpercent"}:
        limit_price = calc_limit_price(float(current_price), sd, float(limit_pct))

    margin_trade_type = int(settings.get("margin_trade_type") or 3)
    if cash_margin == "margin_close":
        order = build_margin_close_order(sym, sd, qty, "limit_pct" if limit_price is not None else "market", limit_price, margin_trade_type=margin_trade_type)
    elif cash_margin == "margin":
        order = build_margin_new_order(sym, sd, qty, "limit_pct" if limit_price is not None else "market", limit_price)
    else:
        order = build_cash_order(sym, sd, qty, "limit_pct" if limit_price is not None else "market", limit_price)

    order_desc = f"{sd} {sym} qty={qty} type={order_type} price={limit_price if limit_price is not None else 'MKT'} ({reason})"

    _order_log_date = datetime.datetime.now().strftime("%Y%m%d")
    _order_log_base = {
        "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
        "symbol": sym,
        "side": sd,
        "qty": qty,
        "order_type": order_type,
        "limit_price": limit_price if limit_price is not None else "MKT",
        "cash_margin": cash_margin,
        "reason": reason,
        "dry_run": dry_run,
    }

    if confirm:
        ok = True
        if ENABLE_GUI:
            try:
                import tkinter as tk
                from tkinter import messagebox

                root = tk.Tk()
                root.withdraw()
                ok = messagebox.askyesno("Confirm Order", order_desc)
                root.destroy()
            except Exception:
                ok = True
        else:
            ans = input(f"CONFIRM ORDER? {order_desc} [y/N]: ").strip().lower()
            ok = ans in {"y", "yes"}
        if not ok:
            try:
                event_queue.put_nowait({"kind": "event", "text": f"order canceled {sym}", "symbol": sym, "price": current_price})
            except Exception:
                pass
            append_order_log({**_order_log_base, "status": "", "result": "canceled", "payload": ""}, _order_log_date)
            return

    if dry_run:
        print(f"[ORDER][DRY_RUN] {order_desc}")
        try:
            event_queue.put_nowait({"kind": "event", "text": f"DRY_RUN {order_desc}", "symbol": sym, "price": current_price})
        except Exception:
            pass
        append_order_log({**_order_log_base, "status": "", "result": "dry_run", "payload": ""}, _order_log_date)
        return

    if not token:
        print(f"[ORDER] token is empty. skip: {order_desc}")
        try:
            event_queue.put_nowait({"kind": "event", "text": f"order skip (no token) {sym}", "symbol": sym, "price": current_price})
        except Exception:
            pass
        append_order_log({**_order_log_base, "status": "", "result": "no_token", "payload": ""}, _order_log_date)
        return

    try:
        status, payload = kabus_send_order(token, order)
        print(f"[ORDER] sendorder status={status} {order_desc}")
        try:
            event_queue.put_nowait({"kind": "event", "text": f"order status={status} {sym}", "symbol": sym, "price": current_price})
        except Exception:
            pass
        if status == 200:
            append_order_log({**_order_log_base, "status": status, "result": "ok", "payload": payload}, _order_log_date)
            order_id = payload.get("OrderId") or payload.get("orderId") or payload.get("order_id")
            if order_id:
                return str(order_id)
            return None
        else:
            print(f"[ORDER] sendorder failed payload={payload}")
            append_order_log({**_order_log_base, "status": status, "result": "failed", "payload": payload}, _order_log_date)
            return None
    except Exception as e:
        print(f"[ORDER] sendorder error: {e} ({order_desc})")
        try:
            event_queue.put_nowait({"kind": "event", "text": f"order error {sym}", "symbol": sym, "price": current_price})
        except Exception:
            pass
        append_order_log({**_order_log_base, "status": "", "result": "error", "payload": str(e)}, _order_log_date)
        return None


def build_cash_order(symbol: str, side: str, qty: int, order_type: str, limit_price: Optional[float]) -> Dict[str, Any]:
    """現物取引の注文パラメータ辞書を構築するヘルパー関数。

    Args:
        symbol (str): 銘柄コード。
        side (str): "buy" or "sell"。
        qty (int): 数量。
        order_type (str): "market" (成行) or "limit_pct" (指値)。
        limit_price (Optional[float]): 指値価格。

    Returns:
        Dict[str, Any]: APIに送信可能な注文オブジェクト。
    """
    obj: Dict[str, Any] = {
        "Symbol": str(symbol),
        "Exchange": int(KABUS_EXCHANGE),
        "SecurityType": 1,
        "Side": "2" if side == "buy" else "1",
        "CashMargin": 1,
        "DelivType": 2 if side == "buy" else 0,
        "FundType": "AA" if side == "buy" else "  ",
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

def build_margin_new_order(symbol: str, side: str, qty: int, order_type: str, limit_price: Optional[float]) -> Dict[str, Any]:
    """信用新規取引の注文パラメータ辞書を構築するヘルパー関数。

    Args:
        symbol (str): 銘柄コード。
        side (str): "buy" or "sell"。
        qty (int): 数量。
        order_type (str): "market" (成行) or "limit_pct" (指値)。
        limit_price (Optional[float]): 指値価格。

    Returns:
        Dict[str, Any]: APIに送信可能な注文オブジェクト。
    """
    obj: Dict[str, Any] = {
        "Symbol": str(symbol),
        "Exchange": int(KABUS_EXCHANGE),
        "SecurityType": 1,
        "Side": "2" if side == "buy" else "1",
        "CashMargin": 2,
        "MarginTradeType": 3,
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

def build_margin_close_order(symbol: str, side: str, qty: int, order_type: str, limit_price: Optional[float], margin_trade_type: int = 3) -> Dict[str, Any]:
    """信用返済取引の注文パラメータ辞書を構築するヘルパー関数。

    Args:
        symbol (str): 銘柄コード。
        side (str): "buy" (買い返済=売り建玉の返済) or "sell" (売り返済=買い建玉の返済)。
        qty (int): 数量。
        order_type (str): "market" (成行) or "limit_pct" (指値)。
        limit_price (Optional[float]): 指値価格。
        margin_trade_type (int): 信用取引区分 (1=制度信用, 2=一般信用長期, 3=一般信用デイトレ)。

    Returns:
        Dict[str, Any]: APIに送信可能な注文オブジェクト。
    """
    obj: Dict[str, Any] = {
        "Symbol": str(symbol),
        "Exchange": int(KABUS_EXCHANGE),
        "SecurityType": 1,
        "Side": "2" if side == "buy" else "1",
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

def monitor_order_and_place_profit_limit(
    token: str,
    order_id: str,
    symbol: str,
    side: str,
    qty: int,
    cash_margin: str,
    margin_trade_type: int,
    profit_yen_per_100: float,
    event_queue: "queue.Queue",
    held_positions: Dict[str, Dict[str, Any]],
    order_password: str = ""
) -> None:
    """新規注文の約定を監視し、約定後に利確指値を入れて5秒監視→未約定ならキャンセルする。
    
    この関数は別スレッドで実行されることを想定しています。
    
    Args:
        token: APIトークン
        order_id: 新規注文の注文ID
        symbol: 銘柄コード
        side: 新規注文の売買（"buy" or "sell"）
        qty: 注文数量
        cash_margin: 取引区分（"cash", "margin", "margin_close"）
        margin_trade_type: 信用取引区分
        profit_yen_per_100: 利確目標（円/100株）
        event_queue: GUI通知用キュー
        held_positions: 保有ポジション辞書（二重決済防止用フラグ設定）
        order_password: 注文パスワード（キャンセル時に必要）
    """
    try:
        print(f"[PROFIT_LIMIT] 約定監視開始: order_id={order_id} {symbol}")
        
        # 約定検知（最大10秒間、0.3秒間隔でポーリング）
        executed_qty = 0
        avg_price = 0.0
        max_wait = 10.0
        poll_interval = 0.3
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                st, payload = kabus_get_orders(token, order_id=order_id)
                if st == 200:
                    if isinstance(payload, list) and len(payload) > 0:
                        order_info = payload[0]
                    elif isinstance(payload, dict):
                        order_info = payload
                    else:
                        time.sleep(poll_interval)
                        continue
                    
                    # 約定数量と平均価格を取得
                    exec_qty = order_info.get("CumQty") or order_info.get("ExecutedQty") or 0
                    if isinstance(exec_qty, (int, float)) and exec_qty > 0:
                        executed_qty = int(exec_qty)
                        avg_price = float(order_info.get("AvgPrice") or order_info.get("ExecutedPrice") or 0)
                        if avg_price > 0:
                            print(f"[PROFIT_LIMIT] 約定検知: {symbol} qty={executed_qty} avg={avg_price:.1f}")
                            break
                time.sleep(poll_interval)
            except Exception as e:
                print(f"[PROFIT_LIMIT] 約定照会エラー: {e}")
                time.sleep(poll_interval)
        
        if executed_qty <= 0 or avg_price <= 0:
            print(f"[PROFIT_LIMIT] 約定未検知（タイムアウト）: {symbol}")
            return
        
        # 利確指値価格を計算
        unit = float(executed_qty) / 100.0
        if side == "buy":
            # 買い→売り返済の利確価格
            target_profit = profit_yen_per_100 * unit
            profit_price = avg_price + (target_profit / executed_qty)
            close_side = "sell"
        else:
            # 売り→買い返済の利確価格
            target_profit = profit_yen_per_100 * unit
            profit_price = avg_price - (target_profit / executed_qty)
            close_side = "buy"
        
        profit_price = round(profit_price, 1)
        print(f"[PROFIT_LIMIT] 利確指値発注: {symbol} side={close_side} price={profit_price:.1f} qty={executed_qty}")
        
        # 利確指値注文を発注
        if cash_margin == "margin":
            profit_order = build_margin_close_order(symbol, close_side, executed_qty, "limit", profit_price, margin_trade_type)
        else:
            profit_order = build_cash_order(symbol, close_side, executed_qty, "limit", profit_price)
        
        st_profit, payload_profit = kabus_send_order(token, profit_order)
        if st_profit != 200:
            print(f"[PROFIT_LIMIT] 利確指値発注失敗: {payload_profit}")
            return
        
        profit_order_id = payload_profit.get("OrderId") or payload_profit.get("orderId")
        if not profit_order_id:
            print(f"[PROFIT_LIMIT] 利確指値の注文ID取得失敗")
            return
        
        print(f"[PROFIT_LIMIT] 利確指値発注成功: order_id={profit_order_id}")
        
        # held_positionsに利確指値稼働中フラグを設定（二重決済防止）
        if symbol in held_positions:
            held_positions[symbol]["profit_limit_active"] = True
            held_positions[symbol]["profit_limit_order_id"] = str(profit_order_id)
        
        try:
            event_queue.put_nowait({"kind": "event", "text": f"利確指値 {symbol} @{profit_price:.1f}", "symbol": symbol, "price": profit_price})
        except Exception:
            pass
        
        # 5秒間監視（0.5秒間隔でポーリング）
        monitor_duration = 5.0
        monitor_interval = 0.5
        monitor_start = time.time()
        profit_filled = False
        
        while time.time() - monitor_start < monitor_duration:
            try:
                st_check, payload_check = kabus_get_orders(token, order_id=str(profit_order_id))
                if st_check == 200:
                    if isinstance(payload_check, list) and len(payload_check) > 0:
                        profit_info = payload_check[0]
                    elif isinstance(payload_check, dict):
                        profit_info = payload_check
                    else:
                        time.sleep(monitor_interval)
                        continue
                    
                    # 状態チェック（5=終了=全約定含む）
                    state = profit_info.get("State") or profit_info.get("state")
                    if state == 5 or state == "5":
                        profit_filled = True
                        print(f"[PROFIT_LIMIT] 利確指値約定: {symbol}")
                        break
                time.sleep(monitor_interval)
            except Exception as e:
                print(f"[PROFIT_LIMIT] 監視エラー: {e}")
                time.sleep(monitor_interval)
        
        # 5秒経過しても未約定ならキャンセル
        if not profit_filled:
            print(f"[PROFIT_LIMIT] 5秒経過、利確指値をキャンセル: {symbol}")
            if order_password:
                try:
                    st_cancel, payload_cancel = kabus_cancel_order(token, str(profit_order_id), order_password)
                    if st_cancel == 200:
                        print(f"[PROFIT_LIMIT] キャンセル成功: {symbol}")
                    else:
                        print(f"[PROFIT_LIMIT] キャンセル失敗: {payload_cancel}")
                except Exception as e:
                    print(f"[PROFIT_LIMIT] キャンセルエラー: {e}")
            else:
                print(f"[PROFIT_LIMIT] 注文パスワード未設定のためキャンセル不可")
            
            try:
                event_queue.put_nowait({"kind": "event", "text": f"利確指値タイムアウト {symbol}", "symbol": symbol})
            except Exception:
                pass
        
        # フラグをクリア
        if symbol in held_positions:
            held_positions[symbol]["profit_limit_active"] = False
            held_positions[symbol]["profit_limit_order_id"] = None
        
    except Exception as e:
        print(f"[PROFIT_LIMIT] エラー: {e}")
        if symbol in held_positions:
            held_positions[symbol]["profit_limit_active"] = False
            held_positions[symbol]["profit_limit_order_id"] = None

def extract_price_volume(board: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """板情報レスポンスから、現在値と出来高を安全に取り出す関数。
    
    APIのレスポンスフィールド名が異なる場合や、データ欠損に対応します。

    Args:
        board (Dict[str, Any]): APIからの板情報レスポンス。

    Returns:
        tuple: (価格(float), 出来高(float))。取得できない場合はNone。
    """
    price = None
    volume = None

    for k in ("CurrentPrice", "Price", "LastPrice"):
        v = board.get(k)
        if isinstance(v, (int, float)):
            price = float(v)
            break

    for k in ("TradingVolume", "Volume", "TotalVolume"):
        v = board.get(k)
        if isinstance(v, (int, float)):
            volume = float(v)
            break

    return price, volume

def get_tdnet_disclosures():
    """
    TDnetの適時開示情報（今日の分）を取得して解析する関数。
    
    1ページ目から順にHTMLを取得し、キーワード条件（POSITIVE_KEYWORDS）に合致する
    開示情報のみをリストとして返します。
    
    Returns:
        tuple: (結果のリスト, ステータスコード, Retry-After秒数)
    """
    # 今日の日付を取得 (YYYYMMDD形式)
    today = datetime.datetime.now().strftime("%Y%m%d")
    
    try:
        results = []

        total_rows = 0
        for page in range(1, MAX_PAGES + 1):
            html, status_code, retry_after = fetch_tdnet_list_html(today, page)
            if status_code == 404:
                if page == 1:
                    print(f"Error: {status_code}")
                    return [], status_code, retry_after
                break
            if status_code != 200:
                print(f"Error: {status_code}")
                return [], status_code, retry_after
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")
            main_table = soup.find("table", {"id": "main-list-table"})
            if main_table is None:
                break

            rows = main_table.find_all("tr")
            page_row_count = 0

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 7:
                    continue

                page_row_count += 1

                time_str = cols[0].text.strip()
                code = cols[1].text.strip()
                name = cols[2].text.strip()

                title_a = cols[3].find("a")
                title = title_a.text.strip() if title_a else cols[3].text.strip()
                pdf_href = title_a.get("href") if title_a else ""
                pdf_url = f"{TDNET_BASE_URL}{pdf_href}" if pdf_href else ""

                xbrl_a = cols[4].find("a")
                xbrl_href = xbrl_a.get("href") if xbrl_a else ""
                xbrl_url = f"{TDNET_BASE_URL}{xbrl_href}" if xbrl_href else ""

                place = cols[5].text.strip()

                # 好材料・悪材料キーワード判定
                is_positive = any(keyword in title for keyword in POSITIVE_KEYWORDS)
                is_negative = any(keyword in title for keyword in NEGATIVE_KEYWORDS)

                # ポジティブかつネガティブでないものだけを抽出
                if is_positive and not is_negative:
                    results.append({
                        "date": today,
                        "time": time_str,
                        "code": code,
                        "name": name,
                        "title": title,
                        "pdf_url": pdf_url,
                        "xbrl_url": xbrl_url,
                        "place": place,
                    })

            total_rows += page_row_count
            # ページに行がない場合は終了
            if page_row_count == 0:
                break

        return results, 200, 0

    except Exception as e:
        print(f"Error occurred: {e}")
        return [], None, 0

def start_gui(event_queue: "queue.Queue", command_queue: "queue.Queue"):
    """Tkinterを使用したGUIを起動する関数。
    
    別スレッドで実行され、メインスレッド（監視ロジック）とQueueを通じて通信します。
    
    Args:
        event_queue (queue.Queue): メインスレッドからGUIへの通知用キュー。
        command_queue (queue.Queue): GUIからメインスレッドへの操作指示用キュー。
    """
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("TDnet監視 / 自動売買")
    root.geometry("760x720")

    canvas = tk.Canvas(root, highlightthickness=0)
    vbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    vbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    container = tk.Frame(canvas)
    container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=container, anchor="nw")

    def _on_mousewheel(event):
        try:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta == 0:
                return "break"
            canvas.yview_scroll(int(-delta / 120), "units")
            return "break"
        except Exception:
            return "break"

    root.bind_all("<MouseWheel>", _on_mousewheel)

    # GUI表示用の変数定義
    vars_ = {
        "watch": tk.StringVar(value="監視銘柄数: 0"),
        "watching_symbols": tk.StringVar(value="監視中銘柄: -"),
        "tdnet": tk.StringVar(value="TDnet: -"),
        "edinet": tk.StringVar(value="EDINET: -"),
        "news": tk.StringVar(value="NEWS: -"),
        "kabus": tk.StringVar(value="KabuStation: -"),
        "event": tk.StringVar(value="イベント: -"),
    }

    # 上部のステータス表示エリア
    # 監視銘柄数と詳細ボタンを同じ行に配置
    watch_row = tk.Frame(container)
    watch_row.pack(fill="x", padx=4, pady=2)
    tk.Label(watch_row, textvariable=vars_["watch"], anchor="w", width=15).pack(side="left")
    
    # 監視中銘柄リストを保存する変数
    current_watching_symbols: List[Tuple[str, str]] = []
    
    def show_watching_symbols_popup():
        """監視中銘柄一覧をポップアップウィンドウで表示"""
        if not current_watching_symbols:
            messagebox.showinfo("監視中銘柄", "現在監視中の銘柄はありません")
            return
        
        w = tk.Toplevel(root)
        w.title("監視中銘柄一覧")
        w.geometry("400x500")
        w.resizable(True, True)
        
        # スクロールバー付きリスト
        body = tk.Frame(w)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        
        sb = tk.Scrollbar(body)
        sb.pack(side="right", fill="y")
        
        txt = tk.Text(body, wrap="word", yscrollcommand=sb.set, font=("MS Gothic", 10))
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        
        # 銘柄リストを表示
        txt.insert("1.0", f"監視中銘柄数: {len(current_watching_symbols)}\n")
        txt.insert("2.0", "=" * 40 + "\n\n")
        
        for i, (symbol, name) in enumerate(current_watching_symbols, 1):
            line = f"{i}. {symbol} - {name}\n"
            txt.insert("end", line)
        
        txt.config(state="disabled")
        
        # 閉じるボタン
        btns = tk.Frame(w)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(btns, text="閉じる", command=w.destroy).pack(side="right")
    
    tk.Button(watch_row, text="詳細", command=show_watching_symbols_popup).pack(side="left", padx=(5, 0))
    
    tk.Label(container, textvariable=vars_["tdnet"], anchor="w").pack(fill="x")
    tk.Label(container, textvariable=vars_["edinet"], anchor="w").pack(fill="x")
    tk.Label(container, textvariable=vars_["news"], anchor="w").pack(fill="x")
    tk.Label(container, textvariable=vars_["kabus"], anchor="w").pack(fill="x")
    tk.Label(container, textvariable=vars_["event"], anchor="w").pack(fill="x")

    topbar = tk.Frame(container)
    topbar.pack(fill="x", padx=8, pady=(6, 0))

    # ヘルプウィンドウ表示処理
    def open_help():
        w = tk.Toplevel(root)
        w.title("ヘルプ / 使い方")
        w.geometry("720x520")

        body = tk.Frame(w)
        body.pack(fill="both", expand=True, padx=8, pady=8)

        sb = tk.Scrollbar(body)
        sb.pack(side="right", fill="y")

        txt = tk.Text(body, wrap="word", yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)

        txt.insert("1.0", build_help_text())
        txt.config(state="disabled")

        btns = tk.Frame(w)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(btns, text="閉じる", command=w.destroy).pack(side="right")

    tk.Button(topbar, text="ヘルプ", command=open_help).pack(side="right")

    # 注文設定エリア
    frm = tk.LabelFrame(container, text="注文設定")
    frm.pack(fill="both", expand=True, padx=8, pady=8)

    # 設定値保持用のTk変数
    v_mode = tk.StringVar(value=ORDER_MODE)
    v_side_mode = tk.StringVar(value=ORDER_SIDE_MODE)
    v_cash_margin = tk.StringVar(value=ORDER_CASH_MARGIN)
    v_order_type = tk.StringVar(value=ORDER_TYPE)
    v_limit_pct = tk.StringVar(value=str(ORDER_LIMIT_PCT))
    v_qty = tk.StringVar(value=str(ORDER_QTY))
    v_dry = tk.IntVar(value=1 if ORDER_DRY_RUN else 0)
    v_confirm = tk.IntVar(value=1 if ORDER_CONFIRM else 0)
    v_vol_mult = tk.StringVar(value=str(ORDER_VOLUME_MULTIPLIER))
    v_price_min = tk.StringVar(value=str(ORDER_PRICE_MIN))
    v_price_max = tk.StringVar(value=str(ORDER_PRICE_MAX))
    v_base_vol_min = tk.StringVar(value=str(ORDER_BASE_VOLUME_MIN))

    v_auto_exit = tk.IntVar(value=1 if AUTO_EXIT_ENABLE else 0)
    v_profit_yen = tk.StringVar(value=str(AUTO_EXIT_PROFIT_YEN_PER_100))
    v_stoploss_yen = tk.StringVar(value=str(AUTO_EXIT_STOPLOSS_YEN_PER_100))
    v_stag_secs = tk.StringVar(value=str(AUTO_EXIT_STAGNATION_SECONDS))
    v_stag_price_pct = tk.StringVar(value=str(AUTO_EXIT_STAGNATION_PRICE_PCT))
    v_stag_vol_mult = tk.StringVar(value=str(AUTO_EXIT_STAGNATION_VOLUME_MULT))
    v_stag_hits = tk.StringVar(value=str(AUTO_EXIT_STAGNATION_HITS))

    last_symbol_var = tk.StringVar(value="-")
    last_price_var = tk.StringVar(value="-")

    # 設定変更をメインスレッドに通知する処理
    def push_settings():
        try:
            command_queue.put_nowait(
                {
                    "kind": "settings",
                    "mode": v_mode.get(),
                    "side_mode": v_side_mode.get(),
                    "cash_margin": v_cash_margin.get(),
                    "order_type": v_order_type.get(),
                    "limit_pct": v_limit_pct.get(),
                    "qty": v_qty.get(),
                    "dry_run": bool(v_dry.get()),
                    "confirm": bool(v_confirm.get()),
                    "volume_mult": v_vol_mult.get(),
                    "price_min": v_price_min.get(),
                    "price_max": v_price_max.get(),
                    "base_volume_min": v_base_vol_min.get(),
                    "auto_exit": bool(v_auto_exit.get()),
                    "profit_yen_per_100": v_profit_yen.get(),
                    "stoploss_yen_per_100": v_stoploss_yen.get(),
                    "stagnation_seconds": v_stag_secs.get(),
                    "stagnation_price_pct": v_stag_price_pct.get(),
                    "stagnation_volume_mult": v_stag_vol_mult.get(),
                    "stagnation_hits": v_stag_hits.get(),
                }
            )
        except Exception:
            pass

    # 手動発注ボタン押下時の処理
    def on_place_order():
        sym = (last_symbol_var.get() or "").strip()
        if not sym or sym == "-":
            messagebox.showwarning("注文", "対象銘柄がありません（直近銘柄が未設定）")
            return
        push_settings()
        try:
            command_queue.put_nowait({"kind": "order_request", "symbol": sym})
        except Exception:
            pass

    # 各種設定項目の配置（ラジオボタン、エントリーなど）
    r1 = tk.Frame(frm)
    r1.pack(fill="x", padx=6, pady=4)
    tk.Label(r1, text="モード", width=14, anchor="w").pack(side="left")
    tk.Radiobutton(r1, text="自動", variable=v_mode, value="auto", command=push_settings).pack(side="left")
    tk.Radiobutton(r1, text="手動", variable=v_mode, value="manual", command=push_settings).pack(side="left")

    r2 = tk.Frame(frm)
    r2.pack(fill="x", padx=6, pady=4)
    tk.Label(r2, text="売買", width=14, anchor="w").pack(side="left")
    tk.Radiobutton(r2, text="両方", variable=v_side_mode, value="both", command=push_settings).pack(side="left")
    tk.Radiobutton(r2, text="買いのみ", variable=v_side_mode, value="buy", command=push_settings).pack(side="left")
    tk.Radiobutton(r2, text="売りのみ", variable=v_side_mode, value="sell", command=push_settings).pack(side="left")

    r3 = tk.Frame(frm)
    r3.pack(fill="x", padx=6, pady=4)
    tk.Label(r3, text="取引区分", width=14, anchor="w").pack(side="left")
    tk.Radiobutton(r3, text="現物", variable=v_cash_margin, value="cash", command=push_settings).pack(side="left")
    tk.Radiobutton(r3, text="信用(新規)", variable=v_cash_margin, value="margin", command=push_settings).pack(side="left")

    r4 = tk.Frame(frm)
    r4.pack(fill="x", padx=6, pady=4)
    tk.Label(r4, text="注文種類", width=14, anchor="w").pack(side="left")
    tk.Radiobutton(r4, text="成行", variable=v_order_type, value="market", command=push_settings).pack(side="left")
    tk.Radiobutton(r4, text="指値(±%)", variable=v_order_type, value="limit_pct", command=push_settings).pack(side="left")
    tk.Label(r4, text="%", width=2).pack(side="left", padx=(10, 0))
    tk.Entry(r4, textvariable=v_limit_pct, width=6).pack(side="left")
    tk.Button(r4, text="反映", command=lambda: _on_push_settings_with_log()).pack(side="left", padx=4)

    r5 = tk.Frame(frm)
    r5.pack(fill="x", padx=6, pady=4)
    tk.Label(r5, text="数量(株)", width=14, anchor="w").pack(side="left")
    tk.Entry(r5, textvariable=v_qty, width=8).pack(side="left")
    tk.Label(r5, text="出来高倍率", width=10, anchor="e").pack(side="left", padx=(12, 0))
    tk.Entry(r5, textvariable=v_vol_mult, width=6).pack(side="left")
    tk.Button(r5, text="反映", command=lambda: _on_push_settings_with_log()).pack(side="left", padx=4)

    r5b = tk.Frame(frm)
    r5b.pack(fill="x", padx=6, pady=4)
    tk.Label(r5b, text="株価値幅", width=14, anchor="w").pack(side="left")
    tk.Label(r5b, text="下限", width=4, anchor="e").pack(side="left")
    tk.Entry(r5b, textvariable=v_price_min, width=8).pack(side="left")
    tk.Label(r5b, text="上限", width=4, anchor="e").pack(side="left", padx=(12, 0))
    tk.Entry(r5b, textvariable=v_price_max, width=8).pack(side="left")
    tk.Label(r5b, text="(0=制限なし)", width=12, anchor="w").pack(side="left", padx=(6, 0))
    tk.Button(r5b, text="反映", command=push_settings).pack(side="left", padx=4)

    r5c = tk.Frame(frm)
    r5c.pack(fill="x", padx=6, pady=4)
    tk.Label(r5c, text="出来高下限", width=14, anchor="w").pack(side="left")
    tk.Entry(r5c, textvariable=v_base_vol_min, width=10).pack(side="left")
    tk.Label(r5c, text="(急増前の出来高, 0=制限なし)", anchor="w").pack(side="left", padx=(6, 0))
    tk.Button(r5c, text="反映", command=push_settings).pack(side="left", padx=4)

    r6 = tk.Frame(frm)
    r6.pack(fill="x", padx=6, pady=4)
    tk.Checkbutton(r6, text="DRY_RUN(テスト)", variable=v_dry, command=push_settings).pack(side="left")
    tk.Checkbutton(r6, text="確認ダイアログ", variable=v_confirm, command=push_settings).pack(side="left", padx=(10, 0))

    r6b = tk.Frame(frm)
    r6b.pack(fill="x", padx=6, pady=4)
    tk.Checkbutton(r6b, text="自動決済", variable=v_auto_exit, command=push_settings).pack(side="left")
    tk.Label(r6b, text="利確(円/100株)", width=14, anchor="e").pack(side="left", padx=(10, 0))
    tk.Entry(r6b, textvariable=v_profit_yen, width=8).pack(side="left")
    tk.Label(r6b, text="損切(円/100株)", width=14, anchor="e").pack(side="left", padx=(10, 0))
    tk.Entry(r6b, textvariable=v_stoploss_yen, width=8).pack(side="left")

    r6c = tk.Frame(frm)
    r6c.pack(fill="x", padx=6, pady=4)
    tk.Label(r6c, text="停滞秒", width=8, anchor="w").pack(side="left")
    tk.Entry(r6c, textvariable=v_stag_secs, width=6).pack(side="left")
    tk.Label(r6c, text="値幅%", width=8, anchor="e").pack(side="left", padx=(10, 0))
    tk.Entry(r6c, textvariable=v_stag_price_pct, width=6).pack(side="left")
    tk.Label(r6c, text="出来高倍", width=10, anchor="e").pack(side="left", padx=(10, 0))
    tk.Entry(r6c, textvariable=v_stag_vol_mult, width=6).pack(side="left")
    tk.Label(r6c, text="連続", width=6, anchor="e").pack(side="left", padx=(10, 0))
    tk.Entry(r6c, textvariable=v_stag_hits, width=4).pack(side="left")
    tk.Button(r6c, text="反映", command=lambda: _on_push_settings_with_log()).pack(side="left", padx=4)

    r7 = tk.Frame(frm)
    r7.pack(fill="x", padx=6, pady=8)
    tk.Label(r7, text="直近銘柄", width=14, anchor="w").pack(side="left")
    tk.Label(r7, textvariable=last_symbol_var, width=10, anchor="w").pack(side="left")
    tk.Label(r7, text="価格", width=6, anchor="e").pack(side="left")
    tk.Label(r7, textvariable=last_price_var, width=10, anchor="w").pack(side="left")
    tk.Button(r7, text="手動発注", command=on_place_order).pack(side="right")

    # 手動監視銘柄エリア（最大5銘柄）
    mw_frm = tk.LabelFrame(container, text="手動監視銘柄（最大5銘柄・常時出来高監視）")
    mw_frm.pack(fill="both", expand=True, padx=8, pady=8)

    mw_entries: List[tk.Entry] = []
    mw_row = tk.Frame(mw_frm)
    mw_row.pack(fill="x", padx=6, pady=4)
    for i in range(5):
        tk.Label(mw_row, text=f"{i+1}:", width=2).pack(side="left")
        e = tk.Entry(mw_row, width=7)
        e.pack(side="left", padx=(0, 6))
        # 初期値を環境変数から設定
        if i < len(MANUAL_WATCH_SYMBOLS):
            e.insert(0, MANUAL_WATCH_SYMBOLS[i])
        mw_entries.append(e)

    def on_apply_manual_watch():
        slots = []
        for i, e in enumerate(mw_entries):
            v = e.get().strip()
            sym = ""
            if v and _MANUAL_SYMBOL_RE.match(v):
                sym = v.upper()
            slots.append({"slot": i, "symbol": sym})
        try:
            command_queue.put_nowait({"kind": "manual_watch", "slots": slots})
        except Exception:
            pass

    tk.Button(mw_row, text="反映", command=lambda: _on_apply_manual_watch_with_log()).pack(side="left", padx=4)

    # --- 実行ログエリア（反映ボタン操作の結果表示用） ---
    exec_log_frm = tk.LabelFrame(container, text="実行ログ")
    exec_log_frm.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    exec_log_text = tk.Text(exec_log_frm, height=6, wrap="word", state="disabled",
                            font=("MS Gothic", 9), bg="#f8f8f0")
    exec_log_sb = tk.Scrollbar(exec_log_frm, orient="vertical", command=exec_log_text.yview)
    exec_log_text.configure(yscrollcommand=exec_log_sb.set)
    exec_log_sb.pack(side="right", fill="y")
    exec_log_text.pack(side="left", fill="both", expand=True, padx=2, pady=2)

    # --- コンソールログエリア（メインスレッドのprint出力を表示） ---
    console_log_frm = tk.LabelFrame(container, text="コンソールログ")
    console_log_frm.pack(fill="both", expand=True, padx=8, pady=(4, 8))
    console_log_text = tk.Text(console_log_frm, height=10, wrap="word", state="disabled",
                               font=("MS Gothic", 9), bg="#1e1e1e", fg="#d4d4d4",
                               insertbackground="#d4d4d4")
    console_log_sb = tk.Scrollbar(console_log_frm, orient="vertical", command=console_log_text.yview)
    console_log_text.configure(yscrollcommand=console_log_sb.set)
    console_log_sb.pack(side="right", fill="y")
    console_log_text.pack(side="left", fill="both", expand=True, padx=2, pady=2)

    LOG_MAX_LINES = 200

    def _append_log(widget, line):
        widget.configure(state="normal")
        widget.insert("end", line if line.endswith("\n") else line + "\n")
        total = int(widget.index("end-1c").split(".")[0])
        if total > LOG_MAX_LINES:
            widget.delete("1.0", f"{total - LOG_MAX_LINES + 1}.0")
        widget.configure(state="disabled")
        widget.see("end")

    def _append_exec_log(line):
        _append_log(exec_log_text, line)

    def _append_console_log(line):
        _append_log(console_log_text, line)

    def _deselect_all_entries():
        try:
            root.focus_set()
        except Exception:
            pass

    def _on_push_settings_with_log():
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        changes = []
        changes.append(f"モード={v_mode.get()}")
        changes.append(f"売買={v_side_mode.get()}")
        changes.append(f"取引区分={v_cash_margin.get()}")
        changes.append(f"注文種類={v_order_type.get()}")
        changes.append(f"指値%={v_limit_pct.get()}")
        changes.append(f"数量={v_qty.get()}")
        changes.append(f"出来高倍率={v_vol_mult.get()}")
        changes.append(f"DRY_RUN={'ON' if v_dry.get() else 'OFF'}")
        changes.append(f"確認ダイアログ={'ON' if v_confirm.get() else 'OFF'}")
        changes.append(f"自動決済={'ON' if v_auto_exit.get() else 'OFF'}")
        changes.append(f"利確={v_profit_yen.get()}")
        changes.append(f"損切={v_stoploss_yen.get()}")
        changes.append(f"停滞秒={v_stag_secs.get()}")
        changes.append(f"値幅%={v_stag_price_pct.get()}")
        changes.append(f"出来高倍={v_stag_vol_mult.get()}")
        changes.append(f"連続={v_stag_hits.get()}")
        push_settings()
        _append_exec_log(f"[{ts}] 注文設定を反映しました: {', '.join(changes)}")
        _deselect_all_entries()
        messagebox.showinfo("反映完了", "注文設定の反映が完了しました。")

    def _on_apply_manual_watch_with_log():
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        syms = []
        for i, e in enumerate(mw_entries):
            v = e.get().strip()
            if v:
                syms.append(f"スロット{i+1}={v.upper()}")
        on_apply_manual_watch()
        desc = ", ".join(syms) if syms else "(全スロット空)"
        _append_exec_log(f"[{ts}] 手動監視銘柄を反映しました: {desc}")
        _deselect_all_entries()
        messagebox.showinfo("反映完了", "手動監視銘柄の反映が完了しました。")

    # メインスレッドからのイベント通知を監視するループ
    def poll_queue():
        nonlocal current_watching_symbols
        try:
            while True:
                msg = event_queue.get_nowait()
                kind = msg.get("kind")
                if kind == "watch":
                    vars_["watch"].set(f"監視銘柄数: {msg.get('count', 0)}")
                elif kind == "watching_symbols":
                    # 銘柄リストを保存
                    text = msg.get('text', '-')
                    vars_["watching_symbols"].set(f"監視中銘柄: {text}")
                    # 銘柄コードと名前のリストを構築
                    symbols_list = []
                    if text and text != '-':
                        items = text.split(', ')
                        for item in items:
                            if '(' in item:
                                symbol = item.split('(')[0].strip()
                                name = item[item.find('(')+1:item.find(')')].strip()
                                symbols_list.append((symbol, name))
                            else:
                                symbols_list.append((item.strip(), ''))
                    current_watching_symbols = symbols_list
                elif kind == "watching_symbols_full":
                    syms = msg.get("symbols")
                    if not isinstance(syms, list):
                        syms = []
                    normalized: List[Tuple[str, str]] = []
                    for it in syms:
                        if isinstance(it, (list, tuple)) and len(it) >= 2:
                            normalized.append((str(it[0]), str(it[1])))
                        elif isinstance(it, dict):
                            normalized.append((str(it.get("symbol") or ""), str(it.get("name") or "")))
                    current_watching_symbols = [(s.strip(), n.strip()) for s, n in normalized if str(s or "").strip()]
                elif kind == "tdnet":
                    vars_["tdnet"].set(f"TDnet: {msg.get('text', '-')}" )
                elif kind == "edinet":
                    vars_["edinet"].set(f"EDINET: 最終チェック {msg.get('text', '-')}" )
                elif kind == "news":
                    vars_["news"].set(f"NEWS: 最終チェック {msg.get('text', '-')}" )
                elif kind == "kabus":
                    vars_["kabus"].set(f"KabuStation: {msg.get('text', '-')}" )
                elif kind == "event":
                    vars_["event"].set(f"イベント: {msg.get('text', '-')}" )
                    if msg.get("symbol"):
                        last_symbol_var.set(str(msg.get("symbol")))
                    if msg.get("price") is not None:
                        last_price_var.set(str(msg.get("price")))
                elif kind == "console_log":
                    _append_console_log(str(msg.get("text", "")))
                elif kind == "manual_watch_invalid":
                    try:
                        idx = int(msg.get("slot"))
                    except Exception:
                        idx = -1
                    if 0 <= idx < len(mw_entries):
                        try:
                            mw_entries[idx].focus_set()
                            mw_entries[idx].selection_range(0, "end")
                        except Exception:
                            pass
        except queue.Empty:
            pass

        root.after(200, poll_queue)

    root.after(200, poll_queue)
    root.mainloop()


def prompt_runtime_config_gui() -> bool:
    """起動時にGUIで設定入力ウィンドウを表示する関数。
    
    環境変数で設定されていない項目や、確認が必要な項目を入力させます。

    Returns:
        bool: OKボタンが押されたらTrue、キャンセルまたは閉じた場合はFalse。
    """
    global KABUS_API_BASE_URL
    global KABUS_API_PASSWORD
    global KABUS_EXCHANGE
    global SURGE_PRICE_PCT
    global SURGE_VOLUME_MULTIPLIER
    global CRASH_PRICE_PCT
    global CRASH_VOLUME_MULTIPLIER
    global ENABLE_GUI

    try:
        import tkinter as tk
    except Exception:
        return False

    root = tk.Tk()
    root.title("Startup Config")
    root.geometry("520x320")
    root.resizable(False, False)

    entries: Dict[str, tk.Entry] = {}

    def add_row(label: str, key: str, value: str, show: str = ""):
        row = tk.Frame(root)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text=label, width=22, anchor="w").pack(side="left")
        e = tk.Entry(row, show=show)
        e.pack(side="left", fill="x", expand=True)
        e.insert(0, value)
        entries[key] = e

    add_row("KABUS_API_BASE_URL", "base", str(KABUS_API_BASE_URL))
    add_row("KABUS_EXCHANGE", "exch", str(KABUS_EXCHANGE))
    add_row("KABUS_API_PASSWORD", "pw", "" if not KABUS_API_PASSWORD else KABUS_API_PASSWORD, show="*")
    add_row("SURGE_PRICE_PCT", "surge_pct", str(SURGE_PRICE_PCT))
    add_row("SURGE_VOLUME_MULT", "surge_vol", str(SURGE_VOLUME_MULTIPLIER))
    add_row("CRASH_PRICE_PCT", "crash_pct", str(CRASH_PRICE_PCT))
    add_row("CRASH_VOLUME_MULT", "crash_vol", str(CRASH_VOLUME_MULTIPLIER))
    add_row("ENABLE_GUI (0/1)", "enable_gui", "1" if ENABLE_GUI else "0")

    result = {"ok": False}

    def on_ok():
        result["ok"] = True
        root.quit()

    def on_cancel():
        result["ok"] = False
        root.quit()

    btns = tk.Frame(root)
    btns.pack(fill="x", padx=10, pady=10)
    tk.Button(btns, text="OK", width=10, command=on_ok).pack(side="right")
    tk.Button(btns, text="Cancel", width=10, command=on_cancel).pack(side="right", padx=4)

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()
    root.destroy()

    if not result["ok"]:
        return False

    # 入力値をグローバル変数に反映
    def _get(key: str) -> str:
        return (entries[key].get() or "").strip()

    base_in = _get("base")
    exch_in = _get("exch")
    pw_in = _get("pw")
    gui_in = _get("enable_gui")

    if base_in:
        KABUS_API_BASE_URL = base_in
    if exch_in:
        KABUS_EXCHANGE = exch_in
    if pw_in:
        KABUS_API_PASSWORD = pw_in

    def _to_float(s: str, default: float) -> float:
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default

    SURGE_PRICE_PCT = _to_float(_get("surge_pct"), SURGE_PRICE_PCT)
    SURGE_VOLUME_MULTIPLIER = _to_float(_get("surge_vol"), SURGE_VOLUME_MULTIPLIER)
    CRASH_PRICE_PCT = _to_float(_get("crash_pct"), CRASH_PRICE_PCT)
    CRASH_VOLUME_MULTIPLIER = _to_float(_get("crash_vol"), CRASH_VOLUME_MULTIPLIER)

    if gui_in in {"0", "1"}:
        ENABLE_GUI = gui_in == "1"

    return True


def prompt_runtime_config_if_needed() -> None:
    """必要に応じて設定入力を促す関数。
    
    パスワード未設定時やPROMPT_CONFIGが有効な場合に呼び出され、
    CUIまたはGUIで入力を受け付けます。
    """
    global KABUS_API_BASE_URL
    global KABUS_API_PASSWORD
    global KABUS_EXCHANGE
    global SURGE_PRICE_PCT
    global SURGE_VOLUME_MULTIPLIER
    global CRASH_PRICE_PCT
    global CRASH_VOLUME_MULTIPLIER
    global ENABLE_GUI

    should_prompt = PROMPT_CONFIG or (not KABUS_API_PASSWORD)
    if not should_prompt:
        return

    def _prompt_float(label: str, current: float, desc: str) -> float:
        s = input(f"{label} [{current}] ({desc}): ").strip()
        if not s:
            return current
        try:
            return float(s)
        except ValueError:
            return current

    interactive_stdin = True
    if not sys.stdin or (hasattr(sys.stdin, "isatty") and (not sys.stdin.isatty())):
        interactive_stdin = False

    if not interactive_stdin:
        ok = prompt_runtime_config_gui()
        if not ok:
            print("Config prompt skipped (no interactive stdin). Set environment variables instead.")
        return

    # CUIでの設定入力フロー
    base_in = input(f"KABUS_API_BASE_URL [{KABUS_API_BASE_URL}] (KabuStation API接続先。通常は変更不要): ").strip()
    if base_in:
        KABUS_API_BASE_URL = base_in

    exch_in = input(f"KABUS_EXCHANGE [{KABUS_EXCHANGE}] (取引所コード。通常は1=東証): ").strip()
    if exch_in:
        KABUS_EXCHANGE = exch_in

    pw_in = getpass.getpass("KABUS_API_PASSWORD (APIトークン発行に必要。空欄で既存値維持): ").strip()
    if pw_in:
        KABUS_API_PASSWORD = pw_in

    SURGE_PRICE_PCT = _prompt_float("SURGE_PRICE_PCT", SURGE_PRICE_PCT, "急騰検知の価格変化率(%)。小さいほど検知が増える")
    SURGE_VOLUME_MULTIPLIER = _prompt_float(
        "SURGE_VOLUME_MULTIPLIER",
        SURGE_VOLUME_MULTIPLIER,
        "急騰検知の出来高倍率。小さいほど検知が増える",
    )
    CRASH_PRICE_PCT = _prompt_float("CRASH_PRICE_PCT", CRASH_PRICE_PCT, "急落検知の価格変化率(%)。小さいほど検知が増える")
    CRASH_VOLUME_MULTIPLIER = _prompt_float(
        "CRASH_VOLUME_MULTIPLIER",
        CRASH_VOLUME_MULTIPLIER,
        "急落検知の出来高倍率。小さいほど検知が増える",
    )

    gui_in = input(f"ENABLE_GUI (0/1) [{'1' if ENABLE_GUI else '0'}] (1でGUI表示。0でコンソールのみ): ").strip()
    if gui_in in {"0", "1"}:
        ENABLE_GUI = gui_in == "1"


def archive_old_logs(keep_days: int = 2) -> None:
    """古いログファイルを圧縮・整理する関数。
    
    指定日数より前のログフォルダやCSVをZIPにまとめ、_backディレクトリに移動します。

    Args:
        keep_days (int): 保持する日数。これより古いものがアーカイブ対象。
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        back_dir = os.path.join(LOG_DIR, "_back")
        os.makedirs(back_dir, exist_ok=True)

        today = datetime.datetime.now().strftime("%Y%m%d")
        today_dt = datetime.datetime.strptime(today, "%Y%m%d")
        cutoff_dt = today_dt - datetime.timedelta(days=int(keep_days))

        candidates = set()
        # 日付フォルダを探す
        try:
            for name in os.listdir(LOG_DIR):
                if len(name) == 8 and name.isdigit() and os.path.isdir(os.path.join(LOG_DIR, name)):
                    candidates.add(name)
        except Exception:
            pass

        # 日付付きCSVファイルを探す
        try:
            for name in os.listdir(LOG_DIR):
                if name.startswith("tdnet_") and name.endswith(".csv"):
                    y = name[len("tdnet_"):-len(".csv")]
                    if len(y) == 8 and y.isdigit():
                        candidates.add(y)
                if name.startswith("trade_events_") and name.endswith(".csv"):
                    y = name[len("trade_events_"):-len(".csv")]
                    if len(y) == 8 and y.isdigit():
                        candidates.add(y)
                if name.startswith("edinet_") and name.endswith(".csv"):
                    y = name[len("edinet_"):-len(".csv")]
                    if len(y) == 8 and y.isdigit():
                        candidates.add(y)
                if name.startswith("news_") and name.endswith(".csv"):
                    y = name[len("news_"):-len(".csv")]
                    if len(y) == 8 and y.isdigit():
                        candidates.add(y)
        except Exception:
            pass

        for yyyymmdd in sorted(candidates):
            try:
                dt = datetime.datetime.strptime(yyyymmdd, "%Y%m%d")
            except Exception:
                continue

            # 新しいものはスキップ
            if dt > cutoff_dt:
                continue

            zip_path = os.path.join(back_dir, f"{yyyymmdd}.zip")
            if os.path.exists(zip_path):
                continue

            date_dir = os.path.join(LOG_DIR, yyyymmdd)
            moved_any = False

            # 旧形式でルートにあるログCSVが残っている場合は日付ディレクトリへ寄せる
            for fn in (f"tdnet_{yyyymmdd}.csv", f"trade_events_{yyyymmdd}.csv", f"edinet_{yyyymmdd}.csv", f"news_{yyyymmdd}.csv", f"order_{yyyymmdd}.csv"):
                src = os.path.join(LOG_DIR, fn)
                if os.path.exists(src):
                    os.makedirs(date_dir, exist_ok=True)
                    shutil.move(src, os.path.join(date_dir, fn))
                    moved_any = True

            if os.path.isdir(date_dir):
                moved_any = True

            if not moved_any:
                continue

            # ZIP圧縮（日付ディレクトリを丸ごと）
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(date_dir):
                    for f in files:
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, date_dir)
                        zf.write(full, arcname=os.path.join(yyyymmdd, rel))

            # 日付ディレクトリ削除
            shutil.rmtree(date_dir, ignore_errors=True)
    except Exception:
        return


def main():
    """メインのエントリーポイント。
    
    スレッドの起動、監視ループ、APIポーリング、発注ロジックの管理を行います。
    """
    print("=== TDnet 好材料監視モニターを開始します ===")
    print(f"ターゲットキーワード: {POSITIVE_KEYWORDS}")

    # 古いログのアーカイブ
    archive_old_logs(keep_days=2)

    # 設定確認
    prompt_runtime_config_if_needed()

    phase_now = get_market_phase_jp()

    print_current_env_config(phase_now)

    current_date = datetime.datetime.now().strftime("%Y%m%d")
    processed_titles = load_processed_keys(current_date) # 既に検知済みのニュースをロード

    # EDINET初期化
    edinet_code_map: Dict[str, str] = {}
    edinet_processed_docs: set = set()
    if EDINET_API_KEY:
        edinet_code_map = load_edinet_code_map()
        edinet_processed_docs = load_edinet_processed_keys(current_date)
        print(f"[EDINET] 監視開始 (VIPキーワード: {EDINET_VIP_KEYWORDS})")
    else:
        print("[EDINET] EDINET_API_KEY が未設定のためEDINET監視は無効です")

    # ニュースモニター初期化
    news_name_dict: Dict[str, str] = load_news_aliases()
    edinet_company_index = load_edinet_company_code_index(EDINET_CODE_LIST_PATH)
    news_processed_urls: set = load_news_processed_keys(current_date)
    news_consecutive_errors = 0
    print(f"[NEWS] ニュース監視開始 (キーワード数: {len(VOLATILITY_KEYWORDS)}, 略称辞書: {len(news_name_dict)} 件)")
    print(f"[NEWS] ポーリング間隔: {NEWS_POLL_SECONDS}秒, 監視時間: {NEWS_WATCH_WINDOW_SECONDS}秒")

    kabus_token = None
    kabus_unregistered_on_start = False
    watchlist = {} # 監視対象の銘柄情報を保持する辞書

    # 手動監視銘柄の初期登録
    if MANUAL_WATCH_SYMBOLS:
        print(f"[MANUAL] 手動監視銘柄: {MANUAL_WATCH_SYMBOLS}")
        for sym in MANUAL_WATCH_SYMBOLS:
            watchlist[sym] = {
                "tdnet_key": f"manual_{sym}",
                "added_at": time.time(),
                "baseline_price": None, # 基準価格（初期値）
                "baseline_volume": None, # 基準出来高（初期値）
                "last_volume": None,
                "last_vol_at": None,
                "vol_hist": None, # 出来高推移履歴
                "rate_ema": None, # 出来高増加率のEMA
                "next_board_at": 0.0,
                "board_backoff": 0.0,
                "order_hit_streak": 0,
                "triggered_surge": False,
                "triggered_crash": False,
                "triggered_order": False,
                "special_quote_streak": 0,
                "source": "manual",
                "filer_name": "",
                "doc_description": "",
                "watch_window": MANUAL_WATCH_WINDOW_SECONDS,
                "stagnation_exit_streak": 0,
                "auto_exit_done": False,
            }
            print(f"[MANUAL] watchlistに追加: {sym} (常時監視)")

    # 昼休み(11:30-12:30)に検知した銘柄は12:30にまとめて監視開始
    pending_watchlist: Dict[str, Dict[str, Any]] = {}
    pending_release_at: float = 0.0

    # 注文設定の初期状態
    order_settings: Dict[str, Any] = {
        "mode": ORDER_MODE,
        "side_mode": ORDER_SIDE_MODE,
        "cash_margin": ORDER_CASH_MARGIN,
        "order_type": ORDER_TYPE,
        "limit_pct": float(ORDER_LIMIT_PCT),
        "qty": int(ORDER_QTY),
        "dry_run": bool(ORDER_DRY_RUN),
        "confirm": bool(ORDER_CONFIRM),
        "volume_mult": float(ORDER_VOLUME_MULTIPLIER),
        "price_min": float(ORDER_PRICE_MIN),
        "price_max": float(ORDER_PRICE_MAX),
        "base_volume_min": float(ORDER_BASE_VOLUME_MIN),
        "auto_exit": bool(AUTO_EXIT_ENABLE),
        "profit_yen_per_100": float(AUTO_EXIT_PROFIT_YEN_PER_100),
        "stoploss_yen_per_100": float(AUTO_EXIT_STOPLOSS_YEN_PER_100),
        "stagnation_seconds": float(AUTO_EXIT_STAGNATION_SECONDS),
        "stagnation_price_pct": float(AUTO_EXIT_STAGNATION_PRICE_PCT),
        "stagnation_volume_mult": float(AUTO_EXIT_STAGNATION_VOLUME_MULT),
        "stagnation_hits": int(AUTO_EXIT_STAGNATION_HITS),
    }

    pending_manual_symbol: Optional[str] = None # 手動注文要求があった銘柄

    event_queue: "queue.Queue" = queue.Queue()
    command_queue: "queue.Queue" = queue.Queue()
    
    # GUIスレッドの開始
    if ENABLE_GUI:
        t = threading.Thread(target=start_gui, args=(event_queue, command_queue), daemon=True)
        t.start()

    # printの出力をGUIコンソールログにも転送するラッパー
    _original_print = builtins.print
    def _gui_print(*args, **kwargs):
        _original_print(*args, **kwargs)
        try:
            import io
            buf = io.StringIO()
            kwargs_copy = dict(kwargs)
            kwargs_copy["file"] = buf
            _original_print(*args, **kwargs_copy)
            text = buf.getvalue().rstrip("\n")
            if text and ENABLE_GUI:
                event_queue.put_nowait({"kind": "console_log", "text": text})
        except Exception:
            pass
    builtins.print = _gui_print

    consecutive_errors = 0
    poll_seconds = BASE_POLL_SECONDS

    next_tdnet_check_at = 0.0
    next_watch_check_at = 0.0
    next_edinet_check_at = 0.0
    edinet_consecutive_errors = 0
    next_news_check_at = 0.0
    next_positions_check_at = 0.0
    held_positions: Dict[str, Dict[str, Any]] = {}

    try:
        # メインループ
        while True:
            now = time.time()

            # 昼休み(11:30-12:30)に検知した銘柄は12:30にまとめて監視開始
            if pending_watchlist and pending_release_at > 0 and now >= pending_release_at:
                for sym in list(pending_watchlist.keys()):
                    if WATCH_MAX_SYMBOLS > 0 and len(watchlist) >= WATCH_MAX_SYMBOLS:
                        break
                    if sym not in watchlist:
                        watchlist[sym] = pending_watchlist[sym]
                        print(f"[LUNCH_BATCH] watchlistに追加: {sym}")
                pending_watchlist.clear()
                pending_release_at = 0.0
                notify_watchlist_change(watchlist, edinet_company_index, event_queue)

            # GUIからのコマンド処理（設定変更や注文要求）
            try:
                while True:
                    cmd = command_queue.get_nowait()
                    kind = cmd.get("kind")
                    if kind == "settings":
                        apply_order_settings(order_settings, cmd)
                    elif kind == "order_request":
                        pending_manual_symbol = str(cmd.get("symbol") or "").strip() or None
                    elif kind == "manual_watch":
                        slots = cmd.get("slots")
                        if not isinstance(slots, list):
                            slots = []

                        # 既存の手動監視銘柄を削除（source="manual"のもの）
                        to_remove = [s for s, st in watchlist.items() if st.get("source") == "manual"]
                        for s in to_remove:
                            watchlist.pop(s, None)

                        # 銘柄名の解決を行うため、必要ならトークンを取得
                        if kabus_token is None:
                            try:
                                kabus_token = kabus_get_token()
                            except Exception:
                                kabus_token = None

                        added_syms: List[str] = []

                        for it in slots[:5]:
                            if not isinstance(it, dict):
                                continue
                            try:
                                slot_idx = int(it.get("slot"))
                            except Exception:
                                slot_idx = -1
                            sym = str(it.get("symbol") or "").strip().upper()
                            if not sym:
                                continue
                            if not _MANUAL_SYMBOL_RE.match(sym):
                                continue
                            if sym in watchlist:
                                continue

                            company_name = ""
                            valid = True
                            if kabus_token:
                                try:
                                    st_sym, payload_sym = kabus_get_symbol_info(sym, kabus_token)
                                    if st_sym != 200:
                                        valid = False
                                    elif isinstance(payload_sym, dict):
                                        company_name = str(payload_sym.get("SymbolName") or payload_sym.get("SymbolNameFull") or payload_sym.get("SymbolNameShort") or "").strip()
                                    else:
                                        valid = False
                                except Exception:
                                    valid = False

                            if not valid:
                                try:
                                    event_queue.put_nowait({"kind": "manual_watch_invalid", "slot": slot_idx})
                                except Exception:
                                    pass
                                continue

                            watchlist[sym] = {
                                "tdnet_key": f"manual_{sym}",
                                "added_at": time.time(),
                                "baseline_price": None,
                                "baseline_volume": None,
                                "last_volume": None,
                                "last_vol_at": None,
                                "vol_hist": None,
                                "rate_ema": None,
                                "next_board_at": 0.0,
                                "board_backoff": 0.0,
                                "order_hit_streak": 0,
                                "triggered_surge": False,
                                "triggered_crash": False,
                                "triggered_order": False,
                                "special_quote_streak": 0,
                                "source": "manual",
                                "filer_name": "",
                                "doc_description": "",
                                "watch_window": MANUAL_WATCH_WINDOW_SECONDS,
                                "stagnation_exit_streak": 0,
                                "auto_exit_done": False,
                                "company_name": company_name,
                            }
                            added_syms.append(sym)

                        try:
                            event_queue.put_nowait({"kind": "event", "text": f"手動監視銘柄更新: {added_syms}", "symbol": ""})
                        except Exception:
                            pass
                        notify_watchlist_change(watchlist, edinet_company_index, event_queue)
            except queue.Empty:
                pass

            # 日付変更時のリセット処理
            now_date = datetime.datetime.now().strftime("%Y%m%d")
            if now_date != current_date:
                current_date = now_date
                processed_titles = load_processed_keys(current_date)
                if EDINET_API_KEY:
                    edinet_processed_docs = load_edinet_processed_keys(current_date)
                news_processed_urls = load_news_processed_keys(current_date)

            # --- TDnet 監視フェーズ ---
            if now >= next_tdnet_check_at:
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] TDnetチェック中...")
                try:
                    event_queue.put_nowait({"kind": "tdnet", "text": datetime.datetime.now().strftime("%H:%M:%S")})
                except Exception:
                    pass
                
                # TDnetから開示情報を取得
                disclosures, status_code, retry_after = get_tdnet_disclosures()

                # エラーハンドリングとバックオフ制御
                if status_code == 200:
                    consecutive_errors = 0
                    poll_seconds = BASE_POLL_SECONDS
                else:
                    consecutive_errors += 1
                    poll_seconds = min(MAX_POLL_SECONDS, BASE_POLL_SECONDS * (2 ** min(consecutive_errors, 6)))
                    if retry_after and retry_after > poll_seconds:
                        poll_seconds = min(MAX_POLL_SECONDS, retry_after)

                tdnet_sleep_seconds = max(1, float(poll_seconds + random.uniform(-JITTER_SECONDS, JITTER_SECONDS)))
                next_tdnet_check_at = now + tdnet_sleep_seconds

                # 未処理の新規開示を抽出
                new_items = []
                for item in disclosures:
                    unique_key = make_unique_key(item)
                    if unique_key not in processed_titles:
                        new_items.append(item)

                if new_items:
                    def _parse_tdnet_dt(it: Dict[str, Any]) -> Optional[datetime.datetime]:
                        d = str(it.get("date") or "").strip()
                        t = str(it.get("time") or "").strip()
                        if not d or not t:
                            return None
                        try:
                            return datetime.datetime.strptime(f"{d} {t}", "%Y%m%d %H:%M")
                        except Exception:
                            return None

                    # 1) 未検知分はすべてログに書き込み
                    for item in new_items:
                        unique_key = make_unique_key(item)
                        print(f"★検知★ {item['time']} | {item['code']} {item['name']}")
                        print(f"内容: {item['title']}")
                        print("-" * 30)
                        append_csv_log(item, item.get("date") or datetime.datetime.now().strftime("%Y%m%d"))
                        processed_titles.add(unique_key)

                    # 2) 監視(Watch)対象への追加判定
                    # 過去のゴミデータを拾わないよう、最新時刻の開示のみを対象とする
                    parsed = [(item, _parse_tdnet_dt(item)) for item in new_items]
                    parsed_ok = [p for p in parsed if p[1] is not None]
                    watch_items = []
                    if parsed_ok:
                        latest_dt = max(p[1] for p in parsed_ok)
                        watch_items = [p[0] for p in parsed_ok if p[1] == latest_dt]
                    else:
                        watch_items = list(new_items)

                    # 監視リスト(watchlist)へ登録
                    for item in watch_items:
                        unique_key = make_unique_key(item)
                        symbol = normalize_tdnet_code_to_symbol(item.get("code", ""))
                        if symbol:
                            in_lunch, release_at = is_lunch_batch_window(datetime.datetime.now(JST))
                            # 監視上限数チェック
                            if (not in_lunch) and WATCH_MAX_SYMBOLS > 0 and len(watchlist) >= WATCH_MAX_SYMBOLS:
                                continue

                            # 初期状態の設定
                            st = {
                                "tdnet_key": unique_key,
                                "added_at": time.time(),
                                "baseline_price": None, # 基準価格（初期値）
                                "baseline_volume": None, # 基準出来高（初期値）
                                "last_volume": None,
                                "last_vol_at": None,
                                "vol_hist": None, # 出来高推移履歴
                                "rate_ema": None, # 出来高増加率のEMA
                                "next_board_at": 0.0,
                                "board_backoff": 0.0,
                                "order_hit_streak": 0,
                                "triggered_surge": False,
                                "triggered_crash": False,
                                "triggered_order": False,
                                "special_quote_streak": 0,
                                "source": "tdnet",
                                "filer_name": "",
                                "doc_description": "",
                                "watch_window": WATCH_WINDOW_SECONDS,
                            }

                            if in_lunch:
                                pending_watchlist[symbol] = st
                                pending_release_at = max(pending_release_at, float(release_at))
                                print(f"[LUNCH_BATCH] TDnet検知 {symbol} → {LUNCH_BATCH_END_HHMM}まで保留")
                            else:
                                watchlist.setdefault(symbol, st)

            # --- EDINET 監視フェーズ ---
            if EDINET_API_KEY and now >= next_edinet_check_at:
                today_hyphen = datetime.datetime.now().strftime("%Y-%m-%d")
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] EDINETチェック中...")
                try:
                    event_queue.put_nowait({"kind": "edinet", "text": datetime.datetime.now().strftime("%H:%M:%S")})
                except Exception:
                    pass

                edinet_docs, edinet_status = fetch_edinet_documents(today_hyphen)

                if edinet_status == 200:
                    edinet_consecutive_errors = 0
                    edinet_poll = EDINET_POLL_SECONDS
                else:
                    edinet_consecutive_errors += 1
                    edinet_poll = min(MAX_POLL_SECONDS, EDINET_POLL_SECONDS * (2 ** min(edinet_consecutive_errors, 4)))

                next_edinet_check_at = now + float(edinet_poll)

                if edinet_status == 200 and edinet_docs:
                    matched_docs = filter_edinet_documents(edinet_docs, edinet_code_map)

                    for doc in matched_docs:
                        doc_id = doc.get("doc_id", "")
                        if doc_id in edinet_processed_docs:
                            continue

                        edinet_processed_docs.add(doc_id)
                        symbol = doc.get("symbol", "")
                        filer_name = doc.get("filer_name", "")
                        doc_desc = doc.get("doc_description", "")
                        vip_kw = doc.get("vip_keyword", "")

                        print(f"★EDINET検知★ {filer_name} | {doc_desc}")
                        if symbol:
                            print(f"  証券コード: {symbol}")
                        else:
                            print(f"  証券コード: 不明 (EDINETコード: {doc.get('edinet_code', '')})")
                        print("-" * 30)

                        # ログ保存
                        append_edinet_log(
                            {
                                "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                **doc,
                            },
                            current_date,
                        )

                        # GUIへ通知
                        try:
                            event_queue.put_nowait({
                                "kind": "event",
                                "text": f"【EDINET】★{vip_kw} {filer_name} → {symbol or '?'} ({doc_desc})",
                                "symbol": symbol,
                            })
                        except Exception:
                            pass

                        # 証券コードが判明していれば watchlist に追加
                        if symbol and symbol not in watchlist:
                            in_lunch, release_at = is_lunch_batch_window(datetime.datetime.now(JST))
                            if in_lunch or (WATCH_MAX_SYMBOLS <= 0 or len(watchlist) < WATCH_MAX_SYMBOLS):
                                edinet_key = f"edinet_{doc_id}"
                                st = {
                                    "tdnet_key": edinet_key,
                                    "added_at": time.time(),
                                    "baseline_price": None,
                                    "baseline_volume": None,
                                    "last_volume": None,
                                    "last_vol_at": None,
                                    "vol_hist": None,
                                    "rate_ema": None,
                                    "next_board_at": 0.0,
                                    "board_backoff": 0.0,
                                    "order_hit_streak": 0,
                                    "triggered_surge": False,
                                    "triggered_crash": False,
                                    "triggered_order": False,
                                    "special_quote_streak": 0,
                                    "source": "edinet",
                                    "filer_name": filer_name,
                                    "doc_description": doc_desc,
                                    "watch_window": EDINET_WATCH_WINDOW_SECONDS,
                                }
                                if in_lunch:
                                    pending_watchlist[symbol] = st
                                    pending_release_at = max(pending_release_at, float(release_at))
                                    print(f"[LUNCH_BATCH] EDINET検知 {symbol} → {LUNCH_BATCH_END_HHMM}まで保留")
                                else:
                                    watchlist[symbol] = st
                                    print(f"[EDINET] watchlistに追加: {symbol} (監視時間: {EDINET_WATCH_WINDOW_SECONDS}秒)")

            # --- ニュース監視フェーズ ---
            if now >= next_news_check_at:
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] ニュースチェック中...")
                try:
                    event_queue.put_nowait({"kind": "news", "text": datetime.datetime.now().strftime("%H:%M:%S")})
                except Exception:
                    pass

                all_news = []
                try:
                    # みんかぶから取得
                    minkabu_articles = fetch_minkabu_news(news_name_dict, edinet_company_index=edinet_company_index)
                    all_news.extend(minkabu_articles)
                    time.sleep(random.uniform(2.0, 5.0))

                    # Yahoo!ファイナンスから取得
                    yahoo_articles = fetch_yahoo_finance_news(news_name_dict, edinet_company_index=edinet_company_index)
                    all_news.extend(yahoo_articles)

                    news_consecutive_errors = 0
                    news_poll = NEWS_POLL_SECONDS
                except Exception as e:
                    print(f"[NEWS] 取得エラー: {e}")
                    news_consecutive_errors += 1
                    news_poll = min(MAX_POLL_SECONDS, NEWS_POLL_SECONDS * (2 ** min(news_consecutive_errors, 4)))

                next_news_check_at = now + float(news_poll) + random.uniform(0.0, 5.0)

                # 新規ニュースの処理
                new_news_count = 0
                for article in all_news:
                    article_url = (article.get("url") or "").strip()
                    if not article_url or article_url in news_processed_urls:
                        continue

                    # 防御的に「直近N分」フィルタ（取得側で漏れた場合の保険）
                    published_ts = article.get("published_ts")
                    try:
                        published_ts_f = float(published_ts) if published_ts is not None and published_ts != "" else None
                    except Exception:
                        published_ts_f = None
                    if published_ts_f is None:
                        continue
                    if published_ts_f <= time.time() - NEWS_LOOKBACK_SECONDS:
                        continue

                    news_processed_urls.add(article_url)
                    symbol = (article.get("symbol") or "").strip()
                    source = article.get("source", "")
                    title = article.get("title", "")
                    matched_kw = article.get("matched_keyword", "")
                    matched_name = article.get("matched_name", "")

                    # 銘柄コードが特定できない場合はログのみ（watchlistには追加しない）
                    new_news_count += 1
                    print(f"★NEWS検知★ [{source}] {title}")
                    if symbol:
                        print(f"  銘柄: {symbol} (キーワード: {matched_kw}, 名称: {matched_name})")
                    else:
                        print(f"  銘柄: 不明 (キーワード: {matched_kw})")
                    print("-" * 30)

                    # ニュースログに追記
                    append_news_log(
                        {
                            "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                            "source": source,
                            "title": title,
                            "url": article_url,
                            "symbol": symbol,
                            "matched_keyword": matched_kw,
                            "matched_name": matched_name,
                            "published_ts": published_ts_f,
                        },
                        current_date,
                    )

                    # GUIへ通知
                    try:
                        event_queue.put_nowait({
                            "kind": "event",
                            "text": f"【NEWS】{source}: {title[:40]}... → {symbol or '?'}",
                            "symbol": symbol,
                        })
                    except Exception:
                        pass

                    # 銘柄コードが判明していればwatchlistに追加
                    if symbol and symbol not in watchlist:
                        in_lunch, release_at = is_lunch_batch_window(datetime.datetime.now(JST))
                        if in_lunch or (WATCH_MAX_SYMBOLS <= 0 or len(watchlist) < WATCH_MAX_SYMBOLS):
                            news_key = f"news_{article_url}"
                            st = {
                                "tdnet_key": news_key,
                                "added_at": time.time(),
                                "baseline_price": None,
                                "baseline_volume": None,
                                "last_volume": None,
                                "last_vol_at": None,
                                "vol_hist": None,
                                "rate_ema": None,
                                "next_board_at": 0.0,
                                "board_backoff": 0.0,
                                "order_hit_streak": 0,
                                "triggered_surge": False,
                                "triggered_crash": False,
                                "triggered_order": False,
                                "special_quote_streak": 0,
                                "source": "news",
                                "filer_name": "",
                                "doc_description": f"[{source}] {title[:60]}",
                                "watch_window": NEWS_WATCH_WINDOW_SECONDS,
                                "triggered_news": True,
                            }

                            if in_lunch:
                                pending_watchlist[symbol] = st
                                pending_release_at = max(pending_release_at, float(release_at))
                                print(f"[LUNCH_BATCH] NEWS検知 {symbol} → {LUNCH_BATCH_END_HHMM}まで保留")
                            else:
                                watchlist[symbol] = st
                                print(f"[NEWS] watchlistに追加: {symbol} (監視時間: {NEWS_WATCH_WINDOW_SECONDS}秒)")

                if new_news_count > 0:
                    print(f"[NEWS] 新規検知: {new_news_count} 件 (Minkabu: {len(minkabu_articles)}, Yahoo: {len(yahoo_articles)})")

            # --- Watchlist 監視フェーズ ---
            if now >= next_watch_check_at and watchlist:
                next_watch_check_at = now + get_watch_poll_seconds()

                try:
                    event_queue.put_nowait({"kind": "watch", "count": len(watchlist)})
                except Exception:
                    pass

                notify_watchlist_change(watchlist, edinet_company_index, event_queue)

                # トークン取得または再取得
                if kabus_token is None:
                    try:
                        kabus_token = kabus_get_token()
                    except Exception:
                        kabus_token = None

                try:
                    event_queue.put_nowait({"kind": "kabus", "text": "token_ok" if kabus_token else "token_ng"})
                except Exception:
                    pass

                # 初回のみ全登録解除（不要なPush配信を止めるため）
                if kabus_token and (not kabus_unregistered_on_start):
                    try:
                        kabus_unregister_all(kabus_token)
                        kabus_unregistered_on_start = True
                    except Exception:
                        pass

                if kabus_token:
                    # 各監視銘柄についてループ処理
                    for symbol in list(watchlist.keys()):
                        state = watchlist.get(symbol) or {}
                        tdnet_key = state.get("tdnet_key", "")

                        if (not str(state.get("company_name") or "").strip()):
                            try:
                                st_sym, payload_sym = kabus_get_symbol_info(symbol, kabus_token)
                                if st_sym == 200 and isinstance(payload_sym, dict):
                                    nm = str(payload_sym.get("SymbolName") or payload_sym.get("SymbolNameFull") or payload_sym.get("SymbolNameShort") or "").strip()
                                    if nm:
                                        state["company_name"] = nm
                                        watchlist[symbol] = state
                            except Exception:
                                pass

                        watch_meta = {
                            "source": str(state.get("source") or ""),
                            "filer_name": str(state.get("filer_name") or ""),
                            "doc_description": str(state.get("doc_description") or ""),
                        }

                        # 監視期間終了判定（EDINET由来はwatch_windowを個別に持つ）
                        watch_window = float(state.get("watch_window") or WATCH_WINDOW_SECONDS)
                        added_at = state.get("added_at") or now
                        if now - added_at > watch_window:
                            if state.get("source") == "manual":
                                # 手動監視銘柄は期限切れにせず、タイマーをリセットして継続
                                state["added_at"] = time.time()
                                state["triggered_surge"] = False
                                state["triggered_crash"] = False
                                state["triggered_order"] = False
                                state["order_hit_streak"] = 0
                                watchlist[symbol] = state
                            else:
                                watchlist.pop(symbol, None)
                            continue

                        # 個別銘柄のポーリングタイミングチェック
                        next_board_at = float(state.get("next_board_at") or 0.0)
                        if float(now) < next_board_at:
                            continue

                        # 板情報取得
                        status, board = kabus_get_board(symbol, kabus_token)
                        
                        # トークン切れ対応
                        if status == 401:
                            kabus_token = None
                            break
                        # 銘柄コードエラー等の対応（APIのバグ回避含む）
                        if status == 400 and isinstance(board, dict) and board.get("Code") == 4002006:
                            try:
                                kabus_unregister_all(kabus_token)
                            except Exception:
                                pass
                            status, board = kabus_get_board(symbol, kabus_token)
                        
                        # APIエラー時のバックオフ処理
                        if status != 200:
                            if status == 429: # レートリミット
                                prev_backoff = float(state.get("board_backoff") or 0.0)
                                if prev_backoff <= 0:
                                    prev_backoff = float(WATCH_RATE_LIMIT_BACKOFF_BASE)
                                backoff = min(float(WATCH_RATE_LIMIT_BACKOFF_MAX), max(float(WATCH_RATE_LIMIT_BACKOFF_BASE), prev_backoff * 2.0))
                                state["board_backoff"] = backoff
                                state["next_board_at"] = float(now) + float(backoff)
                                watchlist[symbol] = state
                            else:
                                # 軽いエラーは短めに間引く
                                state["next_board_at"] = float(now) + float(get_watch_poll_seconds())
                                watchlist[symbol] = state

                            append_watch_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    **watch_meta,
                                    "status": status,
                                    "triggered": state.get("triggered_surge") or state.get("triggered_crash"),
                                },
                                current_date,
                            )
                            continue

                        # 特別買/売気配が続く銘柄は監視対象から外す
                        sq = detect_special_quote_side(board) if isinstance(board, dict) else ""
                        if sq:
                            prev_sq = int(state.get("special_quote_streak") or 0) + 1
                            state["special_quote_streak"] = prev_sq
                            watchlist[symbol] = state
                            if SPECIAL_QUOTE_REMOVE_STREAK > 0 and prev_sq >= SPECIAL_QUOTE_REMOVE_STREAK:
                                watchlist.pop(symbol, None)
                                try:
                                    event_queue.put_nowait({"kind": "event", "text": f"特別気配除外 {symbol} ({sq})", "symbol": symbol})
                                except Exception:
                                    pass
                                continue
                        else:
                            if int(state.get("special_quote_streak") or 0) != 0:
                                state["special_quote_streak"] = 0
                                watchlist[symbol] = state

                        # 板情報から価格と出来高を抽出
                        price, volume = extract_price_volume(board)
                        if price is None or volume is None:
                            # データ欠損時はログだけ残してスキップ
                            append_watch_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    **watch_meta,
                                    "status": "no_price_or_volume",
                                    "triggered": state.get("triggered_surge") or state.get("triggered_crash"),
                                },
                                current_date,
                            )
                            continue

                        # 初回取得時（ベースラインの設定）
                        if state.get("baseline_price") is None:
                            state["baseline_price"] = price
                            state["baseline_volume"] = max(volume, 1.0)
                            state["last_volume"] = volume
                            state["last_vol_at"] = float(now)
                            state["vol_hist"] = [(float(now), float(volume))]
                            state["rate_ema"] = None
                            state["max_price"] = price  # 監視期間中の最高値
                            state["min_price"] = price  # 監視期間中の最安値
                            base_poll = float(get_watch_poll_seconds())
                            state["next_board_at"] = float(now) + random.uniform(0.0, max(0.2, base_poll))
                            state["board_backoff"] = 0.0
                            state["order_hit_streak"] = int(state.get("order_hit_streak") or 0)
                            state["special_quote_streak"] = int(state.get("special_quote_streak") or 0)
                            watchlist[symbol] = state

                            append_watch_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    **watch_meta,
                                    "status": "baseline_set",
                                    "price": price,
                                    "volume": volume,
                                    "baseline_price": price,
                                    "baseline_volume": max(volume, 1.0),
                                    "triggered": state.get("triggered_surge") or state.get("triggered_crash"),
                                },
                                current_date,
                            )
                            continue

                        # 2回目以降：変動率の計算
                        base_price = float(state.get("baseline_price", 0) or 0)
                        base_volume = float(state.get("baseline_volume", 1.0) or 1.0)

                        price = float(price)
                        volume = float(volume)

                        # 価格変化率(%)
                        price_pct = ((price - base_price) / base_price) * 100.0 if base_price != 0 else 0.0

                        # 出来高増加ペースの計算（直近n秒間の増加量からレートを算出）
                        vol_hist = state.get("vol_hist")
                        if not isinstance(vol_hist, list):
                            vol_hist = []
                        vol_hist.append((float(now), float(volume)))
                        win = float(WATCH_VOLRATE_WINDOW_SECONDS)
                        if win <= 0:
                            win = 10.0
                        cutoff = float(now) - win
                        # 古い履歴データの削除
                        while len(vol_hist) >= 2 and float(vol_hist[0][0]) < cutoff:
                            vol_hist.pop(0)
                        state["vol_hist"] = vol_hist

                        oldest_t, oldest_v = vol_hist[0] if vol_hist else (float(now), float(volume))
                        dt = max(0.0001, float(now) - float(oldest_t))
                        dv = max(0.0, float(volume) - float(oldest_v))
                        vol_rate = dv / dt # 単位時間あたりの出来高増加量

                        # 出来高倍率の計算（EMAを使用）
                        prev_ema = state.get("rate_ema")
                        if prev_ema is None:
                            prev_ema = vol_rate

                        denom = max(float(prev_ema), float(WATCH_VOLRATE_MIN_BASE))
                        volume_mult = (vol_rate / denom) if denom > 0 else 0.0

                        # EMA更新
                        alpha = float(WATCH_VOLRATE_EMA_ALPHA)
                        if alpha <= 0:
                            alpha = 0.2
                        if alpha >= 1:
                            alpha = 1.0
                        state["rate_ema"] = (float(prev_ema) * (1.0 - alpha)) + (float(vol_rate) * alpha)
                        
                        # 最高値・最安値の更新（価格変動幅の追跡）
                        max_price = float(state.get("max_price") or price)
                        min_price = float(state.get("min_price") or price)
                        state["max_price"] = max(max_price, price)
                        state["min_price"] = min(min_price, price)
                        
                        state["last_volume"] = volume
                        state["last_vol_at"] = float(now)
                        state["next_board_at"] = float(now) + float(get_watch_poll_seconds()) + random.uniform(0.0, 0.3)
                        watchlist[symbol] = state

                        # 早期終了判定（値動き・出来高変化が乏しい場合は監視解除）
                        if (
                            WATCH_EARLY_STOP_SECONDS > 0
                            and (now - state.get("added_at", now)) >= WATCH_EARLY_STOP_SECONDS
                            and (abs(price_pct) < WATCH_EARLY_STOP_PRICE_PCT)
                            and (abs(volume_mult - 1.0) < WATCH_EARLY_STOP_VOLUME_MULT_DELTA)
                            and (not state.get("triggered_surge"))
                            and (not state.get("triggered_crash"))
                            and (not state.get("triggered_order"))
                        ):
                            append_watch_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    **watch_meta,
                                    "status": "early_stop",
                                    "price": price,
                                    "volume": volume,
                                    "baseline_price": base_price,
                                    "baseline_volume": base_volume,
                                    "price_pct": round(price_pct, 4),
                                    "volume_mult": round(volume_mult, 4),
                                    "triggered": False,
                                },
                                current_date,
                            )
                            watchlist.pop(symbol, None)
                            continue

                        # 保有中の銘柄かどうか判定（新規発注抑止用）
                        _hp_held = held_positions.get(symbol) or {}
                        _hp_has_position = isinstance(_hp_held.get("qty"), int) and _hp_held["qty"] > 0

                        # 手動注文のリクエスト処理
                        if pending_manual_symbol and pending_manual_symbol == symbol:
                            pending_manual_symbol = None
                            if _hp_has_position:
                                print(f"[ORDER] 保有中のため新規発注スキップ: {symbol}")
                                try:
                                    event_queue.put_nowait({"kind": "event", "text": f"保有中スキップ {symbol}", "symbol": symbol, "price": price})
                                except Exception:
                                    pass
                            else:
                                side = decide_side_by_trend(price_pct) # トレンド判定（外部関数想定）
                                if side and should_place_side(str(order_settings.get("side_mode")), side): # 設定との照合
                                    try_place_order(
                                        token=kabus_token,
                                        symbol=symbol,
                                        side=side,
                                        current_price=price,
                                        settings=order_settings,
                                        event_queue=event_queue,
                                        reason="manual",
                                    )

                        # 自動発注ロジック（保有中の銘柄は新規発注しない）
                        _bv_min = float(order_settings.get("base_volume_min") or 0)
                        _vol_mult_ok = volume_mult >= float(order_settings.get("volume_mult") or 0)
                        _bv_ok = (_bv_min <= 0 or float(volume) >= _bv_min)
                        
                        if (
                            str(order_settings.get("mode")).lower() == "auto"
                            and (not state.get("triggered_order"))
                            and (not _hp_has_position)
                            and _vol_mult_ok
                            and (not _bv_ok)
                        ):
                            print(f"[ORDER] skip {symbol}: volume {volume:.0f} < base_volume_min {_bv_min:.0f}")
                        
                        if (
                            str(order_settings.get("mode")).lower() == "auto"
                            and (not state.get("triggered_order"))
                            and (not _hp_has_position)
                            and _vol_mult_ok
                            and _bv_ok
                        ):
                            side = decide_side_by_trend(price_pct)
                            # 価格変動率フィルタと売買フィルタの確認
                            if side and should_place_side(str(order_settings.get("side_mode")), side) and abs(float(price_pct)) >= float(ORDER_MIN_PRICE_PCT):
                                # デイトレ向き銘柄フィルタ（案C + 案A）
                                min_baseline_vol = float(ORDER_MIN_BASELINE_VOLUME)
                                min_price_range_pct = float(ORDER_MIN_PRICE_RANGE_PCT)
                                
                                # ベースライン出来高チェック（普段から出来高がある銘柄のみ）
                                baseline_vol_ok = (min_baseline_vol <= 0 or base_volume >= min_baseline_vol)
                                
                                # 価格変動幅チェック（監視期間中に十分な値動きがある銘柄のみ）
                                max_p = float(state.get("max_price") or price)
                                min_p = float(state.get("min_price") or price)
                                price_range_pct = ((max_p - min_p) / base_price * 100.0) if base_price > 0 else 0.0
                                price_range_ok = (min_price_range_pct <= 0 or price_range_pct >= min_price_range_pct)
                                
                                # フィルタ除外時のログ出力
                                if not baseline_vol_ok:
                                    print(f"[ORDER] skip {symbol}: baseline_volume {base_volume:.0f} < min {min_baseline_vol:.0f} (閑散銘柄)")
                                if not price_range_ok:
                                    print(f"[ORDER] skip {symbol}: price_range {price_range_pct:.2f}% < min {min_price_range_pct:.2f}% (値動き不足)")
                                
                                if baseline_vol_ok and price_range_ok:
                                    streak = int(state.get("order_hit_streak") or 0) + 1
                                    state["order_hit_streak"] = streak
                                    watchlist[symbol] = state
                                    
                                    # 連続して条件を満たした場合のみ発注（ダマシ回避）
                                    need = int(ORDER_CONSECUTIVE_HITS) if int(ORDER_CONSECUTIVE_HITS) > 0 else 1
                                    if streak >= need:
                                        state["triggered_order"] = True
                                        watchlist[symbol] = state
                                        order_id = try_place_order(
                                            token=kabus_token,
                                            symbol=symbol,
                                            side=side,
                                            current_price=price,
                                            settings=order_settings,
                                            event_queue=event_queue,
                                            reason=f"auto vol_mult={volume_mult:.2f}",
                                        )
                                        
                                        # 新規発注成功時、利確指値フローを別スレッドで起動
                                        if order_id and bool(order_settings.get("auto_exit")) and float(order_settings.get("profit_yen_per_100") or 0.0) > 0:
                                            cash_margin_str = str(order_settings.get("cash_margin") or "cash").strip().lower()
                                            margin_trade_type_val = int(order_settings.get("margin_trade_type") or 3)
                                            profit_yen = float(order_settings.get("profit_yen_per_100") or 0.0)
                                            order_password = os.environ.get("KABUS_ORDER_PASSWORD", "")
                                            
                                            monitor_thread = threading.Thread(
                                                target=monitor_order_and_place_profit_limit,
                                                args=(
                                                    kabus_token,
                                                    order_id,
                                                    symbol,
                                                    side,
                                                    int(order_settings.get("qty") or 0),
                                                    cash_margin_str,
                                                    margin_trade_type_val,
                                                    profit_yen,
                                                    event_queue,
                                                    held_positions,
                                                    order_password
                                                ),
                                                daemon=True
                                            )
                                            monitor_thread.start()
                                else:
                                    # デイトレ向きフィルタ未達なら連続カウントをリセット
                                    if int(state.get("order_hit_streak") or 0) != 0:
                                        state["order_hit_streak"] = 0
                                        watchlist[symbol] = state
                            else:
                                # 価格変動率フィルタ未達なら連続カウントをリセット
                                if int(state.get("order_hit_streak") or 0) != 0:
                                    state["order_hit_streak"] = 0
                                    watchlist[symbol] = state

                        # 監視ログ保存
                        append_watch_log(
                            {
                                "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                "tdnet_key": tdnet_key,
                                "symbol": symbol,
                                **watch_meta,
                                "status": "ok",
                                "price": price,
                                "volume": volume,
                                "baseline_price": base_price,
                                "baseline_volume": base_volume,
                                "price_pct": round(price_pct, 4),
                                "volume_mult": round(volume_mult, 4),
                                "triggered": state.get("triggered_surge") or state.get("triggered_crash"),
                            },
                            current_date,
                        )

                        # 急騰検知ロジック
                        spct, svol, cpct, cvol = get_surge_crash_thresholds(datetime.datetime.now(JST))
                        if (not state.get("triggered_surge")) and price_pct >= spct and volume_mult >= svol:
                            state["triggered_surge"] = True
                            watchlist[symbol] = state
                            print(f"★急騰検知★ {symbol} 価格:{price} ({price_pct:.2f}%) 出来高:{volume} ({volume_mult:.2f}x)")

                            append_event_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "event_type": "surge",
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    "price": price,
                                    "volume": volume,
                                    "baseline_price": base_price,
                                    "baseline_volume": base_volume,
                                    "price_pct": round(price_pct, 4),
                                    "volume_mult": round(volume_mult, 4),
                                },
                                current_date,
                            )

                            append_watch_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    **watch_meta,
                                    "status": "surge_detected",
                                    "price": price,
                                    "volume": volume,
                                    "baseline_price": base_price,
                                    "baseline_volume": base_volume,
                                    "price_pct": round(price_pct, 4),
                                    "volume_mult": round(volume_mult, 4),
                                    "triggered": True,
                                },
                                current_date,
                            )

                            try:
                                event_queue.put_nowait({"kind": "event", "text": f"surge {symbol} {price_pct:.2f}% {volume_mult:.2f}x"})
                            except Exception:
                                pass

                        # 急落検知ロジック
                        if (not state.get("triggered_crash")) and price_pct <= (-cpct) and volume_mult >= cvol:
                            state["triggered_crash"] = True
                            watchlist[symbol] = state
                            print(f"★急落検知★ {symbol} 価格:{price} ({price_pct:.2f}%) 出来高:{volume} ({volume_mult:.2f}x)")

                            append_event_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "event_type": "crash",
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    "price": price,
                                    "volume": volume,
                                    "baseline_price": base_price,
                                    "baseline_volume": base_volume,
                                    "price_pct": round(price_pct, 4),
                                    "volume_mult": round(volume_mult, 4),
                                },
                                current_date,
                            )

                            append_watch_log(
                                {
                                    "datetime": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "tdnet_key": tdnet_key,
                                    "symbol": symbol,
                                    **watch_meta,
                                    "status": "crash_detected",
                                    "price": price,
                                    "volume": volume,
                                    "baseline_price": base_price,
                                    "baseline_volume": base_volume,
                                    "price_pct": round(price_pct, 4),
                                    "volume_mult": round(volume_mult, 4),
                                    "triggered": True,
                                },
                                current_date,
                            )

                            try:
                                event_queue.put_nowait({"kind": "event", "text": f"crash {symbol} {price_pct:.2f}% {volume_mult:.2f}x"})
                            except Exception:
                                pass

            # -------------------------------------------------------------------
            # 保有ポジション定期チェック＋自動決済（watchlist非依存）
            # -------------------------------------------------------------------
            now = time.time()
            if kabus_token is None and now >= next_positions_check_at:
                try:
                    kabus_token = kabus_get_token()
                except Exception:
                    kabus_token = None
            if kabus_token and now >= next_positions_check_at:
                next_positions_check_at = now + 5.0
                try:
                    st_pos, payload_pos = kabus_get_positions(kabus_token, product=0, symbol="", side="", addinfo=True)
                    if st_pos == 200 and isinstance(payload_pos, list):
                        new_held: Dict[str, Dict[str, Any]] = {}
                        for p in payload_pos:
                            if not isinstance(p, dict):
                                continue
                            sym = str(p.get("Symbol") or p.get("symbol") or "").strip()
                            if not sym:
                                continue

                            avg = None
                            for k in ("Price", "HoldPrice", "AveragePrice", "AvgPrice"):
                                v = p.get(k)
                                if isinstance(v, (int, float)):
                                    avg = float(v)
                                    break

                            qty = None
                            for k in ("LeavesQty", "HoldQty", "Qty"):
                                v = p.get(k)
                                if isinstance(v, (int, float)):
                                    qty = int(v)
                                    break

                            side_raw = p.get("Side")
                            side_p = "buy" if side_raw in (2, "2", "buy", "BUY") else ("sell" if side_raw in (1, "1", "sell", "SELL") else "")

                            mtt = p.get("MarginTradeType")
                            try:
                                mtt_i = int(mtt) if mtt is not None else None
                            except (ValueError, TypeError):
                                mtt_i = None
                            cm_i = 1 if mtt_i is None else 2

                            cur_price = None
                            for k in ("CurrentPrice", "currentPrice"):
                                v = p.get(k)
                                if isinstance(v, (int, float)):
                                    cur_price = float(v)
                                    break

                            prev = held_positions.get(sym) or {}
                            new_held[sym] = {
                                **prev,
                                "avg_price": avg,
                                "qty": qty,
                                "side": side_p,
                                "cash_margin": cm_i,
                                "margin_trade_type": mtt_i,
                                "current_price": cur_price,
                                "seen_at": float(now),
                                "first_seen_at": float(prev.get("first_seen_at") or now),
                                "stagnation_exit_streak": int(prev.get("stagnation_exit_streak") or 0),
                                "auto_exit_done": bool(prev.get("auto_exit_done")),
                            }

                        held_positions = new_held
                except Exception:
                    pass

                # 自動決済判定（各保有銘柄について）
                if bool(order_settings.get("auto_exit")):
                    for hp_sym, hp in list(held_positions.items()):
                        if hp.get("auto_exit_done"):
                            continue
                        # 利確指値稼働中の場合はスキップ（二重決済防止）
                        if hp.get("profit_limit_active"):
                            continue
                        hp_cm = hp.get("cash_margin")
                        hp_side = str(hp.get("side") or "").strip().lower()
                        hp_qty = hp.get("qty")
                        hp_avg = hp.get("avg_price")

                        is_cash_long = (hp_cm == 1) and hp_side == "buy" and isinstance(hp_qty, int) and hp_qty > 0 and isinstance(hp_avg, (int, float))
                        is_margin_long = (hp_cm == 2) and hp_side == "buy" and isinstance(hp_qty, int) and hp_qty > 0 and isinstance(hp_avg, (int, float))
                        is_margin_short = (hp_cm == 2) and hp_side == "sell" and isinstance(hp_qty, int) and hp_qty > 0 and isinstance(hp_avg, (int, float))
                        if not (is_cash_long or is_margin_long or is_margin_short):
                            continue

                        # 現在値の取得: addinfo=True で取得済みの CurrentPrice を優先、なければ板情報から取得
                        cp = hp.get("current_price")
                        if cp is None or cp <= 0:
                            try:
                                st_b, board_b = kabus_get_board(hp_sym, kabus_token)
                                if st_b == 200 and isinstance(board_b, dict):
                                    bp, _ = extract_price_volume(board_b)
                                    if bp is not None:
                                        cp = float(bp)
                            except Exception:
                                pass
                        if cp is None or cp <= 0:
                            continue

                        profit_target = float(order_settings.get("profit_yen_per_100") or 0.0)
                        stop_target = float(order_settings.get("stoploss_yen_per_100") or 0.0)
                        stag_secs = float(order_settings.get("stagnation_seconds") or 0.0)
                        stag_hits_need = int(order_settings.get("stagnation_hits") or 1)

                        unit = float(hp_qty) / 100.0
                        if is_margin_short:
                            pnl_100 = (((float(hp_avg) - cp) * float(hp_qty)) / unit) if unit > 0 else 0.0
                        else:
                            pnl_100 = (((cp - float(hp_avg)) * float(hp_qty)) / unit) if unit > 0 else 0.0

                        print(f"[POS] {hp_sym} side={hp_side} avg={hp_avg} cur={cp:.1f} pnl/100={pnl_100:.0f}")

                        should_exit = False
                        exit_reason = ""

                        if profit_target > 0 and pnl_100 >= profit_target:
                            should_exit = True
                            exit_reason = f"take_profit pnl/100={pnl_100:.0f}"
                        elif stop_target > 0 and pnl_100 <= (-stop_target):
                            should_exit = True
                            exit_reason = f"stop_loss pnl/100={pnl_100:.0f}"
                        else:
                            first_seen = float(hp.get("first_seen_at") or now)
                            if stag_secs > 0 and (now - first_seen) >= stag_secs:
                                streak3 = int(hp.get("stagnation_exit_streak") or 0) + 1
                                hp["stagnation_exit_streak"] = streak3
                                held_positions[hp_sym] = hp
                                if streak3 >= stag_hits_need:
                                    should_exit = True
                                    exit_reason = f"stagnation hits={streak3}"
                            else:
                                if int(hp.get("stagnation_exit_streak") or 0) != 0:
                                    hp["stagnation_exit_streak"] = 0
                                    held_positions[hp_sym] = hp

                        if should_exit:
                            hp["auto_exit_done"] = True
                            held_positions[hp_sym] = hp
                            close_settings = dict(order_settings)
                            close_settings["cash_margin"] = "margin_close" if (is_margin_long or is_margin_short) else "cash"
                            close_settings["order_type"] = "market"
                            close_settings["limit_pct"] = 0.0
                            close_settings["qty"] = int(hp_qty)
                            hp_mtt = hp.get("margin_trade_type")
                            if hp_mtt is not None:
                                close_settings["margin_trade_type"] = int(hp_mtt)
                            close_side = "buy" if is_margin_short else "sell"
                            try_place_order(
                                token=kabus_token,
                                symbol=hp_sym,
                                side=close_side,
                                current_price=cp,
                                settings=close_settings,
                                event_queue=event_queue,
                                reason=f"auto_exit {exit_reason}",
                            )

            time.sleep(0.2) # ビジー待機を防ぐための短いスリープ

    except KeyboardInterrupt:
        print("監視を終了します")


def print_current_env_config(phase_now: str) -> None:
    def _mask(key: str, val: Any) -> str:
        if key in {"KABUS_API_PASSWORD", "EDINET_API_KEY"}:
            return "set" if bool(val) else "empty"
        return str(val)

    items: List[Tuple[str, Any]] = [
        ("KABUS_API_BASE_URL", KABUS_API_BASE_URL),
        ("KABUS_EXCHANGE", KABUS_EXCHANGE),
        ("KABUS_API_PASSWORD", KABUS_API_PASSWORD),
        ("WATCH_POLL_SECONDS", WATCH_POLL_SECONDS),
        ("WATCH_POLL_SECONDS_OFF_SESSION", WATCH_POLL_SECONDS_OFF_SESSION),
        ("WATCH_EARLY_STOP_SECONDS", WATCH_EARLY_STOP_SECONDS),
        ("WATCH_EARLY_STOP_PRICE_PCT", WATCH_EARLY_STOP_PRICE_PCT),
        ("WATCH_EARLY_STOP_VOLUME_MULT_DELTA", WATCH_EARLY_STOP_VOLUME_MULT_DELTA),
        ("WATCH_VOLRATE_EMA_ALPHA", WATCH_VOLRATE_EMA_ALPHA),
        ("WATCH_VOLRATE_MIN_BASE", WATCH_VOLRATE_MIN_BASE),
        ("WATCH_VOLRATE_WINDOW_SECONDS", WATCH_VOLRATE_WINDOW_SECONDS),
        ("WATCH_MAX_SYMBOLS", WATCH_MAX_SYMBOLS),
        ("WATCH_RATE_LIMIT_BACKOFF_BASE", WATCH_RATE_LIMIT_BACKOFF_BASE),
        ("WATCH_RATE_LIMIT_BACKOFF_MAX", WATCH_RATE_LIMIT_BACKOFF_MAX),
        ("ORDER_MODE", ORDER_MODE),
        ("ORDER_SIDE_MODE", ORDER_SIDE_MODE),
        ("ORDER_CASH_MARGIN", ORDER_CASH_MARGIN),
        ("ORDER_TYPE", ORDER_TYPE),
        ("ORDER_LIMIT_PCT", ORDER_LIMIT_PCT),
        ("ORDER_QTY", ORDER_QTY),
        ("ORDER_DRY_RUN", "1" if ORDER_DRY_RUN else "0"),
        ("ORDER_CONFIRM", "1" if ORDER_CONFIRM else "0"),
        ("ORDER_VOLUME_MULTIPLIER", ORDER_VOLUME_MULTIPLIER),
        ("ORDER_PRICE_MIN", ORDER_PRICE_MIN),
        ("ORDER_PRICE_MAX", ORDER_PRICE_MAX),
        ("ORDER_BASE_VOLUME_MIN", ORDER_BASE_VOLUME_MIN),
        ("ORDER_MIN_PRICE_PCT", ORDER_MIN_PRICE_PCT),
        ("ORDER_CONSECUTIVE_HITS", ORDER_CONSECUTIVE_HITS),
        ("SURGE_PRICE_PCT", SURGE_PRICE_PCT),
        ("SURGE_VOLUME_MULTIPLIER", SURGE_VOLUME_MULTIPLIER),
        ("CRASH_PRICE_PCT", CRASH_PRICE_PCT),
        ("CRASH_VOLUME_MULTIPLIER", CRASH_VOLUME_MULTIPLIER),
        ("AUTO_EXIT_ENABLE", "1" if AUTO_EXIT_ENABLE else "0"),
        ("AUTO_EXIT_PROFIT_YEN_PER_100", AUTO_EXIT_PROFIT_YEN_PER_100),
        ("AUTO_EXIT_STOPLOSS_YEN_PER_100", AUTO_EXIT_STOPLOSS_YEN_PER_100),
        ("AUTO_EXIT_STAGNATION_SECONDS", AUTO_EXIT_STAGNATION_SECONDS),
        ("AUTO_EXIT_STAGNATION_PRICE_PCT", AUTO_EXIT_STAGNATION_PRICE_PCT),
        ("AUTO_EXIT_STAGNATION_VOLUME_MULT", AUTO_EXIT_STAGNATION_VOLUME_MULT),
        ("AUTO_EXIT_STAGNATION_HITS", AUTO_EXIT_STAGNATION_HITS),
        ("ENABLE_GUI", "1" if ENABLE_GUI else "0"),
        ("PROMPT_CONFIG", "1" if PROMPT_CONFIG else "0"),
        ("EDINET_API_KEY", EDINET_API_KEY),
        ("EDINET_POLL_SECONDS", EDINET_POLL_SECONDS),
        ("EDINET_WATCH_WINDOW_SECONDS", EDINET_WATCH_WINDOW_SECONDS),
        ("EDINET_REQUIRE_VIP", "1" if EDINET_REQUIRE_VIP else "0"),
        ("NEWS_POLL_SECONDS", NEWS_POLL_SECONDS),
        ("NEWS_LOOKBACK_MINUTES", NEWS_LOOKBACK_MINUTES),
        ("NEWS_WATCH_WINDOW_SECONDS", NEWS_WATCH_WINDOW_SECONDS),
        ("NEWS_VOLUME_MULT_FACTOR", NEWS_VOLUME_MULT_FACTOR),
        ("NEWS_ALIASES_PATH", NEWS_ALIASES_PATH),
        ("EDINET_CODE_LIST_PATH", EDINET_CODE_LIST_PATH),
        ("MANUAL_WATCH_SYMBOLS", ",".join(MANUAL_WATCH_SYMBOLS) if MANUAL_WATCH_SYMBOLS else "(none)"),
        ("MANUAL_WATCH_WINDOW_SECONDS", MANUAL_WATCH_WINDOW_SECONDS),
    ]

    print("--- current config ---")
    print(f"MARKET_PHASE={phase_now}")
    for k, v in items:
        print(f"{k}={_mask(k, v)}")
    print("----------------------")


if __name__ == "__main__":
    main()