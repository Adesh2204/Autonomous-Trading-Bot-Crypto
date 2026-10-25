"""Carry basket CLI (user directive 25 Oct 2026, "YES, CARRY"): prepare | dry-run | start | supervise | status | report.

Half size: LONG BTC, ETH, HYPE, SP500 and SHORT USDJPY, $9,500 per leg at 1x, held until the
6 Nov unwind; 8% exchange stop per leg, no basket stop, -5% account catastrophe halt.

prepare   writes the mandate bound to the current source hash and release receipt
dry-run   the production runtime on an offline simulated venue fed by live public books; no key is read
start     one live owner process (testnet pas); signs only through the guarded stack
supervise restarts `start` after a crash (under caffeinate on macOS); stops on stop.flag or at the end
"""
import argparse, json, logging, shutil, signal, subprocess, sys, threading, time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
STATE = ROOT / 'runtime' / 'carry-basket'
DOCS = ROOT / 'docs' / 'carry_2026-10-25'
MANDATE = DOCS / 'mandate.json'
RELEASE = DOCS / 'regression_release' / 'test_receipt.json'
UNWIND = datetime(2026, 11, 6, 5, 30, tzinfo=timezone.utc)     # maker 2 h, then touch IOC slices
FLATTEN = datetime(2026, 11, 6, 11, 30, tzinfo=timezone.utc)   # flat-by target; taker only after it
EXPIRES = datetime(2026, 11, 6, 11, 55, tzinfo=timezone.utc)
LEG_NOTIONAL = '9500'
APPROVAL = ('User directive 2026-10-25 23:35 IST, "We wanna move with Carry Strategy" (YES, CARRY): half size, '
            '$9,500 per leg, LONG BTC/ETH/HYPE/SP500 and SHORT USDJPY at 1x, NO basket stop, existing 8% per-leg '
            'exchange stop, hold until the 6 Nov flatten; the user and co-founder accept a ~43% chance of finishing '
            'negative. Answered questions: sliced post-only children for 2 h with a 10-min re-price, then IOC '
            'children <= 25% of the touch; keep the -5% account catastrophe halt.')


def ms(dt):
    return int(dt.timestamp() * 1000)


def public_client():
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.venue_profiles import venue_profile
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    return client


def setup_logging(state, name):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
                        handlers=[logging.FileHandler(state / name), logging.StreamHandler()])


def prepare(args):
    from exchange.paper_operations import active_source_hash, atomic_json
    from exchange.carry_runtime import CARRY_BASKET, CARRY_PROFILE, CarryMandate, sha
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.testnet_certification import TEAM, API
    from exchange.venue_profiles import venue_profile
    from strategies.funding_carry import marked_equity
    client = public_client()
    account = HyperliquidAccount(client, TEAM)
    positions = {s: p for s, p in account.get_positions().items() if p.quantity}
    orders = account.get_frontend_open_orders()
    if positions or orders:
        raise SystemExit(f'Account is not flat (positions={sorted(positions)}, orders={len(orders)}); refusing to prepare.')
    leverage = {s: client.post_info('activeAssetData', user=TEAM, coin=s).get('leverage') for s, _ in CARRY_BASKET}
    not_one_x = {s: v for s, v in leverage.items() if v != dict(type='cross', value=1)}
    if not_one_x:
        # Those legs wait (no orders, no errors) and start by themselves once they read 1x CROSS.
        print(f'WARNING not 1x CROSS yet, these legs will wait: {not_one_x}. '
              'Run docs/carry_2026-10-25/"Set carry markets 1x.command" to start them.')
    equity = marked_equity(account.get_equity().collateral_balance, positions)
    m = CarryMandate(team_wallet=TEAM, api_wallet=API, markets=tuple(s for s, _ in CARRY_BASKET),
                     starts_ms=int(time.time() * 1000), flatten_ms=ms(FLATTEN), expires_ms=ms(EXPIRES),
                     starting_equity=str(equity), leg_notional=LEG_NOTIONAL, source_hash=active_source_hash(ROOT),
                     release_sha256=sha(RELEASE), venue_identity=venue_profile('pas').identity,
                     approval_reference=APPROVAL, profile=CARRY_PROFILE, sides=CARRY_BASKET,
                     unwind_starts_ms=ms(UNWIND)).require()
    atomic_json(MANDATE, asdict(m))
    print(json.dumps(dict(mandate=str(MANDATE), identity=m.identity, starting_equity=str(equity),
                          leg_notional=LEG_NOTIONAL, legs=dict(CARRY_BASKET), leverage=leverage,
                          unwind_starts=UNWIND.isoformat(), flatten=FLATTEN.isoformat()), indent=2))


