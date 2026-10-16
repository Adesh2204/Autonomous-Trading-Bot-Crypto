"""Build V8.5 report from preserved evidence; no network or execution client."""
import hashlib, json, sqlite3, sys
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint

read=lambda p:json.loads((OUT/p).read_text())
tests=read('regression_release/test_receipt.json')
account=read('account_preflight_final/account_check.json')
signer=read('signer_preflight_final.json')
closes=read('independent_close_readback/one_lot_readback.json')
searches=[read(n+'/observations.json') for n in ('public_search_verified','protection_search_verified')]
comparison=read('source_comparison.json')
current=active_source_hash(ROOT)
if not tests['passed'] or tests['source_hash']!=current or tests['source_hash_after']!=current:
    raise RuntimeError('SOURCE_BOUND_REGRESSION_REQUIRED')
if tests['evidence_classifier_sha256']!=hashlib.sha256((OUT/'public_evidence.py').read_bytes()).hexdigest():
    raise RuntimeError('EVIDENCE_CLASSIFIER_CHANGED')
if account['source_hash']!=current or account['source_hash_after']!=current or closes['source_hash']!=current or closes['source_hash_after']!=current:
    raise RuntimeError('FINAL_READBACK_SOURCE_MISMATCH')

checks={}
for name,script in [('strategy_freeze','scripts/check_strategy_freeze.py'),('phase0','scripts/phase0_check.py')]:
    p=subprocess.run([sys.executable,script],cwd=ROOT,capture_output=True,text=True)
    checks[name]=dict(exit_code=p.returncode,result=json.loads(p.stdout) if p.returncode==0 else p.stderr)
    if p.returncode:raise RuntimeError('SAFETY_OR_FREEZE_FAILED')
