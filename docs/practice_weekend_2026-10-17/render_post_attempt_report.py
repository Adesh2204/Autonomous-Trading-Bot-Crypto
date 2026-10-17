"""Render actual stopped-attempt evidence and the separately tested repair."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
import json,hashlib,time
P=Path(__file__).resolve().parent;IST=ZoneInfo('Asia/Calcutta')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def at(ms):return datetime.fromtimestamp(ms/1000,IST).isoformat()
release=read(P/'freshness_repair_regression_release/test_receipt.json')
if not release.get('passed'):raise RuntimeError('NEW_FULL_PASSING_RELEASE_REQUIRED')
old=read(P/'regression_release/test_receipt.json')
run=P/'authorized_qualification_refresh_2026-10-17_1143'
result=read(run/'result.json');audit=read(run/'post_expiry_terminal_reconciliation/audit.json')
capacity_path=P/'final_capacity_audit/audit.json'
if not capacity_path.exists():capacity_path=P/'post_attempt_capacity/audit.json'
capacity=read(capacity_path)
prep=read(P/'qualification_refresh_2026-10-17_1143/preparation.json')
approval=read(P/'qualification_refresh_2026-10-17_1143/qualification_approval.json')
provenance=P/'qualification_refresh_2026-10-17_1143/human_approval_provenance.json'
preservation=read(P/'post_attempt_preservation_receipt.json');now=time.time_ns()//1000000
summary=read(P/'freshness_repair/pre_repair_release_summary.json')
account=capacity['account_final'];start=approval['approved_ms']
fills=[f for f in account['fills'] if f['timestamp_ms']>=start]
funding=[f for f in account['funding_events'] if f['timestamp_ms']>=start]
assert not fills and not funding and audit['terminal_flat'] and capacity['terminal_flat'] and preservation['passed']
summary.update(status='REPAIRED_OFFLINE_ACTUAL_QUALIFICATION_INCOMPLETE_ENTRY_LOCKED',generated_ms=now,
    source_hash=release['source_hash'],source_hash_after=release['source_hash_after'],
    approved_attempt_source_hash=old['source_hash'],
    regression=dict(passed=release['passed'],totals=release['totals'],
        receipt='freshness_repair_regression_release/test_receipt.json',
        receipt_sha256=sha(P/'freshness_repair_regression_release/test_receipt.json'),
        xml_sha256=release['xml_sha256'],checks_before=release['checks_before'],checks_after=release['checks_after'],
        requirements_sha256=release['requirements_sha256'],runtime_versions=release['runtime_versions']),
    preservation_receipt='post_attempt_preservation_receipt.json',
    preservation_receipt_sha256=sha(P/'post_attempt_preservation_receipt.json'),preserved=preservation['passed'],
    freshness_repair=dict(implemented=True,actual_maximum_age_ms=5000,
        genuine_reacquisition_without_retimestamping=True,immutable_wire_revalidated=True,
        native_typed_scope_only=True,pre_http_error_and_transport_boundary_logging=True,
        additional_tests=27,focused_passes=163,actual_exchange_retest=False),
    worker=dict(status='STOPPED_UNKNOWN_REQUIRES_REVIEW',pid=20311,caffeinate_pid=20312,
        currently_running=False,stop_confirmed_by_process_read=True,accepted_ms=approval['approved_ms'],
        expiry_ms=approval['expires_ms'],signed_attempts=1,actual_signature_created=True,
        exact_signature_count=None,guarded_nonce=1792217834069,key_accessed_by_approved_runtime=True,
        recorded_http_submission_claims=0,confirmed_exchange_orders=0,
        http_boundary_telemetry_available_for_original_attempt=False,blind_retry=False,
        actual_new_fills=[],native_stop_submitted=False,native_protection_qualified=False,
        old_oct15_heartbeat='PAUSED',old_oct16_heartbeat='PAUSED',
        dependency='Local Mac, process, power and internet; no remote failover or automatic restart'),
    qualification=dict(status='CONSUMED_LOCAL_UNKNOWN_NO_RETRY',mandate_id=prep['mandate_id'],proposal=prep['proposal'],
        approval_created=True,accepted_ms=approval['approved_ms'],expiry_ms=approval['expires_ms'],
        human_approval_provenance_sha256=sha(provenance),result_sha256=sha(run/'result.json'),
        raw_receipts_sha256=sha(run/'info_receipts.jsonl'),worker_result_status=result['status'],
        worker_realized_pnl=result['realized_pnl'],worker_realized_pnl_status=result['realized_pnl_status'],
        worker_final_flat=result['final_flat'],worker_two_terminal_flat_readbacks=result['two_terminal_flat_readbacks'],
        independent_post_expiry_account_flat=audit['terminal_flat'],
        independent_post_expiry_readbacks=audit['readbacks'],
        original_cloid='0xac0eea156fcec80986dd67c9057b6ded',local_intent_state='UNKNOWN',
        unknown_resolution_written=False,completion_or_native_proof_created=False),
    current_actual_account=dict(as_of_ms=capacity['final_readbacks'][-1]['observed_ms'],
        positions=[],open_orders=[],two_authoritative_flat_zero_order_reads=capacity['final_readbacks'],
        currentness='Timestamped exchange snapshots; no future signing may rely on cached flatness',
        reported_equity=capacity['account_final']['reported_account_equity']),
    actual_task_accounting=dict(window_start_ms=start,window_end_ms=capacity['finished_ms'],
        buy_fills=[],sell_fills=[],completed_round_trips=0,gross_pnl='0',fees='0',funding='0',net_observed_cashflow='0',
        qualification_realized_pnl_certified=False,max_session_drawdown=None,remaining_authorized_budget=None,
        source='Actual exchange-reported account events during the approved attempt window; no new fills or funding'),
    capacity_audit=dict(path=str(capacity_path.relative_to(P)),source_hash=capacity['source_hash'],source_hash_after=capacity['source_hash_after']),
    observed_capacity=[{k:r[k] for k in ('symbol','observed_ms','one_lot_mark_notional','liquidity_only_quantity','liquidity_only_notional','qualified_unattended_notional')} for r in capacity['markets']],
    blockers=['NEW_LOCAL_UNKNOWN_INTENT_REQUIRES_FORMAL_REVIEW',
        'ACTUAL_NATIVE_TRIGGER_AND_CLOSING_PROOF_NOT_QUALIFIED',
        'SUBMINIMUM_NATIVE_RESIDUAL_SUPPORT_UNVERIFIED',
        'CONSUMED_MANDATE_NO_RETRY_AND_NO_AUTONOMOUS_SESSION_APPROVAL'])
summary['practice_contract'].update(session_id=None,mandate_id=None,approval_deadline_ms=None,acceptance_created=False)
for name in ('final_summary.json','release_summary.json'):(P/name).write_text(json.dumps(summary,indent=2)+'\n')
rows='\n'.join(f"| {r['symbol']} | {r['one_lot_mark_notional']} | {r['liquidity_only_notional']} | 0 |" for r in capacity['markets'])
report=f"""# October 17–18 practice release — final A–I report

