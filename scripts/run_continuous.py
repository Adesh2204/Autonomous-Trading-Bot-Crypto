"""Continuous scalper CLI to the end of the scored window: prepare | start | supervise | status.

Committed limits; HYPE added 25 Oct: BTC/EWY/HYPE, LONG and SHORT, one position, <= $1,000 per
entry, <= 2 entries per hour, 1x, 10% of top-of-book, 0.4% risk per trade.
LOCK and a -0.30% period loss cap pause until after the next 12:00 UTC sample.
"""
import argparse, json, logging, signal, subprocess, sys, threading, time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
STATE = ROOT / 'runtime' / 'continuous'
DOCS = ROOT / 'docs' / 'continuous_2026-10-24'
MANDATE = DOCS / 'mandate.json'
TARGETS = DOCS / 'targets.json'
RELEASE = DOCS / 'regression_release' / 'test_receipt.json'
MARKETS = ('pas:BTC', 'pas:EWY', 'pas:HYPE')
FLATTEN = datetime(2026, 11, 6, 11, 30, tzinfo=timezone.utc)    # before the final 12:00 UTC sample
EXIT = datetime(2026, 11, 6, 11, 40, tzinfo=timezone.utc)
EXPIRES = datetime(2026, 11, 6, 11, 55, tzinfo=timezone.utc)
APPROVAL = ('User approval 2026-10-24 16:24 IST (mission step 4, recommendation kept): continuous momentum scalper '
            'to 2026-11-06 inside the committed limits: BTC/EWY, LONG+SHORT, 1 position, <=$1,000 per entry, '
            '2 entries/hour, 1x, 10% top-of-book, 0.4% risk; LOCK and -0.30% period loss cap pause until after '
            'the next 12:00 UTC sample; 3 consecutive order errors halt. User approval 2026-10-25 01:05 IST: add pas:HYPE '
            '(1x cross) as a third market; every other limit unchanged.')


def ms(dt):
    return int(dt.timestamp() * 1000)


def setup_logging(name):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
                        handlers=[logging.FileHandler(STATE / name), logging.StreamHandler()])


def prepare(args):
    from exchange.paper_operations import active_source_hash, atomic_json
    from exchange.overnight_runtime import OvernightMandate
    from exchange.carry_runtime import sha
    from exchange.continuous_runtime import compute_targets, seed_history
    from exchange.day_runtime import fetch_leaderboard
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.testnet_certification import TEAM, API
    from exchange.venue_profiles import venue_profile
    from strategies.funding_carry import marked_equity
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    positions = {s: p for s, p in account.get_positions().items() if p.quantity}
    equity = marked_equity(account.get_equity().collateral_balance, positions)
    board = fetch_leaderboard()
    history = seed_history(board)
    t = compute_targets(board, history)
    # The mandate requires 0 < t1 < t2 < t3; the runtime uses the live targets.
    step = D('0.0001')
    t1 = max(D(t['r6_pct']), step)
    t2 = max(D(t['r5_pct']), t1 + step)
    t3 = max(D(t['lock_pct']), t2 + step)
    notes = (f"t1=R6 {t['r6_pct']}%, t2=R5 {t['r5_pct']}%, t3=LOCK {t['lock_pct']}% of period return (official score, "
             f"leaderboard {t['generated_at']}, published #{t['published_rank']}); recomputed after every sample")
    m = OvernightMandate(team_wallet=TEAM, api_wallet=API, markets=MARKETS, directions=('LONG', 'SHORT'),
                         starts_ms=int(time.time() * 1000), flatten_ms=ms(FLATTEN), exit_ms=ms(EXIT),
                         expires_ms=ms(EXPIRES), starting_equity=str(equity), source_hash=active_source_hash(ROOT),
                         release_sha256=sha(RELEASE), venue_identity=venue_profile('pas').identity,
                         approval_reference=APPROVAL, t1_pct=str(t1), t2_pct=str(t2), t3_pct=str(t3),
                         target_notes=notes, loss_cap_pct='-0.30').require()
    targets = dict(t, history=history, days=len(history) + 1, prior_return_pct=t['published_return_pct'])
    DOCS.mkdir(parents=True, exist_ok=True)
    atomic_json(MANDATE, asdict(m))
    atomic_json(TARGETS, targets)
    print(json.dumps(dict(mandate=str(MANDATE), identity=m.identity, starting_equity=str(equity),
                          open_positions=sorted(positions), **targets), indent=2, default=str))


def start(args):
    from exchange.overnight_runtime import build_overnight_runtime
    from exchange.continuous_runtime import ContinuousRuntime
    setup_logging('continuous.log')
    targets = json.loads(TARGETS.read_text())
    runtime = build_overnight_runtime(ROOT, MANDATE, RELEASE, state_dir=STATE, runtime_cls=ContinuousRuntime,
                                      targets=targets, report_path=STATE, history=targets['history'])
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    sys.exit(0 if runtime.run(stop) else 3)


def supervise(args):
    setup_logging('supervisor.log')
    log = logging.getLogger('continuous-supervisor')
    backoff = 10
    while True:
        log.info('starting continuous runtime (reconciles with the exchange first)')
        started = time.time()
        code = subprocess.call(['caffeinate', '-is', sys.executable, __file__, 'start'], cwd=str(ROOT))
        state = json.loads((STATE / 'overnight_state.json').read_text()) if (STATE / 'overnight_state.json').exists() else {}
        if state.get('finished') or time.time() * 1000 >= ms(FLATTEN) or (STATE / 'stop.flag').exists():
            log.info('run finished, past the final flatten, or stop.flag present (code=%s); no restart', code)
            return
        if time.time() - started > 600:
            backoff = 10
        log.warning('runtime exited code=%s; restarting in %ss', code, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def status(args):
    path = STATE / 'status.json'
    print('== status.json\n' + (path.read_text() if path.exists() else 'missing'))
    reports = sorted(STATE.glob('report_*.md'))
    if reports:
        print(f'== {reports[-1].name}\n' + reports[-1].read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'start', 'supervise', 'status'):
        sub.add_parser(name)
    args = parser.parse_args()
    {'prepare': prepare, 'start': start, 'supervise': supervise, 'status': status}[args.command](args)
