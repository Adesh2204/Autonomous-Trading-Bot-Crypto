"""Evidence-bound final report; refuses incomplete or mismatched regression."""
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import difflib, hashlib, json, sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash, atomic_json
from exchange.qualification_watcher import durable_readback
from exchange.emergency_qualification import POLICY, policy_hash
from strategy_freeze import verify_strategy_freeze
from venue_config import require_paper_migration

require_paper_migration();freeze=verify_strategy_freeze()
receipt=json.loads((out/'regression_release/test_receipt.json').read_text())
assert receipt['passed'] and receipt['source_hash']==receipt['source_hash_after']==active_source_hash(ROOT)
assert receipt['totals']==dict(tests=2046,failures=0,errors=0,skipped=0)
xml=out/'regression_release/regression.xml'
assert hashlib.sha256(xml.read_bytes()).hexdigest()==receipt['xml_sha256']
account=json.loads((out/'read_only_account_v2/account_report.json').read_text())
assert account['status']=='READ_ONLY_ACCOUNT_OBSERVED' and account['source_hash']==active_source_hash(ROOT)
assert account['source_hash_after']==account['source_hash']
assert account['actual_wallet_signatures']==account['exchange_submissions']==0
assert not account['positions'] and not account['orders'] and account['account_reconciliation_ready']
cleanup=durable_readback(out/'read_only_account_v2/read_only.sqlite',account['durable_cleanup']['source_identity'],clean=True)
assert cleanup['snapshots_verified']==2 and not any(cleanup['actions'].values())
before=json.loads((out/'source_before.json').read_text())
protected=['algo-trading-bot/signal_brain.py','docs/strategy_freeze.json','configs/reliability_policy.json',
           'scripts/run_emergency_qualification.py','scripts/watch_testnet_qualification.py']
assert all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==before['files'][n] for n in protected)
changes=json.loads((out/'source_changes.json').read_text())
assert all(hashlib.sha256((ROOT/c['path']).read_bytes()).hexdigest()==c['after_sha256'] for c in changes)
previous=json.loads((ROOT/'docs/qualification_emergency_2026-10-13/final_read_only/readiness.json').read_text())
assert previous['qualification_policy_hash']==policy_hash()
historical=ROOT/'docs/certification_v8_5_2026-10-12/independent_close_readback/one_lot_readback.json'
assert hashlib.sha256(historical.read_bytes()).hexdigest()=='c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764'
record=next(x for x in json.loads(historical.read_text())['records']
            if x['order_status']['order']['order']['oid']==62228843959)