sqlite_checks=[]
for directory in ('account_preflight_sandbox','account_preflight_verified','account_preflight_final'):
    path=OUT/directory/'read_only.sqlite'
    db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    actions={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('intents','api_actions','signed_management')}
    snapshots=db.execute('SELECT data,checksum FROM recovery_snapshots ORDER BY seq').fetchall()
    parsed=[json.loads(row[0]) for row in snapshots]
    valid=all(fingerprint(json.loads(data))==checksum for data,checksum in snapshots)
    source_identities_match=len({json.dumps(v['source_identity'],sort_keys=True) for v in parsed})<=1
    db.close()
    sqlite_checks.append(dict(path=str(path.relative_to(ROOT)),integrity=integrity,action_rows=actions,
        snapshot_count=len(snapshots),all_snapshot_checksums_valid=valid,source_identities_match=source_identities_match,
        last_clean_shutdown=parsed[-1]['last_clean_shutdown'] if parsed else None,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if integrity!='ok' or any(actions.values()) or not valid or not source_identities_match:
        raise RuntimeError('OBSERVER_PERSISTENCE_OR_ACTION_AUDIT_FAILED')
rows=[]
for v in closes['records']:
    o=v['order_status']['order']['order'];c=v['classification']
    f=[f for f in v['raw_window_fills'] if f['oid']==o['oid'] and f['coin']==o['coin']][0]
    rows.append(dict(user=v['user'],coin=o['coin'],oid=o['oid'],quantity=o['origSz'],limit=o['limitPx'],
        original_notional=c['original_limit_notional'],fill_price=f['px'],start_position=f['startPosition'],
        post_fill_position=c['post_fill_position'],direction=f['dir'],time_ms=f['time']))
host_confirmation_path=OUT/'human_sole_host_confirmation.json'
host_confirmation=read(host_confirmation_path.name) if host_confirmation_path.exists() else None
flags=dict(ONE_LOT_FULL_CLOSE_EVIDENCE_VERIFIED=closes['all_six_historical_one_lot_closes_verified'],
    SUBMINIMUM_PROTECTION_CAPABILITY_VERIFIED=False,PROTECTION_PARTIAL_FILL_BEHAVIOR_VERIFIED=False,
    CLOSING_EXCEPTION_IMPLEMENTED=False,PARTIAL_FILL_EXIT_READY=False,ACTUAL_PROTECTION_READY=False,
    CONTROLLED_EXECUTION_READY=False,LONG_CERTIFIED=False,SHORT_CERTIFIED=False,
    FUNDED_RECOVERY_CERTIFIED=False,PRACTICE_READY=False,LIVE_READY=False,PRODUCTION_CHANGED=False,
    READ_ONLY_ACCOUNT_RECONCILED=account['durable_certification_barrier_tested'],
    LOCAL_SIGNER_OWNERSHIP_VERIFIED=signer['status']=='LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED',
    SOLE_SIGNER_HOST_CONFIRMED=bool(host_confirmation and host_confirmation.get('confirmed')))
summary=dict(directive='V8.5',generated_utc=datetime.now(timezone.utc).isoformat(),
    verdict='CONTROLLED_EXECUTION_BLOCKED_SMALL_POSITION_PROTECTION_UNVERIFIED',
    source_hash=current,production_source_changes=[],new_test_files=comparison['new_active_source_files'],
    tests=tests['totals'],full_regression_passed=tests['passed'],phase0_and_freeze=checks,
    verified_historical_one_lot_closes=rows,
    evidence_limits=['Current-runtime lot comparison, historical metadata not independently recovered',
        'Zero post-fill quantity derived from exchange-reported starting quantity and matched fills',
        'Other public wallets; not Anchorium fills/P&L or universal current acceptance'],
    public_search=dict(sampled_unique_users=len({u.lower() for s in searches for u in s['public_users']}),
        par_history_event_rows=sum(h['par_event_rows'] for s in searches for h in s['history_counts']),
        unique_par_orders=sum(h['unique_par_orders'] for s in searches for h in s['history_counts']),
        par_trigger_event_rows=sum(h['par_trigger_event_rows'] for s in searches for h in s['history_counts']),
        bounded_search_requests=sum(s['requests'] for s in searches),independent_readback_requests=closes['requests']),
    account_observed_utc=[account['started_utc'],account['finished_utc']],
    account_readiness=account['account_readiness']['status'],collateral=account['reported_equity']['collateral_balance'],
    observed_flat=account['observed_flat'],all_ten_one_x_cross=account['all_ten_one_x_cross'],
    durable_observer_scope=account['reconciliation_scope'],signer_preflight=signer['status'],
    remote_signer_ownership_verified=False,human_sole_host_confirmation=host_confirmation,
    flags=flags,sqlite_audit=sqlite_checks,signature_created=False,exchange_submissions=0,
    actual_anchorium_round_trip_pnl=None,actual_round_trip_pnl_status='NOT_CERTIFIED',
    proposal=None,approval_requested=False,
    blockers=['Below-$10 stop acceptance/readback/actual-quantity and residual treatment unverified',
        'No production exception implemented until both capabilities have supported scope',
        'Sole signer host unconfirmed' if not flags['SOLE_SIGNER_HOST_CONFIRMED'] else 'Fresh sole-host check remains required at future activation',
        'Fresh exact-risk trade proposal and explicit human approval remain required'],
    next_safe_action='Obtain authoritative par small-position stop clarification or an independently verifiable accepted stop record, using organizer_question_draft.md. Keep entry blocked.')
atomic_json(OUT/'final_summary.json',summary)
atomic_json(OUT/'final_audit.json',dict(source_hash=current,source_matches_regression=True,
    prior_source_files_unchanged=not comparison['changed_previous_files'],
    independent_closes_verified=closes['all_six_historical_one_lot_closes_verified'],
    regression_xml_sha256=tests['xml_sha256'],sqlite_audit=sqlite_checks,
    phase0_and_freeze=checks,exchange_submissions=0,signature_created=False))

table='\n'.join(f"| {v['coin']} | {v['oid']} | {v['direction']} | {v['quantity']} | {v['original_notional']} | {v['fill_price']} | {v['post_fill_position']} |" for v in rows)
market_table='\n'.join(f"| {v['symbol']} | {v.get('quote',{}).get('bid','Unavailable')} | {v.get('quote',{}).get('ask','Unavailable')} | {D(v['spread_bps']):.3f} | {v['minimum_lot_entry_notional']} |" for v in account['focused_executable_reviews'] if v['executable_quote'])
flag_text='\n'.join(f"{k} = {'TRUE' if v else 'FALSE'}" for k,v in flags.items())
report=f"""# Team Anchorium — V8.5 execution validation

Prepared {summary['generated_utc']}. **No actual exchange order was submitted.**

## 1. Direct verdict

**One-lot manual closing has genuine historical evidence. Small-position
protective stops remain unverified, so the first actual trade is still blocked.**
We found six one-lot closes across five `par:` markets. We did not find an
accepted small protective stop in the bounded sample or an explicit official
rule establishing its minimum-value exception. This is an evidence gap, not a
claim that the exchange definitely rejects every small stop.

Your V8.5 directive makes the code exception conditional on establishing both
capabilities. That condition is unmet. No opening, closing or protective-order
minimum validator was relaxed, and no exact trade proposal was presented for
approval.

## 2. Verified one-lot closes

All six original orders were reduce-only, non-trigger limit IOC orders with
status `filled`, zero remaining order size and matched fills equal to the
entire reported starting position. Each quantity equals one lot under fresh
runtime metadata. Two independent reads of each order/fill window agree.

| Market | Order ID | Actual direction | Original size | Original limit value, USDPR | Actual fill price | Fill-derived final quantity |
|---|---:|---|---:|---:|---:|---:|
{table}

These are **other public accounts**, not Team Anchorium trades. The zero final
quantity is derived from the API's reported `startPosition` and matched fill,
not from an independent historical account snapshot. Past lot metadata was
not separately recoverable; the exact sizes match the freshly read lot steps.
This proves these historical operations occurred, not a blanket guarantee for
every current market, size or order type. Raw original orders and fills are in
[the independent readback](independent_close_readback/one_lot_readback.json).

Two additional HYPE one-lot attempts returned `reduceOnlyRejected` and no
matched fills. They were excluded from success counts; a rejection with this
code does not prove the submitted order met the full-position condition.

## 3. Protective-stop result and remaining venue question

The two bounded searches sampled **8 public counterparties**, **15,304 `par`
history event rows** and **8,427 unique orders**. Duplicate open/terminal
history events were not counted as separate orders. There were **zero trigger
order records**, hence no small-stop acceptance, readback or partial-fill
protection example to verify. Several latest-history responses hit their
2,000-row cap, so absence in this sample is not proof of venue-wide absence.
The search used six focused public trade feeds only to discover counterparties;
it did not run candles, signals, ranking or a broad market-data redesign.

The [participant guide](https://perpetual-alpha26.github.io/docs/) states the
ordinary $10 minimum and describes partial IOC fills. The [official TP/SL
page](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
describes position-based and parent-order stops but does not explicitly promise
sub-$10 acceptance. Parent-linked children also do not automatically solve
protection of every partial fill. See [venue_behavior.md](venue_behavior.md)
for the precise source/evidence distinction.

The installed official SDK is **0.24.0**. Its `market_close` constructs an
ordinary reduce-only IOC. Trigger and `positionTpsl` payload support does not,
by itself, prove the server accepts a tiny stop. No zero-size, oversized close,
larger entry or other undocumented workaround was implemented.

The [organizer question](organizer_question_draft.md) asks specifically about
placement versus trigger-time minimum checks, fixed-size versus position-wide
grouping and protection of actual partial fills/residuals. It is **unsent**;
no organizer/support message was sent by this task.

## 4. Exact root cause in the repository

The central validator still rejects a normalized size × price below 10
(`exchange_rules.py`, `MIN_ORDER_NOTIONAL`). `MarketSpec.normalize_order`
independently applies the same minimum to every order, including reduce-only.
`exact_full_close_size` rejects a genuine residual below 10 rather than rounding
it away or increasing the close quantity. Certification's partial-path gate
tests the smallest possible fill and residual — one runtime lot — at reviewed
exit/protection prices. Thus a $25 opening request does not eliminate the gap.

The six historical manual closes resolve the previous lack of one-lot
observations. They do not resolve the shared protection gate or authorize a
global exception in closing and trigger validation. An implemented exception
must eventually have separate close/protection scope and retain exact
position identity, opposite-side direction, fresh account truth, bounded exits,
duplicate prevention and durable unresolved-exposure escalation.

## 5. Files and code changes

**No existing production source or configuration file changed.** All 216 files
in the V8.4 source manifest still match. `signal_brain.py` is byte-identical.
The ordinary $10 opening minimum, order locks and protection-disabled setting
remain enforced.

Added [test_public_execution_evidence_v8_5.py](../../algo-trading-bot/test_public_execution_evidence_v8_5.py):
39 offline anti-false-positive regressions. The new bounded readers and evidence
classifier are confined to this report directory. They use `/info` only, have
no SDK signer or exchange-action path and do not expand production query
allowlists. The classifier's separate hash is bound to the full regression
receipt because this documentation helper is outside the active source hash.

The required legacy occurrence inventory was refreshed. Its large existing
legacy reference/cache population is not a new production dependency.

## 6. Verification

| Check | Result |
|---|---|
| Full baseline plus new regressions | **1,577 passed; 0 failures, 0 errors, 0 skipped** |
| Focused certification/partial-fill/evidence tests | **137 passed** |
| Phase-0 order lockouts | PASS |
| Frozen strategy: file, 8 methods, 32 parameters | PASS |
| Before/after regression active source hash | Identical |
| Before/after classifier hash | Identical |
| Read-only SQLite integrity and checkpoint checksums | PASS |
| New actual signatures/orders/cancels/transfers | **0** |

The new tests reject larger original orders with tiny fills, incomplete or
interleaved fill chains, duplicates, incorrect direction/token/order identity,
rejected stops, ambiguous statuses and misleading acceptance-only evidence.
They keep manual-close evidence separate from stop evidence and verify that
observational proof cannot unlock the production minimum checks. The full
suite retains partial-entry/exit, protection rejection, uncertain-order,
duplicate prevention and restart-containment regressions.

An initial new test had a fixture-construction error (38 passed, 1 failed).
Its receipt is preserved; the fixture was corrected before the successful
137-test and full runs. Sandbox-only network failures are also preserved
separately from successful external public reads. No failure was relabeled a
pass or overwritten.

## 7. Fresh read-only account and signer preflight

Account observation: **12 October 2026, 11:43:13–11:43:27 UTC
(17:13:13–17:13:27 IST), after the full regression completed**.

| Item | Observed result |
|---|---|
| Team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Approved API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` |
| Network / venue | Hyperliquid testnet / `par` |
| Collateral | 1,000,000 USDPR; this total is not substituted for free margin |
| Account mode | unifiedAccount |
| Exchange leverage | All 10 runtime markets: 1x CROSS |
| Positions / frontend orders, before and after | 0 / 0 |
| Returned actual `par` fills / funding | 0 / 0 in the observer's queried history |
| API approval | Valid; expiry `1806859924898` ms |
| Reported account action budget | 13 used of 10,000 |
| Public read budget | Healthy; 608 of 1,200 weight with 120 reserved |
| Clock | Healthy; {account['clock_final']['fresh_confirmations']} fresh confirmations; final estimated offset {account['clock_final']['offset_ms']} ms |
| Local key derivation / nonce exclusion | MATCH / HEALTHY_LOCAL; no signature or nonce allocation |
| Sole signer across other computers | {'Human confirmed this Mac only; local check cannot independently inspect remote hosts' if flags['SOLE_SIGNER_HOST_CONFIRMED'] else 'Not confirmed; the informational question remains unanswered in this evidence'} |

Reconciliation used the existing `CertificationRecovery` and actual reported
fills/funding from time zero through the observation. It saved a durable
checkpoint, closed/reopened its SQLite journal and reconciled again. Both
retained snapshots have valid checksums, matching source identities and a clean
final shutdown. This is a **separate read-only observer journal**. It grants no
execution permit and does not certify funded recovery of an actual position.
Future certification must independently refresh its own live account barrier.
The nonce lease check only proves exclusion on this host/OS user at that moment;
the lease was released afterward.

## 8. Fresh executable liquidity, with honest scope

| Market | Bid | Ask | Spread, bps | One lot at ask, USDPR |
|---|---:|---:|---:|---:|
{market_table}

Each book was fresh and two-sided at its recorded read. These snapshots expire
and are not standing trade offers. All three still have sub-$10 lot values.
BTC had a thin best bid and HYPE a thin best ask relative to the existing 10%-of-BBO
certification depth limit; two-sided liquidity alone is not a sizing pass.
ETH had better displayed depth for a future small test, but it is **not
currently execution-eligible** while small-stop handling remains unverified.
No strategy signal or 300-candle admission was claimed from these book reads.

## 9. Readiness and account truth

```ini
{flag_text}
EXECUTION_MODE = PAPER
ALLOW_LIVE_ORDERS = false
PROTECTION_ENABLED = false
```

`PARTIAL_FILL_EXIT_READY` stays false because the production-safe residual
close/protection path has not been established and implemented. Configured
protection is not accepted or tested exchange-side protection. Public wallets'
PnL is not Anchorium PnL. There is no certified actual Anchorium round-trip
profit or loss, and no funded LONG, SHORT or exposed-position recovery result.

VWAP, EMA, ATR, the 0.40% volatility floor, 15 bps spread ceiling, 300 completed
UTC candles and Top-3 were preserved. No strategy tuning, autonomous activation,
full-wallet trade, repeated-order attempt or recurring task was introduced.

## 10. Single next safe action

**Obtain authoritative `par` clarification or an independently verifiable
accepted below-$10 protective-stop record using the unsent organizer question.**
Keep entry blocked until its placement, exact actual-position coverage and
residual behavior are supported. Then implement only the verified scoped
exception, rerun safety tests and fresh account/liquidity checks, and present
one exact bounded LONG proposal for human approval. No signed order may precede
that approval.

Active source hash: `{current}`.
Regression XML SHA-256: `{tests['xml_sha256']}`.
Brain SHA-256: `bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`.
"""
(OUT/'report.md').write_text(report)
print(json.dumps(dict(verdict=summary['verdict'],tests=summary['tests'],flags=flags,report=str(OUT/'report.md')),indent=2))
