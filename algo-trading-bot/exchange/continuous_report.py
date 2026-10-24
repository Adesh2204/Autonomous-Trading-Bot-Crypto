"""17:45 IST daily report for the continuous scalper: return, rank, trades, issues."""
from collections import Counter
from decimal import Decimal as D
import json

from .continuous_runtime import WATCHED_ISSUES


def period_issues(state_dir, start_ms, end_ms):
    path = state_dir / 'overnight_events.jsonl'
    counts = Counter()
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if start_ms <= r.get('ms', 0) < end_ms and r['kind'] in WATCHED_ISSUES:
                counts[r['kind'] + (':' + str(r.get('reason') or r.get('error') or '')[:60]
                                    if r['kind'] in ('HALT', 'ORDER_ERROR', 'FLATTEN_ERROR') else '')] += 1
    return counts


def write_period_report(runtime, path):
    p = runtime.period
    board = runtime.leaderboard(force=True) or {}
    me = next((t for t in board.get('teams', []) if t['name'] == 'Team Anchorium'), {})
    equity = runtime.equity()
    total = runtime.pnl_pct(equity)
    q, est, published = runtime.estimate(total)
    last = p['closed'][-1] if p['closed'] else None
    window = (last['start_ms'], last['end_ms']) if last else (p['start_ms'], runtime.clock_ms())
    trades = last['trades'] if last else []
    nets = [D(t['net']) for t in trades if t.get('net') is not None]
    issues = period_issues(runtime.state_dir, *window)
    halted = (runtime.state.get('halted') or {}).get('reason')
    lines = [
        f"Return: published R {D(str(me.get('return', 0))) * 100:+.5f}% (board {board.get('generated_at')}) | "
        f"estimate now {total:+.5f}% | last period {last['return_pct'] if last else 'n/a'}% "
        f"({(D(last['end_equity']) - D(last['start_equity'])) if last else D(0):+.2f} USDP)",
        f"Rank: published #{published} (score {me.get('score')}, Q {me.get('q')}) | estimated #{est} on live Q {q:.5f}",
        f"Targets for today (period return): #6 {runtime.targets['r6_pct']}% / #5 {runtime.targets['r5_pct']}% / "
        f"LOCK {runtime.targets['lock_pct']}%",
        f"Trades last period: {len(trades)} (long {sum(1 for t in trades if t.get('side') == 'LONG')} / short "
        f"{sum(1 for t in trades if t.get('side') == 'SHORT')}) | wins/losses {sum(1 for n in nets if n > 0)}/"
        f"{sum(1 for n in nets if n <= 0)} | net {sum(nets, D(0)):+.4f} USDP | all-time trades {len(runtime.state['trades'])}",
        f"Status: {'HALTED (needs a human): ' + halted if halted else 'running'}"
        + (' | LOCK reached last period' if last and last['locked'] else '')
        + (' | loss cap hit last period' if last and last['loss_paused'] else ''),
        "Issues last period: " + (', '.join(f'{k} x{v}' for k, v in sorted(issues.items())) or 'none'),
    ]
    finished = runtime.state.get('finished')
    if finished:
        r = (finished.get('readings') or [{}])[-1]
        lines.append(f"Final exchange check: positions = {r.get('positions')}, orders = {r.get('orders')} -> "
                     f"{'FLAT VERIFIED' if finished.get('flat') else 'NOT VERIFIED - CHECK MANUALLY'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')
    return path
