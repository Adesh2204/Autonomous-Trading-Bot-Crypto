"""Render this repair's report from completed real local/public observations."""
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import hashlib,json,time,xml.etree.ElementTree as ET

OUT=Path(__file__).resolve().parent
read=lambda p:json.loads((OUT/p).read_text())
sha=lambda p:hashlib.sha256((OUT/p).read_bytes()).hexdigest()
release=read('regression_release/test_receipt.json')
pre=read('final_preflight/preparation.json')
preserve=read('preservation_receipt.json')
unknown=read('unknown_forensic_verdict.json')
audit=read('original_order_audit/readback.json')
assert release['passed'] is True and preserve['passed'] is True
assert release['source_hash']==release['source_hash_after']==pre['source_hash']==pre['source_hash_after']==preserve['source_hash']
assert pre['status']=='PREFLIGHT_BLOCKED' and pre['signatures']==pre['orders_submitted']==0
assert not (OUT/'final_preflight/proposal.json').exists()
assert not (OUT/'final_preflight/required_acknowledgments.json').exists()
assert unknown['raw_row_unchanged'] and unknown['effective_newer_unknown'] and not unknown['new_certificate_applied']
assert len(audit['readbacks'])==2 and all(x['stable'] for x in audit['readbacks'])
assert 'candidate_proposal' in pre and pre['central_validation']['allowed']

