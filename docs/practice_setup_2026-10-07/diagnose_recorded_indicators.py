"""Inspect frozen indicators from saved public scan inputs, without any network."""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.base_exchange import Candle, ExchangeError, decimal
from exchange.paper_operations import active_source_hash
from frozen_strategy import FrozenStrategy

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--candles', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
args = p.parse_args()
if args.output.exists():
    p.error('preserve previous diagnostic evidence; select a new output')
logging.disable(logging.CRITICAL)
raw = args.candles.read_bytes()
snapshots = {}
for line in raw.splitlines():
    record = json.loads(line)
    if record['symbol'] in {'par:SP500', 'par:HYPE'} and record['candles']:
        snapshots[record['symbol']] = record
report = dict(scope='OFFLINE_DIAGNOSTIC_OF_RECORDED_PUBLIC_SCAN_INPUTS',
              active_source_hash=active_source_hash(ROOT), exchange_actions_submitted=0,
              strategy_changed=False, input_path=str(args.candles.resolve()),
              input_snapshot_sha256=hashlib.sha256(raw).hexdigest(), snapshots=[])
brain = FrozenStrategy(None)
for symbol, record in snapshots.items():
    candles = []
    for row in record['candles']:
        fields = {k: v for k, v in row.items() if k in Candle.__dataclass_fields__}
        for name in ('open', 'high', 'low', 'close', 'volume'):
            fields[name] = Decimal(str(fields[name]))
        candles.append(Candle(**fields))
    enriched = brain.evaluate_candles(candles)
    last = enriched.iloc[-1]
    indicators = {}
    invalid_required = []
    for name in ('Close', 'ATR_14', 'EMA_9', 'EMA_21', 'VWAP', 'VWAP_Slope'):
        required_positive = name != 'VWAP_Slope'
        observed = dict(value=str(last[name]), scanner_requires_positive=required_positive)
        try:
            decimal(last[name], positive=required_positive)
            observed['validation'] = 'PASS'
        except ExchangeError as exc:
            observed['validation'] = str(exc)
            if required_positive:
                invalid_required.append(name)
        indicators[name] = observed
    report['snapshots'].append(dict(symbol=symbol,
        scan_observed_at_ms=record['scan_observed_at_ms'], bar_count=len(candles),
        zero_volume_bars=sum(c.volume == 0 for c in candles),
        zero_range_bars=sum(c.high == c.low for c in candles),
        last_candle_open_ms=candles[-1].timestamp_ms, indicators=indicators,
        invalid_required_indicators=invalid_required,
        note='Signed/zero slope is valid. Positive ATR validation is an existing guard, not a strategy change.'))
with args.output.open('x') as stream:
    stream.write(json.dumps(report, indent=2) + '\n')
print(json.dumps(dict(output=str(args.output.resolve()), snapshots=report['snapshots'])))
