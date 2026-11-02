"""Carry basket CLI (user directive 25 Oct 2026, "YES, CARRY"): prepare | dry-run | start | supervise | status | report.

Full size (26 Oct): LONG BTC, ETH, HYPE, SP500 and SHORT USDJPY, $19,000 per leg at 1x, held until the
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
# Full size needs ~760 touch-limited slices at ~1/min: maker 2 h, then ~13 h of IOC slices before 11:30.
UNWIND = datetime(2026, 11, 5, 20, 0, tzinfo=timezone.utc)
FLATTEN = datetime(2026, 11, 6, 11, 30, tzinfo=timezone.utc)   # flat-by target; taker only after it
EXPIRES = datetime(2026, 11, 6, 11, 55, tzinfo=timezone.utc)
LEG_NOTIONAL = '19000'
# 26 Oct 22:35 IST (user): HYPE is the priority leg; the rest follow their 24 h funding; total $95k at 1x.
# 27 Oct 01:35 IST (user, after the 2x route turned out to need a flat account): more HYPE within 1x.
# $95k: HYPE $50k, SP500 $15k, BTC $13k, ETH $12k, USDJPY $5k. Over-target legs are trimmed first.
LEG_NOTIONALS = (('pas:BTC', '13000'), ('pas:ETH', '12000'), ('pas:HYPE', '50000'), ('pas:SP500', '15000'),
                 ('pas:USDJPY', '5000'))
# 27 Oct 09:05 IST (user: "don't sell or trim HYPE, leverage at 2x, give more to the other markets"): HYPE is
# held exactly as it is; the five markets move to a 2x cross SETTING through raise_carry_leverage_2x.py and the
# basket grows to 1.5x the starting equity. USDJPY stays $5k; SP500, BTC and ETH share the rest equally.
LEVERAGE = 2
EXPOSURE = D('1.5')
HOLD_LEGS = ('pas:HYPE',)
FIXED_LEGS = (('pas:USDJPY', '5000'),)
EQUAL_LEGS = ('pas:BTC', 'pas:ETH', 'pas:SP500')
# 29 Oct 13:45 IST (user: "start buying with the remaining balance... most into HYPE, then SP500, then BTC, then
# ETH and then others"): HYPE is no longer a hold leg. Every leg keeps what it holds and the room up to 1.85x the
# starting equity is shared 5:4:3:2:1 in that order, so every target is above the size held (no sale or trim).
RANKED_EXPOSURE = D('1.85')
RANKED_SHARES = (('pas:HYPE', 5), ('pas:SP500', 4), ('pas:BTC', 3), ('pas:ETH', 2), ('pas:USDJPY', 1))
 # 31 Oct 22:40 IST (user: "square off USDJPY and S&P500 ... put all the balance into HYPE ... reduce the leverage
# from 2x to 1.5x"; answered question "1.5x, HYPE gets part"): SP500 and USDJPY are sold to flat with reduce-only
# IOC children, BTC and ETH are held exactly as they are, and HYPE gets the room up to 1.5x the CURRENT equity.
# The exchange setting stays 2x (whole numbers only); 1.5x is the exposure.
CLOSE_EXPOSURE = D('1.5')
CLOSE_LEGS = ('pas:SP500', 'pas:USDJPY')
CLOSE_HOLD_LEGS = ('pas:BTC', 'pas:ETH')
CLOSE_GROW_LEG = 'pas:HYPE'
# 1 Nov 12:05 IST (user: "invest the remaining total balance of 26k dollars strictly all into HYPE making sure the
# leverage still stays 1.5x"; the basket was already at 1.5x, answered question "keep 1.5x: move BTC/ETH into
# HYPE"): $26,000 of BTC and ETH, in proportion to their marked values, is trimmed with reduce-only IOC children
# and HYPE is bought with exactly what was trimmed, never above 1.5x the current equity.
# 1 Nov 22:30 IST (user: "trim some more of the btc and eth ... atleast 10k dollars ... put it into hype ... leverage
# til 1.5x only ... volatility does not increase much"): a further $10,000 is moved the same way. The kept BTC/ETH
# budgets now round DOWN to $100, so at least $10,000 is trimmed (at most $10,200); the smallest move that meets the
# instruction keeps the volatility increase as small as possible.
MOVE_AMOUNT = D('10000')
MOVE_FROM_LEGS = ('pas:BTC', 'pas:ETH')
# 1 Nov 23:10 IST (user: "Ok increase the leverage for 1.85x"; answered question "$185k: bot's 1.85x cap"): exposure
# rises to 1.85x the STARTING equity (the existing CARRY_MAX_EXPOSURE_2X cap, about 1.75x the current equity), so the
# free margin at the 2x setting stays above the loss that trips the -5% halt. BTC and ETH are held exactly as they
# are; HYPE alone gets the room, bought with touch-limited IOC children and never sold or trimmed.
RAISE_EXPOSURE = D('1.85')
# 2 Nov 11:40 IST (user, strict: "make the leverage 2x strictly from 1.85x to 2x, these are my strict instructions
# for all three positions"): exposure rises to 2x the STARTING equity, the same base as the 1.85x. BTC, ETH and HYPE
# are all scaled up by the same factor (each keeps its share of the basket), bought with touch-limited IOC children;
# nothing is sold or trimmed. 2x the current equity would need every dollar of free margin at the 2x setting.
SCALE_EXPOSURE = D('2')
SCALE_LEGS = ('pas:BTC', 'pas:ETH', 'pas:HYPE')
# 2 Nov 20:50 IST (user, strict: "trim about 40-50k from HYPE now and put that money into the markets ... which is
# going to be profitable by tommorow ... keep the levarge same"): $50,000 of HYPE (never more) is trimmed with
# reduce-only IOC children and SP500 is bought LONG with what was trimmed. Of the ten pas markets SP500 alone paid
# longs funding over both 24 h and 7 d, it is about 6x less volatile than HYPE and is already at the 2x setting.
# BTC and ETH are held exactly as they are, USDJPY stays closed and the exposure stays at most 2x the starting equity.
SHIFT_AMOUNT = D('50000')
SHIFT_MIN_BUY = D('40000')       # the low end of the instruction: refuse if the 2x cap would leave SP500 less
SHIFT_FROM_LEG = 'pas:HYPE'
SHIFT_TO_LEG = 'pas:SP500'
SHIFT_HOLD_LEGS = ('pas:BTC', 'pas:ETH')
SHIFT_CLOSE_LEGS = ('pas:USDJPY',)
TAKER_DEPTH_BPS = 5              # IOC children: up to 25% of the depth within 5 bps of the touch
APPROVAL = ('User directive 2026-10-25 23:35 IST, "We wanna move with Carry Strategy" (YES, CARRY): half size, '
            '$9,500 per leg, LONG BTC/ETH/HYPE/SP500 and SHORT USDJPY at 1x, NO basket stop, existing 8% per-leg '
            'exchange stop, hold until the 6 Nov flatten; the user and co-founder accept a ~43% chance of finishing '
            'negative. Answered questions: sliced post-only children for 2 h with a 10-min re-price, then IOC '
            'children <= 25% of the touch; keep the -5% account catastrophe halt. 26 Oct 11:55 IST the user chose '
            'FULL SIZE, $19,000 per leg ("trade with big money"), after the model numbers: median +0.91%, P(loss) '
            '~43%, 5th percentile about -4.2%. 26 Oct 22:35 IST the user made HYPE the priority leg ($35k; '
            'BTC $18k, ETH $17k, SP500 $20k, USDJPY $5k by funding; total $95k at 1x) and allowed IOC '
            'children of up to 25% of the depth within 5 bps of the touch. 27 Oct 01:05 IST the user asked for more '
            'risk, HYPE heavy: 2x cross setting, exposure 1.5x equity ($142.5k: HYPE $60k, SP500 $30k, BTC $25k, ETH '
            '$22.5k, USDJPY $5k), after the model numbers (P(profit) 44%, P(#1) 34%, -5% halt hit in ~46% of paths); '
            'the -5% account halt and 8% leg stops are kept. The 2x route needs a flat account; 27 Oct 01:35 IST the user '
            'chose instead more HYPE within 1x: HYPE $50k, SP500 $15k, BTC $13k, ETH $12k, USDJPY $5k, trimming '
            'over-target legs first. 27 Oct 09:05 IST the user chose to keep HYPE exactly as held (no sale, trim or '
            'top-up), approved raising the five markets to a 2x cross setting while the basket is open (a raise-only '
            'route; leverage is never lowered and no order is placed by it), and chose 1.5x exposure: USDJPY $5k, '
            'SP500/BTC/ETH sharing the rest equally. 29 Oct 13:45 IST the user ordered the remaining balance into the '
            'basket ("start buying with that as well"): most into HYPE, then SP500, then BTC, then ETH, then the '
            'others; exposure 1.85x the starting equity, HYPE no longer held as is, the room above each leg\'s held '
            'value shared 5:4:3:2:1 in that order; nothing is sold or trimmed; the -5% halt and 8% leg stops are kept. '
            '31 Oct 22:40 IST the user ordered SP500 and USDJPY squared off and the balance put into HYPE with the '
            'leverage reduced from 2x to 1.5x; answered question: total exposure 1.5x the current equity, BTC and ETH '
            'held as they are, HYPE gets the rest (about $85k), the rest of the freed margin stays unused. The setting '
            'stays 2x (whole numbers only); the -5% halt and 8% leg stops are kept. 1 Nov 12:05 IST the user ordered '
            'the remaining $26k into HYPE with the leverage kept at 1.5x; the basket was already at 1.5x, answered '
            'question: keep 1.5x and move $26,000 of BTC/ETH (in proportion) into HYPE with reduce-only IOC trims '
            'first; nothing else changes. 1 Nov 22:30 IST the user ordered at least $10,000 more of BTC/ETH trimmed into HYPE '
            'with the exposure kept at 1.5x and the volatility increase kept small: $10,000 (at most $10,200) is moved '
            'the same way, in proportion, reduce-only IOC trims first; nothing else changes. 1 Nov 23:10 IST the user '
            'ordered the leverage raised to 1.85x; answered question "$185k: bot\'s 1.85x cap": exposure 1.85x the '
            'starting equity (about 1.75x the current equity), BTC and ETH held as they are, HYPE alone bought with the '
            'room; the 2x setting, 8% leg stops and -5% halt are kept. 2 Nov 11:40 IST the user strictly ordered the '
            'leverage raised from 1.85x to 2x for all three positions: exposure 2x the starting equity (the base of '
            'the 1.85x), BTC, ETH and HYPE scaled up in proportion with touch-limited IOC children, nothing sold; the '
            '2x setting, 8% leg stops and -5% halt are kept. 2 Nov 20:50 IST the user strictly ordered about $40-50k '
            'trimmed from HYPE and put into the markets most likely to be profitable by tomorrow, with the leverage kept '
            'the same: $50,000 of HYPE (never more) is trimmed with reduce-only touch-limited IOC children and SP500 '
            '(the only market paying longs funding over 24 h and 7 d, already at the 2x setting) is bought LONG with '
            'what was trimmed, capped at 2x the starting equity; BTC and ETH are held as they are and USDJPY stays '
            'closed; the 2x setting, 8% leg stops and -5% halt are kept. No profit or rank is guaranteed.')


def two_x_notionals(starting_equity, held_notionals):
    """Leg budgets: hold legs at their marked value rounded up to $100, fixed legs as set, and the rest of
    EXPOSURE x the starting equity split equally over EQUAL_LEGS, rounded down to $100."""
    from exchange.carry_runtime import CARRY_BASKET
    held = {s: (D(v) / 100).to_integral_value(rounding='ROUND_CEILING') * 100 for s, v in held_notionals.items()}
    if set(held) != set(HOLD_LEGS):
        raise SystemExit(f'Hold legs must all be held: {sorted(held)} vs {HOLD_LEGS}')
    fixed = {s: D(v) for s, v in FIXED_LEGS}
    rest = D(starting_equity) * EXPOSURE - sum(held.values(), D(0)) - sum(fixed.values(), D(0))
    each = (rest / len(EQUAL_LEGS) / 100).to_integral_value(rounding='ROUND_FLOOR') * 100
    legs = dict(held, **fixed, **{s: each for s in EQUAL_LEGS})
    return tuple((s, str(legs[s])) for s, _ in CARRY_BASKET)


def ranked_notionals(starting_equity, held_notionals):
    """Leg budgets: each leg's marked value plus its RANKED_SHARES part of the room up to RANKED_EXPOSURE x the
    starting equity, rounded down to $100. Refuses unless every leg is held, every target is above what it holds
    and the targets fall strictly in the ranked order."""
    from exchange.carry_runtime import CARRY_BASKET
    held = {s: D(v) for s, v in held_notionals.items()}
    if set(held) != {s for s, _ in RANKED_SHARES}:
        raise SystemExit(f'Every leg must be held: {sorted(held)}')
    room = D(starting_equity) * RANKED_EXPOSURE - sum(held.values(), D(0))
    weights = sum(w for _, w in RANKED_SHARES)
    legs = {s: ((held[s] + room * w / weights) / 100).to_integral_value(rounding='ROUND_FLOOR') * 100
            for s, w in RANKED_SHARES}
    ranked = [legs[s] for s, _ in RANKED_SHARES]
    if any(legs[s] <= held[s] for s in legs) or any(a <= b for a, b in zip(ranked, ranked[1:])):
        raise SystemExit(f'Ranked budgets would sell or break the order: held={held} legs={legs}')
    return tuple((s, str(legs[s])) for s, _ in CARRY_BASKET)


def close_notionals(equity, held_notionals):
    """Leg budgets for the 31 Oct reallocation: CLOSE_HOLD_LEGS at their marked value rounded up to $100 and
    CLOSE_GROW_LEG at the rest of CLOSE_EXPOSURE x the current equity, rounded down to $100. Close legs get no
    budget. Refuses unless the hold and grow legs are held and the grow leg's budget is above what it holds."""
    from exchange.carry_runtime import CARRY_BASKET
    held = {s: D(v) for s, v in held_notionals.items()}
    keep = (*CLOSE_HOLD_LEGS, CLOSE_GROW_LEG)
    if any(not held.get(s) for s in keep):
        raise SystemExit(f'{keep} must all be held: {sorted(held)}')
    legs = {s: (held[s] / 100).to_integral_value(rounding='ROUND_CEILING') * 100 for s in CLOSE_HOLD_LEGS}
    room = D(equity) * CLOSE_EXPOSURE - sum(legs.values(), D(0))
    legs[CLOSE_GROW_LEG] = (room / 100).to_integral_value(rounding='ROUND_FLOOR') * 100
    if legs[CLOSE_GROW_LEG] <= held[CLOSE_GROW_LEG]:
        raise SystemExit(f'{CLOSE_GROW_LEG} budget would sell: held={held} legs={legs}')
    return tuple((s, str(legs[s])) for s, _ in CARRY_BASKET if s in legs)


