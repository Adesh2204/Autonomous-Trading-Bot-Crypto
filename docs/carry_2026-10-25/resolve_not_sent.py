"""Human-run: mark one UNKNOWN carry order as NOT TRANSMITTED, after re-checking the proof.

For a carry child refused by the transport's own checks before any HTTP request (26 Oct 16:30 IST:
ENTRY_RELIABILITY_GATE_REQUIRED on an ETH child). The journal recorded it UNKNOWN, which correctly
blocks every entry and cancel until it is resolved. This script changes exactly that one row, only if
all of the following hold, and only after you type the confirmation:
  * no carry runtime is running, and exactly one carry row is UNKNOWN;
  * its recorded error came from the SDK transport (sdk_transport.py) and it is a known check code;
  * its tamper-evident audit trail has no DISPATCHED stage (written right before every HTTP post);
  * the exchange reports its cloid as unknownOid and there is no fill on that market since it was created.
"""
from pathlib import Path
import json, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))
CHECK_CODES = {'V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY', 'ENTRY_RELIABILITY_GATE_REQUIRED', 'SIGNING_READINESS_REVOKED',
               'COMPLIANCE_ACTION_PERMIT_REQUIRED', 'ACCOUNT_CHANGED_BEFORE_SIGNING', 'GLOBAL_POSITION_LEASE_REVOKED',
               'STARTUP_ENTRY_LOCK_REQUIRED', 'NONCE_SIGNING_DEGRADED', 'CARRY_AUTHORITY_REQUIRED'}


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
    if len(rows) != 1 or not rows[0]['intent_key'].startswith('carry-'):
        raise SystemExit(f'Expected exactly one UNKNOWN carry row, found {[r["intent_key"] for r in rows]}; nothing changed.')
    row = rows[0]
    symbol = json.loads(row['request'])['symbol']
    details = json.loads(row['outcome'] or '{}').get('error_details', {})
    stages = [s for s, in j.db.execute('SELECT stage FROM intent_audit WHERE intent_key=? ORDER BY seq', (row['intent_key'],))]
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    status = account._query('orderStatus', oid=row['cloid'])
    fills = [f for f in account.get_fills(start_ms=row['created_ms'] - 60000) if f.symbol == symbol]
    checks = dict(transport_check_refusal=details.get('reason') in CHECK_CODES and 'exchange/sdk_transpo' in details.get('traceback', ''),
                  never_dispatched='DISPATCHED' not in stages and 'ACKNOWLEDGED' not in stages,
                  exchange_unknown_oid=status == {'status': 'unknownOid'}, no_fills_on_market=not fills)
    print(json.dumps(dict(intent=row['intent_key'], symbol=symbol, reason=details.get('reason'), audit_stages=stages,
                          checks=checks), indent=2))
    if not all(checks.values()):
        raise SystemExit('A check failed; nothing changed.')
    phrase = 'THIS ORDER WAS NOT SENT'
    if input(f'Type exactly: {phrase}\n> ').strip() != phrase:
        raise SystemExit('Not confirmed; nothing changed.')
    now = time.time_ns() // 1000000
    evidence = dict(code='PRE_DISPATCH_REFUSED', transmitted=False, verified_ms=now,
                    resolved_by='HUMAN_CONFIRMED_IN_TERMINAL', checks=checks, audit_stages=stages)
    j.update(row['intent_key'], 'REJECTED', now, outcome=evidence)
    j.event('UNKNOWN_INTENT_RESOLVED_NOT_TRANSMITTED', now, intent_key=row['intent_key'], cloid=row['cloid'], **evidence)
    print('Resolved:', j.intent(row['intent_key'])['state'])
    j.close()


if __name__ == '__main__':
    main()