Updated {at(now)}. **The approved qualification ran once and stopped with a preserved local UNKNOWN entry. No exchange order/fill is confirmed. Independent reads after signing expiry confirm a flat account and zero open orders. The freshness failure is repaired and tested offline; native and subminimum protection remain unqualified, and trading remains locked.**

## A. Dynamic pricing, actual failure and repair

The approved corridor worked: fresh ask **81,478**, selected immutable BUY IOC limit **81,518**, below the approved **81,605** maximum and within the 5 bps route cap. The original 81,410-versus-81,412 fixed-limit obstacle was not the cause of this stop.

The approved source retained its original readiness snapshot through repeated SDK checks. Source and raw receipt chronology put readiness at approximately 1792217829566; final book receipt was 1792217835092, an age of **5,526 ms**, over the unchanged **5,000 ms** limit. Bid/ask and funding remained within the approved limits. The original executor persisted `ExchangeError`, not the exact exception text; `pre_http_diagnosis.json` explicitly distinguishes the source/timestamp reconstruction from a recorded transport rejection or nontransmission certificate.

The isolated native corridor path now reuses the existing typed signing boundary: genuinely reacquire account/readiness/metadata/book data when needed, rerun central risk/compliance and exact authorization for the **same reserved wire**, then validate the five-second evidence without repeating a serial REST bundle that ages it. Quantity, price, CLOID, permit ownership, global entry lease, nonce, source, expiry and cleanup-time limits remain binding. An UNKNOWN or already transmitted intent cannot use this renewal. Ordinary production and legacy fixed-price paths keep their existing gates. Native trigger placement retains its exact stop checks.

Native transport now records explicit pre-HTTP rejection reason, nonce/CLOID and HTTP start/response/uncertainty boundaries without exporting signatures or keys. **163 focused tests passed**, including 27 new after-nonce reacquisition, changed account/orders/fees/funding/depth/price/source/authority, health, five-second-boundary and diagnostic cases. No new actual-wallet signature or exchange retry was performed to test this repair.

## B. Genuine native-stop and residual evidence

