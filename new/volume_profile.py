# -*- coding: utf-8 -*-
"""
volume_profile.py — 価格帯別出来高
====================================
指定期間の日足データから価格帯別出来高を算出する。
"""

from typing import Tuple
import numpy as np
import pandas as pd

from config import VOLUME_PROFILE_BINS


def compute_volume_profile(
    df: pd.DataFrame,
    n_bins: int = VOLUME_PROFILE_BINS,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    価格帯別出来高を算出する。

    Args:
        df: DatetimeIndex を持つ OHLCV DataFrame
        n_bins: 価格帯の分割数

    Returns:
        (bin_edges, bin_centers, volume_at_price)
        - bin_edges: (n_bins + 1,) 配列 — 各ビンの境界価格
        - bin_centers: (n_bins,) 配列 — 各ビンの中央価格
        - volume_at_price: (n_bins,) 配列 — 各ビンの出来高合計
    """
    if df.empty or n_bins < 1:
        return np.array([]), np.array([]), np.array([])

    p_min = df["low"].min()
    p_max = df["high"].max()

    if p_min == p_max:
        return np.array([p_min, p_max]), np.array([p_min]), np.array([df["volume"].sum()])

    bin_edges = np.linspace(p_min, p_max, n_bins + 1)
    volume_at_price = np.zeros(n_bins)

    for _, row in df.iterrows():
        typical_price = (row["high"] + row["low"] + row["close"]) / 3.0
        bin_idx = int((typical_price - p_min) / (p_max - p_min) * (n_bins - 1))
        bin_idx = max(0, min(bin_idx, n_bins - 1))
        volume_at_price[bin_idx] += row["volume"]

    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0

    return bin_edges, bin_centers, volume_at_price


def find_support_resistance(
    bin_centers: np.ndarray,
    volume_at_price: np.ndarray,
    top_n: int = 5,
) -> pd.DataFrame:
    """
    出来高が大きい価格帯（支持線・抵抗線候補）を返す。

    Returns:
        DataFrame: columns=[price, volume] 出来高が大きい順に top_n 件
    """
    if len(bin_centers) == 0:
        return pd.DataFrame(columns=["price", "volume"])

    indices = np.argsort(volume_at_price)[::-1][:top_n]
    return pd.DataFrame({
        "price": bin_centers[indices],
        "volume": volume_at_price[indices],
    })
