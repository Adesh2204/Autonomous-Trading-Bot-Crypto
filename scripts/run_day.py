"""Day-session scalper CLI: prepare | dry-run | start | supervise | status | report.

Committed limits except direction: BTC/EWY, LONG and SHORT, one position,
<= $1,000 per entry, <= 2 entries per hour, 1x, 10% of top-of-book.
"""
import argparse, json, logging, signal, subprocess, sys, threading, time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import ROUND_UP, Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
STATE = ROOT / 'runtime' / 'day-session'
DOCS = ROOT / 'docs' / 'day_2026-10-24'
MANDATE = DOCS / 'mandate.json'
TARGETS = DOCS / 'targets.json'
RELEASE = DOCS / 'regression_release' / 'test_receipt.json'
REPORT = STATE / 'report_2026-10-25.md'          # path as requested by the user
MARKETS = ('pas:BTC', 'pas:EWY')
FLATTEN = datetime(2026, 10, 24, 12, 15, tzinfo=timezone.utc)   # 17:45 IST
EXIT = datetime(2026, 10, 24, 12, 20, tzinfo=timezone.utc)      # 17:50 IST
EXPIRES = datetime(2026, 10, 24, 12, 30, tzinfo=timezone.utc)   # 18:00 IST
APPROVAL = ('User request 2026-10-24 13:00 IST: day-session scalper inside the committed limits with SHORT '
            'enabled (the only limit change): BTC/EWY, 1 position, <=$1,000 per entry, 2 entries/hour, 1x, 10% '
            'top-of-book; flat by 17:45 IST, exit 17:50 IST.')


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


def needed_total_return(target_q, days, prior_pct):
    """Smallest total R (%) whose official Q beats target_q, today's return being the only non-zero day."""
    from exchange.day_runtime import live_q
    lo, hi = D(0), D('5')
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if live_q(mid, days) > target_q else (mid, hi)
    return hi


def up(value):
    """Targets are thresholds to clear: round up, never down."""
    return str(value.quantize(D('0.0001'), rounding=ROUND_UP))


