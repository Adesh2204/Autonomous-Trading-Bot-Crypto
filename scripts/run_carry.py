"""Funding-carry runtime CLI: prepare | dry-run | start | supervise | status | report.

prepare   writes the mandate bound to the current source hash and release receipt
dry-run   public data only: signals, simulated orders, simulated stops; no key is read
start     one live owner process (testnet pas); signs only through the guarded stack
supervise restarts `start` after a crash, under caffeinate; stops when the run ends
"""
import argparse, json, logging, os, signal, subprocess, sys, threading, time
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
STATE = ROOT / 'runtime' / 'carry-pas'
MANDATE = ROOT / 'docs' / 'carry_2026-10-24' / 'mandate.json'
RELEASE = ROOT / 'docs' / 'carry_2026-10-24' / 'regression_release' / 'test_receipt.json'
MARKETS = ('pas:BTC', 'pas:ETH', 'pas:HYPE', 'pas:SP500', 'pas:USDJPY')
FLATTEN = datetime(2026, 11, 6, 11, 30, tzinfo=timezone.utc)   # 30 min before scored end
EXPIRES = datetime(2026, 11, 6, 11, 55, tzinfo=timezone.utc)
APPROVAL = ('User selected Option B (full funding-carry basket, 1x, 5 legs) with the Moderate guardrail '
            'preset at the Phase 4 checkpoint on 2026-10-23: -5% account halt+flatten, -8% exchange stop '
            'per position, max 5 positions, 1x, flatten 30 min before 2026-11-06 12:00 UTC.')


def ms(dt):
    return int(dt.timestamp() * 1000)


def public_client():
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.venue_profiles import venue_profile
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    return client


def setup_logging(name):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
                        handlers=[logging.FileHandler(STATE / name), logging.StreamHandler()])


def prepare(args):
    from exchange.paper_operations import active_source_hash, atomic_json
    from exchange.carry_runtime import CarryMandate, sha
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.testnet_certification import TEAM, API
    from exchange.venue_profiles import venue_profile
    from strategies.funding_carry import marked_equity
    client = public_client()
    account = HyperliquidAccount(client, TEAM)
    positions = {s: p for s, p in account.get_positions().items() if p.quantity}
    equity = marked_equity(account.get_equity().collateral_balance, positions)
    leg = (equity * D('0.95') / 5).quantize(D('1'))
    m = CarryMandate(team_wallet=TEAM, api_wallet=API, markets=MARKETS, starts_ms=int(time.time() * 1000),
                     flatten_ms=ms(FLATTEN), expires_ms=ms(EXPIRES), starting_equity=str(equity),
                     leg_notional=str(leg), source_hash=active_source_hash(ROOT), release_sha256=sha(RELEASE),
                     venue_identity=venue_profile('pas').identity, approval_reference=APPROVAL).require()
    MANDATE.parent.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict
    atomic_json(MANDATE, asdict(m))
    print(json.dumps(dict(mandate=str(MANDATE), identity=m.identity, starting_equity=str(equity),
                          leg_notional=str(leg), open_positions=sorted(positions)), indent=2))