def instant(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat(timespec='milliseconds')

ctx=pre['context'];q=ctx['quote'];r=ctx['readiness'];p=pre['candidate_proposal']
test_totals={}
for name in ('reproduced_defects','repair_tests_final','focused_final','signing_boundaries'):
    test_totals[name]={k:sum(int(s.attrib.get(k,0)) for s in ET.parse(OUT/(name+'.xml')).getroot().iter('testsuite'))
        for k in ('tests','failures','errors','skipped')}
summary=dict(
    verdict='BLOCKED_EXTERNAL_EVIDENCE',engineering_verdict='OFFLINE_SOFTWARE_REPAIR_VERIFIED',
    native_protection_verdict='VENUE_UNQUALIFIED',task='Practice par UNKNOWN and native Stop Limit repair',
    generated_ms=time.time_ns()//1000000,starting_source=preserve['baseline_source'],source_hash=release['source_hash'],
    git_branch='codex/par-native-qualification-2026-10-18',source_files_changed=preserve['changes'],
    execution_mode='PAPER',allow_live_orders=False,signing_authority='NONE',
    actual_wallet_signatures=0,actual_exchange_writes=0,approval_created=False,autonomous_worker_launched=False,
    full_regression=release['totals'],xml_sha256=release['xml_sha256'],focused_tests=test_totals,
    strategy_freeze_before=release['checks_before']['strategy_freeze'],strategy_freeze_after=release['checks_after']['strategy_freeze'],
    phase0_before=release['checks_before']['phase0'],phase0_after=release['checks_after']['phase0'],
    prior_2850_receipt_preserved=preserve['protected']['docs/pas_migration_2026-10-17/regression_release_v2/test_receipt.json'],
    pas_strategy_capital_authorization_limits_unchanged=preserve['pas_strategy_capital_authorization_limits_unchanged'],
    original_databases=preserve['databases'],unknown=dict(cloid=unknown['original_cloid'],nonce=unknown['original_nonce'],
        original_source=unknown['original_signing_source'],verdict=unknown['verdict'],original_row_unchanged=True,
        earlier_certificate_applies=False,new_certificate_applied=False,
        original_transport_claim_count=len(unknown['recorded_transmission_claims']),
        original_boundary_record_count=len(unknown['original_boundary_records']),
        reconstructed_age_is_original_causal_record=False,readbacks=audit['readbacks']),
    preflight_status=pre['status'],blockers=pre['blockers'],
    preflight_observed_ms=pre['observed_ms'],preflight_finished_ms=pre['finished_ms'],
    account=dict(positions=ctx['positions'],open_orders=ctx['open_orders'],readiness=r['status'],
        account_mode=r['account_mode'],collateral_token=r['collateral_token_name'],collateral=r['collateral'],
        active_asset=ctx['active_asset'],account_ms=ctx['account_ms'],readiness_ms=r['observed_ms']),
    market=q,diagnostic_candidate=p,candidate_is_execution_authority=False,
    prior_native_attempt=pre['prior_qualification'],
    actual_account_accounting=pre['account']['realized'],
    accounting_scope='Only observed historical account events, all verified fills are October 15; no new qualification trade or performance in this task',
    new_verified_qualification_fills=0,new_qualification_realized_pnl=None,
    evidence_request_sent=False,
    dependencies='Local supervision and any later separately approved cleanup depend on this Mac/process/app/power/internet; no server availability or fill guarantee',
    unqualified=['actual par native acceptance/trigger/closing fill','native subminimum residual protection','unattended entries','organizer weekend permission','resolution or authorized isolation of newer UNKNOWN','consumed prior invocation recovery'])

artifacts=['operator_request.md','baseline.json','regression_release/test_receipt.json','regression_release/regression.xml',
    'final_preflight/preparation.json','final_preflight/info_receipts.jsonl',
    'unknown_forensic_verdict.json','original_order_audit/readback.json','original_order_audit/info_receipts.jsonl',
    'preservation_receipt.json','reproduced_defects.xml','repair_tests_final.xml','focused_final.xml','signing_boundaries.xml',
    'RECOVERY_EVIDENCE_REQUEST.txt','SUPERVISED_RUNBOOK.md']
summary['artifact_sha256']={x:sha(x) for x in artifacts}
for name in ('final_summary.json','release_summary.json'):
    (OUT/name).write_text(json.dumps(summary,indent=2)+'\n')

blockers='\n'.join('- `'+x+'`' for x in pre['blockers'])
table='\n'.join('| '+k+' | '+str(v)+' |' for k,v in {
    'Observed (IST)':instant(pre['observed_ms']),
    'Finished (IST)':instant(pre['finished_ms']),
    'Venue / account mode':'TESTNET par / '+r['account_mode'],
    'Positions / open orders':str(len(ctx['positions']))+' / '+str(len(ctx['open_orders'])),
    'USDPR collateral':r['collateral'],
    'BTC leverage':str(ctx['active_asset']['leverage']),
    'Bid / ask':q['bid']+' / '+q['ask'],
    'Best bid / ask BTC depth':q['bid_quantity']+' / '+q['ask_quantity'],
    'Mark / oracle':q['mark']+' / '+q['oracle'],
    'Reported user cross fee':r['fees']['userCrossRate'],
    'Computed par taker fee bound':p['taker_fee_rate'],
    'Observed hourly funding':q['hourly_funding'],
    'Candidate funding ceiling':pre['maximum_abs_funding_rate'],
    'Preview BUY / maximum cap':pre['preview_selected_price']+' / '+pre['maximum_buy_price'],
    'Candidate ask corridor':pre['minimum_ask']+'–'+pre['maximum_ask'],
    'Stop trigger / stop-limit and cleanup floor':p['stop_trigger']+' / '+p['stop_limit'],
    'Selected-price immediate cleanup net, before funding':pre['current_selected_cleanup_net_before_funding'],
    'Planned loss at approved floor, before funding':pre['planned_loss_at_approved_floor'],
    'Maximum funding reserve':pre['maximum_funding_reserve'],
    'Central validation':pre['central_validation']['code'],
    'SQLite integrity':pre['sqlite_integrity']}.items())
age_table='\n'.join('| '+label+' | '+str(stamp)+' | '+str(pre['observed_ms']-stamp)+' | '+str(pre['finished_ms']-stamp)+' |'
    for label,stamp in [('Book timestamp',q['timestamp_ms']),('Mark / funding context',q['mark_timestamp_ms']),
                        ('Account snapshot',ctx['account_ms']),('Readiness including fees',r['observed_ms'])])

report=f'''# Practice par UNKNOWN and native Stop Limit repair — October 18, 2026

**Overall verdict: BLOCKED_EXTERNAL_EVIDENCE.** Demonstrated software repairs are verified offline. The existing unsigned preflight now reports its actual blockers; no trade, key access, actual-wallet signature, acceptance, exchange write or autonomous worker was created. Native protection remains **VENUE_UNQUALIFIED**.

Starting source: `{preserve['baseline_source']}`. Final source: `{release['source_hash']}`. Branch: `codex/par-native-qualification-2026-10-18`. Eight Python files changed relative to the requested starting local release, including two new files and two narrowly adapted existing tests. The prior dirty PAS work was preserved, not reverted. The comparison is to the supplied local release, not Git HEAD.

## Reproduced causes and repairs

The pre-repair reproduction retained six failing test cases in [reproduced_defects.xml](reproduced_defects.xml). They represent these four defects:

| Defect | Exact cause | Implemented repair and evidence |
| --- | --- | --- |
| Native proof export always failed after the newer validator | The native caller passed a `SimpleNamespace` without `dex`; the shared raw-evidence validator accessed that attribute and raised `AttributeError`. | Supply explicit `dex='par'` at the native caller. The shared PAS/long-session evidence validator is untouched. A complete synthetic raw chain passes; missing trigger/fill/flatness or wrong collateral still fails. Synthetic proof files exist only inside temporary test fixtures. |
| Harmless valuation changes broke three stop stages | Preparation, armed readback and definite-rejection snapshot checks compared full `Position` objects, including mark-dependent unrealized PnL/margin values. | Use the existing exposure identity comparison for symbol, quantity, entry and leverage. All freshness, ownership, order and reconciliation checks remain. The three independently reproduced stages now pass without treating quantity changes as harmless. |
| An associated closing fill below the stop floor was accepted | Fill association checked identity, side and size but did not enforce the approved Stop Limit price. | Reject SELL fills below the limit or BUY fills above it with `QUALIFICATION_STOP_FILL_PRICE_CONFLICT`; remain UNKNOWN and unqualified. No alternate cleanup or certificate follows a conflicting fill. |
| Dynamic position TP/SL could be mistaken for the approved fixed-size route | Stop detail validation did not reject `isPositionTpsl=true`. | Reject that readback for this independent fixed-size `grouping='na'` route. No dynamic/zero-size position order or larger size was introduced. |

The actual initial preflight on the requested `d37a392…` release incorrectly reported `AWAITING_EXACT_HUMAN_QUALIFICATION_APPROVAL` despite the newer durable UNKNOWN, consumed native attempt and missing weekend practice permission. It is preserved under [initial_preflight](initial_preflight/preparation.json), including its stale, unused candidate. The repaired `prepare` now inspects the actual journals read-only, retains the older certificate's exact scope, checks checkpoint/SQLite integrity, exposes unresolved intents/management and consumed invocation controls, and reports every known blocker while still obtaining fresh unsigned account/market observations. It writes no proposal/acknowledgment artifacts when blocked. Invalid configuration/release failures now also produce `preparation.json`, with precise safety codes.

The execution builder checks durable prior-state blockers before opening the actual journal, creating the public client, loading keys or allocating a nonce. Practice permission is separately validated and hash-bound through the native authorization checks. Outside the published practice interval, scope/date/hash validation requires an original operator-reviewed organizer record; arbitrary text is not authenticated by a boolean. No such actual permission record was created here. Existing exact approval, cleanup timing, action limits and consumed-attempt barriers remain.

Future native transport boundary records now include actual working source, originally authorized source, exact mandate/configuration identity, team/API public identity, action hash, nonce, expiry and CLOID. A genuine pre-HTTP failure additionally appends an immutable matching intent audit row. It stores no signature/key/payload and never clears an UNKNOWN. These forward-only records improve future causal evidence; they do not backfill the missing original October 17 telemetry.

## Original UNKNOWN verdict

The unresolved order is **`{unknown['original_cloid']}`**, nonce **`{unknown['original_nonce']}`**, original mandate **`{unknown['original_mandate']}`**, original signing source **`{unknown['original_signing_source']}`**. Its exact request is BUY IOC `0.0002 par:BTC` at `81518`. The immutable row is still `UNKNOWN`, OID null, outcome `TRANSMISSION_UNCERTAIN / ExchangeError`.

The older certificate covers **`{unknown['earlier_certified_cloid']}`**, a different source/order. Its checksum and original row are preserved; it has not been reused. Original-order logs contain no explicit causal final-guard rejection, original boundary record or recorded transmission claim for the newer order. The reconstructed `5526 ms` readiness age versus the `5000 ms` threshold is an inference, not an original recorded failure. It cannot support a non-transmission certificate on its own.

Two fresh direct public account/order readbacks at {instant(audit['readbacks'][0]['observed_ms'])} and {instant(audit['readbacks'][1]['observed_ms'])} showed `unknownOid`, no current par position and no current par open orders. These describe current observed account state; they do not resolve the original transmission. The newer row remains in the effective unresolved view. No row, nonce, certificate or global attempt marker was edited. The consumed prior invocation still reports `EMERGENCY_EXIT_REQUIRED`, `do_not_restart=true` and incomplete terminal proof.

Required evidence is precisely listed in [RECOVERY_EVIDENCE_REQUEST.txt](RECOVERY_EVIDENCE_REQUEST.txt): independently verifiable original action/terminal evidence tied to the exact identities, or original explicit pre-HTTP causal evidence with trusted source/transport provenance. Any proposed isolation must independently address shared account/signer/nonce and late-execution risks and be separately authorized. Renaming a DEX or observing flatness is not isolation. The request is a draft and was not sent.

## Final unsigned preflight

Status: **{pre['status']}**. Full machine-readable contents: [final_preflight/preparation.json](final_preflight/preparation.json). Actual blockers:

{blockers}

| Observation / diagnostic value | Actual value |
| --- | --- |
{table}

These are timestamped observations, not current execution authority or a profitable-exit promise. The diagnostic candidate ID is `{pre['mandate_id']}`. There is no emitted executable `proposal.json`, no genuine new approval and no active authority for it. The maximum-price values and loss estimates are diagnostics for the existing controlled test only. They must be reacquired after prerequisites pass; do not copy the earlier unused candidate or stale prices.

| Supporting evidence | Timestamp ms | Age at context observation ms | Age at report completion ms |
| --- | --- | --- | --- |
{age_table}

Independent unavailable fee/funding exchange clocks remain null rather than invented; the table names their local readiness/context observation coverage. Raw request/response receive times remain in [info_receipts.jsonl](final_preflight/info_receipts.jsonl). The worker would still require fresh complete signing checks; a diagnostic read does not waive them. Public rate waits are bounded; a fallback label is not proof of HTTP429. Actual recorded request/error records are retained.

## Native route and readiness limits

The retained wire is an independent fixed-size reduce-only Stop Limit (`grouping='na'`, `isMarket=false`, `tpsl='sl'`), not a position-sized replacement. This is consistent with the [official exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint). Official documentation describes mark-price triggering, fixed versus full-position sizing, and a stop-limit gap that can leave the order resting; see [TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl). These protocol documents do not prove the registered par route has completed a real natural-trigger lifecycle.

The exact `0.0002 BTC` full-entry native experiment and `0.0001 BTC` immediate IOC partial-abort route remain unchanged. Native subminimum residual protection is unqualified. Existing parent/child association, actual fill IDs, partial/remainder accounting, settled-order checks, owned cancellation, source/nonce/clock/rate/account barriers and uncertain-no-retry semantics remain. There is no verified protective stop today.

Offline software readiness is **VERIFIED_ONLY_FOR_TESTED_CASES**. Actual venue capability still requires a separately approved entry, correct stop acceptance, natural trigger, linked actual closing fill within limits, real fees/funding and two authoritative flat/zero-order readbacks. Acceptance alone or IOC cleanup is not native qualification. No autonomous trading promotion follows this repair.

## Validation and preservation

- Full final-source regression: **{release['totals']['tests']} passed, {release['totals']['failures']} failures, {release['totals']['errors']} errors, {release['totals']['skipped']} skipped**. Source stayed identical before/after. [Source-bound receipt](regression_release/test_receipt.json), [XML](regression_release/regression.xml), [log](regression_release/regression.log).
- Six original failures reproduced, then repaired; **39 new deterministic tests pass**. A broader focused run passed **263**; separate signing-boundary tests passed **9**. These supporting counts are not added to or substituted for the full-suite count.
- Production-policy/phase-0 and strategy-freeze checks passed before and after full regression. PAS modules, signal brain/frozen methods/parameters, capital allocation, shared SDK/recovery/journal modules and authorization limits are unchanged relative to the starting release. Two existing synthetic builder tests now explicitly mock calendar permission so their original ordering assertions remain meaningful; no production permission fixture is installed.
- Original 2,850-test receipt and XML remain byte-identical historical evidence. They do not certify changed source. Qualification, nonce and configuration database logical contents are unchanged, SQLite checks report `ok`, recovery checkpoint checksums pass, and original trade proof files remain unchanged. See [preservation_receipt.json](preservation_receipt.json).
- Final XML SHA-256: `{release['xml_sha256']}`. Source, report/input evidence and key artifact hashes are recorded in [final_summary.json](final_summary.json) and [release_summary.json](release_summary.json).

The observed historical account events remain the October 15 BUY `0.0002 @ 81512` (order `62755970305`, fill `800659111758533`, fee `0.014672 USDPR`) and SELL `0.0002 @ 81909` (order `62805581662`, fill `260274449763192`, fee `0.014743 USDPR`). Gross `0.0794`, fees `0.029415`, actual funding `+0.000527`, net **`+0.050512 TEST USDPR`**. Those are preserved historical results, not today's native qualification performance or official competition score. No new qualification fill/P&L was produced.

## Required next decision

Use the exact read-only command and the conditional execution interface in [SUPERVISED_RUNBOOK.md](SUPERVISED_RUNBOOK.md). First obtain admissible UNKNOWN evidence or an independently justified authorized recovery policy, review the consumed native invocation, and establish applicable original organizer permission. Only then prepare new current values and request a fresh exact human approval. This repair neither asks for nor creates an approval while hard blockers remain. No restart/reset, broader scope, extended authorization, loss fallback, PAS change or autonomous activation was made.

Mac/process/app/power/internet remain dependencies. A local interruption can prevent observation and bounded cleanup; the stop-limit itself cannot guarantee a fill or cap a gap loss. The original frozen strategy and PAPER/false lockouts remain in force.
'''
(OUT/'IMPLEMENTATION_REPORT.md').write_text(report)
summary['artifact_sha256']['IMPLEMENTATION_REPORT.md']=sha('IMPLEMENTATION_REPORT.md')
for name in ('final_summary.json','release_summary.json'):(OUT/name).write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(dict(verdict=summary['verdict'],source_hash=summary['source_hash'],tests=release['totals'],report=str(OUT/'IMPLEMENTATION_REPORT.md'))))
