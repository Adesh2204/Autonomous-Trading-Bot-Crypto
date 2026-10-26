"""Human-run: mark the 26 Oct 01:19 IST SP500 carry child as NOT TRANSMITTED, after re-checking the proof.

The child passed the validator and was refused by the final pre-HTTP check in sdk_transport.check
(V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY), so it was never posted. The journal recorded it UNKNOWN, which
correctly blocks every entry and cancel until someone resolves it. This script resolves only that
one row, only if all of the following still hold, and only after you type the confirmation:
  * no carry runtime is running;
  * the row is UNKNOWN and its recorded exception is the pre-HTTP scope refusal;
  * the journal has no transport-dispatch record for its cloid;
  * the exchange reports the cloid as unknownOid and there is no SP500 fill since the row was created.
"""
from pathlib import Path
import json, subprocess, sys, time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'algo-trading-bot'))


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
    rows = [r for r in j.intents() if r['intent_key'].startswith('carry-in:pas:SP500:') and r['state'] == 'UNKNOWN']
    if len(rows) != 1:
        raise SystemExit(f'Expected exactly one UNKNOWN SP500 carry row, found {len(rows)}; nothing changed.')
    row = rows[0]
    outcome = json.loads(row['outcome'] or '{}')
    trace = outcome.get('error_details', {}).get('traceback', '')
    dispatched = j.db.execute("SELECT COUNT(*) FROM events WHERE data LIKE ? AND kind NOT IN "
                              "('COMPLIANCE_ACTION_AUTHORIZED','SIGNED_ATTEMPT','EXCHANGE_ORDER_RESULT','AMBIGUOUS_ORDER_RESULT')",
                              ('%' + row['cloid'] + '%',)).fetchone()[0]
    client = HyperliquidClient(venue=venue_profile('pas'))
    client.startup()
    account = HyperliquidAccount(client, TEAM)
    status = account._query('orderStatus', oid=row['cloid'])
    fills = [f for f in account.get_fills(start_ms=row['created_ms'] - 60000) if f.symbol == 'pas:SP500']
    # On the signing path this code is raised only by entry_scope.require_entry inside
    # sdk_transport.check, which runs before session.post (the stored traceback is truncated).
    checks = dict(pre_http_scope_refusal=outcome.get('error_details', {}).get('reason') == 'V4_PAS_BTC_EWY_NEW_ENTRIES_ONLY'
                  and 'sdk_transport.py' in trace and 'session.post' not in trace,
                  no_dispatch_record=dispatched == 0, exchange_unknown_oid=status == {'status': 'unknownOid'},
                  no_sp500_fills=not fills)
    print(json.dumps(dict(intent=row['intent_key'], cloid=row['cloid'], checks=checks), indent=2))
    if not all(checks.values()):
        raise SystemExit('A check failed; nothing changed.')
    phrase = 'SP500 CHILD WAS NOT SENT'
    if input(f'Type exactly: {phrase}\n> ').strip() != phrase:
        raise SystemExit('Not confirmed; nothing changed.')
    now = time.time_ns() // 1000000
    evidence = dict(code='PRE_HTTP_ENTRY_SCOPE_REJECTED', transmitted=False, verified_ms=now,
                    resolved_by='HUMAN_CONFIRMED_IN_TERMINAL', checks=checks)
    j.update(row['intent_key'], 'REJECTED', now, outcome=evidence)
    j.event('UNKNOWN_INTENT_RESOLVED_NOT_TRANSMITTED', now, intent_key=row['intent_key'], cloid=row['cloid'], **evidence)
    print('Resolved:', j.intent(row['intent_key'])['state'])
    j.close()


if __name__ == '__main__':
    main()
