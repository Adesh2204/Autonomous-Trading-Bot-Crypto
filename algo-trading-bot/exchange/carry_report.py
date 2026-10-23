"""Morning report for the carry runtime. Reads its durable files and, if given,
exchange-reported fills. Rank is not exposed by any exchange API."""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import json


def _lines(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_report(state_dir, mandate, account=None, *, since_ms=None):
    state_dir = Path(state_dir)
    beats = _lines(state_dir / 'heartbeat.jsonl')
    events = _lines(state_dir / 'carry_events.jsonl')
    state = json.loads((state_dir / 'carry_state.json').read_text()) if (state_dir / 'carry_state.json').exists() else {}
    now = datetime.now(timezone.utc)
    since_ms = since_ms or int(now.timestamp() * 1000) - 12 * 3600000
    start = D(mandate.starting_equity)
    last = beats[-1] if beats else {}
    night = [b for b in beats if datetime.fromisoformat(b['utc']).timestamp() * 1000 >= since_ms]
    equity = D(last.get('equity', start))
    night_start = D(night[0]['equity']) if night else equity
    recent = [e for e in events if e['ms'] >= since_ms]
    entries = [e for e in recent if e['kind'] == 'ENTRY_RESULT' and D(str(e.get('filled') or 0)) > 0]
    longs = sum(1 for e in recent if e['kind'] == 'ENTRY_ATTEMPT' and e.get('side') == 'LONG')
    shorts = sum(1 for e in recent if e['kind'] == 'ENTRY_ATTEMPT' and e.get('side') == 'SHORT')
    closed = []
    if account is not None:
        by_order = {}
        for f in account.get_fills(start_ms=since_ms):
            if f.symbol in mandate.markets and f.closed_pnl:
                key = (f.symbol, f.order_id)
                by_order[key] = by_order.get(key, D(0)) + f.closed_pnl - f.fee
        closed = sorted(by_order.items(), key=lambda kv: kv[1])
    wins = [v for _, v in closed if v > 0]
    halts = [e for e in recent if e['kind'] == 'HALT']
    errors = [e for e in recent if e['kind'] in {'ORDER_ERROR', 'CYCLE_ERROR', 'FLATTEN_ERROR', 'STREAM_ERROR'}]
    pnl_total = equity - start
    if state.get('halted'):
        advice = 'STOP / REVIEW: the runtime is halted (' + str(state['halted'].get('reason')) + '); it will not re-enter by itself.'
    elif errors and len(errors) > 10:
        advice = 'ADJUST: repeated errors overnight; review carry_events.jsonl before continuing.'
    elif pnl_total < -start * D('0.03'):
        advice = 'ADJUST: drawdown above 3%; consider reducing leg size before the -5% halt triggers.'
    else:
        advice = 'KEEP RUNNING: guardrails intact; carry thesis unchanged.'
    out = [
        f"Overnight net P&L: {equity - night_start:+.2f} USDP ({(equity / night_start - 1) * 100 if night_start else 0:+.3f}%) | "
        f"since start: {pnl_total:+.2f} USDP ({(equity / start - 1) * 100:+.3f}%) | rank: check the leaderboard (no exchange API exposes it)",
        '',
        f"Report time: {now.isoformat()}  Equity: {equity}  Start equity: {start}",
        f"Entries attempted overnight: {longs + shorts} (long {longs} / short {shorts}); filled: {len(entries)}",
        f"Open positions: " + (', '.join(f"{p['symbol']} {p['side']} {p['size']} @ {p['entry']} uPnL {p['upnl']}"
                                         for p in last.get('positions', [])) or 'none'),
        f"Closed legs overnight: {len(closed)}; win rate: {(len(wins) / len(closed) * 100) if closed else 0:.0f}%",
        f"Biggest win: {closed[-1][0][0]} {closed[-1][1]:+.2f}" if closed and closed[-1][1] > 0 else 'Biggest win: none',
        f"Biggest loss: {closed[0][0][0]} {closed[0][1]:+.2f}" if closed and closed[0][1] < 0 else 'Biggest loss: none',
        f"Guardrail triggers: {len(halts)}" + ''.join(f"\n  - {h.get('reason')} at {h.get('utc')}" for h in halts),
        f"Errors: {len(errors)}" + ''.join(f"\n  - {e['kind']} {e.get('error', '')} at {e.get('utc')}" for e in errors[-10:]),
        f"Protection: {last.get('protection')}",
        '',
        f"Recommendation: {advice}",
    ]
    path = state_dir / f"morning_report_{now.date().isoformat()}.md"
    path.write_text('\n'.join(out) + '\n')
    return path
