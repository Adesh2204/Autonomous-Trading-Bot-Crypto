"""Report only; never assemble a signer, acceptance or trading worker."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
import hashlib,json,time

P=Path(__file__).resolve().parent;ROOT=P.parents[1];IST=ZoneInfo('Asia/Calcutta')
def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def at(ms):return datetime.fromtimestamp(ms/1000,IST).isoformat() if ms is not None else 'not created'
release=read(P/'regression_release/test_receipt.json')
if not release.get('passed'):raise RuntimeError('MATCHING_PASSED_FULL_RELEASE_REQUIRED')
audit=read(P/'public_evidence/audit.json');preserve=read(P/'preservation_receipt.json')
selection=P/'current_qualification_preparation.json'
prep_path=(P/read(selection)['path']).resolve() if selection.exists() else P/'qualification_proposal/preparation.json'
if not prep_path.resolve().is_relative_to(P.resolve()):raise RuntimeError('PROPOSAL_MUST_REMAIN_IN_TASK_EVIDENCE')
prep=read(prep_path) if prep_path.exists() else dict(status='NOT_PREPARED')
prior_response_path=P/'qualification_proposal/approval_response_disposition.json'
prior_response=read(prior_response_path) if prior_response_path.exists() else None
now=time.time_ns()//1000000
summary=dict(status='ENGINEERING_PASSED_QUALIFICATION_REQUIRES_NEW_EXACT_HUMAN_DECISION',
    generated_ms=now,execution_mode='PAPER',allow_live_orders=False,
    source_hash=release['source_hash'],source_hash_after=release['source_hash_after'],
    regression=dict(passed=release['passed'],totals=release['totals'],
        receipt='regression_release/test_receipt.json',receipt_sha256=sha(P/'regression_release/test_receipt.json'),
        xml_sha256=release['xml_sha256'],requirements_sha256=release['requirements_sha256'],
        runtime_versions=release['runtime_versions'],checks_before=release['checks_before'],checks_after=release['checks_after']),
    preserved=preserve['passed'],preservation_receipt_sha256=sha(P/'preservation_receipt.json'),
    pricing=dict(mode='NATIVE_CURRENT_ASK_CORRIDOR_IOC_V2',reference_relative_adverse_bps='10',
        adverse_absolute_cap='100',reference_relative_favourable_bps='10',favourable_absolute_cap='100',
        per_wire_slippage_bps='5',quantity='0.0002',mandate_mutation_allowed=False,
        failed_preflight_consumes_invocation=True,unknown_retry_allowed=False),
    native_protection=dict(qualified=False,small_native_stop_verified=False,position_tpsl_par_subminimum='UNKNOWN',
        actual_stop_submission_this_task=False,partial_fill_guard_unchanged=True,report='native_stop_findings.json'),
    observed_capacity=[{k:r[k] for k in ('symbol','observed_ms','one_lot_mark_notional','liquidity_only_quantity','liquidity_only_notional','qualified_unattended_notional')} for r in audit['markets']],
    current_actual_account=dict(as_of_ms=audit['final_readbacks'][-1]['observed_ms'],
        two_authoritative_flat_zero_order_reads=audit['final_readbacks'],positions=[],open_orders=[],
        currentness='Snapshot only; mandatory fresh reads before any signing',
        reported_equity=audit['account_final']['reported_account_equity']),
    practice_contract=dict(implemented=True,mode='EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1',
        session_id=None,mandate_id=None,approval_deadline_ms=None,acceptance_created=False,
        network='testnet',dex='par',directions=['LONG'],maximum_signing_duration_ms=86400000,
        latest_possible_expiry_ist='2026-10-18T23:57:00+05:30',maximum_entry_attempts=2,
        maximum_global_positions=1,leverage=1,proposed_bankroll='20000',authorized_bankroll=None,
        session_loss_fraction='.01',per_trade_risk_fraction='.005',signed_actions_maximum=12,
        owned_cancellation_rounds_maximum=2,entry_cutoff_before_expiry_ms=900000,
        scheduled_risk_close_before_expiry_ms=300000,midnight_resets=False,automatic_renewal=False,
        native_and_partial_evidence_required=True,short_authorized=False),
    worker=dict(status='NOT_STARTED',pid=None,actual_exchange_writes=0,actual_wallet_signatures=0,
        key_accessed=False,observer_substituted_for_trading=False,paid_llm_runtime_required=False,
        old_oct15_heartbeat='PAUSED',old_oct16_heartbeat='PAUSED',
        dependency='Local Mac, process, power and internet; sleep prevention is not failover'),
    actual_task_accounting=dict(window_start_ms=read(P/'baseline.json')['created_ms'],window_end_ms=now,
        buy_fills=[],sell_fills=[],completed_round_trips=0,gross_pnl='0',fees='0',funding='0',net_realized='0',
        source='No execution in this task; account audit returned only prior Oct15 events',
        max_session_drawdown=None,remaining_authorized_budget=None),
    prior_actual_oct15=dict(buy_order='62755970305',buy_fill='800659111758533',buy_quantity='0.0002',
        buy_price='81512',entry_fee='0.014672',sell_order='62805581662',sell_fill='260274449763192',
        sell_quantity='0.0002',sell_price='81909',exit_fee='0.014743',gross='0.0794',
        total_fees='0.029415',funding='0.000527',net='0.050512',collateral='TEST USDPR',
        organizer_whitelist_or_reset_evidence=False),
    prior_qualification_response=prior_response,
    qualification=dict(status=prep['status'],preparation=str(prep_path.relative_to(P)),mandate_id=prep.get('mandate_id'),proposal=prep.get('proposal'),
        approval_deadline_ms=prep.get('approval_deadline_ms'),authorization_duration_ms=300000,
        approval_created=False,preparation_sha256=sha(prep_path) if prep_path.exists() else None,
        requires_explicit_unqualified_native_supervised_test_exception=True),
    blockers=['ACTUAL_NATIVE_TRIGGER_PROTECTION_NOT_QUALIFIED',
        'SUBMINIMUM_NATIVE_RESIDUAL_PROTECTION_UNVERIFIED_FOR_ALL_TEN_RUNTIME_MARKETS',
        'NO_NEW_EXACT_HUMAN_QUALIFICATION_EXCEPTION_OR_AUTONOMOUS_SESSION_APPROVAL'],
    no_guarantee='Offline tests cannot guarantee a venue fill, a loss cap, a profitable trade or uninterrupted operation.')
for name in ('release_summary.json','final_summary.json'):(P/name).write_text(json.dumps(summary,indent=2)+'\n')
rows='\n'.join(f"| {r['symbol']} | {r['one_lot_mark_notional']} | {r['liquidity_only_notional']} | 0 |" for r in audit['markets'])
q=prep.get('proposal')
qualification='No qualifying proposal was generated. '+prep.get('blocker',prep['status'])
prior_note=''
if prior_response:
    prior_note=f"Previous mandate `{prior_response['mandate_id']}` expired: approval was required by {at(prior_response['approval_deadline_ms'])}; execution was checked at {at(prior_response['response_observed_ms'])}, past even its latest possible five-minute expiry. Actual click time is unavailable. The genuine response is preserved; no backdated acceptance, key access, signature, order or execution invocation occurred. Its response cannot authorize the new mandate below.\n\n"
if q:
    qualification=f"""New **supervised qualification** mandate: `{prep['mandate_id']}`. Approval deadline: **{at(prep['approval_deadline_ms'])}**. No acceptance exists.

