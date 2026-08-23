import time
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import libquant_engine

engine = libquant_engine.PyQuantEngine()

# Benchmark a burst of synthetic ticks.
start = time.perf_counter()
for i in range(200_000):
    tick = {
        "timestamp_ns": int((time.time_ns() // 1_000_000_000) * 1_000_000_000) + i,
        "price": 100.0 + (i % 5) * 0.25,
        "volume": 10 + (i % 17),
    }
    engine.push_tick(tick)

elapsed = time.perf_counter() - start
print(f"Processed 200k ticks in {elapsed:.4f}s ({200_000 / elapsed:.0f} ticks/s)")
print(engine.snapshot())
