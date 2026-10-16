"""Build source-bound V8.6 engineering report; no account client, keys or actions."""
import hashlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
read=lambda name:json.loads((OUT/name).read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
tests=read('regression_release/test_receipt.json');source=active_source_hash(ROOT)
if not tests['passed'] or tests['source_hash']!=source or tests['source_hash_after']!=source:
 raise RuntimeError('PASSING_SOURCE_BOUND_FULL_REGRESSION_REQUIRED')
if tests['evidence_classifier_sha256']!=sha(OUT/'protection_evidence.py'):
 raise RuntimeError('STOP_CLASSIFIER_SOURCE_CHANGED')
manifest=read('source_manifest.json')
if any(sha(ROOT/p)!=v for p,v in manifest['files'].items()):raise RuntimeError('MANIFEST_CHANGED')
search=read('protection_read_verified/observations.json')
if not search['source_stable'] or search['source_hash']!=source or search['source_hash_after']!=source:
 raise RuntimeError('PUBLIC_READ_SOURCE_MISMATCH')
raw=read('protection_read_verified/raw_info.json')
if any(r['request']['type'] not in {'perpDexs','meta','recentTrades','clearinghouseState','frontendOpenOrders','historicalOrders','orderStatus'} for r in raw):
 raise RuntimeError('PUBLIC_READ_ONLY_BOUND_VIOLATION')
if any('dex' in r['request'] and r['request']['dex']!='par' for r in raw):raise RuntimeError('WRONG_DEX_QUERY')
prior=ROOT/'docs/certification_v8_5_2026-10-12'
closepath=prior/'independent_close_readback/one_lot_readback.json'
if sha(closepath)!='c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764':
 raise RuntimeError('ORIGINAL_CLOSE_PROOF_CHANGED')
closes=json.loads(closepath.read_text())
if not closes['all_six_historical_one_lot_closes_verified']:raise RuntimeError('CLOSE_PROOF_NOT_VERIFIED')
account=json.loads((prior/'account_preflight_final/account_check.json').read_text())
comparison=read('source_comparison.json')
checks={}
for name,script in [('strategy_freeze','scripts/check_strategy_freeze.py'),('phase0','scripts/phase0_check.py')]:
 p=subprocess.run([sys.executable,script],cwd=ROOT,capture_output=True,text=True)
 checks[name]=dict(exit_code=p.returncode,result=json.loads(p.stdout) if p.returncode==0 else p.stderr)
 if p.returncode:raise RuntimeError('FREEZE_OR_SAFETY_FAILED')
rows=[]
for v in closes['records']:
 o=v['order_status']['order']['order'];c=v['classification']
 rows.append(dict(coin=o['coin'],oid=o['oid'],close_side='BUY' if o['side']=='B' else 'SELL',
    quantity=o['origSz'],limit=o['limitPx'],notional=c['original_limit_notional'],post_position=c['post_fill_position']))
orders=[o for r in raw if r['request']['type']=='frontendOpenOrders' for o in r['response']]
flags=dict(ONE_LOT_FULL_CLOSE_EVIDENCE_VERIFIED=True,CLOSING_EXCEPTION_IMPLEMENTED=True,
 SCOPED_FULL_POSITION_CLOSE_OFFLINE_TESTS_PASSED=True,UNIVERSAL_SUBMINIMUM_CLOSE_VERIFIED=False,
 ONE_LOT_PROTECTIVE_STOP_ACCEPTANCE_VERIFIED=False,SUBMINIMUM_PROTECTION_CAPABILITY_VERIFIED=False,
 PROTECTION_PARTIAL_FILL_BEHAVIOR_VERIFIED=False,PARTIAL_FILL_EXIT_READY=False,
 ACTUAL_PROTECTION_READY=False,CONTROLLED_EXECUTION_READY=False,LONG_CERTIFIED=False,
 SHORT_CERTIFIED=False,FUNDED_RECOVERY_CERTIFIED=False,PRACTICE_READY=False,LIVE_READY=False,
 PROTECTION_ENABLED=False,PRODUCTION_INFRASTRUCTURE_CHANGED=True,PRODUCTION_STRATEGY_CHANGED=False,
 PRODUCTION_TRADING_ACTIVATED=False,SOLE_SIGNER_HOST_CONFIRMED=False)
summary=dict(directive='V8.6',generated_utc=datetime.now(timezone.utc).isoformat(),
 verdict='SCOPED_CLOSE_IMPLEMENTED_ENTRY_BLOCKED_UNVERIFIED_ONE_LOT_PROTECTION',source_hash=source,
 production_source_files_modified=comparison['changed'],new_active_files=comparison['added'],
 strategy_brain_sha256=sha(ROOT/'algo-trading-bot/signal_brain.py'),safety_checks=checks,
 tests=tests['totals'],baseline_tests=1577,new_tests=56,full_regression_passed=True,
 regression_xml_sha256=tests['xml_sha256'],historical_close_evidence=rows,
 close_scope='Only verified exact size/direction/market/runtime-mapping IOC full closes; ordinary/trigger minimum unchanged',
 public_stop_inspection=dict(started_utc=search['started_utc'],finished_utc=search['finished_utc'],
    users=len(search['users']),open_order_rows=len(orders),open_trigger_rows=sum(o.get('isTrigger') is True for o in orders),
    additional_history_rows=sum(h['par_rows'] for h in search['histories']),
    unique_additional_historical_orders=sum(h['unique_par_orders'] for h in search['histories']),
    historical_trigger_rows=sum(h['trigger_rows'] for h in search['histories']),
    requests=search['requests'],charged_weight=search['charged_weight'],source_stable=search['source_stable']),
 flags=flags,actual_exchange_submissions=0,actual_wallet_signatures=0,
 offline_signing='Ephemeral fixtures only; real HTTP prohibited by fixture',
 fresh_activation_preflight_performed=False,
 fresh_activation_preflight_status='DEFERRED_UNTIL_CLOSING_AND_PROTECTION_GATES_BOTH_PASS',
 prior_account_observation=dict(started_utc=account['started_utc'],finished_utc=account['finished_utc'],
    account_ready=account['account_readiness']['status'],balance=account['reported_equity']['collateral_balance'],
    observed_flat=account['observed_flat'],all_ten_one_x_cross=account['all_ten_one_x_cross'],
    scope='Prior V8.5 only, older source, not a V8.6 activation permit or present account guarantee'),
 actual_round_trip_pnl=None,proposal=None,approval_requested=False,
 remaining_blockers=['One-lot/sub-$10 stop admission, readback coverage and residual behavior unverified',
    'Closing scope does not establish arbitrary subminimum sizes/directions; two-lot residual remains blocked',
    'Fresh account/signer/nonce/clock/liquidity/reconciliation preflight still required after venue behavior validated',
    'Human sole-signer-host confirmation and an exact bounded trade approval remain outstanding'],
 next_safe_action='Obtain authoritative par one-lot protective-stop clarification or a verifiable original stop/position/fill record using the UNSENT organizer question. Keep entry blocked.')
atomic_json(OUT/'final_summary.json',summary)
atomic_json(OUT/'final_audit.json',dict(source_hash=source,manifest_files_verified=len(manifest['files']),
 regression_xml_sha256=tests['xml_sha256'],public_raw_sha256=sha(OUT/'protection_read_verified/raw_info.json'),
 close_evidence_sha256=sha(closepath),safety_checks=checks,actual_exchange_submissions=0,actual_wallet_signatures=0))
file_table='\n'.join(f'| `{p}` | {description} |' for p,description in [
 ('algo-trading-bot/exchange/full_position_close.py','New explicit IOC scope, historical proof identity and exact full-position validation.'),
 ('algo-trading-bot/exchange/partial_fill_safety.py','Separate scoped closing helper; strict protection sizing is retained.'),
 ('algo-trading-bot/exchange/exchange_rules.py','Explicit close operation only; normal order minimum and other central checks remain.'),
 ('algo-trading-bot/exchange/compliance_guard.py','Central exact-action permit carries the full-close size check to the SDK boundary.'),
 ('algo-trading-bot/exchange/hyperliquid_execution.py','Dedicated close_full_position path, exact precision, double position read, existing durable recovery.'),
 ('algo-trading-bot/exchange/testnet_certification.py','Explicit close opt-in, bounded residual exit, independent protection-qualified result.'),
 ('algo-trading-bot/exchange/certification_runtime.py','Prepared close composition; actual LONG certificate requires verified protection and actual evidence.'),
 ('algo-trading-bot/test_exact_full_close_v8_6.py','56 offline cases for scope, partial fills, stops, uncertainty, duplicates and restart.')])
close_table='\n'.join(f"| {r['coin']} | {r['close_side']} | {r['quantity']} | {r['oid']} | {r['notional']} |" for r in rows)
flag_text='\n'.join(f"{k} = {'TRUE' if v else 'FALSE'}" for k,v in flags.items())
report=f'''# Team Anchorium — V8.6 exact full-position close implementation

## 1. Direct verdict

**The narrow closing fix is implemented and tested. The first funded testnet trade remains blocked.**
We can prepare an exact IOC close for the previously verified size/direction/market combinations,
without increasing the position to meet $10. We have not independently verified a one-lot stop
that protects a sub-$10 position. Therefore there is no safe LONG proposal to approve yet.

No actual exchange order, cancel, configuration change or actual-wallet signature was made.
PAPER/false and disabled protection remain enforced. Ephemeral offline signatures are test fixtures.

## 2. Confirmed root cause and venue evidence

Ordinary MarketSpec normalization and the central validator reject orders below $10 before signing.
The existing exact-close sizing helper also rejected small residuals. Those general rules remain;
the new dedicated closing operation can exempt only a verified exact full-position IOC shape.

The V8.5 independent public readbacks established six original reduce-only IOC orders, filled
statuses, exact original sizes and matched fills whose reported starting quantity reduces to zero.
These are other public wallets. They are not Anchorium trades. The zero quantity is fill-derived,
not an independent historical position snapshot. One lot is compared with current runtime metadata;
historical metadata was not separately recovered. Historical acceptance is not a universal or
present-day venue guarantee.

| Market | Closing side | Exact supported sub-$10 size | Original order ID | Original limit notional |
|---|---|---:|---:|---:|
{close_table}

BUY closes a short; SELL closes a long. Thus BTC has one-lot evidence in both directions,
whereas ETH/HYPE/EWJ have BUY-only evidence and BRENT has SELL-only evidence. Other shapes,
including an unverified two-lot BTC residual, remain blocked. Ordinary $10-or-larger full closes
still pass the existing rules. The dedicated subminimum scope additionally requires the original
runtime asset mapping and size decimals; a mapping change fails closed.

The preserved original proof hash is `{sha(closepath)}`.

## 3. What the narrowly scoped path checks

1. Explicit `close_full_position` operation, LIMIT IOC, reduce-only true and a recognized closing identity.
2. One actual `par` position and fresh, reconciled account truth; size equals the entire observed remainder.
3. Opposite direction, exact lot/price representation, no quantity rounding, oversizing or exposure top-up.
4. Observed historical scope for a sub-$10 order; no extrapolation to stops, partial-position closes or another market.
5. Existing account, agent, metadata, quote, mark-price band, risk, compliance, rate, nonce and authorization gates.
6. An exact-action central SDK permit rechecks positions twice at the signing boundary. A changed position
   blocks signing, pauses entries and retains durable uncertainty for review.
7. Existing durable client order identities prevent retransmission. Confirmed partial exits use the new actual
   remainder within the approved two-attempt exit bound; unknown status stops the sequence without a blind retry.

The normal `submit`, replacement, PAPER normalization and protective-order routes retain the minimum.
The actual certification builder is prepared to use this explicit close path, but it still calls
`require_safe_partial_path` before acquiring its signer. That entry gate remains blocked here.

## 4. Independent one-lot protective-stop investigation

A new public read-only inspection ran from **{search['started_utc']} to {search['finished_utc']}**
(UTC; add 5h30 for IST). It used four bounded trade feeds only to find legitimate public counterparties,
then inspected existing orders/positions and two additional histories. It did not run the scanner,
request candle histories, create a wallet signature or submit an exchange action.

| V8.6 observation | Result |
|---|---:|
| Public accounts inspected for existing orders/positions | {len(search['users'])} |
| Current open-order rows | {len(orders)} |
| Current trigger orders | {sum(o.get('isTrigger') is True for o in orders)} |
| Additional par historical event rows | {sum(h['par_rows'] for h in search['histories'])} |
| Unique additional historical orders | {sum(h['unique_par_orders'] for h in search['histories'])} |
| Historical trigger rows in this additional sample | {sum(h['trigger_rows'] for h in search['histories'])} |
| Read-only /info requests | {search['requests']} |
| Conservatively charged public weight | {search['charged_weight']} |
| Independently accepted one-lot stop covering a position | 0 |

Both new histories hit the 2,000-row cap. This is a bounded sample, not a census. Absence of a stop
example does **not** establish that the venue rejects small stops. The earlier V8.5 history sample
is preserved separately; its 15,304 event rows/8,427 unique orders must not be mistaken for new rows.
The sandbox DNS failure is preserved under `protection_read_sandbox`; the successful public read
is under `protection_read_verified`. Source hashes match before and after the successful read.

The [official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
explains position protection, fixed-size versus position-following behavior and parent-order handling.
It does not specify the needed sub-$10 admission exception. A child attached to a partly filled
parent is not automatically retained after a manual cancellation. A stop limit can remain unfilled
if a gap passes its limit.

The [official exchange endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint)
documents trigger payloads, `positionTpsl` grouping and ordinary minimum-order rejection, without
establishing a par one-lot exception. The [official error reference](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses)
separates minimum-notional errors from reduce-only errors. Neither the SDK serializer nor a
successful IOC closing record establishes small-stop admission.

The new evidence assessor requires an original one-lot subminimum stop, reduce-only/trigger flags,
correct side, exact current position coverage, stable before/after state and matching open-order
status readback. Even an accepted open stop would not by itself prove trigger/residual execution.
No existing record in this bounded check satisfied those conditions. Protection remains unverified.

## 5. Protection rejection cannot earn a LONG certificate

Previously, a rejected stop followed by successful emergency closure could have status
`TRADE_CLOSED_RECONCILED`, and the runtime used that status to mark LONG certification complete.

The accounting status is retained: it correctly says the position closed and its reported P&L
reconciled. A separate `certification_passed` result now requires actual-size protection acceptance.
The runtime additionally requires flat reconciliation and **actual testnet evidence**, so offline
fixtures cannot set an actual account certificate. A rejected/unverified stop never earns a LONG
certificate. The durable `certification_completed:<identity>` marker only consumes the attempt;
it is not proof of qualification and still prevents repeated entry after restart.

## 6. Source files changed

| Source file | Purpose |
|---|---|
{file_table}

Six existing infrastructure files changed, two active files were added. The other prior manifest
files, including all four configuration files, remain identical. `production_changes.diff` records
the existing-file comparison against V8.5; pre-edit copies are preserved in `source_before`.
Read-only evidence helpers, raw observations, report generators and the unsent question live in this
documentation directory, outside the production exchange path. There is no new strategy or ML feature.

## 7. Tests and frozen strategy

**Full regression: {tests['totals']['tests']} passed; {tests['totals']['failures']} failures;
{tests['totals']['errors']} errors; {tests['totals']['skipped']} skipped.** This includes all
1,577 baseline cases plus 56 new cases. The earlier targeted infrastructure run passed 294 cases;
the final focused new test run passed 56. These runs overlap and are not added together.

New coverage includes exact observed scopes, wrong direction/mapping/size, stale/reconciled account
requirements, normal entry/trigger lockouts, SDK quantity/wire identity, changing position at the
permit boundary, rejected/unknown close outcomes, no duplicate transmission, one-lot partial entry,
unverified two-lot escalation, actual one-lot residual after a partial exit, stop rejection,
restart with both consumed and unresolved attempts, and false-positive public stop evidence.

The initial targeted run had fixture setup/mapping errors (12 failures, six errors); they are
preserved in `targeted_initial`. The next focused run exposed the central permit callback gap
(one failure), which was fixed in the production permit rather than bypassed in the test.
`targeted_retry` is preserved. The final full suite used unchanged active source throughout.

Phase-0: **PASS**, including the Angel and testnet write lockouts and PAPER/false defaults.
Strategy freeze: **PASS** — one whole frozen file, eight frozen methods, 32 parameters.
`signal_brain.py` is byte-identical to `nse-working-baseline`; hash:
`{sha(ROOT/'algo-trading-bot/signal_brain.py')}`.
VWAP, EMA, ATR, state behavior, UTC input convention, 0.40% ATR floor, 15 bps spread ceiling,
300 completed bars and Top-3 were not changed. Active source hash: `{source}`.
XML hash: `{tests['xml_sha256']}`. The documentation evidence-classifier hash is also bound to the receipt.

## 8. Account preflight and trade proposal

The user requested a fresh activation preflight **when both closing and protection are validated**.
That condition is not met, so the activation preflight and LONG proposal are deferred.
No actual wallet key was loaded or used by this V8.6 investigation.

For context only, the prior V8.5 read observed a unified account, 1,000,000 USDPR, all ten markets at
1x CROSS, an approved API agent, no positions/orders and a reconciled separate read-only journal.
Its timestamps were **{account['started_utc']}–{account['finished_utc']} UTC**. Those checks were made
against older source, and are not current readiness or permission. Its local signer lease check
also did not establish sole ownership across other hosts. Human sole-signer-host confirmation remains
outstanding. A future proposal requires fresh account, signer/nonce/clock/rate, market/liquidity,
reconciliation, protection-capability and exact risk checks, followed by explicit trade approval.

There is **no eligible trade to authorize now**. BTC is the only investigated crypto with verified
one-lot IOC closes in both directions; this is not a liquidity recommendation or a protection approval.
There is no Anchorium actual round-trip P&L from this work. Test fixtures and other wallets' fills
are not reported as our profits, funded recovery or strategy performance.

## 9. Readiness flags

```ini
{flag_text}
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
```

`PARTIAL_FILL_EXIT_READY` stays false because the narrow scope does not prove every possible
small residual and its protection. Infrastructure code changed; strategy and trading activation did not.

## 10. Remaining blockers and the single next safe action

Obtain an authoritative **par one-lot protective-stop** rule or an independently verifiable original
stop record with actual position coverage and trigger/residual behavior. The exact questions are
in `organizer_question_draft.md`, explicitly **UNSENT**. No organizer message is authorized or sent.

Keep entry blocked until that evidence supports a narrow stop solution. Do not enlarge exposure,
remove the ordinary minimum, submit a probe stop, activate autonomous trading or manufacture an
approval proposal. If the protection mechanism is unsupported, the correct outcome remains a blocked
certification entry. If supported, implement/test that independently, then refresh the account and
prepare one bounded LONG for explicit human approval.
'''
(OUT/'report.md').write_text(report)
print(json.dumps(dict(report=str(OUT/'report.md'),tests=tests['totals'],flags=flags),indent=2))