assert record['classification']['one_lot_full_close'] and not record['classification']['stop_acceptance_observed']
observed=datetime.fromtimestamp(account['completed_ms']/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()
q=account['quote'];spread=(float(q['ask'])-float(q['bid']))/float(q['mid'])*10000
flags=dict(BTC_EXACT_RESIDUAL_CLOSE_CODE_READY=True,BTC_HISTORICAL_ONE_LOT_IOC_CLOSE_EVIDENCE=True,
    ISOLATED_NATIVE_STOP_LIFECYCLE_OFFLINE_TESTED=True,ONE_LOT_PROTECTIVE_STOP_ACCEPTANCE_VERIFIED=False,
    PROTECTION_PARTIAL_FILL_BEHAVIOR_VERIFIED=False,PARTIAL_FILL_EXIT_READY=False,
    ACTUAL_PROTECTION_READY=False,CONTROLLED_EXECUTION_READY=False,
    ACTUAL_TEAM_QUALIFICATION_FILL_VERIFIED=False,LONG_CERTIFIED=False,FUNDED_RECOVERY_CERTIFIED=False,
    PRACTICE_READY=False,LIVE_READY=False,PROTECTION_ENABLED=False,PRODUCTION_STRATEGY_CHANGED=False,
    PRODUCTION_TRADING_ACTIVATED=False)
summary=dict(status='ENGINEERING_COMPLETE_VENUE_PROTECTION_VALIDATION_BLOCKED',
    active_source_hash=active_source_hash(ROOT),source_hash_before=before['active_source_hash'],
    tests=receipt['totals'],new_tests=62,baseline_tests=1984,source_bound_regression=True,
    frozen_strategy_verified=freeze,protected_files_unchanged=protected,
    actual_wallet_signatures=0,exchange_submissions=0,execution_mode='PAPER',allow_live_orders=False,
    files_modified=changes,qualification_policy=POLICY,qualification_policy_hash=policy_hash(),
    account_observed_ist=observed,account_ms=account['account_ms'],team_wallet=account['team_wallet'],
    api_wallet=account['api_wallet'],positions=account['positions'],orders=account['orders'],
    read_only_checkpoint_verification=cleanup,flags=flags,
    remaining_blockers=['Actual one-lot stop placement/readback/trigger/partial/cancel behavior unverified',
        'Existing emergency authorization explicitly prohibits stops; its four-action budget is unchanged',
        'No new exact-proposal human execution approval; old source-bound proposals are unusable',
        'IOC closure is bounded by liquidity, price, exact scope, account health and two attempts; cannot guarantee flat'],
    next_safe_action='Obtain authoritative par clarification/evidence for the 0.0001 BTC reduce-only stop lifecycle; then review a separately bounded exact venue-validation proposal. No order is authorized by this report.')
atomic_json(out/'final_summary.json',summary)
def link(label,name):return '['+label+'](<'+str(ROOT/name)+'>)'
files='\n'.join('- '+link(c['path'],c['path'])+(' — new.' if c['new'] else ' — narrow infrastructure change.') for c in changes)
checks='\n'.join('- '+k+': '+('PASS' if v['exit_code']==0 and v['result'].get('passed') else 'FAIL')
                  for k,v in receipt['checks_after'].items())
flagtext='\n'.join(k+' = '+('TRUE' if v else 'FALSE') for k,v in flags.items())
report=f'''# Team Anchorium — BTC exit safety report

Engineering work completed. **No order was placed. The BTC residual-close code is tested; actual small-position stop protection is still unverified.** The protected qualification gate remains closed.

## 1. What this work covers

This is a focused execution-infrastructure change. It preserves the existing qualification policy, risk limits and frozen VWAP strategy. It introduces no strategy, server deployment, repeat trading, account administration or schedule. It creates no new trade proposal or approval. `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` remain enforced, and global protection remains disabled.

The previous full-suite baseline was 1,984 tests. It included the earlier emergency qualification changes; the older 1,633/1,893 baselines are not the current starting point.

## 2. A 0.0002 BTC entry and a 0.0001 BTC residual, in simple terms

BTC metadata currently has a 0.0001 BTC size step, so 0.0002 BTC is two lots. An entry can fill one lot and leave the other unfilled. A close of two lots can also fill one lot and leave one lot held.

The bot must use the actual exchange position. It does not infer the position from its entry request or a response summary. The existing workflow first settles the original entry, verifies its fills, and, for a resting partial entry, confirms cancellation of the remaining entry before closing. The new exit barrier also prevents an IOC close while another order or cancellation is unresolved.

| Actual position read from the exchange | Exact exit request | Treatment |
|---|---|---|
| +0.0002 BTC | SELL 0.0002 BTC, reduce-only IOC | Ordinary $10 minimum if the reviewed exit price is at least 50,000 |
| +0.0001 BTC | SELL 0.0001 BTC, reduce-only IOC | Only the existing narrow historical BTC full-position-close scope |
| Position changes before signing | No order | Reconcile again; never send the previous size |
| First close leaves +0.0001 BTC | Second exit requests exactly 0.0001 BTC | At most the existing two bounded exit attempts |
| Price falls below the approved exit floor, account reads fail, or attempts end with exposure | Halt new entries and report the residual | A new explicit recovery decision may be needed |

The system never buys more BTC to reach an order minimum, rounds away a residual, or submits an oversized close hoping the exchange will clamp it. A repeated call to an existing intent returns its durable outcome without re-signing it.

An offline BTC test exercises: BUY 0.0002 → partial SELL 0.0001 → actual remaining position 0.0001 → exact reduce-only SELL 0.0001 → exchange-fixture position zero. Another exercises a native stop's partial execution and the same residual close. These are synthetic test records, not Team Anchorium trades.

## 3. What the historical closing evidence actually proves

The unchanged independent readback contains `par:BTC` order **62228843959**, asset scope 2670000, SELL 0.0001 BTC, reduce-only IOC. Its order limit was 82,075, making the requested notional 8.20750 USDPR. The matching reported fill was 0.0001 BTC at 82,486, with reported starting position +0.0001 BTC. The resulting position derived from the reported start and fill is zero.

This was another public account's historical trade. It demonstrates that exact one-lot shape was accepted and filled. It does not establish a universal documented exemption, a guarantee of a future fill, a historical account-state snapshot, or any protective-stop capability. The evidence file hash remains unchanged: `c421e3ffc251cb770c67b44395301e50ec0fbb6903146f18c51aa370a88a2764`.

The full-position IOC exception is not used for opening trades or trigger orders. Runtime symbol, asset ID, lot size, close direction, whole-position quantity, fresh reconciliation, price and authorization checks remain mandatory.

## 4. Verified documentation and its limits

Hyperliquid documents native trigger orders with `isMarket`, `triggerPx`, `tpsl` and reduce-only handling. It documents the ordinary $10 perpetual-order minimum. The pages reviewed do not explicitly establish a below-$10 fixed-size stop exemption on testnet `par`. [Exchange API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint), [error responses](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses).

A stop uses the mark price to trigger. A stop-limit can become an ordinary resting order if the book moves through its limit; triggering does not guarantee execution. Fixed-size stops do not automatically resize with a changed position. The documentation also warns that cancellation of a partially filled parent order can cancel its attached TP/SL children, so this implementation does not assume an attached child protects that partial position. [Official TP/SL behavior](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl).

`open`, `triggered`, `filled`, rejection and cancellation are different exchange statuses. Order identity and actual reported fills must be checked separately. [Order status and fills](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint).

## 5. Issue found: disappearance was weaker than cancellation proof

The shared uncertain-order recovery previously set `remainder_cancelled` from absence in the current open-order list. A disappearing order may have triggered, have an execution child, or be in an unresolved state. A partial fill could therefore be treated as settled too early.

Recovery now requires a recognized terminal status plus absence of a live remainder. A partial fill with an unknown or triggered status stays UNKNOWN in the generic reconciler. Native triggered-stop children are resolved by the isolated stop reconciler. A reported filled status without actual matching fills is not accepted as a fill.

This change strengthens exchange plumbing; it does not alter a signal, stop distance, target or strategy state rule.

## 6. New isolated native-stop manager

`QualificationStopManager` is a fixed-size stop-limit lifecycle using the existing native SDK trigger submission, central validator, journal, nonce, account lock and exact-action authorization. It grants no signing authority and never submits an entry. The module is separate from production strategy logic.

- Plans an opposite-side reduce-only stop for exactly the currently observed held quantity.
- Uses explicit proposal stop prices; it calculates no strategy ATR or replacement VWAP stop.
- Preserves ordinary minimum validation. A one-lot BTC stop below $10 is rejected locally with `SMALL_STOP_VENUE_SUPPORT_UNVERIFIED`.
- Persists the source/proposal-bound attempt before dispatch. A lost response or restart cannot produce a second stop.
- Requires matching original CLOID/OID, asset/coin, side, original quantity, trigger and limit prices, reduce-only flag, frontend open-order row and independent order status.
- Records `coverage_observed` separately from `protection_verified`. The latter remains FALSE. Unit fixtures cannot promote it.
- Performs no automatic rearm, modification, size increase or replacement. A changed position makes the saved stop coverage stale.

The existing emergency proposal explicitly says no stop will be submitted. Its authorization still rejects trigger actions. Its one-entry/two-exit/one-cancel/four-signed-action limits and outer 1,000 USDPR cap are unchanged. The cap is not a target position or a guaranteed loss limit. The normal production spread ceiling remains 15 bps; the separate qualification ceiling remains 50 bps.

The new manager is exercised through existing certification authorization in offline fixtures. It is not installed as an active stop in the emergency launcher. Adding an actual stop to a future qualification requires a new exact proposal and reviewed action budget; an IOC entry + stop + cancellation + two possible exits would need five actions, exceeding the current emergency four-action cap. No such budget expansion is implemented or approved here.

## 7. Acceptance, triggering, partial execution and cancellation

| Observation | Manager behavior |
|---|---|
| SDK reports resting/accepted | Requires independent readback before observing coverage |
| Readback matches and actual position has the exact same size | READBACK_ACCEPTED; capability still unverified |
| Definite placement rejection, with no accepted OID, and consistent account reads | REJECTED; records residual and permits only separately authorized safe exit handling |
| Lost acknowledgment, unknown ID, mismatch or stale account snapshot | UNKNOWN; no duplicate stop or competing exit |
| Stop triggers but fills nothing | TRIGGERED_UNSETTLED; position remains exposed |
| Triggered child stays open after a partial fill | Tracks its remaining order size and actual position; blocks competing exit |
| All explicit children reach verified terminal states | Records actual matching fills and actual residual; never assumes the original stop quantity was filled |
| Parent is triggered with no documented child mapping | Remains unresolved unless complete matching fills and a flat account establish completion |
| Cancel acknowledgment arrives | Reads status and live orders again; success alone does not prove removal |
| Cancel is uncertain | Durable cancellation barrier; no second cancel or new close until read-only recovery resolves it |

Duplicate fill observations are counted once. Conflicting fills, excess filled quantity, wrong side, malformed or duplicate children, unrelated live orders and position growth all prevent acceptance. A residual after a terminal stop is not automatically protected again; if it is below $10, the protection limitation remains explicit.

## 8. Disconnect and restart recovery

A disconnect clears coverage confidence and saved settled-stop proof. The manager never assumes the stop vanished or the position became flat. REST can refresh the original order's status, child IDs, actual fills, frontend orders and current position. REST failure leaves UNKNOWN.

Restart ignores saved active coverage. It reuses the original durable identity and performs read-only reconciliation. If an uncertain cancellation belongs to this exact stop, its original management action is recovered from account evidence without a signature. An unrelated or unresolved management action remains a barrier. No restart automatically submits, replaces or closes an order.

The emergency route's existing one-entry consumption and restart lock remain intact. Actual positions and pending orders continue to occupy the global account lock.

## 9. Operator recovery instructions for a future authorized attempt

1. Stop new entries. Preserve the proposal/source hash, intent, CLOID, OID, nonce evidence and journal.
2. Read the original order status, real fills, frontend open orders and actual team-account position. Never treat `unknownOid` or a missing row as absence proof.
3. Resolve a remaining entry before planning a close. Resolve a triggered stop's children or cancel its exact live order under separately permitted limits before a competing close.
4. If an exact supported BTC residual remains and the existing authorization is valid, use the opposite-side reduce-only IOC for precisely that quantity at a fresh permitted price. Keep the approved floor and two-attempt bound.
5. If liquidity/price/authorization is inadequate, a close is rejected, or state is uncertain, halt and escalate the exact remaining exposure. Do not enlarge it or relax the floor.
6. Completion requires actual fill records, actual zero position and no unresolved or unexpected orders. P&L uses exchange-reported fees, fills and funding. There is no actual round-trip proof from this implementation work.

## 10. Files changed

{files}

Only the two listed existing infrastructure files changed relative to this task's source snapshot. All earlier dirty repository changes remain preserved. `signal_brain.py`, the freeze manifest, reliability/protection configuration and both existing qualification launcher/watcher scripts are byte-identical to their pre-task versions. The original NSE repository was untouched.

Documentation/evidence added under this report directory: source snapshot and patch, focused test XML/logs, full regression receipt/XML/log, read-only account/checkpoint evidence, this report, summary and artifact hashes. No new recurring task was created.

## 11. Tests and source verification

**2,046 passed; 0 failures, 0 errors, 0 skips.** This includes the entire 1,984-test baseline and 62 new tests. The full-suite source hash was identical before and after. Full regression duration: {receipt['finished_unix']-receipt['started_unix']:.2f} seconds.

{checks}

The freeze verification covers the brain file, eight frozen methods and 32 parameter comparisons. VWAP, EMA, ATR, long/short conditions, stop/target concepts, UTC input convention, 0.40% scanner ATR floor, 15 bps production spread limit, 300 completed bars and Top-3 were preserved.

The new tests cover actual BTC lot/asset SDK wire in an offline composition, partial entries, one-lot residuals, native stop rejection, uncertain acceptance, incorrect readbacks, triggering without execution, open/rejected/canceled execution children, partial stop fills, duplicate observations, cancel races, lost connections, unknown cancellation recovery, restart, damaged provenance, stale snapshots and entry/exit permission boundaries.

Development failures were fixed and preserved, not erased: the first focused run had 39 failures/100 passes while the new manager's durable hash/identity fields were being corrected; diagnostic runs caught fixture formatting/quantity issues. The later broader focused run passed 362 tests. The final native-stop set passed 62 tests. The full source-bound release above is the authoritative final result.

## 12. Fresh read-only team-account observation

Observed **{observed}**. This is a timestamped observation, not a future execution approval or a lasting liquidity guarantee.

| Check | Observed result |
|---|---|
| Network / DEX | Hyperliquid TESTNET / `par` |
| Registered account | `{account['team_wallet']}` |
| API wallet | `{account['api_wallet']}`; locally derived public identity matched |
| Agent | Approved; reported expiry {account['account_readiness']['agent_expiry_ms']} ms |
| Account mode | unifiedAccount |
| Reported USDPR balance | {account['account_readiness']['collateral']} |
| BTC leverage | 1x CROSS; other nine settings were not reconfigured or rechecked in this BTC-focused observation |
| Actual positions / orders | 0 / 0 |
| Actual reported fills in reconciliation | 0; no team qualification fill demonstrated |
| Actual account reconciliation | Healthy |
| Local nonce/signer lease | Healthy; no nonce allocated, no signature created |
| Sole signing host | Prior human confirmation plus current local lease; cannot independently inspect remote machines |
| BTC bid / ask / mark / oracle | {q['bid']} / {q['ask']} / {q['mark']} / {q['oracle']} |
| Observed spread | {spread:.4f} bps |
| Illustrative one-lot exit-bound notional | {account['one_lot_notional_at_illustrative_floor']} USDPR — below $10 |
| Illustrative two-lot exit-bound notional | {account['two_lot_notional_at_illustrative_floor']} USDPR |
| Clock | {account['clock_health']['state']}, offset {account['clock_health']['offset_ms']} ms |

The illustration uses the existing exit-floor formula for reporting; it is not an approved native stop or trade proposal. Actual stop acceptance could not be demonstrated because no signed action was authorized. There were 36 public `/info` reads, zero exchange submissions and zero actual-wallet signatures. Two checkpoint checksums, SQLite integrity, source identities and clean shutdown were verified; intent, API-action and signed-management tables contain zero actions.

The first local account-report attempt failed before any HTTP call because its progress callback signature needed correction. That failed report is retained separately. The successful second run is clearly labeled `read_only_account_v2`; it is not mixed with the first attempt or previous trade proposals.

## 13. Source identity

- Full active source before this task: `{before['active_source_hash']}`.
- Full active source tested and observed: `{active_source_hash(ROOT)}`.
- Brain SHA-256, unchanged: `{before['files']['algo-trading-bot/signal_brain.py']}`.
- Core checkpoint source hash: `{cleanup['source_identity']['working_source_hash']}`. This deliberately narrower checkpoint scope differs from the full regression hash, which includes scripts and tests.
- Frozen manifest and protection/reliability configuration hashes are unchanged. Historical close evidence is unchanged.
- Git commit `{before['git_commit']}` is accompanied by the dirty source hashes; this report does not pretend the pre-existing dirty work is committed.

## 14. Final readiness and remaining limits

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
{flagtext}
```

`BTC_EXACT_RESIDUAL_CLOSE_CODE_READY` is narrow engineering readiness under the existing verified IOC scope and approved price bounds. The older broader `PARTIAL_FILL_EXIT_READY` flag stays FALSE because a complete protected partial-fill path has not been validated at the exchange. Actual protection, controlled protected execution, funded recovery, practice readiness, a genuine team fill and organizer whitelisting remain separate unproven claims.

Remaining limits are substantive: small-stop support and trigger/partial/cancel behavior are unverified; no actual bounded execution was authorized; existing proposals are expired and source-invalidated; stop-limit execution is not guaranteed; exact IOC closure can fail if liquidity or the approved price bound is inadequate; unknown children/cancellation/schema/account history must halt execution.

**Next safe action:** obtain authoritative `par` clarification or genuine independently reviewable evidence for a 0.0001 BTC reduce-only stop's placement and lifecycle. Then review a fresh, separately bounded venue-validation proposal with an exact stop/action budget and human authorization. This implementation report authorizes no order and activates no trading.
'''
(out/'report.md').write_text(report)
atomic_json(out/'final_verification.json',dict(source_bound_full_regression=True,
    active_source_hash=active_source_hash(ROOT),totals=receipt['totals'],strategy_freeze=freeze,
    protected_files_unchanged=protected,checkpoint_verification=cleanup,
    historical_close_evidence_unchanged=True,actual_wallet_signatures=0,exchange_submissions=0,
    flags=flags,previous_qualification_policy_unchanged=True))
atomic_json(out/'artifact_sha256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
    for p in out.rglob('*') if p.is_file() and 'source_before' not in p.parts and p.name!='artifact_sha256.json'
    and not p.name.endswith(('-wal','-shm'))})
print(json.dumps(dict(report=str(out/'report.md'),tests=receipt['totals'],flags=flags)))