def move_notionals(equity, held_notionals):
    """Leg budgets for the 1 Nov move: MOVE_FROM_LEGS lose MOVE_AMOUNT in proportion to their marked values (each
    rounded down to $100, so never less is sold) and CLOSE_GROW_LEG gets what they lose, capped at CLOSE_EXPOSURE x
    the current equity and rounded down to $100. Refuses unless every leg is held and the grow leg's budget is
    above what it holds."""
    from exchange.carry_runtime import CARRY_BASKET
    held = {s: D(v) for s, v in held_notionals.items()}
    keep = (*MOVE_FROM_LEGS, CLOSE_GROW_LEG)
    if any(not held.get(s) for s in keep):
        raise SystemExit(f'{keep} must all be held: {sorted(held)}')
    source = sum((held[s] for s in MOVE_FROM_LEGS), D(0))
    if MOVE_AMOUNT >= source:
        raise SystemExit(f'Cannot move {MOVE_AMOUNT} out of {source}')
    legs = {s: (held[s] * (1 - MOVE_AMOUNT / source) / 100).to_integral_value(rounding='ROUND_FLOOR') * 100
            for s in MOVE_FROM_LEGS}
    moved = source - sum(legs.values(), D(0))
    room = D(equity) * CLOSE_EXPOSURE - sum(legs.values(), D(0))
    grow = min(held[CLOSE_GROW_LEG] + moved, room)
    legs[CLOSE_GROW_LEG] = (grow / 100).to_integral_value(rounding='ROUND_FLOOR') * 100
    if legs[CLOSE_GROW_LEG] <= held[CLOSE_GROW_LEG]:
        raise SystemExit(f'{CLOSE_GROW_LEG} budget would sell: held={held} legs={legs}')
    return tuple((s, str(legs[s])) for s, _ in CARRY_BASKET if s in legs)


