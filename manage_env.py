import os
import sys
import json
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, ttk


DEFAULT_ENV_PATH = ".env"
PRESETS_PATH = "env_presets.json"


# プリセット管理機能
def load_presets() -> Dict[str, Dict[str, str]]:
    """プリセットを読み込む"""
    if not os.path.exists(PRESETS_PATH):
        return {}
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_presets(presets: Dict[str, Dict[str, str]]) -> bool:
    """プリセットを保存"""
    try:
        with open(PRESETS_PATH, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def apply_preset(preset_name: str, env: Dict[str, str]) -> Dict[str, str]:
    """プリセットを現在の環境変数に適用"""
    presets = load_presets()
    if preset_name not in presets:
        return env
    
    preset_values = presets[preset_name]
    updated_env = env.copy()
    updated_env.update(preset_values)
    return updated_env

def save_current_as_preset(preset_name: str, env: Dict[str, str]) -> bool:
    """現在の環境変数をプリセットとして保存"""
    presets = load_presets()
    presets[preset_name] = env.copy()
    return save_presets(presets)

def delete_preset(preset_name: str) -> bool:
    """プリセットを削除"""
    presets = load_presets()
    if preset_name in presets:
        del presets[preset_name]
        return save_presets(presets)
    return False

# デフォルトプリセット
DEFAULT_PRESETS = {
    "保守的設定": {
        "ORDER_VOLUME_MULTIPLIER": "5",
        "ORDER_CONSECUTIVE_HITS": "3",
        "SURGE_PRICE_PCT": "3",
        "SURGE_VOLUME_MULTIPLIER": "3",
        "CRASH_PRICE_PCT": "3",
        "CRASH_VOLUME_MULTIPLIER": "3",
        "AUTO_EXIT_ENABLE": "1",
        "PROFIT_TARGET_PCT": "2",
        "LOSS_LIMIT_PCT": "1",
    },
    "積極的設定": {
        "ORDER_VOLUME_MULTIPLIER": "2",
        "ORDER_CONSECUTIVE_HITS": "1",
        "SURGE_PRICE_PCT": "1.5",
        "SURGE_VOLUME_MULTIPLIER": "1.5",
        "CRASH_PRICE_PCT": "1.5",
        "CRASH_VOLUME_MULTIPLIER": "1.5",
        "AUTO_EXIT_ENABLE": "1",
        "PROFIT_TARGET_PCT": "3",
        "LOSS_LIMIT_PCT": "1.5",
    },
    "テスト用": {
        "ORDER_DRY_RUN": "1",
        "ORDER_VOLUME_MULTIPLIER": "2",
        "ORDER_CONSECUTIVE_HITS": "2",
        "MANUAL_ONLY_MODE": "1",
        "EMAIL_ENABLE": "0",
        "WEBSOCKET_ENABLE": "0",
    }
}


ENV_SPECS: List[Dict[str, Any]] = [
    {
        "key": "KABUS_API_BASE_URL",
        "default": "http://localhost:18080",
        "type": "str",
        "desc": "KabuStationの接続先URL。通常はlocalhostのままでOK。変更すると接続先が変わります。",
    },
    {
        "key": "KABUS_API_PASSWORD",
        "default": "",
        "type": "password",
        "desc": "KabuStation APIトークン取得用パスワード。未設定/誤設定だとトークン取得に失敗します。",
    },
    {
        "key": "KABUS_EXCHANGE",
        "default": "1",
        "type": "str",
        "desc": "取引所コード。通常は1(東証)。銘柄取得・発注のマーケット指定に影響します。",
    },
    {
        "key": "ENABLE_GUI",
        "default": "0",
        "type": "bool",
        "desc": "1でGUI表示、0でコンソールのみ。GUIの有無が切り替わります。",
    },
    {
        "key": "PROMPT_CONFIG",
        "default": "1",
        "type": "bool",
        "desc": "1で起動時に設定入力を促します。0にすると起動プロンプトを抑制します（.envで固定運用向け）。",
    },
    {
        "key": "EDINET_API_KEY",
        "default": "",
        "type": "str",
        "desc": "EDINET APIキー。空だとEDINET取得が制限/失敗する可能性があります。",
    },
    {
        "key": "EDINET_POLL_SECONDS",
        "default": "60",
        "type": "int",
        "desc": "EDINETのチェック間隔（秒）。短くすると検知が速いがAPI負荷が増えます。",
    },
    {
        "key": "EDINET_WATCH_WINDOW_SECONDS",
        "default": "600",
        "type": "int",
        "desc": "EDINET由来で追加した銘柄を監視する最大時間（秒）。長いほど追従します。",
    },
    {
        "key": "EDINET_REQUIRE_VIP",
        "default": "0",
        "type": "bool",
        "desc": "1にするとVIP提出者のみ反応。0なら広く拾います（ノイズ増減に影響）。",
    },
    {
        "key": "NEWS_POLL_SECONDS",
        "default": "45",
        "type": "int",
        "desc": "ニュースチェック間隔（秒）。短いほど検知は速いがアクセス頻度が増えます。",
    },
    {
        "key": "NEWS_LOOKBACK_MINUTES",
        "default": "30",
        "type": "int",
        "desc": "何分以内のニュースを対象にするか。短いほど『新着のみ』になります。",
    },
    {
        "key": "NEWS_WATCH_WINDOW_SECONDS",
        "default": "300",
        "type": "int",
        "desc": "ニュースで追加した銘柄の監視時間（秒）。長いほどフォローします。",
    },
    {
        "key": "NEWS_VOLUME_MULT_FACTOR",
        "default": "1.5",
        "type": "float",
        "desc": "ニュース由来銘柄の出来高倍率判定を厳しくする係数。上げるほどダマシが減るが検知も減ります。",
    },
    {
        "key": "NEWS_ALIASES_PATH",
        "default": "aliases.json",
        "type": "str",
        "desc": "略称辞書JSONのパス。変更すると参照するファイルが変わります。",
    },
    {
        "key": "MANUAL_ONLY_MODE",
        "default": "0",
        "type": "bool",
        "desc": "1で手動選択銘柄のみモード。TDnet/EDINET/ニュースの自動監視・自動発注を停止し、手動で追加した銘柄のみ監視します。各ログに一時停止の旨が記録されます。",
    },
    {
        "key": "MANUAL_WATCH_SYMBOLS",
        "default": "",
        "type": "str",
        "desc": "手動監視銘柄（最大10銘柄）。カンマ区切りで証券コードを指定します。例: 7203,6758,9984",
    },
    {
        "key": "MANUAL_WATCH_WINDOW_SECONDS",
        "default": "86400",
        "type": "float",
        "desc": "手動監視銘柄の監視ウィンドウ（秒）。非常に長い値を設定して常時監視とします。",
    },
    {
        "key": "LUNCH_BATCH_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1で昼休みバッチ（指定時間帯に検知した銘柄をまとめて監視開始）を有効化します。",
    },
    {
        "key": "LUNCH_BATCH_START_HHMM",
        "default": "11:30",
        "type": "str",
        "desc": "昼休みバッチの溜め込み開始時刻(HH:MM)。",
    },
    {
        "key": "LUNCH_BATCH_END_HHMM",
        "default": "12:30",
        "type": "str",
        "desc": "昼休みバッチの解放時刻(HH:MM)。この時刻にまとめてwatchlistへ追加します。",
    },
    {
        "key": "MORNING_BATCH_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1で朝バッチ（指定時間帯に検知した当日材料をまとめて監視開始）を有効化します。",
    },
    {
        "key": "MORNING_BATCH_START_HHMM",
        "default": "00:00",
        "type": "str",
        "desc": "朝バッチの溜め込み開始時刻(HH:MM)。",
    },
    {
        "key": "MORNING_BATCH_END_HHMM",
        "default": "09:00",
        "type": "str",
        "desc": "朝バッチの解放時刻(HH:MM)。",
    },
    {
        "key": "AFTERHOURS_ADD_STOP_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1で場引け後の一定時間帯は自動でwatchlistへ追加しません（情報収集のみ）。",
    },
    {
        "key": "AFTERHOURS_ADD_STOP_START_HHMM",
        "default": "15:30",
        "type": "str",
        "desc": "場引け後の自動追加停止の開始時刻(HH:MM)。",
    },
    {
        "key": "AFTERHOURS_ADD_STOP_END_HHMM",
        "default": "24:00",
        "type": "str",
        "desc": "場引け後の自動追加停止の終了時刻(HH:MM)。",
    },
    {
        "key": "SPECIAL_QUOTE_REMOVE_STREAK",
        "default": "3",
        "type": "int",
        "desc": "特別買/売気配が連続した銘柄を監視対象から外すまでの連続回数。0以下で無効。",
    },
    {
        "key": "HFT_OBI_ENABLE",
        "default": "0",
        "type": "bool",
        "desc": "1でHFT板情報インバランス（OBI）検知を有効化。板の買い気配数量と売り気配数量の偏りを統計的に検知し、シグナルを出します。",
    },
    {
        "key": "HFT_OBI_HISTORY_SIZE",
        "default": "50",
        "type": "int",
        "desc": "OBI履歴保持ティック数。大きいほど長期的な傾向を捉えますが、反応が鈍くなります。",
    },
    {
        "key": "HFT_OBI_MIN_HISTORY",
        "default": "20",
        "type": "int",
        "desc": "OBI判定に必要な最小履歴数。この数に達するまではシグナルを出しません。",
    },
    {
        "key": "HFT_OBI_ENTRY_SIGMA",
        "default": "2.5",
        "type": "float",
        "desc": "買い/売りエントリーシグナル閾値（標準偏差の倍数）。大きいほど厳しい条件になります。",
    },
    {
        "key": "HFT_OBI_EXIT_SIGMA",
        "default": "2.0",
        "type": "float",
        "desc": "売り/買いイグジットシグナル閾値（標準偏差の倍数）。大きいほど厳しい条件になります。",
    },
    {
        "key": "HFT_OBI_CVD_MIN_BUY",
        "default": "0",
        "type": "float",
        "desc": "CVD（累積出来高差）の最小閾値（買いシグナル時）。買いシグナルを出すにはCVDがこの値以上である必要があります。",
    },
    {
        "key": "HFT_OBI_CVD_MAX_SELL",
        "default": "0",
        "type": "float",
        "desc": "CVD（累積出来高差）の最大閾値（売りシグナル時）。売りシグナルを出すにはCVDがこの値以下である必要があります。",
    },
    {
        "key": "MA_FILTER_ENABLE",
        "default": "0",
        "type": "bool",
        "desc": "1で移動平均線（MA）フィルタを有効化。価格がMA上/下、ゴールデンクロス/デッドクロスなどの条件でエントリーを制限します。",
    },
    {
        "key": "MA_TYPE",
        "default": "SMA",
        "type": "str",
        "desc": "移動平均線の種類。SMA（単純移動平均）またはEMA（指数移動平均）を選択します。",
    },
    {
        "key": "MA_SHORT_PERIOD",
        "default": "5",
        "type": "int",
        "desc": "短期移動平均線の期間（ティック数）。小さいほど直近の価格変動に敏感になります。",
    },
    {
        "key": "MA_LONG_PERIOD",
        "default": "20",
        "type": "int",
        "desc": "長期移動平均線の期間（ティック数）。大きいほど長期的なトレンドを捉えます。",
    },
    {
        "key": "MA_CROSS_ENTRY",
        "default": "1",
        "type": "bool",
        "desc": "1でゴールデンクロス/デッドクロスでのエントリー判定を有効化。短期MAが長期MAを上抜けで買い、下抜けで売り。",
    },
    {
        "key": "MA_TREND_FILTER",
        "default": "1",
        "type": "bool",
        "desc": "1でトレンドフィルタを有効化。価格が長期MA上なら買いのみ、下なら売りのみ許可します。",
    },
    {
        "key": "VWAP_FILTER_ENABLE",
        "default": "0",
        "type": "bool",
        "desc": "1でVWAP（出来高加重平均価格）フィルタを有効化。価格とVWAPの位置関係でエントリーを制限します。",
    },
    {
        "key": "VWAP_ENTRY_ABOVE",
        "default": "1",
        "type": "bool",
        "desc": "1でVWAP位置フィルタを有効化。価格がVWAP上なら買いのみ、下なら売りのみ許可します。",
    },
    {
        "key": "VWAP_DEVIATION_PCT",
        "default": "0.5",
        "type": "float",
        "desc": "VWAP乖離率(%)のフィルタ。価格がVWAPからこの%以上乖離している場合はエントリーを制限します。0で無効。",
    },
    {
        "key": "WATCH_POLL_SECONDS_OFF_SESSION",
        "default": "10",
        "type": "float",
        "desc": "場外（取引時間外）の監視間隔（秒）。短いほど監視が細かいが負荷が増えます。",
    },
    {
        "key": "WATCH_EARLY_STOP_SECONDS",
        "default": "60",
        "type": "float",
        "desc": "値動きが無い場合の早期打ち切り判定時間（秒）。短いほど早く監視終了します。",
    },
    {
        "key": "WATCH_EARLY_STOP_PRICE_PCT",
        "default": "0.2",
        "type": "float",
        "desc": "早期打ち切りの価格変化率(%)しきい値。小さいほど『動いた』判定になり打ち切りにくくなります。",
    },
    {
        "key": "WATCH_EARLY_STOP_VOLUME_MULT_DELTA",
        "default": "0.05",
        "type": "float",
        "desc": "早期打ち切りの出来高倍率変化のしきい値。小さいほど打ち切りにくくなります。",
    },
    {
        "key": "WATCH_VOLRATE_EMA_ALPHA",
        "default": "0.2",
        "type": "float",
        "desc": "出来高倍率EMAの平滑化係数。大きいほど直近に敏感、小さいほど滑らかになります。",
    },
    {
        "key": "WATCH_VOLRATE_MIN_BASE",
        "default": "1.0",
        "type": "float",
        "desc": "出来高倍率のベース下限。小さくし過ぎるとノイズが増えることがあります。",
    },
    {
        "key": "WATCH_VOLRATE_WINDOW_SECONDS",
        "default": "10",
        "type": "float",
        "desc": "出来高倍率を計算する時間窓（秒）。短いほど短期変化に反応します。",
    },
    {
        "key": "WATCH_MAX_SYMBOLS",
        "default": "8",
        "type": "int",
        "desc": "同時監視の上限銘柄数。増やすと追えるがAPI負荷/制限に当たりやすくなります。",
    },
    {
        "key": "WATCH_RATE_LIMIT_BACKOFF_BASE",
        "default": "5",
        "type": "float",
        "desc": "APIレート制限時の待機（秒）基本値。大きいほど回復まで待ちます。",
    },
    {
        "key": "WATCH_RATE_LIMIT_BACKOFF_MAX",
        "default": "60",
        "type": "float",
        "desc": "APIレート制限時の待機（秒）最大値。大きいほど最大待機が長くなります。",
    },
    {
        "key": "ORDER_MODE",
        "default": "manual",
        "type": "str",
        "desc": "manual=手動、auto=自動発注。autoにすると条件一致で注文を出すロジックが動きます。",
    },
    {
        "key": "ORDER_SIDE_MODE",
        "default": "both",
        "type": "str",
        "desc": "both/buy/sell。発注方向の制御。buyのみ等にすると片側だけになります。",
    },
    {
        "key": "ORDER_CASH_MARGIN",
        "default": "cash",
        "type": "str",
        "desc": "cash=現物、margin=信用。注文種別に影響します。",
    },
    {
        "key": "ORDER_TYPE",
        "default": "market",
        "type": "str",
        "desc": "market=成行、limit_pct=指値（乖離率指定）。指値運用に切り替えると約定条件が変わります。",
    },
    {
        "key": "ORDER_LIMIT_PCT",
        "default": "1",
        "type": "float",
        "desc": "指値（limit_pct）の乖離率%。大きいほど指値が離れて約定しにくい場合があります。",
    },
    {
        "key": "ORDER_QTY",
        "default": "100",
        "type": "int",
        "desc": "注文数量。実売買の株数に直結します（注意）。",
    },
    {
        "key": "ORDER_DRY_RUN",
        "default": "1",
        "type": "bool",
        "desc": "1でドライラン（実発注しない）。0にすると実際に発注します（注意）。",
    },
    {
        "key": "ORDER_CONFIRM",
        "default": "1",
        "type": "bool",
        "desc": "1で発注前確認あり。0で確認なし（自動運用向けだが注意）。",
    },
    {
        "key": "ORDER_VOLUME_MULTIPLIER",
        "default": "3",
        "type": "float",
        "desc": "自動発注トリガーの出来高倍率。小さいほど発注しやすく、誤発注リスクも増えます。",
    },
    {
        "key": "ORDER_PRICE_MIN",
        "default": "0",
        "type": "float",
        "desc": "発注対象の株価下限（円）。0で制限なし。設定すると、この価格未満の銘柄には発注しません（決済注文は除く）。",
    },
    {
        "key": "ORDER_PRICE_MAX",
        "default": "0",
        "type": "float",
        "desc": "発注対象の株価上限（円）。0で制限なし。設定すると、この価格を超える銘柄には発注しません（決済注文は除く）。",
    },
    {
        "key": "ORDER_BASE_VOLUME_MIN",
        "default": "0",
        "type": "float",
        "desc": "発注対象の出来高下限（株）。0で制限なし。設定すると、発注判断時点の累積出来高がこの値未満の銘柄には自動発注しません。推奨: 50000〜100000。",
    },
    {
        "key": "ORDER_MIN_PRICE_PCT",
        "default": "0.3",
        "type": "float",
        "desc": "自動発注に必要な最低価格変動率(%)。小さいほど発注が増えます。",
    },
    {
        "key": "ORDER_MIN_BASELINE_VOLUME",
        "default": "50000",
        "type": "float",
        "desc": "ベースライン出来高の最低値（株）。普段から出来高がある銘柄のみ自動発注します。0で制限なし。閑散銘柄のダマシ回避に有効です。",
    },
    {
        "key": "ORDER_MIN_PRICE_RANGE_PCT",
        "default": "1.0",
        "type": "float",
        "desc": "監視期間中の最低価格変動幅(%)。継続的な値動きがある銘柄のみ自動発注します。0で制限なし。デイトレ向き銘柄フィルタです。",
    },
    {
        "key": "ORDER_CONSECUTIVE_HITS",
        "default": "2",
        "type": "int",
        "desc": "条件一致が何回連続で出たら発注するか。大きいほど慎重になります。",
    },
    {
        "key": "SURGE_PRICE_PCT",
        "default": "2",
        "type": "float",
        "desc": "急騰イベントの価格変化率(%)。小さいほど検知が増えます。",
    },
    {
        "key": "SURGE_VOLUME_MULTIPLIER",
        "default": "2",
        "type": "float",
        "desc": "急騰イベントの出来高倍率。小さいほど検知が増えます。",
    },
    {
        "key": "CRASH_PRICE_PCT",
        "default": "2",
        "type": "float",
        "desc": "急落イベントの価格変化率(%)。小さいほど検知が増えます。",
    },
    {
        "key": "CRASH_VOLUME_MULTIPLIER",
        "default": "2",
        "type": "float",
        "desc": "急落イベントの出来高倍率。小さいほど検知が増えます。",
    },
    {
        "key": "OPENING_NOISE_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1で前場寄り付き時間帯(OPENING_NOISE_START_HHMM〜END)のみ、急騰/急落検知の閾値を寄り付き用設定に切り替えます。",
    },
    {
        "key": "OPENING_NOISE_START_HHMM",
        "default": "09:00",
        "type": "str",
        "desc": "前場寄り付きノイズ対策の開始時刻(HH:MM)。この時間帯は急騰/急落閾値を寄り付き用に切り替えます。",
    },
    {
        "key": "OPENING_NOISE_END_HHMM",
        "default": "09:30",
        "type": "str",
        "desc": "前場寄り付きノイズ対策の終了時刻(HH:MM)。",
    },
    {
        "key": "OPENING_SURGE_PRICE_PCT",
        "default": "3",
        "type": "float",
        "desc": "前場寄り付き時間帯の急騰イベント価格変化率(%)。通常のSURGE_PRICE_PCTより大きくすると寄りの誤検知が減ります。",
    },
    {
        "key": "OPENING_SURGE_VOLUME_MULTIPLIER",
        "default": "4",
        "type": "float",
        "desc": "前場寄り付き時間帯の急騰イベント出来高倍率。通常のSURGE_VOLUME_MULTIPLIERより大きくすると寄りの誤検知が減ります。",
    },
    {
        "key": "OPENING_CRASH_PRICE_PCT",
        "default": "3",
        "type": "float",
        "desc": "前場寄り付き時間帯の急落イベント価格変化率(%)。通常のCRASH_PRICE_PCTより大きくすると寄りの誤検知が減ります。",
    },
    {
        "key": "OPENING_CRASH_VOLUME_MULTIPLIER",
        "default": "4",
        "type": "float",
        "desc": "前場寄り付き時間帯の急落イベント出来高倍率。通常のCRASH_VOLUME_MULTIPLIERより大きくすると寄りの誤検知が減ります。",
    },
    {
        "key": "PM_OPENING_NOISE_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1で後場寄り付き時間帯(PM_OPENING_NOISE_START_HHMM〜END)のみ、急騰/急落検知の閾値を後場寄り付き用設定に切り替えます。",
    },
    {
        "key": "PM_OPENING_NOISE_START_HHMM",
        "default": "12:30",
        "type": "str",
        "desc": "後場寄り付きノイズ対策の開始時刻(HH:MM)。",
    },
    {
        "key": "PM_OPENING_NOISE_END_HHMM",
        "default": "13:00",
        "type": "str",
        "desc": "後場寄り付きノイズ対策の終了時刻(HH:MM)。",
    },
    {
        "key": "PM_OPENING_SURGE_PRICE_PCT",
        "default": "3",
        "type": "float",
        "desc": "後場寄り付き時間帯の急騰イベント価格変化率(%)。",
    },
    {
        "key": "PM_OPENING_SURGE_VOLUME_MULTIPLIER",
        "default": "4",
        "type": "float",
        "desc": "後場寄り付き時間帯の急騰イベント出来高倍率。",
    },
    {
        "key": "PM_OPENING_CRASH_PRICE_PCT",
        "default": "3",
        "type": "float",
        "desc": "後場寄り付き時間帯の急落イベント価格変化率(%)。",
    },
    {
        "key": "PM_OPENING_CRASH_VOLUME_MULTIPLIER",
        "default": "4",
        "type": "float",
        "desc": "後場寄り付き時間帯の急落イベント出来高倍率。",
    },
    {
        "key": "OPENING_ORDER_SUPPRESS_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1で寄り付き直後(前場09:00/後場12:30)の一定時間は新規発注を抑止します（決済注文は除く）。",
    },
    {
        "key": "OPENING_ORDER_SUPPRESS_MINUTES",
        "default": "10",
        "type": "int",
        "desc": "寄り付き直後の新規発注抑止時間（分）。前場09:00からN分・後場12:30からN分に適用します。",
    },
    {
        "key": "ORDER_CUTOFF_HHMM",
        "default": "15:00",
        "type": "str",
        "desc": "新規建のカットオフ時刻(HH:MM)。この時刻以降は新規注文を行いません（決済注文は除く）。空欄で無効。",
    },
    {
        "key": "AUTO_EXIT_ENABLE",
        "default": "0",
        "type": "bool",
        "desc": "1で自動決済を有効化。利確/損切り/停滞での手仕舞いロジックが動きます。",
    },
    {
        "key": "AUTO_EXIT_PROFIT_YEN_PER_100",
        "default": "1000",
        "type": "float",
        "desc": "100株あたりの利確額（円）。小さいほど早く利確します。",
    },
    {
        "key": "AUTO_EXIT_STOPLOSS_YEN_PER_100",
        "default": "500",
        "type": "float",
        "desc": "100株あたりの損切り額（円）。小さいほど早く損切りします。",
    },
    {
        "key": "AUTO_EXIT_STAGNATION_SECONDS",
        "default": "120",
        "type": "float",
        "desc": "停滞判定の時間（秒）。短いほど『動かない』で決済しやすくなります。",
    },
    {
        "key": "AUTO_EXIT_STAGNATION_PRICE_PCT",
        "default": "0.2",
        "type": "float",
        "desc": "停滞判定の価格変動率(%)。小さいほど停滞扱いになりにくいです。",
    },
    {
        "key": "AUTO_EXIT_STAGNATION_VOLUME_MULT",
        "default": "1.05",
        "type": "float",
        "desc": "停滞判定の出来高倍率。小さいほど停滞扱いになりにくいです。",
    },
    {
        "key": "AUTO_EXIT_STAGNATION_HITS",
        "default": "5",
        "type": "int",
        "desc": "停滞判定が何回続いたら決済するか。大きいほど慎重になります。",
    },
    {
        "key": "AUTO_EXIT_MARKET_CLOSE_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1で大引け前の強制全決済を有効化。指定時刻に全保有ポジションを成行で決済します。",
    },
    {
        "key": "AUTO_EXIT_MARKET_CLOSE_HHMM",
        "default": "15:15",
        "type": "str",
        "desc": "大引け前の強制全決済を実行する時刻(HH:MM)。この時刻以降に全ポジションを成行決済します。",
    },
    {
        "key": "EDINET_CODE_LIST_PATH",
        "default": "EdinetcodeDlInfo.csv",
        "type": "str",
        "desc": "EDINETコードリストCSVのパス。銘柄コード変換に使用します。",
    },
    {
        "key": "EMAIL_ENABLE",
        "default": "0",
        "type": "bool",
        "desc": "1でメール通知を有効化。30分間隔で検知数・取引数・損益を自動送信します。",
    },
    {
        "key": "EMAIL_SMTP_HOST",
        "default": "smtp.gmail.com",
        "type": "str",
        "desc": "SMTPサーバーのホスト名。Gmailの場合は smtp.gmail.com。",
    },
    {
        "key": "EMAIL_SMTP_PORT",
        "default": "587",
        "type": "int",
        "desc": "SMTPサーバーのポート番号。TLS(STARTTLS)は587、SSLは465。",
    },
    {
        "key": "EMAIL_SMTP_USER",
        "default": "",
        "type": "str",
        "desc": "SMTP認証のユーザー名（メールアドレス）。",
    },
    {
        "key": "EMAIL_SMTP_PASSWORD",
        "default": "",
        "type": "password",
        "desc": "SMTP認証のパスワード。Gmailの場合はアプリパスワードを使用してください。",
    },
    {
        "key": "EMAIL_TO",
        "default": "",
        "type": "str",
        "desc": "通知メールの送信先アドレス。",
    },
    {
        "key": "WEBSOCKET_ENABLE",
        "default": "1",
        "type": "bool",
        "desc": "1でWebSocket約定通知を有効化。リアルタイムで約定を検知し、状態遷移を自動化します。",
    },
    {
        "key": "WEBSOCKET_RECONNECT_INTERVAL",
        "default": "30",
        "type": "int",
        "desc": "WebSocket切断時の再接続間隔（秒）。短いほど早く再接続しますが負荷が増えます。",
    },
    {
        "key": "WEBSOCKET_TIMEOUT_SECONDS",
        "default": "60",
        "type": "int",
        "desc": "WebSocket接続のタイムアウト時間（秒）。長いほど不安定なネットワークに耐えます。",
    },
]


def _parse_env_file(path: str) -> Tuple[Dict[str, str], List[str]]:
    """Return (env_map, raw_lines). Keeps raw lines to preserve order/comments."""
    env: Dict[str, str] = {}
    if not os.path.exists(path):
        return env, []

    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        val = v.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key:
            env[key] = val

    return env, lines


def _serialize_env_value(v: str) -> str:
    # Quote only if needed (spaces or #).
    if any(ch.isspace() for ch in v) or "#" in v:
        return '"' + v.replace('"', '\\"') + '"'
    return v


def _spec_by_key() -> Dict[str, Dict[str, Any]]:
    return {str(s["key"]): s for s in ENV_SPECS}


def _to_bool_str(b: bool) -> str:
    return "1" if b else "0"


def _parse_bool_str(s: str) -> bool:
    return (s or "").strip() in {"1", "true", "True"}


def _write_env_file(path: str, new_env: Dict[str, str], raw_lines: List[str]) -> None:
    keys_in_file = set()
    out_lines: List[str] = []

    # Rewrite existing keys in-place (preserve comments/unknown lines)
    for line in raw_lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            out_lines.append(line)
            continue

        k, _ = s.split("=", 1)
        key = k.strip()
        if key in new_env:
            keys_in_file.add(key)
            out_lines.append(f"{key}={_serialize_env_value(str(new_env[key]))}")
        else:
            out_lines.append(line)

    # Append missing keys
    missing = [k for k in new_env.keys() if k not in keys_in_file]
    if missing:
        if out_lines and out_lines[-1].strip() != "":
            out_lines.append("")
        for key in missing:
            out_lines.append(f"{key}={_serialize_env_value(str(new_env[key]))}")

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out_lines) + "\n")