def targets():
    from exchange.day_runtime import fetch_leaderboard
    data = fetch_leaderboard()
    ranked = {t['rank']: t for t in data['teams'] if t.get('rank')}
    me = next(t for t in data['teams'] if t['name'] == 'Team Anchorium')
    start = datetime.fromisoformat(data['from'].replace('Z', '+00:00')).timestamp()
    days = int((time.time() - start) // 86400) + 1     # daily returns after today's 12:00 UTC sample
    prior = D(str(me['return'])) * 100
    q5, q6 = D(str(ranked[5]['q'])), D(str(ranked[6]['q']))
    r6, r5 = needed_total_return(q6, days, prior), needed_total_return(q5, days, prior)
    # Buffer: (a) one round trip at the $1,000 cap (0.18% fees + ~10 bps slippage = $2.80 = 0.0028%),
    # (b) #5 also re-samples today; require beating a #5 whose Q improves by 2%.
    r5_up = needed_total_return(q5 * D('1.02'), days, prior)
    lock = max(r5 + D('0.0028'), r5_up)
    rows = {k: dict(name=ranked[k]['name'], return_pct=f"{ranked[k]['return'] * 100:+.5f}",
                    q=f"{ranked[k]['q']:.5f}", score=f"{ranked[k]['score']:.5f}") for k in (4, 5, 6, 7)}
    return dict(generated_at=data['generated_at'], days=days, prior_return_pct=f'{prior:.6f}',
                my_rank=me.get('rank'), my_q=f"{me['q']:.5f}", my_score=f"{me['score']:.5f}",
                r6_pct=up(r6), r5_pct=up(r5), r5_if_q_up_2pct=up(r5_up), lock_pct=up(lock),
                ranks=rows, formula='Q = (max(R,0)+0.005)/(|R| + 1.5*sigma + 0.05); score = 0.8*Q + 0.2*J; '
                'sigma = sample stdev of daily returns * sqrt(n); daily sample 12:00 UTC (+240 s)')


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
    t = targets()
    notes = (f"t1=R6 {t['r6_pct']}%, t2=R5 {t['r5_pct']}%, t3=LOCK {t['lock_pct']}% (official score, "
             f"leaderboard {t['generated_at']}, me #{t['my_rank']}, prior R {t['prior_return_pct']}%)")
    m = OvernightMandate(team_wallet=TEAM, api_wallet=API, markets=MARKETS, directions=('LONG', 'SHORT'),
                         starts_ms=int(time.time() * 1000), flatten_ms=ms(FLATTEN), exit_ms=ms(EXIT),
                         expires_ms=ms(EXPIRES), starting_equity=str(equity), source_hash=active_source_hash(ROOT),
                         release_sha256=sha(RELEASE), venue_identity=venue_profile('pas').identity,
                         approval_reference=APPROVAL, t1_pct=t['r6_pct'], t2_pct=t['r5_pct'], t3_pct=t['lock_pct'],
                         target_notes=notes, loss_cap_pct='-0.30').require()
    DOCS.mkdir(parents=True, exist_ok=True)
    atomic_json(MANDATE, asdict(m))
    atomic_json(TARGETS, t)
    print(json.dumps(dict(mandate=str(MANDATE), identity=m.identity, starting_equity=str(equity),
                          open_positions=sorted(positions), **t), indent=2))


def dry_run(args):
    """Live public data: closed-bar scans in both directions plus a replay of recent bars."""
    from exchange.hyperliquid_market_data import HyperliquidMarketData
    from exchange.overnight_runtime import to_bars
    from strategies.momentum_scalper import ScalpParams, guaranteed, levels, setup, size, trend
    setup_logging('dryrun.log')
    log = logging.getLogger('day-dryrun')
    client = public_client()
    md = HyperliquidMarketData(client)
    p = ScalpParams(markets=MARKETS, directions=('LONG', 'SHORT'))
    try:
        t = targets()
        log.info('TARGETS R6=%s%% R5=%s%% LOCK=%s%% | %s', t['r6_pct'], t['r5_pct'], t['lock_pct'], t['formula'])
    except Exception as exc:
        log.warning('TARGETS unavailable: %s', exc)

    def bars(symbol, interval, count, end=None):
        step = {'5m': 300000, '15m': 900000}[interval]
        now = int(time.time() * 1000)
        e = (end or now) // step * step - 1
        return to_bars(md.get_candles(symbol, e + 1 - count * step, e, interval=interval, now_ms=now))

    def order(symbol, d):
        q, spec = md.get_quote(symbol), client.market(symbol)
        ref, top = (q.ask, q.ask_quantity) if d['side'] == 'LONG' else (q.bid, q.bid_quantity)
        stop, target = levels(ref, d['atr'], d['side'], p)
        qty = spec.normalize_size(size(equity=D(100000), risk_fraction=p.risk_fraction, stop_distance=abs(ref - stop),
                                       price=ref, max_notional=D(1000), top_quantity=top, participation=D('0.1')))
        close = 'SELL' if d['side'] == 'LONG' else 'BUY'
        return (f"{'BUY' if d['side'] == 'LONG' else 'SELL'} IOC {qty} @ {ref} (~${qty * ref:.2f}) | exchange SL "
                f"{spec.normalize_price(stop, close)} | TP {spec.normalize_price(target, close)} | reduce-only exits {close}")

    # Replay: every closed 5m bar of the last ~2h, evaluated with only the data available at that bar.
    for symbol in MARKETS:
        b5, b15 = bars(symbol, '5m', 64), bars(symbol, '15m', 80)
        for i in range(40, len(b5)):
            cut = b5[i]['t'] + 300000
            d = setup(b5[:i + 1], [b for b in b15 if b['t'] + 900000 <= cut], p)
            if d and d['side']:
                log.info('REPLAY_SIGNAL %s %s at %s reason=%s atr=%.5f', symbol, d['side'],
                         datetime.fromtimestamp(b5[i]['t'] / 1000, timezone.utc).strftime('%H:%M UTC'),
                         d['reason'], d['atr'])
    end = time.time() + args.minutes * 60
    decided = None
    while time.time() < end:
        now = int(time.time() * 1000)
        close = now // 300000 * 300000
        try:
            if decided != close and (decided is None or 5000 <= now - close <= 40000):
                decided = close
                for symbol in MARKETS:
                    b5, b15 = bars(symbol, '5m', 40), bars(symbol, '15m', 60)
                    fresh = bool(b5) and b5[-1]['t'] == close - 300000
                    d = setup(b5, b15, p) if fresh else None
                    log.info('SCAN %s trend15m=%s fresh_bar=%s signal=%s', symbol, trend(b15, p), fresh, d)
                    if d and d['side']:
                        log.info('SIM_ORDER %s %s', symbol, order(symbol, d))
                    g = guaranteed(b5, b15, p)
                    if g and g['side']:
                        log.info('GUARANTEE_WOULD_BE %s %s half-size: %s', symbol, g['side'], order(symbol, g))
        except Exception as exc:
            log.error('DRYRUN_ERROR %s: %s', type(exc).__name__, exc)
        time.sleep(10)
    log.info('DRYRUN_COMPLETE')


def start(args):
    from exchange.overnight_runtime import build_overnight_runtime
    from exchange.day_runtime import DayRuntime
    setup_logging('day.log')
    runtime = build_overnight_runtime(ROOT, MANDATE, RELEASE, state_dir=STATE, runtime_cls=DayRuntime,
                                      targets=json.loads(TARGETS.read_text()), report_path=REPORT)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    sys.exit(0 if runtime.run(stop) else 3)


def supervise(args):
    setup_logging('supervisor.log')
    log = logging.getLogger('day-supervisor')
    backoff = 10
    while True:
        log.info('starting day-session runtime')
        code = subprocess.call(['caffeinate', '-is', sys.executable, __file__, 'start'], cwd=str(ROOT))
        state = json.loads((STATE / 'overnight_state.json').read_text()) if (STATE / 'overnight_state.json').exists() else {}
        if state.get('finished') or time.time() * 1000 >= ms(FLATTEN) or (STATE / 'stop.flag').exists():
            log.info('run finished, past 17:45 IST, or stop.flag present (code=%s); supervisor exits, no restart', code)
            return
        log.warning('runtime exited code=%s before 17:45 IST; restarting in %ss (reconciles first)', code, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 120)


def status(args):
    for name in ('status.json',):
        path = STATE / name
        print(f'== {name}\n' + (path.read_text() if path.exists() else 'missing'))
    beats = STATE / 'day_heartbeat.jsonl'
    if beats.exists():
        print('== last day heartbeat\n' + beats.read_text().splitlines()[-1])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare')
    d = sub.add_parser('dry-run'); d.add_argument('--minutes', type=float, default=5)
    for name in ('start', 'supervise', 'status'):
        sub.add_parser(name)
    args = parser.parse_args()
    {'prepare': prepare, 'dry-run': dry_run, 'start': start, 'supervise': supervise, 'status': status}[args.command](args)
