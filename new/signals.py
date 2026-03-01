# -*- coding: utf-8 -*-
"""
signals.py — テクニカルシグナル検出
=====================================
SMA, RSI, MACD, ボリンジャーバンド, 一目均衡表, ADX, パラボリックSAR
による多種シグナルを検出し、良い/悪いシグナルとして分類する。
"""

from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from config import MA_PARAMS


# ══════════════════════════════════════════════════════════════════════════════
# テクニカル指標 算出
# ══════════════════════════════════════════════════════════════════════════════
# シグナル スコア定義
# ═══════════════════════════════════════════════════════════════════════════════
# 正の値 = 買い方向の強さ（bullishシグナルに使用）
# 負の値 = 売り方向の強さ（bearishシグナルに使用）
# 絶対値: 3=非常に強い, 2=中程度, 1=弱い/予備的
SIGNAL_SCORES: Dict[str, int] = {
    # ─── MA系シグナル ───
    "ゴールデンクロス (短期/中期)":       2,
    "ゴールデンクロス (中期/長期)":       3,
    "デッドクロス (短期/中期)":          -2,
    "デッドクロス (中期/長期)":          -3,
    "パーフェクトオーダー (強気)":        3,
    "パーフェクトオーダー (弱気)":       -3,
    "グランビルの法則 (買い第1法則)":     3,
    "グランビルの法則 (売り第1法則)":    -3,
    "終値がSMA短期を上抜け":             1,
    "終値がSMA短期を下抜け":            -1,
    "終値がSMA長期を上抜け":             2,
    "終値がSMA長期を下抜け":            -2,
    # ─── RSI ───
    "RSI 売られすぎ反転":                2,
    "RSI 買われすぎ反転":               -2,
    "RSI ダイバージェンス (強気)":        3,
    "RSI ダイバージェンス (弱気)":       -3,
    # ─── MACD ───
    "MACD ゴールデンクロス":             2,
    "MACD デッドクロス":                -2,
    # ─── ボリンジャーバンド ───
    "ボリンジャー下限反発":              2,
    "ボリンジャー上限反落":             -2,
    # ─── 一目均衡表 ───
    "一目均衡表 三役好転":               3,
    "一目均衡表 三役逆転":              -3,
    # ─── ADX ───
    "ADX トレンド発生":                  1,
    # ─── パラボリックSAR ───
    "パラボリックSAR 反転 (買い)":       2,
    "パラボリックSAR 反転 (売り)":      -2,
    # ─── 騰落率 ───
    "騰落率オーバーシュート (上方)":     -1,
    "騰落率オーバーシュート (下方)":      1,
    # ─── ローソク足パターン（買い）───
    "包み足（陽線）":                    2,
    "はらみ足（陽はらみ）":              1,
    "カラカサ / ハンマー":               2,
    "明けの明星":                        3,
    "赤三兵":                            3,
    "出来高急増（陽線）":                2,
    "窓開け上昇（ギャップアップ）":      1,
    "たくり線":                          2,
    "三空叩き込み":                      3,
    "ピンバー（反転・買い）":            2,
    "リバーサル・デー（強気）":          2,
    # ─── ローソク足パターン（売り）───
    "包み足（陰線）":                   -2,
    "流星":                             -2,
    "宵の明星":                         -3,
    "黒三兵":                           -3,
    "三羽烏（小実体群）":               -1,
    "出来高急増（陰線）":               -2,
    "窓開け下落（ギャップダウン）":      -1,
    "十字線（天井圏）":                 -1,
    "十字線（底値圏）":                  1,
    "首吊り線":                         -2,
    "窓埋め（上昇後）":                 -1,
    "三空踏み上げ":                     -3,
    "ピンバー（反転・売り）":           -2,
    "下放れ二本立ち":                   -2,
    "トウバ（墓石十字線）":             -2,
    "リバーサル・デー（弱気）":         -2,
}


def get_signal_score(signal_name: str) -> int:
    """シグナル名からスコアを返す（未登録は0）"""
    return SIGNAL_SCORES.get(signal_name, 0)