def _prompt(key: str, current: Optional[str], default: str) -> str:
    cur_disp = current if current is not None else ""
    hint = cur_disp if cur_disp != "" else default
    s = input(f"{key} [{hint}]: ").strip()
    if s == "":
        if current is not None:
            return current
        return default
    return s


def _run_gui(env_path: str) -> int:
    env, raw_lines = _parse_env_file(env_path)
    specs = ENV_SPECS
    spec_map = _spec_by_key()

    root = tk.Tk()
    root.title(".env 設定エディタ")
    root.geometry("1140x700")

    top = tk.Frame(root)
    top.pack(fill="x", padx=10, pady=8)

    tk.Label(top, text=f".env: {os.path.abspath(env_path)}").pack(side="left")
    
    # プリセット管理UI
    preset_frame = tk.Frame(top)
    preset_frame.pack(side="right", padx=(20, 0))
    
    # プリセット初期化（デフォルトプリセットがなければ作成）
    presets = load_presets()
    if not presets:
        save_presets(DEFAULT_PRESETS)
        presets = DEFAULT_PRESETS.copy()
    
    # プリセット選択
    tk.Label(preset_frame, text="プリセット:").pack(side="left", padx=(0, 5))
    preset_var = tk.StringVar()
    preset_combo = ttk.Combobox(preset_frame, textvariable=preset_var, width=15, state="readonly")
    preset_combo['values'] = list(presets.keys())
    preset_combo.pack(side="left", padx=(0, 5))
    
    def apply_selected_preset():
        preset_name = preset_var.get()
        if not preset_name:
            messagebox.showwarning("警告", "プリセットを選択してください")
            return
        
        if messagebox.askyesno("確認", f"プリセット「{preset_name}」を適用しますか？\n現在の設定は上書きされます。"):
            # プリセットの値を各入力フィールドに反映
            preset_values = presets[preset_name]
            for key, value in preset_values.items():
                if key in vars_bool:
                    vars_bool[key].set(_parse_bool_str(value))
                elif key in vars_str:
                    vars_str[key].set(value)
            messagebox.showinfo("完了", f"プリセット「{preset_name}」を適用しました")
    
    def save_current_preset():
        preset_name = preset_var.get()
        if not preset_name:
            # 新しいプリセット名を入力
            dialog = tk.Toplevel(root)
            dialog.title("プリセット保存")
            dialog.geometry("300x100")
            dialog.transient(root)
            dialog.grab_set()
            
            tk.Label(dialog, text="プリセット名:").pack(pady=(10, 5))
            name_var = tk.StringVar()
            name_entry = tk.Entry(dialog, textvariable=name_var, width=30)
            name_entry.pack(pady=5)
            name_entry.focus_set()
            
            def do_save():
                name = name_var.get().strip()
                if not name:
                    messagebox.showwarning("警告", "プリセット名を入力してください")
                    return
                
                # 現在の値を収集
                current_values = {}
                for key in vars_bool:
                    current_values[key] = "1" if vars_bool[key].get() else "0"
                for key in vars_str:
                    current_values[key] = vars_str[key].get()
                
                if save_current_as_preset(name, current_values):
                    presets[name] = current_values
                    preset_combo['values'] = list(presets.keys())
                    preset_var.set(name)
                    messagebox.showinfo("完了", f"プリセット「{name}」を保存しました")
                    dialog.destroy()
                else:
                    messagebox.showerror("エラー", "プリセットの保存に失敗しました")
            
            tk.Button(dialog, text="保存", command=do_save).pack(pady=10)
            name_entry.bind("<Return>", lambda e: do_save())
            return
        
        if messagebox.askyesno("確認", f"現在の設定をプリセット「{preset_name}」に上書き保存しますか？"):
            # 現在の値を収集
            current_values = {}
            for key in vars_bool:
                current_values[key] = "1" if vars_bool[key].get() else "0"
            for key in vars_str:
                current_values[key] = vars_str[key].get()
            
            if save_current_as_preset(preset_name, current_values):
                presets[preset_name] = current_values
                messagebox.showinfo("完了", f"プリセット「{preset_name}」を更新しました")
            else:
                messagebox.showerror("エラー", "プリセットの保存に失敗しました")
    
    def delete_current_preset():
        preset_name = preset_var.get()
        if not preset_name:
            messagebox.showwarning("警告", "プリセットを選択してください")
            return
        
        if messagebox.askyesno("確認", f"プリセット「{preset_name}」を削除しますか？"):
            if delete_preset(preset_name):
                del presets[preset_name]
                preset_combo['values'] = list(presets.keys())
                preset_var.set("")
                messagebox.showinfo("完了", f"プリセット「{preset_name}」を削除しました")
            else:
                messagebox.showerror("エラー", "プリセットの削除に失敗しました")
    
    # プリセット操作ボタン
    tk.Button(preset_frame, text="適用", command=apply_selected_preset, width=8).pack(side="left", padx=2)
    tk.Button(preset_frame, text="保存", command=save_current_preset, width=8).pack(side="left", padx=2)
    tk.Button(preset_frame, text="削除", command=delete_current_preset, width=8).pack(side="left", padx=2)

    main = tk.PanedWindow(root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
    main.pack(fill="both", expand=True, padx=10, pady=10)

    left = tk.Frame(main)
    right = tk.Frame(main)
    main.add(left, stretch="always")
    main.add(right)

    # Scrollable list
    canvas = tk.Canvas(left, highlightthickness=0)
    scrollbar = tk.Scrollbar(left, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas)
    scroll_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def _on_mousewheel(event: tk.Event) -> str:
        try:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta == 0:
                return "break"
            canvas.yview_scroll(int(-delta / 120), "units")
            return "break"
        except Exception:
            return "break"

    desc_var = tk.StringVar(value="項目の右にある [説明] を押すと、ここに説明が出ます。")
    tk.Label(right, text="説明", font=("Meiryo", 11, "bold")).pack(anchor="w", padx=(8, 0))
    desc_box = tk.Message(right, textvariable=desc_var, width=320)
    desc_box.pack(fill="x", pady=(4, 10), padx=(8, 0))

    tk.Label(right, text="操作", font=("Meiryo", 11, "bold")).pack(anchor="w", padx=(8, 0))

    vars_str: Dict[str, tk.StringVar] = {}
    vars_bool: Dict[str, tk.BooleanVar] = {}
    focus_widgets: List[tk.Widget] = []
    widget_to_key_label: Dict[tk.Widget, tk.Label] = {}
    current_highlight_label: Optional[tk.Label] = None
    normal_key_label_font = ("Meiryo", 10, "normal")
    highlight_key_label_font = ("Meiryo", 10, "normal")

    def _set_current_highlight(label: Optional[tk.Label]) -> None:
        nonlocal current_highlight_label
        try:
            if current_highlight_label is not None:
                current_highlight_label.config(fg="black", font=normal_key_label_font)
        except Exception:
            pass

        current_highlight_label = label

        try:
            if current_highlight_label is not None:
                current_highlight_label.config(fg="red", font=highlight_key_label_font)
        except Exception:
            pass

    def _focus_move(delta: int) -> str:
        try:
            if not focus_widgets:
                return "break"

            current = root.focus_get()
            if current in focus_widgets:
                idx = focus_widgets.index(current)
            else:
                idx = 0

            n = len(focus_widgets)
            next_idx = (idx + int(delta)) % n
            focus_widgets[next_idx].focus_set()
        except Exception:
            pass
        return "break"

    def _bind_focus_keys(w: tk.Widget) -> None:
        w.bind("<Return>", lambda e: _focus_move(+1))
        w.bind("<Shift-Return>", lambda e: _focus_move(-1))
        w.bind("<KP_Enter>", lambda e: _focus_move(+1))
        w.bind("<Shift-KP_Enter>", lambda e: _focus_move(-1))

    def _section_title_for_key(key: str) -> str:
        k = str(key or "")
        if k.startswith("KABUS_"):
            return "KabuStation"
        if k in {"ENABLE_GUI", "PROMPT_CONFIG"}:
            return "起動/表示"
        if k.startswith("EDINET_"):
            return "EDINET"
        if k.startswith("NEWS_"):
            return "ニュース"
        if k == "MANUAL_ONLY_MODE":
            return "手動監視"
        if k.startswith("MANUAL_WATCH_"):
            return "手動監視"
        if k.startswith("LUNCH_BATCH_"):
            return "昼休みバッチ"
        if k.startswith("MORNING_BATCH_"):
            return "朝バッチ"
        if k.startswith("AFTERHOURS_ADD_STOP_"):
            return "場引け後の自動追加停止"
        if k.startswith("HFT_OBI_"):
            return "HFT板情報インバランス検知"
        if k.startswith("MA_"):
            return "移動平均線フィルタ"
        if k.startswith("VWAP_"):
            return "VWAPフィルタ"
        if k.startswith("WATCH_") or k in {"SPECIAL_QUOTE_REMOVE_STREAK"}:
            return "監視(Watchlist)"
        if k.startswith("ORDER_"):
            return "注文"
        if k.startswith("SURGE_") or k.startswith("CRASH_"):
            return "イベント検知"
        if k.startswith("AUTO_EXIT_"):
            return "自動決済"
        if k.startswith("EMAIL_"):
            return "メール通知"
        if k.startswith("WEBSOCKET_"):
            return "WebSocket約定通知"
        return "その他"

    def show_desc(key: str) -> None:
        spec = spec_map.get(key, {})
        desc = str(spec.get("desc") or "")
        if not desc:
            desc = "説明は未設定です。"
        desc_var.set(f"{key}\n\n{desc}")

    def _on_focus_in(widget: tk.Widget, key: str) -> None:
        show_desc(key)
        _set_current_highlight(widget_to_key_label.get(widget))

    def initial_value(spec: Dict[str, Any]) -> str:
        key = str(spec["key"])
        if key in env:
            return str(env[key])
        return str(spec.get("default", ""))

    def build_row(r: int, spec: Dict[str, Any]) -> None:
        key = str(spec["key"])
        typ = str(spec.get("type") or "str")

        key_label = tk.Label(scroll_frame, text=key, width=38, anchor="w", font=normal_key_label_font)
        key_label.grid(row=r, column=0, sticky="w", padx=(0, 6), pady=2)

        if typ == "bool":
            bv = tk.BooleanVar(value=_parse_bool_str(initial_value(spec)))
            vars_bool[key] = bv
            cb = tk.Checkbutton(scroll_frame, variable=bv)
            cb.grid(row=r, column=1, sticky="w", pady=2, padx=(20, 0))
            widget_to_key_label[cb] = key_label
            cb.bind("<FocusIn>", lambda e, w=cb, k=key: _on_focus_in(w, k))
            cb.bind("<MouseWheel>", _on_mousewheel)
            cb.bind("<space>", lambda e, w=cb: (w.invoke(), "break")[1])
            _bind_focus_keys(cb)
            focus_widgets.append(cb)
        else:
            sv = tk.StringVar(value=initial_value(spec))
            vars_str[key] = sv
            show = "*" if typ == "password" else ""
            ent = tk.Entry(scroll_frame, textvariable=sv, width=34, show=show)
            ent.grid(row=r, column=1, sticky="w", pady=2, padx=(20, 0))
            widget_to_key_label[ent] = key_label
            ent.bind("<FocusIn>", lambda e, w=ent, k=key: _on_focus_in(w, k))
            ent.bind("<MouseWheel>", _on_mousewheel)
            _bind_focus_keys(ent)
            focus_widgets.append(ent)

    row_i = 0
    prev_section = ""
    for spec in specs:
        key = str(spec.get("key") or "")
        section = _section_title_for_key(key)
        if section != prev_section:
            tk.Label(
                scroll_frame,
                text=section,
                font=("Meiryo", 10, "bold"),
                anchor="w",
            ).grid(row=row_i, column=0, columnspan=3, sticky="w", pady=(10, 4))
            row_i += 1
            prev_section = section

        build_row(row_i, spec)
        row_i += 1

    btns = tk.Frame(right)
    btns.pack(fill="x", pady=(6, 6))

    def collect_env() -> Dict[str, str]:
        out: Dict[str, str] = {}
        for spec in specs:
            key = str(spec["key"])
            typ = str(spec.get("type") or "str")
            if typ == "bool":
                out[key] = _to_bool_str(bool(vars_bool[key].get()))
            else:
                out[key] = str(vars_str[key].get()).strip()
        return out

    def validate_env(new_env: Dict[str, str]) -> Optional[str]:
        for spec in specs:
            key = str(spec["key"])
            typ = str(spec.get("type") or "str")
            val = (new_env.get(key) or "").strip()

            if typ == "int":
                try:
                    int(val)
                except Exception:
                    return f"{key} は整数で入力してください: {val!r}"
            if typ == "float":
                try:
                    float(val)
                except Exception:
                    return f"{key} は数値(float)で入力してください: {val!r}"
        return None

    def on_save() -> None:
        new_env = collect_env()
        err = validate_env(new_env)
        if err:
            messagebox.showerror("入力エラー", err)
            return
        try:
            _write_env_file(env_path, new_env, raw_lines)
        except Exception as e:
            messagebox.showerror("保存失敗", str(e))
            return
        messagebox.showinfo("保存完了", ".env を保存しました。\n次回起動から反映されます。")

    def on_ctrl_s(_: tk.Event) -> str:
        on_save()
        return "break"

    def on_reload() -> None:
        nonlocal env, raw_lines
        env, raw_lines = _parse_env_file(env_path)
        for spec in specs:
            key = str(spec["key"])
            typ = str(spec.get("type") or "str")
            v = env.get(key)
            if v is None:
                v = str(spec.get("default", ""))
            if typ == "bool":
                vars_bool[key].set(_parse_bool_str(str(v)))
            else:
                vars_str[key].set(str(v))

    tk.Button(btns, text="再読込", command=on_reload, width=10).pack(side="left")
    tk.Button(btns, text="保存", command=on_save, width=10).pack(side="left", padx=(8, 0))
    tk.Button(btns, text="閉じる", command=root.destroy, width=10).pack(side="left", padx=(8, 0))

    # Scroll / shortcut bindings
    canvas.bind("<MouseWheel>", _on_mousewheel)
    scroll_frame.bind("<MouseWheel>", _on_mousewheel)
    root.bind_all("<Control-s>", on_ctrl_s)
    root.bind_all("<Control-S>", on_ctrl_s)

    show_desc(str(specs[0]["key"]))

    def _focus_first() -> None:
        try:
            if not focus_widgets:
                return
            w0 = focus_widgets[0]
            w0.focus_set()
            try:
                if isinstance(w0, tk.Entry):
                    w0.selection_range(0, "end")
                    w0.icursor("end")
            except Exception:
                pass
            _set_current_highlight(widget_to_key_label.get(w0))
        except Exception:
            pass

    root.after(100, _focus_first)
    root.mainloop()
    return 0


def main(argv: List[str]) -> int:
    if "--cli" in argv:
        args = [a for a in argv[1:] if a != "--cli"]
        env_path = args[0] if len(args) >= 1 else DEFAULT_ENV_PATH
    else:
        env_path = argv[1] if len(argv) >= 2 else DEFAULT_ENV_PATH

    env, raw_lines = _parse_env_file(env_path)

    print(f"[ENV] .env path: {os.path.abspath(env_path)}")
    if not raw_lines:
        print("[ENV] .env not found or empty. It will be created.")

    if "--cli" not in argv:
        return _run_gui(env_path)

    updated = dict(env)

    print("[ENV] Enter values (blank keeps current / uses default if missing).")
    for spec in ENV_SPECS:
        key = spec["key"]
        default = spec["default"]
        current = updated.get(key)

        if key.upper().endswith("PASSWORD") and current is not None:
            cur_mask = "(set)"
        else:
            cur_mask = current

        # Show masked current in prompt message by passing current, but avoid leaking passwords.
        shown_current = None
        if key.upper().endswith("PASSWORD") and current is not None:
            shown_current = "(set)"
        else:
            shown_current = current

        val = _prompt(key, shown_current, default)
        if key.upper().endswith("PASSWORD") and val == "(set)":
            # If user just hit enter, _prompt returns current/default, but with masked current it can return "(set)".
            # Treat it as unchanged when password was already set.
            if current is not None:
                val = current
            else:
                val = ""

        updated[key] = val

    _write_env_file(env_path, updated, raw_lines)
    print("[ENV] Saved.")

    # Show summary (avoid printing secrets)
    print("[ENV] Current values:")
    for spec in ENV_SPECS:
        key = spec["key"]
        val = updated.get(key, "")
        if key.upper().endswith("PASSWORD") and val:
            disp = "(set)"
        else:
            disp = val
        print(f"  {key}={disp}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