- One TESTNET `par:BTC` LONG BUY IOC, exactly **{q['quantity']} BTC**, maximum notional {q['max_notional']} TEST USDPR and **1x CROSS**.
- Initial bid/ask {q['reference_bid']} / {q['reference_ask']}. Approved current-ask corridor **{q['minimum_ask']}–{q['maximum_ask']}**; maximum BUY limit **{q['maximum_buy_price']}**. Each actual wire is rounded from its fresh ask with at most **5 bps** slippage; it is frozen before durable intent/SDK signing. The immutable proposal permits neither widening nor repricing an uncertain submission.
- Maximum adverse and favourable movements are separately the smaller of 10 bps and 100 USDPR/BTC, with runtime rounding inward. Fresh spread <=15 bps; exact quantity <=10% of both best bid and ask quantities; fresh source, fee, funding, margin, account, clock, rate and sole signer/nonce gates remain mandatory.
- Computed taker fee ceiling **{D(q['taker_fee_rate'])*100}%**, absolute current funding-rate ceiling **{q['maximum_abs_funding_rate']}**. Worst approved one-boundary funding reserve **{prep['maximum_funding_reserve']}** TEST USDPR is an estimate, not a cashflow.
- Full two-lot entry uses one independent, fixed-size reduce-only SELL Stop Limit: mark trigger **{q['stop_trigger']}**, limit/floor **{q['stop_limit']}**. This does not claim `positionTpsl` or subminimum native support.
- Exactly 0.0001 BTC partial entry is immediately aborted with the separately approved exact-position reduce-only IOC path; no small native stop is placed. All cleanup prices must remain >=**{q['exit_bound']}**, with <=20 bps route slippage, <=2 resolved IOC cleanup attempts, <=1 owned cancellation round and <=6 signed actions total. Uncertain order/child/cancellation halts competing submissions.
- Estimated immediate cleanup net at the current selected BUY limit: **{prep['current_selected_cleanup_net_before_funding']} TEST USDPR**, before funding. At the maximum approved BUY limit: **{prep['expected_immediate_cleanup_net_before_funding']}**. Planned loss at the floor, including fees: **{prep['planned_loss_at_approved_floor']}**, plus the conservative funding reserve, within the **10 TEST USDPR test budget**. This budget is not a guaranteed loss cap.
- Authority lasts at most **five minutes after genuine acceptance**; a natural trigger may be observed for at most 120 seconds, shortened to reserve cleanup time. No forced trigger. Accepted-but-untriggered native protection remains INCOMPLETE. A rejected/unfilled/partial/uncertain order, gap or outage may leave exposure.