def dry_run(args):
    """Production runtime and protection on the offline SimVenue, fed by live public books.

    No key is read and nothing is signed. The schedule is compressed so a short run covers the
    whole lifecycle: $1,000 legs, a 3-minute maker window, a 1-minute re-price and 10 s between
    taker children (live: $9,500, 2 h, 10 min, 30 s). Resting maker children fill only when the
    live touch trades through them or, labelled as simulated flow, half their size with a 10%
    chance per cycle. Halfway through, a stop update is made to fail with DUPLICATE_ORDER while a
    valid full-size stop rests (bug #12). At the end the run touches stop.flag.
    """
    from exchange.carry_basket import CarryBasketRuntime
    from exchange.carry_runtime import CARRY_BASKET, CARRY_PROFILE, CarryMandate
    from exchange.carry_simulation import build_simulated_runtime
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.hyperliquid_market_data import HyperliquidMarketData
    from exchange.testnet_certification import TEAM, API
    from exchange.venue_profiles import venue_profile
    state = ROOT / 'runtime' / 'carry-basket-dryrun'
    if state.exists():
        shutil.rmtree(state)
    setup_logging(state, 'dryrun.log')
    log = logging.getLogger('carry-dryrun')
    client = public_client()
    public = HyperliquidMarketData(client)
    account = HyperliquidAccount(client, TEAM)
    real = dict(positions=sorted(s for s, p in account.get_positions().items() if p.quantity),
                open_orders=len(account.get_frontend_open_orders()),
                collateral=str(account.get_equity().collateral_balance))
    log.info('DRYRUN_REAL_ACCOUNT_READ_ONLY %s', real)
    cache = {}

    def books(symbol):
        hit = cache.get(symbol)
        if hit is None or time.time() - hit[0] > 2:
            cache[symbol] = (time.time(), public.get_orderbook(symbol))
        return cache[symbol][1]
    now_ms = lambda: time.time_ns() // 1000000
    start = now_ms()
    m = CarryMandate(team_wallet=TEAM, api_wallet=API, markets=tuple(s for s, _ in CARRY_BASKET), starts_ms=start,
                     flatten_ms=ms(FLATTEN), expires_ms=ms(EXPIRES), starting_equity=real['collateral'],
                     leg_notional='1000', source_hash='0' * 64, release_sha256='0' * 64,
                     venue_identity=venue_profile('pas').identity, approval_reference='DRY RUN ONLY - NOT A LIVE MANDATE',
                     profile=CARRY_PROFILE, sides=CARRY_BASKET, unwind_starts_ms=ms(UNWIND),
                     maker_window_ms=180000, reprice_ms=60000, taker_gap_ms=10000)
    try:
        m.require()
        raise SystemExit('Dry-run mandate unexpectedly valid for live use; refusing.')
    except Exception as exc:
        log.info('DRYRUN_MANDATE_NOT_LIVE_VALID %s (by design: it can never sign)', exc)
    minutes = args.minutes
    fault_at = start + int(minutes * 60000 * 0.6)
    end_at = start + int(minutes * 60000)

    class DryRun(CarryBasketRuntime):
        HEARTBEAT_MS = 300000
        injected = False

        def cycle(self):
            venue.tick()
            super().cycle()
            now = self.clock_ms()
            if not self.injected and now >= fault_at:
                held = [s for s, (q, _) in venue.positions.items()]
                stops = [o for o in venue.orders.values() if o['isTrigger'] and o['coin'] in held]
                if stops:
                    self.injected = True
                    stop = stops[0]
                    stop['triggerPx'] = str(D(stop['triggerPx']) * D('0.999'))
                    venue.fail_next_protection = 'DUPLICATE_ORDER'
                    log.info('DRYRUN_FAULT_INJECTED stop update for %s will fail with DUPLICATE_ORDER', stop['coin'])
                    self.check_stops(force=True)
                    log.info('DRYRUN_AFTER_FAULT %s status=%s', stop['coin'], self.protection.states.get(stop['coin']))
                    self.check_stops(force=True)
                    log.info('DRYRUN_AFTER_REPAIR %s status=%s', stop['coin'], self.protection.states.get(stop['coin']))
            if now >= end_at and not self.stop_flag.exists():
                log.info('DRYRUN_TOUCH_STOP_FLAG')
                self.stop_flag.touch()

    runtime, venue = build_simulated_runtime(m, client=client, books=books, clock_ms=now_ms, state_dir=state,
                                             journal_path=state / 'sim_journal.sqlite',
                                             collateral=D(real['collateral']), maker_fill_chance=0.1,
                                             runtime_cls=DryRun)
    stop = threading.Event()
    runtime.run(stop)
    log.info('DRYRUN_COMPLETE positions=%s open_orders=%d legs=%s', {s: str(q) for s, (q, _) in venue.positions.items()},
             len(venue.orders), {s: l['mode'] for s, l in runtime.state['legs'].items()})


