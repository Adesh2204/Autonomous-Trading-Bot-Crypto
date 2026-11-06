"""Overnight scalper CLI: prepare | dry-run | start | supervise | status | report.

prepare   targets from the public leaderboard; mandate bound to source + receipt
dry-run   public data only: signals and simulated orders; no key is read
start     one live owner process (testnet pas) inside the committed limits
supervise restarts `start` after a crash until 08:45 IST; never after the run ends
"""
import argparse, json, logging, signal, subprocess, sys, threading, time, urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
STATE = ROOT / 'runtime' / 'overnight-pas'
MANDATE = ROOT / 'docs' / 'overnight_2026-10-24' / 'mandate.json'
RELEASE = ROOT / 'docs' / 'overnight_2026-10-24' / 'regression_release' / 'test_receipt.json'
MARKETS = ('pas:BTC', 'pas:EWY')
FLATTEN = datetime(2026, 10, 24, 3, 15, tzinfo=timezone.utc)   # 08:45 IST
EXIT = datetime(2026, 10, 24, 3, 20, tzinfo=timezone.utc)      # 08:50 IST
EXPIRES = datetime(2026, 10, 24, 3, 30, tzinfo=timezone.utc)   # 09:00 IST
LEADERBOARD = 'https://d23m2l9bjnbgul.cloudfront.net/public/leaderboard.json'
APPROVAL = ('User request 2026-10-24 00:25 IST: overnight momentum scalper inside the committed limits '
            '(BTC/EWY, LONG-only, 1 position, <=$1,000 per entry, 2 entries/hour, 1x), exchange SL+TP, '
            'flat by 08:45 IST, exit 08:50 IST.')


def ms(dt):
    return int(dt.timestamp() * 1000)


def setup_logging(name):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
                        handlers=[logging.FileHandler(STATE / name), logging.StreamHandler()])


def public_client():
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.venue_profiles import venue_profile
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    return client


def needed_return(target_q, days):
    """Smallest R whose official Q beats target_q, if tonight's R is one daily return."""
    from strategies.momentum_scalper import official_q
    import statistics
    lo, hi = D(0), D('0.05')
    for _ in range(60):
        mid = (lo + hi) / 2
        returns = [0.0] * (days - 1) + [float(mid)]
        sigma = D(str(statistics.stdev(returns) * days ** 0.5)) if days > 1 else D(0)
        lo, hi = (lo, mid) if official_q(mid, sigma) > target_q else (mid, hi)
    return hi * 100