# ══════════════════════════════════════════════════════════════════════════════
def compute_sma(df: pd.DataFrame, period: int) -> pd.Series:
    """終値の単純移動平均線を算出"""
    return df["close"].rolling(window=period, min_periods=period).mean()


def add_sma_columns(
    df: pd.DataFrame,
    timeframe: str = "daily",
    params: Optional[Dict] = None,
) -> pd.DataFrame:
    """DataFrame に SMA_short / SMA_medium / SMA_long カラムを追加する。"""
    if params is None:
        params = MA_PARAMS.get(timeframe, MA_PARAMS["daily"])
    df = df.copy()
    df["SMA_short"]  = compute_sma(df, params["short"])
    df["SMA_medium"] = compute_sma(df, params["medium"])
    df["SMA_long"]   = compute_sma(df, params["long"])
    return df


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI (Relative Strength Index) を算出"""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12, slow: int = 26, signal: int = 9,
) -> pd.DataFrame:
    """MACD, シグナル線, ヒストグラムを算出"""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    result = df.copy() if False else pd.DataFrame(index=df.index)
    result["MACD"] = macd_line
    result["MACD_signal"] = signal_line
    result["MACD_hist"] = histogram
    return result


def compute_bollinger(
    df: pd.DataFrame, period: int = 20, num_std: float = 2.0,
) -> pd.DataFrame:
    """ボリンジャーバンド (上限/下限/中間) を算出"""
    sma = df["close"].rolling(window=period, min_periods=period).mean()
    std = df["close"].rolling(window=period, min_periods=period).std()
    result = pd.DataFrame(index=df.index)
    result["BB_mid"] = sma
    result["BB_upper"] = sma + num_std * std
    result["BB_lower"] = sma - num_std * std
    return result


def compute_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    """一目均衡表の各ラインを算出"""
    high = df["high"]
    low = df["low"]
    # 転換線 (9期間)
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    # 基準線 (26期間)
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    # 先行スパンA (転換線+基準線)/2 を26期間先行
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    # 先行スパンB (52期間の中間) を26期間先行
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    # 遅行線 (終値を26期間遅行)
    chikou = df["close"].shift(-26)

    result = pd.DataFrame(index=df.index)
    result["tenkan"] = tenkan
    result["kijun"] = kijun
    result["senkou_a"] = senkou_a
    result["senkou_b"] = senkou_b
    result["chikou"] = chikou
    return result


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX (Average Directional Index) を算出"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()

    plus_di = 100 * plus_dm.rolling(window=period).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.rolling(window=period).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(window=period, min_periods=period).mean()
    return adx


def compute_parabolic_sar(df: pd.DataFrame, af_start=0.02, af_max=0.2) -> pd.Series:
    """パラボリックSAR を算出"""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    sar = np.zeros(n)
    af = af_start
    is_long = True
    ep = high[0]
    sar[0] = low[0]

    for i in range(1, n):
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
        if is_long:
            sar[i] = min(sar[i], low[i - 1])
            if i >= 2:
                sar[i] = min(sar[i], low[i - 2])
            if sar[i] > low[i]:
                is_long = False
                sar[i] = ep
                ep = low[i]
                af = af_start
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_start, af_max)
        else:
            sar[i] = max(sar[i], high[i - 1])
            if i >= 2:
                sar[i] = max(sar[i], high[i - 2])
            if sar[i] < high[i]:
                is_long = True
                sar[i] = ep
                ep = high[i]
                af = af_start
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_start, af_max)

    return pd.Series(sar, index=df.index, name="SAR")


# ══════════════════════════════════════════════════════════════════════════════
# シグナル検出
# ══════════════════════════════════════════════════════════════════════════════
def _slope(series: pd.Series) -> pd.Series:
    """前日比の変化（傾き）"""
    return series.diff()


def detect_ma_signals(
    df: pd.DataFrame,
    timeframe: str = "daily",
    params: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """
    全テクニカルシグナルを検出する。
    MA系 + RSI + MACD + BB + 一目均衡表 + ADX + SAR + 乖離率

    返り値: [{"name": "...", "type": "bullish"/"bearish",
              "timeframe": "...", "date": Timestamp, "detail": "..."}, ...]
    """
    if params is None:
        params = MA_PARAMS.get(timeframe, MA_PARAMS["daily"])

    # SMA カラムがなければ追加
    if "SMA_short" not in df.columns:
        df = add_sma_columns(df, timeframe, params)

    signals: List[Dict[str, Any]] = []

    if len(df) < 52:  # 一目均衡表に最低限必要
        if len(df) < 2:
            return signals

    close = df["close"]
    short = df["SMA_short"]
    medium = df["SMA_medium"]
    long_ = df["SMA_long"]

    short_slope = _slope(short)
    medium_slope = _slope(medium)
    long_slope = _slope(long_)

    # テクニカル指標を事前計算
    rsi = compute_rsi(df, 14)
    macd_df = compute_macd(df)
    bb = compute_bollinger(df)
    adx = compute_adx(df)
    sar = compute_parabolic_sar(df)

    ichimoku = None
    if len(df) >= 52:
        ichimoku = compute_ichimoku(df)

    # 5日移動平均乖離率
    sma5 = close.rolling(5).mean()
    deviation_5 = ((close - sma5) / sma5 * 100)

    for i in range(1, len(df)):
        date = df.index[i]

        # NaN チェック (SMA)
        s_ok = not pd.isna(short.iloc[i]) and not pd.isna(short.iloc[i - 1])
        m_ok = not pd.isna(medium.iloc[i]) and not pd.isna(medium.iloc[i - 1])
        l_ok = not pd.isna(long_.iloc[i]) and not pd.isna(long_.iloc[i - 1])
        all_ma_ok = s_ok and m_ok and l_ok

        # ─── MA系シグナル ───
        if all_ma_ok:
            # 1. ゴールデンクロス (短期/中期)
            if short.iloc[i - 1] <= medium.iloc[i - 1] and short.iloc[i] > medium.iloc[i]:
                signals.append({
                    "name": "ゴールデンクロス (短期/中期)",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"SMA{params['short']}がSMA{params['medium']}を上抜け",
                })

            # 2. ゴールデンクロス (中期/長期)
            if medium.iloc[i - 1] <= long_.iloc[i - 1] and medium.iloc[i] > long_.iloc[i]:
                signals.append({
                    "name": "ゴールデンクロス (中期/長期)",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"SMA{params['medium']}がSMA{params['long']}を上抜け",
                })

            # 3. デッドクロス (短期/中期)
            if short.iloc[i - 1] >= medium.iloc[i - 1] and short.iloc[i] < medium.iloc[i]:
                signals.append({
                    "name": "デッドクロス (短期/中期)",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"SMA{params['short']}がSMA{params['medium']}を下抜け",
                })

            # 4. デッドクロス (中期/長期)
            if medium.iloc[i - 1] >= long_.iloc[i - 1] and medium.iloc[i] < long_.iloc[i]:
                signals.append({
                    "name": "デッドクロス (中期/長期)",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"SMA{params['medium']}がSMA{params['long']}を下抜け",
                })

            # 5. パーフェクトオーダー (強気)
            if (short.iloc[i] > medium.iloc[i] > long_.iloc[i]
                    and not pd.isna(short_slope.iloc[i])
                    and short_slope.iloc[i] > 0
                    and medium_slope.iloc[i] > 0
                    and long_slope.iloc[i] > 0):
                signals.append({
                    "name": "パーフェクトオーダー (強気)",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "短期>中期>長期、3本すべて上昇中",
                })

            # 6. パーフェクトオーダー (弱気)
            if (short.iloc[i] < medium.iloc[i] < long_.iloc[i]
                    and not pd.isna(short_slope.iloc[i])
                    and short_slope.iloc[i] < 0
                    and medium_slope.iloc[i] < 0
                    and long_slope.iloc[i] < 0):
                signals.append({
                    "name": "パーフェクトオーダー (弱気)",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "短期<中期<長期、3本すべて下落中",
                })

            # 7. グランビルの法則 (買い第1法則)
            if (i >= 5 and not pd.isna(long_slope.iloc[i])
                    and close.iloc[i - 1] <= long_.iloc[i - 1]
                    and close.iloc[i] > long_.iloc[i]):
                recent_slopes = long_slope.iloc[max(0, i - 5):i].dropna()
                if len(recent_slopes) > 0 and recent_slopes.mean() <= 0 and long_slope.iloc[i] >= 0:
                    signals.append({
                        "name": "グランビルの法則 (買い第1法則)",
                        "type": "bullish",
                        "timeframe": timeframe,
                        "date": date,
                        "detail": f"価格がSMA{params['long']}を下から上抜け（長期MA転換）",
                    })

            # 8. グランビルの法則 (売り第1法則)
            if (i >= 5 and not pd.isna(long_slope.iloc[i])
                    and close.iloc[i - 1] >= long_.iloc[i - 1]
                    and close.iloc[i] < long_.iloc[i]):
                recent_slopes = long_slope.iloc[max(0, i - 5):i].dropna()
                if len(recent_slopes) > 0 and recent_slopes.mean() >= 0 and long_slope.iloc[i] <= 0:
                    signals.append({
                        "name": "グランビルの法則 (売り第1法則)",
                        "type": "bearish",
                        "timeframe": timeframe,
                        "date": date,
                        "detail": f"価格がSMA{params['long']}を上から下抜け（長期MA転換）",
                    })

        # ─── 終値の MA 上抜け/下抜け ───
        if s_ok:
            # 9. 終値がSMA短期を上抜け
            if close.iloc[i - 1] <= short.iloc[i - 1] and close.iloc[i] > short.iloc[i]:
                signals.append({
                    "name": "終値がSMA短期を上抜け",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"終値がSMA{params['short']}を下から上へ突破",
                })

            # 10. 終値がSMA短期を下抜け
            if close.iloc[i - 1] >= short.iloc[i - 1] and close.iloc[i] < short.iloc[i]:
                signals.append({
                    "name": "終値がSMA短期を下抜け",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"終値がSMA{params['short']}を上から下へ突破",
                })

        if l_ok:
            # 11. 終値がSMA長期を上抜け
            if close.iloc[i - 1] <= long_.iloc[i - 1] and close.iloc[i] > long_.iloc[i]:
                signals.append({
                    "name": "終値がSMA長期を上抜け",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"終値がSMA{params['long']}を下から上へ突破",
                })

            # 12. 終値がSMA長期を下抜け
            if close.iloc[i - 1] >= long_.iloc[i - 1] and close.iloc[i] < long_.iloc[i]:
                signals.append({
                    "name": "終値がSMA長期を下抜け",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"終値がSMA{params['long']}を上から下へ突破",
                })

        # ─── RSI シグナル ───
        rsi_val = rsi.iloc[i] if i < len(rsi) else np.nan
        rsi_prev = rsi.iloc[i - 1] if (i - 1) < len(rsi) else np.nan
        if not pd.isna(rsi_val) and not pd.isna(rsi_prev):
            # 13. RSI 売られすぎ反転 (30以下 → 30以上)
            if rsi_prev <= 30 and rsi_val > 30:
                signals.append({
                    "name": "RSI 売られすぎ反転",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"RSI(14)が{rsi_val:.1f}へ上昇（30以下から反転）",
                })

            # 14. RSI 買われすぎ反転 (70以上 → 70以下)
            if rsi_prev >= 70 and rsi_val < 70:
                signals.append({
                    "name": "RSI 買われすぎ反転",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"RSI(14)が{rsi_val:.1f}へ下落（70以上から反転）",
                })

        # ─── RSI ダイバージェンス ───
        if i >= 20 and not pd.isna(rsi_val):
            lookback = min(i, 20)
            price_window = close.iloc[i - lookback:i + 1]
            rsi_window = rsi.iloc[i - lookback:i + 1].dropna()
            if len(rsi_window) >= 5:
                # 15. 強気ダイバージェンス: 価格安値更新 + RSI安値切り上げ
                price_min_idx = price_window.idxmin()
                if (close.iloc[i] <= price_window.min() * 1.02
                        and not pd.isna(rsi.loc[price_min_idx] if price_min_idx in rsi.index else np.nan)):
                    rsi_at_low = rsi.loc[price_min_idx] if price_min_idx in rsi.index else np.nan
                    if not pd.isna(rsi_at_low) and rsi_val > rsi_at_low + 3:
                        signals.append({
                            "name": "RSI ダイバージェンス (強気)",
                            "type": "bullish",
                            "timeframe": timeframe,
                            "date": date,
                            "detail": f"株価が安値圏だがRSIは上昇（反転示唆）",
                        })

                # 16. 弱気ダイバージェンス: 価格高値更新 + RSI高値切り下げ
                price_max_idx = price_window.idxmax()
                if (close.iloc[i] >= price_window.max() * 0.98
                        and not pd.isna(rsi.loc[price_max_idx] if price_max_idx in rsi.index else np.nan)):
                    rsi_at_high = rsi.loc[price_max_idx] if price_max_idx in rsi.index else np.nan
                    if not pd.isna(rsi_at_high) and rsi_val < rsi_at_high - 3:
                        signals.append({
                            "name": "RSI ダイバージェンス (弱気)",
                            "type": "bearish",
                            "timeframe": timeframe,
                            "date": date,
                            "detail": f"株価が高値圏だがRSIは下落（反転示唆）",
                        })

        # ─── MACD シグナル ───
        macd_val = macd_df["MACD"].iloc[i]
        macd_sig = macd_df["MACD_signal"].iloc[i]
        macd_prev = macd_df["MACD"].iloc[i - 1]
        macd_sig_prev = macd_df["MACD_signal"].iloc[i - 1]
        if not any(pd.isna(v) for v in [macd_val, macd_sig, macd_prev, macd_sig_prev]):
            # 17. MACD ゴールデンクロス
            if macd_prev <= macd_sig_prev and macd_val > macd_sig:
                signals.append({
                    "name": "MACD ゴールデンクロス",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "MACD線がシグナル線を上抜け — 上昇モメンタム",
                })

            # 18. MACD デッドクロス
            if macd_prev >= macd_sig_prev and macd_val < macd_sig:
                signals.append({
                    "name": "MACD デッドクロス",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "MACD線がシグナル線を下抜け — 下落モメンタム",
                })

        # ─── ボリンジャーバンド ───
        bb_upper = bb["BB_upper"].iloc[i]
        bb_lower = bb["BB_lower"].iloc[i]
        if not pd.isna(bb_upper) and not pd.isna(bb_lower):
            bb_prev_upper = bb["BB_upper"].iloc[i - 1]
            bb_prev_lower = bb["BB_lower"].iloc[i - 1]

            # 19. BB 下限タッチ → 反発
            if (not pd.isna(bb_prev_lower)
                    and close.iloc[i - 1] <= bb_prev_lower
                    and close.iloc[i] > bb_lower):
                signals.append({
                    "name": "ボリンジャー下限反発",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "終値がBB-2σ以下から反発 — 売られすぎ反転",
                })

            # 20. BB 上限タッチ → 反落
            if (not pd.isna(bb_prev_upper)
                    and close.iloc[i - 1] >= bb_prev_upper
                    and close.iloc[i] < bb_upper):
                signals.append({
                    "name": "ボリンジャー上限反落",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "終値がBB+2σ以上から反落 — 買われすぎ反転",
                })

        # ─── 一目均衡表 ───
        if ichimoku is not None and i < len(ichimoku):
            tenkan_v = ichimoku["tenkan"].iloc[i]
            kijun_v = ichimoku["kijun"].iloc[i]
            spa = ichimoku["senkou_a"].iloc[i]
            spb = ichimoku["senkou_b"].iloc[i]
            chikou_v = ichimoku["chikou"].iloc[i]
            if not any(pd.isna(v) for v in [tenkan_v, kijun_v, spa, spb]):
                cloud_top = max(spa, spb)
                cloud_bottom = min(spa, spb)

                # 21. 三役好転
                chikou_ok = (not pd.isna(chikou_v)
                             and i + 26 < len(df)
                             and chikou_v > close.iloc[i])
                if (tenkan_v > kijun_v
                        and close.iloc[i] > cloud_top
                        and chikou_ok):
                    signals.append({
                        "name": "一目均衡表 三役好転",
                        "type": "bullish",
                        "timeframe": timeframe,
                        "date": date,
                        "detail": "転換線>基準線、株価>雲、遅行線>株価 — 強力な買いシグナル",
                    })

                # 22. 三役逆転
                chikou_bear = (not pd.isna(chikou_v)
                               and i + 26 < len(df)
                               and chikou_v < close.iloc[i])
                if (tenkan_v < kijun_v
                        and close.iloc[i] < cloud_bottom
                        and chikou_bear):
                    signals.append({
                        "name": "一目均衡表 三役逆転",
                        "type": "bearish",
                        "timeframe": timeframe,
                        "date": date,
                        "detail": "転換線<基準線、株価<雲、遅行線<株価 — 強力な売りシグナル",
                    })

        # ─── ADX (トレンド発生) ───
        adx_val = adx.iloc[i] if i < len(adx) else np.nan
        adx_prev = adx.iloc[i - 1] if (i - 1) < len(adx) else np.nan
        if not pd.isna(adx_val) and not pd.isna(adx_prev):
            # 23. ADX が 25 を上抜け（トレンド発生）
            if adx_prev <= 25 and adx_val > 25:
                signals.append({
                    "name": "ADX トレンド発生",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"ADX(14)が{adx_val:.1f}へ上昇（25超え＝強いトレンド開始）",
                })

        # ─── パラボリックSAR ───
        sar_val = sar.iloc[i]
        sar_prev = sar.iloc[i - 1]
        if not pd.isna(sar_val) and not pd.isna(sar_prev):
            # 24. SAR 反転 (買い): SAR が上 → 下に移動
            if sar_prev > close.iloc[i - 1] and sar_val < close.iloc[i]:
                signals.append({
                    "name": "パラボリックSAR 反転 (買い)",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "SARが株価の下側に移動 — トレンド転換（買い）",
                })

            # 25. SAR 反転 (売り): SAR が下 → 上に移動
            if sar_prev < close.iloc[i - 1] and sar_val > close.iloc[i]:
                signals.append({
                    "name": "パラボリックSAR 反転 (売り)",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": "SARが株価の上側に移動 — トレンド転換（売り）",
                })

        # ─── 騰落率急騰（オーバーシュート）───
        if not pd.isna(deviation_5.iloc[i]):
            # 26. 5日MA乖離率 +10%以上
            if deviation_5.iloc[i] >= 10:
                signals.append({
                    "name": "騰落率オーバーシュート (上方)",
                    "type": "bearish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"5日MA乖離率 +{deviation_5.iloc[i]:.1f}% — 過熱感（反落注意）",
                })

            # 追加: 5日MA乖離率 -10%以下
            if deviation_5.iloc[i] <= -10:
                signals.append({
                    "name": "騰落率オーバーシュート (下方)",
                    "type": "bullish",
                    "timeframe": timeframe,
                    "date": date,
                    "detail": f"5日MA乖離率 {deviation_5.iloc[i]:.1f}% — 売られすぎ（反発注意）",
                })

    return signals


def get_latest_signals(
    df: pd.DataFrame,
    timeframe: str = "daily",
    lookback: int = 5,
    params: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """直近 lookback 日分のシグナルだけを返す便利関数"""
    all_signals = detect_ma_signals(df, timeframe, params)
    if not all_signals:
        return []
    cutoff = df.index[-lookback] if len(df) >= lookback else df.index[0]
    return [s for s in all_signals if s["date"] >= cutoff]