def start(args):
    from exchange.carry_basket import build_carry_basket_runtime
    setup_logging(STATE, 'carry.log')
    runtime = build_carry_basket_runtime(ROOT, MANDATE, RELEASE, state_dir=STATE)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    runtime.run(stop)


def supervise(args):
    setup_logging(STATE, 'supervisor.log')
    log = logging.getLogger('carry-supervisor')
    backoff = 10
    keep_awake = ['caffeinate', '-is'] if shutil.which('caffeinate') else []
    while True:
        log.info('starting carry basket runtime (reconciles with the exchange first)')
        code = subprocess.call(keep_awake + [sys.executable, __file__, 'start'], cwd=str(ROOT))
        if (STATE / 'stop.flag').exists():
            log.info('stop.flag present (code=%s); supervisor exiting', code)
            return
        if time.time() * 1000 >= ms(EXPIRES):
            log.info('mandate expired (code=%s); supervisor exiting', code)
            return
        state = json.loads((STATE / 'carry_state.json').read_text()) if (STATE / 'carry_state.json').exists() else {}
        log.warning('runtime exited code=%s halted=%s; restarting in %ss', code, state.get('halted'), backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def status(args):
    for name in ('status.json',):
        path = STATE / name
        print(f'== {name}\n' + (path.read_text() if path.exists() else 'missing'))
    events = STATE / 'carry_events.jsonl'
    if events.exists():
        print('== last events\n' + '\n'.join(events.read_text().splitlines()[-15:]))


def report(args):
    from exchange.carry_runtime import CarryMandate
    from exchange.carry_report import basket_status
    snapshot = json.loads((STATE / 'status.json').read_text())
    events = [json.loads(l) for l in (STATE / 'carry_events.jsonl').read_text().splitlines() if l.strip()]
    cutoff = time.time() * 1000 - 24 * 3600000
    print(basket_status(snapshot, CarryMandate.read(MANDATE), [e for e in events if e.get('ms', 0) >= cutoff]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare')
    d = sub.add_parser('dry-run'); d.add_argument('--minutes', type=float, default=15)
    for name in ('start', 'supervise', 'status', 'report'):
        sub.add_parser(name)
    args = parser.parse_args()
    handlers = {'prepare': prepare, 'dry-run': dry_run, 'start': start, 'supervise': supervise,
                'status': status, 'report': report}
    handlers[args.command](args)