There was **no confirmed entry fill and no native stop placement, acceptance, trigger, child or closing fill** in the actual attempt. Native qualification is INCOMPLETE. The successful historical one-lot IOC close still proves only its scoped full-position IOC recovery; it does not establish native Stop Limit acceptance below 10 TEST USDPR.

[Official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes default position-sized TP/SL, fixed explicit sizes, parent-child cancellation risks and potentially unfilled triggered limits. [The API schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) exposes `positionTpsl`; the required registered-`par` subminimum exception remains unverified. The earlier bounded audit of six public accounts/three histories found no qualifying native record; two histories were truncated at 2,000 rows. This is not a venue-wide prohibition finding. All eight requested questions remain documented in `native_stop_findings.json`. The partial-fill guard remains enabled.

## C. Latest observed LONG capacity

Refreshed {at(capacity['context_observed_ms'])}. Genuine runtime metadata, finite both-side books and 1x account data were used. Liquidity-only estimates retain 10% participation and are **not executable authority**; they can become stale and exclude unresolved native/partial and strategy gates. Below-minimum estimates cannot support an opening order.

| Market | One-lot mark value, TEST USDPR | Liquidity-only LONG notional | Qualified unattended notional |
| --- | ---: | ---: | ---: |
{rows}

All ten one-lot mark values remain below 10. A correct LONG stop limit below its trigger/current mark is lower still. No permitted market currently avoids the minimum-lot native-stop issue. Qualified unattended capacity remains **0**; the new local UNKNOWN entry is an additional lock. No new market, precision change, liquidity enlargement or leverage change was introduced.

## D. Full regression and integrity

**Latest repaired release: {release['totals']['tests']} passed, zero failures/errors/skips.** Full 2,726-test prior release plus 27 new tests. Source before/after: `{release['source_hash']}` / `{release['source_hash_after']}`. XML SHA-256: `{release['xml_sha256']}`. Receipt SHA-256: `{summary['regression']['receipt_sha256']}`. Requirements SHA-256: `{release['requirements_sha256']}`. Strategy freeze and Phase-0 passed before and after; SDK 0.24.0 and dependency pins match.

The actual attempt used the separately preserved **2,726-test** release, source `{old['source_hash']}`, XML `{old['xml_sha256']}`. Its approval/source/XML and raw account proof were not replaced by the newer offline release. The modified source has not been retested on the exchange.

Post-attempt preservation passed: original strategy/configs/BUY/SELL proof files, all original raw intent rows and old immutable UNKNOWN certificate remain intact. SQLite integrity and checkpoint checksums pass. The actual nonce legitimately advanced once to **1792217834069** during the approved signing attempt; it was not rolled back. All actual-account database dumps and the new UNKNOWN row remained unchanged throughout the subsequent engineering/tests. See `post_attempt_preservation_receipt.json` and `change_manifest.json`.

## E. Exact approvals and session scope

Mandate `206517755e77aafd6c989f0129b5fd14bd784cafed50c95a48324d150f94e977` expired before execution; the later genuine response was preserved without backdating or execution.

New mandate **`{prep['mandate_id']}`** was genuinely accepted at **{at(approval['approved_ms'])}**, within its decision deadline. Authority expired at **{at(approval['expires_ms'])}**. Human-response provenance SHA-256: `{sha(provenance)}`. This authorized exactly one 0.0002 BTC LONG test, 1x CROSS, <=25 TEST USDPR, fresh ask 81,403–81,565, maximum BUY 81,605, <=5 bps entry route, fee ceiling 0.09%, funding cap 0.0001989106, <=15 bps spread and <=10% both-best-book participation. Full-size stop trigger/limit were 80,620/80,217; one-lot partial entry would be aborted by the scoped exact-position reduce-only IOC. Cleanup required >=80,217, <=20 bps slippage, <=2 resolved IOC attempts, <=1 owned cancellation round and <=6 signed actions. The 10 TEST USDPR budget was not a guaranteed loss cap. No stop/cleanup was needed or submitted because no exchange entry was established.

That mandate is **consumed and expired**. No new qualification proposal or automatic approval is being generated after the UNKNOWN outcome. The Oct17–18 contract remains implemented but has **no autonomous session ID, accepted mandate, approval deadline, authorized bankroll or running signer**. Its proposed 20,000 bankroll, one global position, two total entry attempts, 1x, 0.5% trade risk, 1% carried session loss, <=24-hour signing duration, October 18 23:57 IST absolute maximum, 15-minute entry cutoff and five-minute scheduled risk-close buffer remain unchanged. No midnight reset or renewal is allowed.

## F. Exact local command and execution evidence

The actual command, verified against PID/source/proposal/approval/output identity, was:

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/run_native_qualification.py execute \\
  --proposal docs/practice_weekend_2026-10-17/qualification_refresh_2026-10-17_1143/proposal.json \\
  --approval docs/practice_weekend_2026-10-17/qualification_refresh_2026-10-17_1143/qualification_approval.json \\
  --test-receipt docs/practice_weekend_2026-10-17/regression_release/test_receipt.json \\
  --output docs/practice_weekend_2026-10-17/authorized_qualification_refresh_2026-10-17_1143
```

**Do not rerun this command.** It ran from this cloned repository and consumed its invocation. Autonomous `anchorium_cli.py start --authorized` was not launched; a complete runnable command cannot name a real accepted autonomous session or validated native proof yet. `operator_commands.md` describes the stopped invocation and gated future CLI. The standalone runtime requires no Codex or paid LLM; local Mac/process/power/internet availability remains necessary.

## G. Actual stopped worker and account truth

Worker **20311**, process-bound caffeinate **20312**, both verified stopped. One signed entry attempt allocated nonce **1792217834069** and original CLOID **`0xac0eea156fcec80986dd67c9057b6ded`**. An actual guarded signature was created; exact total signature count was not logged. The durable wire was 0.0002 BTC at 81,518. It became local UNKNOWN with no numeric exchange order ID. There are **zero recorded transmission claims**. The old native transport lacked complete pre-HTTP telemetry; missing records alone are not promoted into a new nontransmission certificate. No blind resubmission, cancel, SELL, restart, limit widening or source change occurred while the worker was alive.

The worker returned `{result['status']}` / `{result['error']}`. Its own final-flat/completion flags remain false because the local intent was unresolved. Independent unsigned reconciliation separately established account truth twice after the signing expiry: **{at(audit['readbacks'][0]['observed_ms'])}** and **{at(audit['readbacks'][1]['observed_ms'])}**, each with no positions/orders and `unknownOid` for the exact original CLOID. A later capacity/account audit again recorded two flat/zero-order reads, latest **{at(capacity['final_readbacks'][-1]['observed_ms'])}**. These are timestamped snapshots, not a completed round trip or permission to clear the entry lock.

Original raw receipt errors: zero; no actual HTTP429 evidence. Local rolling-rate waits/backoff events are not labeled as venue HTTP429. Recovery was bounded and used the original identity; no next-day worker or heartbeat was started. Both old heartbeats remain PAUSED. Caffeinate is not remote failover or an uptime guarantee.

## H. Actual fills, fees, funding and P&L

The approved attempt's actual account window contains **zero new BUY fills, SELL fills, fees or funding events**, and zero completed round trips. Observed account cashflow change is **0 TEST USDPR**. The raw worker's qualification P&L remains null / `REALIZED_PNL_NOT_CERTIFIED`; no successful or profitable qualification is claimed. No native/exit completion proof was created. Maximum session drawdown and remaining autonomous risk budget are null because no autonomous session existed.

The prior **October 15** trade remains separate: BUY 0.0002 @81,512, order 62755970305 / fill 800659111758533 / fee 0.014672; SELL @81,909, order 62805581662 / fill 260274449763192 / fee 0.014743. Gross +0.0794, total fees 0.029415, actual funding +0.000527, **net +0.050512 TEST USDPR**. It is not October 17 income. Original proofs are untouched; no organizer whitelist/reset claim is made.

## I. Specific blocker and next valid action

The freshness failure is repaired and independently tested offline. The actual consumed attempt remains locally UNKNOWN, despite authoritative flat/no-fill account snapshots. The new row must receive formal independent review from the original signed-source, nonce, transmission-claim and raw exchange evidence; it must not be deleted or inferred terminal merely from `unknownOid` or flatness. The original immutable certificate is still valid only for its original historical row.

Native Stop Limit trigger/child/closing and subminimum-residual support are also still unqualified. **Further signing and autonomous activation remain blocked.** A future admissible test requires that lifecycle review, genuine native/residual prerequisites as applicable, a source-matching release and a separately presented exact human decision. The consumed mandate is never resumed. No future profit, native trigger, specified trade count, loss cap or uninterrupted operation is guaranteed.
"""
for name in ('final_report.md','implementation_report.md','post_attempt_report.md'):(P/name).write_text(report)
(P/'current_status.json').write_text(json.dumps(dict(status=summary['status'],updated_ms=now,
    current_source_hash=release['source_hash'],latest_full_test_count=release['totals']['tests'],
    worker=summary['worker'],qualification=summary['qualification'],blockers=summary['blockers']),indent=2)+'\n')
print(json.dumps(dict(status=summary['status'],tests=release['totals']['tests'],source_hash=release['source_hash'],
    actual_account_flat=audit['terminal_flat'],new_local_unknown_preserved=True),indent=2))