def raise_notionals(starting_equity, held_notionals):
    """Leg budgets for the 1 Nov 1.85x raise: MOVE_FROM_LEGS at their marked value rounded up to $100 (hold legs)
    and CLOSE_GROW_LEG at the rest of RAISE_EXPOSURE x the starting equity, rounded down to $100. Refuses unless
    every leg is held and the grow leg's budget is above what it holds."""
    from exchange.carry_runtime import CARRY_BASKET
    held = {s: D(v) for s, v in held_notionals.items()}
    keep = (*MOVE_FROM_LEGS, CLOSE_GROW_LEG)
    if any(not held.get(s) for s in keep):
        raise SystemExit(f'{keep} must all be held: {sorted(held)}')
    legs = {s: (held[s] / 100).to_integral_value(rounding='ROUND_CEILING') * 100 for s in MOVE_FROM_LEGS}
    room = D(starting_equity) * RAISE_EXPOSURE - sum(legs.values(), D(0))
    legs[CLOSE_GROW_LEG] = (room / 100).to_integral_value(rounding='ROUND_FLOOR') * 100
    if legs[CLOSE_GROW_LEG] <= held[CLOSE_GROW_LEG]:
        raise SystemExit(f'{CLOSE_GROW_LEG} budget would sell: held={held} legs={legs}')
    return tuple((s, str(legs[s])) for s, _ in CARRY_BASKET if s in legs)