The approval must explicitly allow this one supervised test while native protection is still unqualified. The request also says “Do not create new BUYs while actual native protection remains unqualified”; no BUY may proceed without that narrow, exact human exception. It grants no autonomous or future trading authority. Wallets: team `{q['team_wallet']}`; API `{q['api_wallet']}`; this Mac is the sole signer host. The consumed `aac5cd9405582382d7e79d355853211751bef350ffd45e653ae1f487e01437a0` is preserved and will not be rerun."""
report=f"""# October 17–18 practice release — engineering and qualification report

Generated {at(now)}. **Engineering release passed; autonomous trading has not started. Native Stop Limit trigger/closing and subminimum-residual protection remain unqualified.** PAPER/false and the frozen strategy are unchanged. No actual-wallet signature, order or acceptance was created in this task.

## A. Dynamic pricing and tests

The previous approved cap 81,410 could not buy a fresh ask of 81,412. The new versioned corridor binds the initial ask, permitted movement and hard maximum BUY price before approval. One fresh correctly rounded IOC price is selected before reserving its durable intent. Final signing checks validate that same wire against fresh market/account data. Movement beyond either bound, deteriorated fees/funding/depth or stale evidence blocks it; no mandate mutation, uncertain retry or duplicate entry is permitted. Even a failed public preflight consumes this new invocation and requires a new human decision.

28 new corridor tests cover the previous small crossing, both corridor edges, inward rounding, independent bps/absolute caps, liquidity/fees/funding, stale account/quotes, leverage, exact approval, expiry, immutable durable wires, duplicate calls and consumed-preflight restart prevention. 23 new practice-contract tests cover dates, <=24h scope, expiry, revocation, unchanged risk caps, midnight carry and missing evidence. The earlier 151-test focus passed before adding the final consumption test; all 51 new tests are also in the full regression below. All signatures in these tests use isolated offline fixtures.

## B. Native Stop Limit and residual findings

