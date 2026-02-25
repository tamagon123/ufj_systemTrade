# -*- coding: utf-8 -*-
"""
timeframes.py — 週足・月足リサンプリング
=========================================
日足 DataFrame から週足・月足を動的に生成する。
"""

import pandas as pd


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    日足 DataFrame → 週足にリサンプリング。
    df の index は DatetimeIndex、カラムは open/high/low/close/volume。
    """
    if df.empty:
        return df.copy()
    weekly = df.resample("W-FRI").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    return weekly


def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """
    日足 DataFrame → 月足にリサンプリング。
    """
    if df.empty:
        return df.copy()
    monthly = df.resample("ME").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    return monthly