def scale_notionals(starting_equity, held_notionals):
    """Leg budgets for the 2 Nov 2x raise: every SCALE_LEGS leg at its marked value times SCALE_EXPOSURE x the
    starting equity / the basket's marked value, rounded down to $100. Refuses unless every leg is held and every
    budget is above what it holds (nothing is sold)."""
    from exchange.carry_runtime import CARRY_BASKET
    held = {s: D(v) for s, v in held_notionals.items()}
    if any(not held.get(s) for s in SCALE_LEGS) or set(held) != set(SCALE_LEGS):
        raise SystemExit(f'{SCALE_LEGS} must be exactly the legs held: {sorted(held)}')
    factor = D(starting_equity) * SCALE_EXPOSURE / sum(held.values(), D(0))
    legs = {s: (held[s] * factor / 100).to_integral_value(rounding='ROUND_FLOOR') * 100 for s in SCALE_LEGS}
    if any(legs[s] <= held[s] for s in SCALE_LEGS):
        raise SystemExit(f'2x budgets would sell: held={held} legs={legs}')
    return tuple((s, str(legs[s])) for s, _ in CARRY_BASKET if s in legs)


def shift_notionals(starting_equity, held_notionals):
    """Leg budgets for the 2 Nov HYPE -> SP500 shift: SHIFT_HOLD_LEGS at their marked value rounded up to $100 (hold
    legs), SHIFT_FROM_LEG at its marked value less SHIFT_AMOUNT rounded UP to $100 (so never more is sold) and
    SHIFT_TO_LEG at what that trims, capped at SCALE_EXPOSURE x the starting equity and rounded down to $100.
    Refuses unless exactly the hold legs and the source leg are held and SP500 gets at least SHIFT_MIN_BUY."""
    from exchange.carry_runtime import CARRY_BASKET
    held = {s: D(v) for s, v in held_notionals.items()}
    keep = (*SHIFT_HOLD_LEGS, SHIFT_FROM_LEG)
    if any(not held.get(s) for s in keep) or set(held) != set(keep):
        raise SystemExit(f'{keep} must be exactly the legs held: {sorted(held)}')
    if SHIFT_AMOUNT >= held[SHIFT_FROM_LEG]:
        raise SystemExit(f'Cannot move {SHIFT_AMOUNT} out of {held[SHIFT_FROM_LEG]}')
    legs = {s: (held[s] / 100).to_integral_value(rounding='ROUND_CEILING') * 100 for s in SHIFT_HOLD_LEGS}
    legs[SHIFT_FROM_LEG] = ((held[SHIFT_FROM_LEG] - SHIFT_AMOUNT) / 100).to_integral_value(rounding='ROUND_CEILING') * 100
    moved = held[SHIFT_FROM_LEG] - legs[SHIFT_FROM_LEG]
    room = D(starting_equity) * SCALE_EXPOSURE - sum(legs.values(), D(0))
    legs[SHIFT_TO_LEG] = (min(moved, room) / 100).to_integral_value(rounding='ROUND_FLOOR') * 100
    if legs[SHIFT_TO_LEG] < SHIFT_MIN_BUY:
        raise SystemExit(f'{SHIFT_TO_LEG} would get less than {SHIFT_MIN_BUY}: held={held} legs={legs}')
    return tuple((s, str(legs[s])) for s, _ in CARRY_BASKET if s in legs)


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
    not_one_x = {s: v for s, v in leverage.items() if v != dict(type='cross', value=LEVERAGE)}
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
                     unwind_starts_ms=ms(UNWIND), leg_notionals=LEG_NOTIONALS,
                     taker_depth_bps=TAKER_DEPTH_BPS, leverage=LEVERAGE).require()
    atomic_json(MANDATE, asdict(m))
    print(json.dumps(dict(mandate=str(MANDATE), identity=m.identity, starting_equity=str(equity),
                          leg_notional=LEG_NOTIONAL, legs=dict(CARRY_BASKET), leverage=leverage,
                          unwind_starts=UNWIND.isoformat(), flatten=FLATTEN.isoformat()), indent=2))