[Official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes default position-sized TP/SL, fixed explicit sizes, parent-child cancellation risks and the possibility of an unfilled triggered limit. [The API schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) exposes `positionTpsl`; it does not establish the required `par` subminimum exemption. The pinned SDK is 0.24.0. No unproved zero-size sentinel or native-minimum bypass was introduced.

The unsigned audit made {audit['requests']} bounded /info requests with {len(audit['errors'])} recorded errors: ten permitted markets, six public accounts and three histories. Two histories reached the 2,000-row bound. No native candidates or actual native parent/child closing proof appeared. This is limited evidence, not proof that the venue prohibits position-associated small stops. See `native_stop_findings.json` for all eight requested questions and exact scope.

The historical exact one-lot IOC SELL is preserved; it proves only that scoped IOC recovery path. The supervised two-lot test can investigate an ordinary-minimum full-size native stop and safely attempt the authorized one-lot abort. Even successful full-size trigger proof alone cannot qualify unattended one-lot native protection. Existing partial-fill guards remain active.

## C. Current observed LONG capacity

Snapshot {at(audit['context_observed_ms'])}; ages grow after capture and this table is not an executable quote. Liquidity-only estimates enforce 10% both-side best-book/raw depth and 1x observed capacity, capped at 1,000; they exclude pending native/partial and full strategy gates. Values below 10 cannot satisfy an opening minimum.

| Market | One-lot mark value, TEST USDPR | Liquidity-only LONG notional | Qualified unattended notional |
| --- | ---: | ---: | ---: |
{rows}

Every runtime minimum lot is below 10 at the observed mark. A valid LONG SELL stop below mark with its limit below trigger is lower still. No permitted alternative market currently avoids that one-lot native minimum issue. Supported unattended capacity is therefore **0**. A 20,000 bankroll is a proposal, and larger desired notionals are research targets.

## D. Regression, source and preservation

**{release['totals']['tests']} passed; {release['totals']['failures']} failures, {release['totals']['errors']} errors, {release['totals']['skipped']} skipped.** Full original 2,675 baseline plus 51 new tests. Source before/after: `{release['source_hash']}` / `{release['source_hash_after']}`. Regression XML SHA-256: `{release['xml_sha256']}`. Receipt SHA-256: `{summary['regression']['receipt_sha256']}`. Requirements SHA-256: `{release['requirements_sha256']}`. Strategy freeze and Phase-0 passed before and after. SDK 0.24.0 and all dependency pins match local diagnostics.

Preservation receipt passed: original strategy/proofs/configs/locks unchanged; all three actual-account SQLite logical dumps unchanged, integrity OK; both recovery checkpoint checksums valid; raw historical intents and immutable UNKNOWN certificate preserved. Actual nonce remains 1792082604141. The public evidence audit ran concurrently with engineering, so its before/after source hashes differ; it is explicitly not stable-source execution certification. Final release and new proposal must match the stable hash above. The legacy dependency occurrence inventory was refreshed.

## E. New exact qualification and autonomous session scope

{prior_note}
{qualification}

The new `EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1` contract is implemented separately from the expired October 16 contract. A future exact autonomous mandate may start/accept October 17, end October 18, last <=24h and never exceed October 18 23:57 IST. Entries stop 15 minutes before expiry; scheduled risk closure begins five minutes before expiry; signing and owned recovery end at hard expiry. It carries attempts, allocation, realized P&L, peak equity and drawdown through midnight. TESTNET `par`, LONG only, one global position, two total entry attempts, 1x, <=0.5% trade risk, <=1% session loss, <=12 signed actions and <=2 owned cancellation rounds remain fixed. Observation can continue without extending signer authority. No Oct19 rollover.

**No executable autonomous session ID, mandate ID, approval deadline, acceptance or authorized bankroll exists**, because native and partial-residual prerequisites fail. These fields remain null in the saved summary. No fake session ID was invented to fill this report.

## F. Local terminal commands

CLI grammar and local `doctor` were verified with the matching source. The standalone application has no LLM runtime dependency. The saved `operator_commands.md` gives diagnostics, qualification and future session commands. A complete verified autonomous execution command cannot yet name a real accepted session or validated native proof; the future command is explicitly a gated template and has not been executed. The user need not type or edit anything: ordinary commands will be performed after valid exact consent and prerequisites.

## G. Worker and exchange execution evidence

Actual trading worker **NOT STARTED**, PID null. Actual orders/signatures this task: **0 / 0**. No observer was substituted for trading. Process inspection identified only the offline regression worker, not an execution-enabled worker. Both old heartbeats are PAUSED. Fresh mandatory account/source/book/fee/funding/nonce checks remain necessary after any approval.

The account was authoritatively flat with zero open orders twice at {at(audit['final_readbacks'][0]['observed_ms'])} and {at(audit['final_readbacks'][1]['observed_ms'])}. This is timestamped snapshot evidence, not a currentness guarantee. Actual account equity was 1,000,000.050512 TEST USDPR with margin used zero. There is no verified protective stop. Mac/process/power/internet interruption can stop local supervision; caffeinate does not guarantee availability or remote failover.

## H. Actual fills, fees, funding and P&L

This task: zero submitted orders, BUY/SELL fills and completed round trips. Realized P&L, trading fees and funding attributable to its nonexistent execution are **0 TEST USDPR**. No autonomous session drawdown or remaining authorized budget is asserted; those fields are null. Offline results are not real earnings.

The existing **October 15** trade remains separately verified: BUY 0.0002 BTC @81,512, order 62755970305, fill 800659111758533, fee 0.014672; SELL @81,909, order 62805581662, fill 260274449763192, fee 0.014743. Gross +0.0794, total fees 0.029415, reported funding +0.000527, **net +0.050512 TEST USDPR**. The new public audit recovered these same prior events; they are not October 17 earnings. Both original proof files are preserved. No organizer whitelist/reset evidence is claimed.

## I. Exact blocker and next action

The small fixed-price approval failure is repaired and offline verified. Genuine native Stop Limit trigger/child fills and subminimum-residual native support are still missing. The next admissible execution is only the exact supervised qualification above, after a genuine new approval explicitly permits that narrow BUY exception and loss-making cleanup. No uncertain retry, widened price, revived approval, silent stop bypass, automatic session renewal or guaranteed profit is permitted.

After any approved test: preserve actual parent/child/fill IDs, fees/funding and real net P&L; require two authoritative flat/zero-order reads. If the stop is accepted but never naturally triggers, record INCOMPLETE, perform only authorized settled-order cleanup and request a new human decision. Autonomous LONG activation remains blocked until all real native/partial prerequisites and a separate exact session approval exist.
"""
for name in ('final_report.md','implementation_report.md'):(P/name).write_text(report)
print(json.dumps(dict(status=summary['status'],tests=release['totals']['tests'],source=release['source_hash'],qualification=summary['qualification']['mandate_id']),indent=2))
