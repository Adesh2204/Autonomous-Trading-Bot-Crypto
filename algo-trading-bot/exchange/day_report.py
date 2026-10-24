"""17:50 IST day-session report: one screen, return and rank first."""
from decimal import Decimal as D


def ended_by(state):
    halted = (state.get('halted') or {}).get('reason')
    if halted == 'LOSS_CAP_0_30_PCT':
        return 'loss cap (-0.30%)'
    if halted:
        return 'safety halt: ' + halted
    if (state.get('day_guard') or {}).get('locked'):
        return 'LOCK reached (paused) then 17:45 IST scheduled stop'
    return '17:45 IST scheduled stop'


def write_day_report(runtime, path):
    state = runtime.state
    equity = runtime.equity()
    ret = runtime.pnl_pct(equity)
    q, est, published = runtime.estimate(ret)
    board = runtime.leaderboard(force=True) or {}
    trades = state.get('trades', [])
    nets = [D(t['net']) for t in trades if t.get('net') is not None]
    wins = sum(1 for n in nets if n > 0)
    finished = state.get('finished') or {}
    readings = finished.get('readings') or []
    flat = finished.get('flat')
    first = state.get('first_trade_verified')
    lines = [
        f"Final return: {ret:+.5f}% (today {ret - runtime.prior_return_pct:+.5f}%, {equity - runtime.start_equity:+.2f} USDP) | "
        f"Rank: published #{published} (leaderboard {board.get('generated_at')}; it re-samples daily at 12:00 UTC = 17:30 IST) | "
        f"estimated #{est} on live Q {q:.5f}",
        f"Trades: {len(trades)} (long {sum(1 for t in trades if t.get('side') == 'LONG')} / "
        f"short {sum(1 for t in trades if t.get('side') == 'SHORT')}) | wins/losses {wins}/{len(nets) - wins}"
        + (f" | best {max(nets):+.3f} / worst {min(nets):+.3f} USDP" if nets else ''),
        f"Session ended by: {ended_by(state)}",
        f"First live entry verification: " + (
            'PASSED ' + str(first) if first else
            'FAILED -> flattened, orders cancelled, halted (' + str((state.get('halted') or {}).get('reason')) + ')'
            if str((state.get('halted') or {}).get('reason', '')).startswith('ENTRY_VERIFICATION_FAILED') else
            'no live entry occurred') + (' | manual guarded flatten completed' if finished.get('manual_flatten') else ''),
        f"Targets: R6 {runtime.targets['r6_pct']}% / R5 {runtime.targets['r5_pct']}% / LOCK {runtime.targets['lock_pct']}%",
        f"Exchange check: positions = {readings[-1]['positions'] if readings else '?'}, orders = "
        f"{readings[-1]['orders'] if readings else '?'} -> {'FLAT VERIFIED' if flat else 'NOT VERIFIED - CHECK MANUALLY'}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n')
    return path