def dry_run(args):
    """Same decision logic on live public data; orders and stops are simulated."""
    from exchange.hyperliquid_market_data import HyperliquidMarketData
    from exchange.carry_runtime import l2_capacity
    from strategies.funding_carry import CarryParams, FundingCarry, HOUR_MS
    setup_logging('dryrun.log')
    log = logging.getLogger('carry-dryrun')
    client = public_client()
    public = HyperliquidMarketData(client)
    strategy = FundingCarry(CarryParams(markets=MARKETS))
    equity0, leg, stop_frac = D('100000'), D('19000'), D('0.08')
    sim, realized, end = {}, D(0), time.time() + args.minutes * 60
    fee = D('0.0009')

    def funding():
        out = {}
        for s in MARKETS:
            rows = client.post_info('fundingHistory', coin=s, startTime=int(time.time() * 1000) - 30 * HOUR_MS)
            out[s] = {int(r['time']) // HOUR_MS * HOUR_MS: D(r['fundingRate']) for r in rows}
        return out

    def walk(book, side, qty):
        left, cost = qty, D(0)
        for level in (book.asks if side == 'BUY' else book.bids):
            take = min(left, level.quantity)
            cost += take * level.price
            left -= take
            if not left:
                break
        return (cost / (qty - left)) if qty > left else None, qty - left

    cycle = 0
    while time.time() < end:
        now = int(time.time() * 1000)
        try:
            if cycle % 10 == 0:     # dry-run evaluates every ~5 min to show signals
                exits, entries = strategy.decide(funding(), {s: (p['qty'] if p['side'] == 'LONG' else -p['qty'])
                                                             for s, p in sim.items()}, {}, now)
                log.info('DECISION exits=%s entries=%s', [(e['symbol'], e['reason']) for e in exits],
                         [(e['symbol'], e['side'], f"{e['mean_funding']:.7f}") for e in entries])
                for e in entries:
                    if len(sim) >= 5:
                        break
                    s = e['symbol']
                    spec = client.market(s)
                    quote = public.get_quote(s)
                    book = public.get_orderbook(s)
                    side = 'BUY' if e['side'] == 'LONG' else 'SELL'
                    limit = spec.normalize_price(quote.ask * D('1.003') if side == 'BUY' else quote.bid * D('0.997'), side)
                    qty = spec.normalize_size(leg / quote.mid)
                    cap = l2_capacity(book, side, limit, D('0.25'))
                    mark_oracle = abs(quote.mark - quote.oracle) / quote.oracle * 10000
                    checks = dict(l2_capacity_ok=qty <= cap, mark_oracle_bps=f'{mark_oracle:.1f}',
                                  mark_oracle_ok=mark_oracle <= 50,
                                  limit_vs_mid_bps=f'{abs(limit - quote.mid) / quote.mid * 10000:.1f}')
                    price, filled = walk(book, side, qty)
                    if not all(v for k, v in checks.items() if k.endswith('_ok')) or price is None:
                        log.info('SIM_ENTRY_BLOCKED %s %s checks=%s', s, e['side'], checks)
                        continue
                    stop = price * (1 - stop_frac) if side == 'BUY' else price * (1 + stop_frac)
                    sim[s] = dict(side=e['side'], qty=filled, entry=price, stop=stop)
                    realized -= filled * price * fee
                    log.info('SIM_ENTRY %s %s qty=%s ~$%s fill=%s slip_vs_mid=%.1fbps stop=%s checks=%s', s, e['side'],
                             filled, (filled * price).quantize(D('1')), price,
                             float(abs(price - quote.mid) / quote.mid * 10000), spec.normalize_price(stop, side), checks)
                for e in exits:
                    p = sim.pop(e['symbol'], None)
                    if p:
                        log.info('SIM_EXIT %s %s', e['symbol'], e['reason'])
            upnl = D(0)
            for s, p in list(sim.items()):
                mark = public.get_quote(s).mark
                sign = 1 if p['side'] == 'LONG' else -1
                if (sign > 0 and mark <= p['stop']) or (sign < 0 and mark >= p['stop']):
                    realized += sign * (p['stop'] - p['entry']) * p['qty'] - p['qty'] * p['stop'] * fee
                    log.info('SIM_STOP %s at %s', s, p['stop'])
                    del sim[s]
                    continue
                upnl += sign * (mark - p['entry']) * p['qty']
            eq = equity0 + realized + upnl
            log.info('SIM_HEARTBEAT equity=%s pnl=%+.4f%% legs=%s halt=%s', eq.quantize(D('0.01')),
                     float((eq / equity0 - 1) * 100), sorted(sim), eq <= equity0 * D('0.95'))
        except Exception as exc:
            log.error('DRYRUN_ERROR %s: %s', type(exc).__name__, exc)
        cycle += 1
        time.sleep(30)
    log.info('DRYRUN_COMPLETE legs=%s', sorted(sim))


def start(args):
    from exchange.carry_runtime import build_carry_runtime
    setup_logging('carry.log')
    runtime = build_carry_runtime(ROOT, MANDATE, RELEASE, state_dir=STATE)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    runtime.run(stop)


def supervise(args):
    setup_logging('supervisor.log')
    log = logging.getLogger('carry-supervisor')
    backoff = 10
    while True:
        log.info('starting carry runtime')
        code = subprocess.call(['caffeinate', '-is', sys.executable, __file__, 'start'], cwd=str(ROOT))
        state = json.loads((STATE / 'carry_state.json').read_text()) if (STATE / 'carry_state.json').exists() else {}
        if code == 0 and time.time() * 1000 >= ms(FLATTEN):
            log.info('competition window finished; supervisor exiting')
            return
        if code == 0 and (STATE / 'stop.flag').exists():
            log.info('stop.flag present; supervisor exiting')
            return
        log.warning('runtime exited code=%s halted=%s; restarting in %ss', code, state.get('halted'), backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def status(args):
    for name in ('status.json', 'carry_state.json'):
        path = STATE / name
        print(f'== {name}\n' + (path.read_text() if path.exists() else 'missing'))
    events = STATE / 'carry_events.jsonl'
    if events.exists():
        print('== last events\n' + '\n'.join(events.read_text().splitlines()[-15:]))


def report(args):
    from exchange.carry_runtime import CarryMandate
    from exchange.carry_report import write_report
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.testnet_certification import TEAM
    path = write_report(STATE, CarryMandate.read(MANDATE), HyperliquidAccount(public_client(), TEAM))
    print(path.read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare')
    d = sub.add_parser('dry-run'); d.add_argument('--minutes', type=float, default=30)
    for name in ('start', 'supervise', 'status', 'report'):
        sub.add_parser(name)
    args = parser.parse_args()
    handlers = {'prepare': prepare, 'dry-run': dry_run, 'start': start, 'supervise': supervise,
                'status': status, 'report': report}
    handlers[args.command](args)