def targets():
    with urllib.request.urlopen(LEADERBOARD, timeout=15) as r:
        data = json.load(r)
    teams = {t['rank']: t for t in data['teams'] if t.get('rank')}
    me = next(t for t in data['teams'] if t['name'] == 'Team Anchorium')
    days = max(2, int((time.time() - datetime.fromisoformat(data['from'].replace('Z', '+00:00')).timestamp()) // 86400) + 1)
    need6, need5 = needed_return(D(str(teams[6]['q'])), days), needed_return(D(str(teams[5]['q'])), days)
    t1 = D('0.3')
    t2 = max(D('0.5'), need6)
    t3 = max(need5, t2 + D('0.1'))
    notes = (f"leaderboard {data['generated_at']}: me #{me['rank']} R={me['return']*100:+.4f}%; "
             f"#3 {teams[3]['name']} R={teams[3]['return']*100:+.4f}%; #5 {teams[5]['name']} R={teams[5]['return']*100:+.4f}%; "
             f"#6 {teams[6]['name']} R={teams[6]['return']*100:+.4f}%. Official score Q needs ~{need6:.4f}% for #6 and "
             f"~{need5:.4f}% for #5; T2 uses the 0.5% minimum, T3 kept above T2.")
    return t1, t2, t3, notes


def prepare(args):
    from exchange.paper_operations import active_source_hash, atomic_json
    from exchange.overnight_runtime import OvernightMandate
    from exchange.carry_runtime import sha
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.testnet_certification import TEAM, API
    from exchange.venue_profiles import venue_profile
    from strategies.funding_carry import marked_equity
    account = HyperliquidAccount(public_client(), TEAM)
    positions = {s: p for s, p in account.get_positions().items() if p.quantity}
    equity = marked_equity(account.get_equity().collateral_balance, positions)
    t1, t2, t3, notes = targets()
    m = OvernightMandate(team_wallet=TEAM, api_wallet=API, markets=MARKETS, starts_ms=int(time.time() * 1000),
                         flatten_ms=ms(FLATTEN), exit_ms=ms(EXIT), expires_ms=ms(EXPIRES), starting_equity=str(equity),
                         source_hash=active_source_hash(ROOT), release_sha256=sha(RELEASE),
                         venue_identity=venue_profile('pas').identity, approval_reference=APPROVAL,
                         t1_pct=f'{t1:.4f}', t2_pct=f'{t2:.4f}', t3_pct=f'{t3:.4f}', target_notes=notes).require()
    MANDATE.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(MANDATE, asdict(m))
    print(json.dumps(dict(mandate=str(MANDATE), identity=m.identity, starting_equity=str(equity),
                          T1=m.t1_pct, T2=m.t2_pct, T3=m.t3_pct, notes=notes, open_positions=sorted(positions)), indent=2))


def dry_run(args):
    """Same signal code on live public data; entries, SL/TP and exits are simulated."""
    from exchange.hyperliquid_market_data import HyperliquidMarketData
    from exchange.overnight_runtime import to_bars
    from strategies.momentum_scalper import ScalpParams, guaranteed, levels, setup, size, trend
    setup_logging('dryrun.log')
    log = logging.getLogger('overnight-dryrun')
    client = public_client()
    md = HyperliquidMarketData(client)
    p = ScalpParams(markets=MARKETS)
    sim, done, end, decided = None, [], time.time() + args.minutes * 60, None
    started = time.time()
    try:
        t1, t2, t3, notes = targets()
        log.info('TARGETS T1=%.4f%% T2=%.4f%% T3=%.4f%% | %s', t1, t2, t3, notes)
    except Exception as exc:
        log.warning('TARGETS unavailable: %s', exc)

    def bars(symbol, interval, count):
        step = {'5m': 300000, '15m': 900000}[interval]
        now = int(time.time() * 1000)
        e = now // step * step - 1
        return to_bars(md.get_candles(symbol, e + 1 - count * step, e, interval=interval, now_ms=now))

    while time.time() < end:
        now = int(time.time() * 1000)
        bar_close = now // 300000 * 300000
        try:
            if sim:
                q = md.get_quote(sim['symbol'])
                why = ('STOP' if q.bid <= sim['stop'] else 'TAKE_PROFIT' if q.bid >= sim['target'] else
                       'TIME_STOP' if p.time_stop_ms is not None and now - sim['ms'] >= p.time_stop_ms else None)
                if why:
                    px = sim['stop'] if why == 'STOP' else sim['target'] if why == 'TAKE_PROFIT' else q.bid
                    net = (px - sim['entry']) * sim['qty'] - (px + sim['entry']) * sim['qty'] * D('0.0009')
                    done.append(net)
                    log.info('SIM_EXIT %s %s at %s net=%+.4f', sim['symbol'], why, px, net)
                    sim = None
            first = decided is None
            if (first or 5000 <= now - bar_close <= 100000) and decided != bar_close:
                decided = bar_close
                for symbol in MARKETS:
                    b5, b15 = bars(symbol, '5m', 40), bars(symbol, '15m', 60)
                    d = setup(b5, b15, p)
                    log.info('SCAN %s trend15m=%s last5m_close=%s prior6_high=%s signal=%s', symbol, trend(b15, p),
                             b5[-1]['c'], max(b['h'] for b in b5[-7:-1]), d)
                    if d and d['side'] == 'LONG' and sim is None:
                        q, spec = md.get_quote(symbol), client.market(symbol)
                        stop, target = levels(q.ask, d['atr'], 'LONG', p)
                        qty = spec.normalize_size(size(equity=D(100000), risk_fraction=p.risk_fraction,
                            stop_distance=q.ask - stop, price=q.ask, max_notional=D(1000),
                            top_quantity=q.ask_quantity, participation=D('0.1')))
                        sim = dict(symbol=symbol, entry=q.ask, qty=qty, stop=stop, target=target, ms=now)
                        log.info('SIM_ENTRY %s LONG qty=%s ~$%.0f @ask=%s SL=%s TP=%s slip_vs_mid=%.1fbps', symbol, qty,
                                 qty * q.ask, q.ask, spec.normalize_price(stop, 'SELL'), spec.normalize_price(target, 'SELL'),
                                 (q.ask - q.mid) / q.mid * 10000)
                if sim is None and time.time() - started >= 45 * 60:
                    g = guaranteed(bars('pas:BTC', '5m', 40), bars('pas:BTC', '15m', 60), p)
                    log.info('TRADE_GUARANTEE_CHECK %s', g)
        except Exception as exc:
            log.error('DRYRUN_ERROR %s: %s', type(exc).__name__, exc)
        time.sleep(15)
    log.info('DRYRUN_COMPLETE open=%s closed=%d net=%s', sim and sim['symbol'], len(done), sum(done, D(0)))


def start(args):
    from exchange.overnight_runtime import build_overnight_runtime
    setup_logging('overnight.log')
    runtime = build_overnight_runtime(ROOT, MANDATE, RELEASE, state_dir=STATE)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    flat = runtime.run(stop)
    sys.exit(0 if flat else 3)


def supervise(args):
    setup_logging('supervisor.log')
    log = logging.getLogger('overnight-supervisor')
    backoff = 10
    while True:
        log.info('starting overnight runtime')
        code = subprocess.call(['caffeinate', '-is', sys.executable, __file__, 'start'], cwd=str(ROOT))
        state = json.loads((STATE / 'overnight_state.json').read_text()) if (STATE / 'overnight_state.json').exists() else {}
        if state.get('finished') or time.time() * 1000 >= ms(FLATTEN) or (STATE / 'stop.flag').exists():
            log.info('run finished, past 08:45 IST, or stop.flag present (code=%s); supervisor exits, no restart', code)
            return
        log.warning('runtime exited code=%s before 08:45 IST; restarting in %ss (reconciles first)', code, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 120)


def status(args):
    for name in ('status.json', 'overnight_state.json'):
        path = STATE / name
        print(f'== {name}\n' + (path.read_text() if path.exists() else 'missing'))


def report(args):
    from exchange.overnight_runtime import OvernightMandate
    from exchange.overnight_report import write_report
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.testnet_certification import TEAM
    print(write_report(STATE, OvernightMandate.read(MANDATE), HyperliquidAccount(public_client(), TEAM)).read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare')
    d = sub.add_parser('dry-run'); d.add_argument('--minutes', type=float, default=10)
    for name in ('start', 'supervise', 'status', 'report'):
        sub.add_parser(name)
    args = parser.parse_args()
    {'prepare': prepare, 'dry-run': dry_run, 'start': start, 'supervise': supervise,
     'status': status, 'report': report}[args.command](args)
