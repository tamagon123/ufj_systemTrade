import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
os.environ["PYTHONUTF8"] = "1"

import pandas as pd
import numpy as np
from signals import detect_ma_signals, add_sma_columns
from candlestick import detect_all_patterns
from signal_performance import analyze_signal_performance

np.random.seed(42)
dates = pd.bdate_range("2024-01-01", periods=500)
close = 1000 + np.cumsum(np.random.randn(500) * 10)
df = pd.DataFrame({
    "open": close + np.random.randn(500) * 5,
    "high": close + abs(np.random.randn(500) * 10),
    "low": close - abs(np.random.randn(500) * 10),
    "close": close,
    "volume": np.random.randint(100000, 1000000, 500),
}, index=dates)

df = add_sma_columns(df)
sigs = detect_ma_signals(df) + detect_all_patterns(df)
perf = analyze_signal_performance(df, sigs)

types = len(set(s["name"] for s in sigs))
print(f"Unique signal types: {types}")
print(f"Performance stats: {len(perf)} types")

ok = all(
    v["win_rate"] >= 0 and v["win_rate"] <= 1 and v["count"] > 0
    for v in perf.values()
)
print(f"All stats valid: {ok}")

for name, s in list(perf.items())[:5]:
    print(f"  {name}: count={s['count']} wr={s['win_rate']:.0%} ev={s['expected_value']:+.2%} sr={s['sharpe_ratio']:.2f}")

print("PERF TEST PASSED" if ok else "PERF TEST FAILED")