def rebind(args):
    """New mandate for the OPEN basket (same start and starting equity as the prior mandate): positions only in the
    basket on its sides, resting orders only reduce-only stops, every market at the mandate's cross setting."""
    from exchange.paper_operations import active_source_hash, atomic_json
    from exchange.carry_runtime import CARRY_BASKET, CARRY_PROFILE, CarryMandate, sha
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.testnet_certification import TEAM, API
    from exchange.venue_profiles import venue_profile
    prior = json.loads(Path(args.prior).read_text())
    client = public_client()
    account = HyperliquidAccount(client, TEAM)
    positions = {s: p for s, p in account.get_positions().items() if p.quantity}
    basket = dict(CARRY_BASKET)
    if any(s not in basket or (p.quantity > 0) != (basket[s] == 'LONG') for s, p in positions.items()):
        raise SystemExit(f'Foreign or wrong-side position: {sorted(positions)}; refusing.')
    if any(not (o.get('isTrigger') and o.get('reduceOnly')) for o in account.get_frontend_open_orders()):
        raise SystemExit('A resting order is not a reduce-only stop; refusing.')
    leverage = {s: client.post_info('activeAssetData', user=TEAM, coin=s).get('leverage') for s in basket}
    if any(v != dict(type='cross', value=LEVERAGE) for v in leverage.values()):
        raise SystemExit(f'Markets are not at {LEVERAGE}x CROSS yet: {leverage}; run raise_carry_leverage_2x.py first.')
    marks = {s: D(str(client.post_info('activeAssetData', user=TEAM, coin=s).get('markPx'))) for s in positions}
    equity = account.get_equity().collateral_balance          # unified USDP balance, already includes uPnL
    notionals = shift_notionals(prior['starting_equity'], {s: abs(p.quantity) * marks[s] for s, p in positions.items()})
    m = CarryMandate(team_wallet=TEAM, api_wallet=API, markets=tuple(basket), starts_ms=prior['starts_ms'],
                     flatten_ms=ms(FLATTEN), expires_ms=ms(EXPIRES), starting_equity=prior['starting_equity'],
                     leg_notional=LEG_NOTIONAL, source_hash=active_source_hash(ROOT), release_sha256=sha(RELEASE),
                     venue_identity=venue_profile('pas').identity, approval_reference=APPROVAL, profile=CARRY_PROFILE,
                     sides=CARRY_BASKET, unwind_starts_ms=ms(UNWIND), leg_notionals=notionals,
                     taker_depth_bps=TAKER_DEPTH_BPS, leverage=LEVERAGE, hold_legs=SHIFT_HOLD_LEGS,
                     close_legs=SHIFT_CLOSE_LEGS).require()
    atomic_json(MANDATE, asdict(m))
    print(json.dumps(dict(mandate=m.identity[:16], legs=dict(notionals), hold=SHIFT_HOLD_LEGS, close=SHIFT_CLOSE_LEGS,
                          equity=str(equity), exposure=str(sum(D(v) for _, v in notionals)), leverage=LEVERAGE,
                          held={s: str(p.quantity) for s, p in positions.items()}), indent=2))


