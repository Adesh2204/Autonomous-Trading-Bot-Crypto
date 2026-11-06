"""Human-run: mark one UNKNOWN carry IOC entry, dispatched with no reply, as NOT EXECUTED, after re-checking the proof.

3 Nov 2026 01:12 IST: during a testnet API outage an EWJ IOC buy child was signed and dispatched, the exchange closed
the connection without a response (TRANSMISSION_UNCERTAIN), and the journal correctly recorded it UNKNOWN, which blocks
every entry and cancel and stops the carry runtime from restarting. resolve_not_sent.py only covers orders refused before
dispatch. This script changes exactly that one row, only if all of the following hold, and only after you type the
confirmation:
  * no carry runtime is running, and exactly one carry row is UNKNOWN;
  * it is an IOC carry entry child (it cannot rest on the book) whose only recorded failure is the connection error,
    and its audit trail ends DISPATCHED -> UNKNOWN with no acknowledgement;
  * at least 10 minutes have passed since it was dispatched;
  * the exchange reports its cloid as unknownOid on two reads, and there is no fill on that market since it was dispatched;
  * even if it were still executed later, it would stay within that leg's remaining budget in the current mandate.
The order was signed without an expiry, so a late execution cannot be ruled out cryptographically; the bounds above keep
that residual case inside the plan (the fill ledger and the stop resize would pick it up).
"""
from decimal import Decimal as D
from pathlib import Path
import json, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
MIN_AGE_MS = 600000
PHRASE = 'THIS IOC ORDER DID NOT EXECUTE'


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Run this yourself in Terminal.')
    if subprocess.run(['pgrep', '-f', 'run_carry.py'], capture_output=True).returncode == 0:
        raise SystemExit('A carry runtime is running. Stop it first (stop.flag).')
    from exchange.execution_journal import ExecutionJournal
    from exchange.hyperliquid_account import HyperliquidAccount
    from exchange.hyperliquid_client import HyperliquidClient
    from exchange.testnet_certification import TEAM
    from exchange.venue_profiles import venue_profile
    j = ExecutionJournal(ROOT / 'runtime/testnet/anchorium-bot-1/pas.sqlite', session_id='anchorium-pas-v1', team_address=TEAM)
    rows = [r for r in j.intents() if r['state'] == 'UNKNOWN']
    if len(rows) != 1 or not rows[0]['intent_key'].startswith('carry-in:'):
        raise SystemExit(f'Expected exactly one UNKNOWN carry entry row, found {[r["intent_key"] for r in rows]}; nothing changed.')
    row = rows[0]
    request = json.loads(row['request'])
    symbol = request['symbol']
    outcome = json.loads(row['outcome'] or '{}')
    audit = list(j.db.execute('SELECT stage, timestamp_ms FROM intent_audit WHERE intent_key=? ORDER BY seq', (row['intent_key'],)))
    stages = [s for s, _ in audit]
    dispatched_ms = max((t for s, t in audit if s == 'DISPATCHED'), default=None)
    mandate = json.loads((ROOT / 'docs/carry_2026-10-25/mandate.json').read_text())
    budget = D(dict(mandate['leg_notionals']).get(symbol, '0'))
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    first = account._query('orderStatus', oid=row['cloid'])
    time.sleep(5)
    second = account._query('orderStatus', oid=row['cloid'])
    now = client.clock_ms()
    fills = [f for f in account.get_fills(start_ms=(dispatched_ms or row['created_ms']) - 1000) if f.symbol == symbol]
    position = account.get_positions().get(symbol)
    mark = D(str(client.post_info('activeAssetData', user=TEAM, coin=symbol).get('markPx')))
    held_value = abs(position.quantity) * mark if position else D(0)
    worst = D(str(request['quantity'])) * D(str(request['price']))
    checks = dict(
        ioc_carry_entry=request.get('tif') == 'Ioc' and request.get('strategy_id') in {'CARRY_LONG', 'CARRY_SHORT'},
        connection_error_only=outcome.get('code') == 'TRANSMISSION_UNCERTAIN',
        dispatched_without_reply=stages[-2:] == ['DISPATCHED', 'UNKNOWN'] and 'ACKNOWLEDGED' not in stages,
        older_than_10_min=dispatched_ms is not None and now - dispatched_ms >= MIN_AGE_MS,
        exchange_unknown_oid_twice=first == {'status': 'unknownOid'} and second == {'status': 'unknownOid'},
        no_fills_on_market_since_dispatch=not fills,
        worst_case_within_leg_budget=worst <= budget - held_value)
    print(json.dumps(dict(intent=row['intent_key'], symbol=symbol, side=request.get('side'), quantity=request.get('quantity'),
                          limit=request.get('price'), tif=request.get('tif'), audit_stages=stages,
                          minutes_since_dispatch=round((now - (dispatched_ms or now)) / 60000, 1),
                          leg_budget=str(budget), held_value=str(round(held_value, 2)), worst_case=str(round(worst, 2)),
                          checks=checks), indent=2))
    if not all(checks.values()):
        raise SystemExit('A check failed; nothing changed.')
    if input(f'Type exactly: {PHRASE}\n> ').strip() != PHRASE:
        raise SystemExit('Not confirmed; nothing changed.')
    now = client.clock_ms()
    evidence = dict(code='DISPATCHED_IOC_NOT_EXECUTED', transmitted='UNCERTAIN', verified_ms=now,
                    resolved_by='HUMAN_CONFIRMED_IN_TERMINAL', checks=checks, audit_stages=stages,
                    residual='signed without expiry; a late execution would stay within the leg budget')
    j.update(row['intent_key'], 'REJECTED', now, outcome=evidence)
    j.event('UNKNOWN_INTENT_RESOLVED_DISPATCHED_IOC_NOT_EXECUTED', now, intent_key=row['intent_key'], cloid=row['cloid'],
            **evidence)
    print('Resolved:', j.intent(row['intent_key'])['state'])
    client.close()
    j.close()


if __name__ == '__main__':
    main()
