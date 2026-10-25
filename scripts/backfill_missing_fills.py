"""Backfill round trips the exchange reports but a runtime journal never recorded (bug #11).

Offline and read-only towards the exchange: it reads a saved exchange-fills evidence file
(userFillsByTime rows) and a runtime state file, and appends every missing round trip to the
state's trade log with reason BACKFILLED_FROM_EXCHANGE_FILLS, plus one event line per trade.
It never signs, never places orders, and refuses to run while the runtime might be live
(no stop.flag, or a FINISHED record missing).

  python3 scripts/backfill_missing_fills.py --fills docs/fee_bleed_2026-10-25/exchange_fills_since_2026-10-15.json \
      --state runtime/continuous --since-ms 1792918024186 [--apply]
"""
import argparse, json, sys
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
from exchange.fill_ledger import missing_trades       # noqa: E402  (pure stdlib module)


def recorded_tids(state, rows):
    tids = {t for trade in state.get('trades', []) for t in trade.get('fill_tids', ())}
    windows = [(t['symbol'], t['entry_ms'] - 60000, t.get('exit_ms', t['entry_ms']) + 5000)
               for t in state.get('trades', []) if not t.get('fill_tids')]
    for r in rows:
        if any(r['coin'] == s and a <= int(r['time']) <= b for s, a, b in windows):
            tids.add(str(r['tid']))
    return tids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fills', required=True)
    ap.add_argument('--state', required=True, help='runtime state directory (holds overnight_state.json)')
    ap.add_argument('--since-ms', type=int, required=True, help='only fills at or after this time (session start)')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    state_dir = Path(a.state)
    if not (state_dir / 'stop.flag').exists():
        raise SystemExit('REFUSED: stop.flag absent; the runtime may be live. Stop it first.')
    path = state_dir / 'overnight_state.json'
    state = json.loads(path.read_text())
    if not state.get('finished'):
        raise SystemExit('REFUSED: the run has no FINISHED record; verify it is stopped and flat first.')
    evidence = json.loads(Path(a.fills).read_text())
    rows = [r for r in evidence['rows'] if r['coin'].startswith('pas:') and int(r['time']) >= a.since_ms]
    missing, conflicts, open_ = missing_trades(rows, recorded_tids(state, rows))
    report = dict(missing=len(missing), conflicts=len(conflicts), open=sorted(open_), trades=[])
    events = []
    for trip in missing:
        trade = dict(symbol=trip['symbol'], side=trip['side'], entry_ms=trip['entry_ms'], exit_ms=trip['exit_ms'],
                     entry=str(trip['entry']), exit=str(trip['exit']), quantity=str(trip['quantity']),
                     net=str(trip['net']), fees=str(trip['fees']), reason='BACKFILLED_FROM_EXCHANGE_FILLS',
                     fill_tids=trip['tids'], oids=trip['oids'], evidence=str(Path(a.fills).name))
        report['trades'].append(trade)
        now = datetime.now(timezone.utc)
        events.append(dict(kind='FILL_BACKFILLED', ms=int(now.timestamp() * 1000), utc=now.isoformat(),
                           symbol=trade['symbol'], side=trade['side'], net=trade['net'], fills=len(trip['tids']),
                           entry_utc=datetime.fromtimestamp(trip['entry_ms'] / 1000, timezone.utc).isoformat()))
    if a.apply and missing:
        state['trades'].extend(report['trades'])
        state.setdefault('backfills', []).append(dict(utc=datetime.now(timezone.utc).isoformat(),
                                                      evidence=str(Path(a.fills).name), trades=len(missing)))
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(path)
        with (state_dir / 'overnight_events.jsonl').open('a') as f:
            for e in events:
                f.write(json.dumps(e) + '\n')
    report['applied'] = bool(a.apply and missing)
    report['net_total'] = str(sum((D(t['net']) for t in report['trades']), D(0)))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