def dry_run(args):
    """Production runtime and protection on the offline SimVenue, fed by live public books.

    No key is read and nothing is signed. The schedule is compressed so a short run covers the
    whole lifecycle: $1,000 legs, a 3-minute maker window, a 1-minute re-price and 10 s between
    taker children (live: $19,000, 2 h, 10 min, 30 s). Resting maker children fill only when the
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
    # Exit 4 when an order of ours still rests after shutdown (bug #13): never a silent clean exit.
    sys.exit(0 if runtime.run(stop) is not False else 4)


def supervise(args):
    setup_logging(STATE, 'supervisor.log')
    log = logging.getLogger('carry-supervisor')
    backoff = 10
    keep_awake = ['caffeinate', '-is'] if shutil.which('caffeinate') else []
    while True:
        log.info('starting carry basket runtime (reconciles with the exchange first)')
        code = subprocess.call(keep_awake + [sys.executable, __file__, 'start'], cwd=str(ROOT))
        if (STATE / 'stop.flag').exists():
            if code == 4 or (STATE / 'SHUTDOWN_INCOMPLETE').exists():
                log.error('SHUTDOWN_INCOMPLETE: an order still rests on the exchange; cancel it or restart to '
                          'retry (code=%s)', code)
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
    r = sub.add_parser('rebind'); r.add_argument('--prior', required=True)
    d = sub.add_parser('dry-run'); d.add_argument('--minutes', type=float, default=15)
    for name in ('start', 'supervise', 'status', 'report'):
        sub.add_parser(name)
    args = parser.parse_args()
    handlers = {'prepare': prepare, 'rebind': rebind, 'dry-run': dry_run, 'start': start, 'supervise': supervise,
                'status': status, 'report': report}
    handlers[args.command](args)
