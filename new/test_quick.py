# -*- coding: utf-8 -*-
"""Quick test for all analysis modules"""
import sys
sys.path.insert(0, ".")

import pandas as pd
import numpy as np
from signals import add_sma_columns, detect_ma_signals
from candlestick import detect_all_patterns
from timeframes import resample_weekly, resample_monthly
from volume_profile import compute_volume_profile

# Generate synthetic data
dates = pd.date_range("2025-01-01", periods=100, freq="B")
np.random.seed(42)
prices = 1000 + np.cumsum(np.random.randn(100) * 10)
df = pd.DataFrame({
    "open": prices + np.random.randn(100) * 2,
    "high": prices + abs(np.random.randn(100) * 5),
    "low": prices - abs(np.random.randn(100) * 5),
    "close": prices,
    "volume": np.random.randint(10000, 100000, 100),
}, index=dates)

# Test SMA + signals
df_sma = add_sma_columns(df, "daily")
sma_cols = [c for c in df_sma.columns if "SMA" in c]
print(f"SMA columns: {sma_cols}")

ma_signals = detect_ma_signals(df_sma, "daily")
print(f"MA signals: {len(ma_signals)}")
for s in ma_signals[:3]:
    print(f"  {s['type']}: {s['name']} @ {s['date'].strftime('%Y-%m-%d')}")

# Test candlestick
candle_signals = detect_all_patterns(df, "daily")
print(f"Candlestick signals: {len(candle_signals)}")
for s in candle_signals[:3]:
    print(f"  {s['type']}: {s['name']}")

# Test timeframes
weekly = resample_weekly(df)
monthly = resample_monthly(df)
print(f"Weekly: {len(weekly)} bars, Monthly: {len(monthly)} bars")

# Test volume profile
_, centers, vol = compute_volume_profile(df)
print(f"Volume profile: {len(centers)} bins")

print("\nALL TESTS PASSED")
