"""One-screen morning report for the overnight scalper."""
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import json
import urllib.request

LEADERBOARD = 'https://d23m2l9bjnbgul.cloudfront.net/public/leaderboard.json'
TEAM_NAME = 'Team Anchorium'


def official_rank():
    """Public leaderboard (score-ranked, sampled daily at 12:00 UTC); None if unavailable."""
    try:
        with urllib.request.urlopen(LEADERBOARD, timeout=15) as r:
            data = json.load(r)
        team = next(t for t in data['teams'] if t['name'] == TEAM_NAME)
        return dict(rank=team.get('rank'), teams=len(data['teams']), generated_at=data.get('generated_at'),
                    official_return_pct=team['return'] * 100)
    except Exception as exc:
        return dict(rank=None, error=type(exc).__name__)


def _lines(path):
    path = Path(path)
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def ended_by(state):
    halted = (state.get('halted') or {}).get('reason')
    if halted == 'T3_LOCK_NIGHT_WON':
        return 'T3 lock (night won)'
    if halted in {'T1_PROFIT_LOCK', 'T2_PROFIT_LOCK'}:
        return 'profit lock (' + halted + ')'
    if halted == 'LOSS_CAP':
        return 'loss cap (-2%)'
    if halted:
        return 'safety halt: ' + halted
    return '08:45 IST scheduled stop'


def write_report(state_dir, mandate, account=None, *, rank=None):
    state_dir = Path(state_dir)
    state = json.loads((state_dir / 'overnight_state.json').read_text()) if (state_dir / 'overnight_state.json').exists() else {}
    beats = _lines(state_dir / 'heartbeat.jsonl')
    start = D(mandate.starting_equity)
    equity = D(beats[-1]['equity']) if beats else start
    pnl_pct = (equity / start - 1) * 100
    rank = rank if rank is not None else official_rank()
    trades = state.get('trades', [])
    nets = [D(t['net']) for t in trades if t.get('net') is not None]
    wins, losses = [n for n in nets if n > 0], [n for n in nets if n <= 0]
    finished = state.get('finished') or {}
    readings = finished.get('readings') or []
    flat = finished.get('flat')
    rank_text = (f"#{rank['rank']} of {rank['teams']} (official score; leaderboard {rank.get('generated_at')}, "
                 f"samples daily at 12:00 UTC)") if rank.get('rank') else f"unavailable ({rank.get('error')})"
    out = [
        f"Net P&L: {pnl_pct:+.4f}% ({equity - start:+.2f} USDP) | Current rank: {rank_text}",
        f"Trades: {len(trades)} (long {sum(1 for t in trades if t.get('side', 'LONG') == 'LONG')} / "
        f"short {sum(1 for t in trades if t.get('side') == 'SHORT')}; permitted: {', '.join(mandate.directions)})",
        f"Wins/losses: {len(wins)}/{len(losses)} | Biggest win: {max(nets):+.2f} | Biggest loss: {min(nets):+.2f}"
        if nets else 'Wins/losses: 0/0 | Biggest win: none | Biggest loss: none',
        f"Night ended by: {ended_by(state)}",
        f"Targets: T1 {mandate.t1_pct}% / T2 {mandate.t2_pct}% / T3 {mandate.t3_pct}% ({mandate.target_notes})",
        f"Exchange check: positions = {readings[-1]['positions'] if readings else '?'}, "
        f"orders = {readings[-1]['orders'] if readings else '?'} -> {'FLAT VERIFIED' if flat else 'NOT VERIFIED - CHECK MANUALLY'}",
        "Restore your 23-Oct work: git switch exp/new-strategy && git stash pop   "
        "(or: git apply ~/backup-23oct-20261024-0025.patch)",
    ]
    path = state_dir / f"morning_report_{datetime.now(timezone.utc).date().isoformat()}.md"
    path.write_text('\n'.join(out) + '\n')
    return path
