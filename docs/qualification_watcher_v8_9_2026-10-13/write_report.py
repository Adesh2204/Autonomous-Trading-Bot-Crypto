"""Summarize completed V8.9 evidence, never promote readiness or perform network calls."""
from pathlib import Path
from decimal import Decimal as D
from collections import Counter
import hashlib,json,shlex,sys
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
run=Path(sys.argv[1]).resolve()
r=json.loads((run/'readiness.json').read_text())
tests=json.loads((OUT/'regression_release/test_receipt.json').read_text())
old=json.loads((OUT/'root_cause.json').read_text())
changes=json.loads((OUT/'source_changes.json').read_text())
handoff=json.loads((run/'operator_handoff.json').read_text())
observations=[json.loads(x) for x in (run/'observations.jsonl').read_text().splitlines()] if (run/'observations.jsonl').exists() else []
counts=Counter((x['symbol'],x['entry_side']) for x in observations)
passes=Counter((x['symbol'],x['entry_side']) for x in observations if x['potential'])
reasons=Counter(x.get('blocker') or 'POTENTIAL_OPPORTUNITY' for x in observations)
stream=r.get('stream_before_shutdown',{})
account=(r.get('attempts') or [r.get('end_account_audit',{})])[-1]
summary=dict(report='TEAM_ANCHORIUM_V8_9',generated_utc=datetime.now(timezone.utc).isoformat(),run_directory=str(run),
    actual_read_only_status=r['status'],source_hash=r['source_hash'],source_hash_after=r['source_hash_after'],policy_hash=r['policy_hash'],
    full_regression=tests,modified_source_files=changes,prior_root_causes=old,market_directions=r.get('coverage',{}),
    observations=len(observations),potential_observations=sum(passes.values()),reasons=dict(reasons),
    full_opportunity_attempts=r.get('full_opportunity_attempts'),reconciliations=r.get('reconciliation_calls'),
    account=account,signer=r.get('signer_check'),stream=stream,rates=r.get('rates'),durable_cleanup=r.get('durable_cleanup'),
    operator_handoff=handoff,exchange_submissions=0,actual_wallet_signatures=0,actual_fill_verified=False,
    normal_protection_verified=False,practice_ready=False,live_ready=False,organizer_whitelisting_confirmed=False)
(OUT/'final_summary.json').write_text(json.dumps(summary,indent=2,default=str)+'\n')
q=lambda v:shlex.quote(str(v))
receipt=OUT/'regression_release/test_receipt.json'
watch_cmd=(f'cd {q(ROOT)}\n'+'.venv/bin/python scripts/watch_testnet_qualification.py \\\n  --duration-seconds 300 \\\n  --output-directory "docs/qualification_watcher_v8_9_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \\\n  --test-receipt docs/qualification_watcher_v8_9_2026-10-13/regression_release/test_receipt.json \\\n  --final-account-audit')
lines=['# Team Anchorium — V8.9 qualification workflow', '',
'## A. Root-cause verdict','',
'The latest saved three-market rejection was genuine under the retained risk policy. It was not a rounding bug: the legal opening quantity is rounded DOWN after the smaller of the notional, each best-level depth, exchange maximum size and margin limits. A separate latency problem made short-lived valid books harder to use. A separate reporting defect retained obsolete candidate fields after a failed rereview; the global submission gate already remained closed.', '',
'Historical evidence: `'+old['evidence_file']+'`, '+old['started']+' to '+old['finished']+'. These were separate timestamped observations, not simultaneous or current books.', '',
'| Market | Minimum legal entry quantity | Minimum entry notional | Largest allowed quantity | Largest allowed notional |',
'|---|---:|---:|---:|---:|']
for x in old['markets']:lines.append(f"| {x['symbol']} | {x['minimum_valid_quantity']} | {x['minimum_opening_notional']} | {x['largest_allowed_quantity']} | {x['largest_allowed_notional']} |")
lines+=['','BTC was limited by its bid; ETH and HYPE by their asks. Earlier V8.8 BTC initially permitted 0.0002 BTC / 16.6944 USDPR, but its best ask later shrank and correctly invalidated that opportunity. Neither broader Level-2 depth nor wallet funding automatically fixes a strict best-level constraint.', '',
'## B. Code changes','',
'- `exchange/qualification_watcher.py`: `inspect_book`, `sweep`, `research_residuals` inspect runtime precision, genuine books and both directions; aggregated-depth calculations are research only. `PublicBookStream` checks exact subscription acknowledgments, two distinct timestamped updates, receiver heartbeat, three-connection bound and cache invalidation. `PublicBookReader` paces REST fallback. `OpportunityGate` limits full checks to two per session, at least 60 seconds apart. `ReadOnlyQualificationSession.validate` reuses one journal/limiter/recovery object, checks the prior execution journal and actual signer, reconciles the selected market and verifies every residual using existing central validators. `durable_readback` checks both retained checkpoints through an independent read-only handle, including account/source/identity/checksum consistency.',
'- `scripts/watch_testnet_qualification.py`: implemented bounded observation, opportunity-triggered checks, source/policy checks, optional one-time end account audit, clean shutdown, source-bound evidence and operator handoff. No execution mode or signed endpoint is available in this command.',
'- `scripts/run_testnet_qualification.py`: extracted unchanged proposal-file construction into `publish_proposal`, added `clear_candidate` to remove stale candidate fields before rereview, and extended `preparation_summary` with real file paths, supported next commands and explicit CLI expiry reporting. The old full preparation command remains compatible; the new watcher is the fast operator path.',
'- `test_qualification_watcher_v8_9.py`: 71 new offline cases. Existing execution, strategy, closing scope and production policy code were unchanged. Source diff and hashes: `v8_9_changes.patch`, `source_changes.json`.', '',
'## C. Watcher command and safe stop','',
'Run one bounded, read-only observation with a new evidence directory:', '', '```bash',watch_cmd,'```','',
'Press Ctrl+C once to stop. SIGTERM also requests a safe stop. The watcher writes diagnostics and closes its public socket and SQLite journal. Do not use kill -9 unless the process cannot respond. It exits when a proposal is ready or its observation window ends. A current full validation may finish after the observation duration; the hard cancellation bound is duration + 180 seconds. The default command therefore permits up to 480 seconds including ongoing checks. It never schedules itself or automatically restarts.', '',
'Public WS uses official `l2Book` with the prefixed market coin, without precision aggregation or fast mode. Default depth is up to 20 levels per side, so the report covers the **observed** L2 book, not unbounded hidden depth. Authoritative sources: [subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), [heartbeats](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats). Actual support is separately evidenced by acknowledgments and repeated updates below. If stream data is missing/stale after a 10-second startup grace, REST is admitted at most once per symbol per five seconds, subject to the unchanged shared public budget and reserve.', '',
'## D. Market coverage and close scopes','',
'All ten runtime `par:` markets are inspected in both directions as research. Existing execution scope remains LONG only in BTC/ETH/HYPE, conditional on all gates; no new market or SHORT activation was added. BTC historical BUY and SELL one-lot shapes support direction-specific research, not a promise of future fills. ETH/HYPE one-lot BUY examples do not verify tiny SELL closes for a LONG. A single proven lot also does not certify all two-, three- or more-lot subminimum residuals. BRENT/EWJ historical shapes remain narrowly scoped; the complete residual range and separate execution-scope approval still matter.', '',
'Latest recorded research rows below are individually timestamped. They are not an authorization or a simultaneous guarantee of current executable liquidity. Complete bid/ask sizes, 10% limits, sweeps/VWAP estimates, raw observed levels and residual details are in the run `readiness.json` and `observations.jsonl`.', '',
'| Market / side | Observations | Potential observations | Last minimum entry qty | Last BBO-bounded qty | Last recorded blocker |',
'|---|---:|---:|---:|---:|---|']
for key,x in sorted(r.get('coverage',{}).items()):
 k=(x['symbol'],x['entry_side'])
 lines.append(f"| {x['symbol']} / {x['entry_side']} | {counts[k]} | {passes[k]} | {x.get('minimum_valid_entry_quantity','unknown')} | {x.get('maximum_book_quantity','unknown')} | {x.get('blocker') or 'Potential only; Stage B required'} |")
lines+=['','The counts above are repeated observations, not independent trades or profitability samples. Best-level eligibility is never replaced by aggregated L2 research. Prices, fee estimates and depth can change before approval and again before signing.', '',
'## E. Performance and budgets','',
f"Actual bounded read-only run lasted {r.get('elapsed_seconds')} seconds. It saved {len(observations)} directional book observations and triggered {r.get('full_opportunity_attempts','unknown')} opportunity validation(s), with {r.get('reconciliation_calls','unknown')} actual recovery call(s). An optional end audit is separately labeled and cannot publish a proposal.", '',
'Full candidate timings (seconds): '+str([x.get('elapsed_seconds') for x in r.get('attempts',[])])+'. End account audit: '+str(r.get('end_account_audit',{}).get('elapsed_seconds'))+'.', '',
'Final public rate report:', '', '```json',json.dumps(r.get('rates',{}),indent=2),'```','',
'The prior complete three-market preparation took 140.956 seconds in the saved disappearing-BTC example, including long budget waits. This is an observational comparison across different venue conditions, not a controlled benchmark. The new normal path has one selected-market reconciliation; the existing bounded clock-pair retry can require a second. It removes the separate initial reconciliation, network re-reconciliation after journal reopen, unrelated market account checks and final re-ranking pass. Position/order/history reads required for current consistency remain fresh; signing-boundary checks are unchanged. Raw account diagnostics and fee schedules may make readiness.json large; they are evidence, not extra trading operations.', '',
'## F. Regression and strategy integrity','',
f"Full regression: {tests.get('totals')}; pass={tests.get('passed')}. Prior baseline 1,822 plus 71 new tests. Focused suites: 260 passed, zero failures. Intermediate failed development fixtures/reports are preserved. The complete run includes partial/no fills, uncertain/rejected closes, restart/duplicate prevention, protection rejection, source-bound release checks and actual-fill proof predicates; synthetic results do not certify exchange stop acceptance.", '',
'Full source before: `'+tests['source_hash']+'`.',
'Full source after: `'+str(tests.get('source_hash_after'))+'`.',
'XML SHA-256: `'+str(tests.get('xml_sha256'))+'`.',
'Phase-0 and frozen-strategy checks before and after are included in the full regression receipt. `signal_brain.py` remains byte-identical; production UTC VWAP/EMA/ATR, 0.40% volatility, 15 bps spread, 300 bars and Top-3 remain unchanged. Global PAPER/false, protection disabled, ordinary $10 opening minimum, $25 qualification ceiling and 1x CROSS requirements remain.', '',
'## G. Actual read-only result','',
f"Status: **{r['status']}**. Blocker: `{r.get('blocker')}`. Observation ran {r['started_utc']} through {r['finished_utc']}.", '',
'Actual WS channel support observed for: '+', '.join(sorted(stream.get('verified_public_channel_observations',{})))+'.',
f"Subscriptions confirmed: {stream.get('confirmed_count','unknown')} / {stream.get('desired_count','unknown')}; connection attempts: {stream.get('attempts','unknown')}; receiver gap maximum: {stream.get('max_receiver_gap_seconds','unknown')} seconds.", '',
'Account result is a timestamped read, not continuing assurance. Team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` remains the account address; API `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` is the agent. Local identity derives only its public address; local nonce ownership test allocates no nonce and creates no signature. Prior human confirmation of sole host is retained, but no software local lease can inspect another machine. The exact-trade approval remains unfilled.', '',
'Account summary:', '', '```json',json.dumps({k:account.get(k) for k in ['account_observed_ms','final_positions','final_orders','final_reconciliation','active_asset','clock','blocker']},indent=2,default=str),'```','',
'Durable cleanup: `'+json.dumps(r.get('durable_cleanup'),default=str)+'`.', '',
'No actual exchange signature, entry, close, cancellation, transfer or configuration change occurred. No actual fill or whitelist confirmation exists. This watcher does not create a fabricated WHITELIST_TRADE_PROOF.json.', '',
'## H. One-off authorization, execution and recovery','',
'Operator handoff file: `'+str(run/'operator_handoff.json')+'`.', '',
'```json',json.dumps(handoff,indent=2),'```','',
'If no ready proposal exists, there is no exact order to approve. Use the bounded watcher command again only by a deliberate operator decision. It will print the actual proposal, unfilled approval template, source-bound receipt, copy command and supported execution command if it finds a valid opportunity. Never use a previous proposal or guess a file path.', '',
'When a proposal is ready, review its exact hash, quantity, notional, prices, fee estimates, exit floor and IST approval deadline. Copy the unfilled template using the printed copy command, review/edit the copy yourself, and supply a nonempty operator_approval plus actual integer approved_ms/expires_ms. Approval must be within 300,000 ms of proposal observation, expiry must be later than the current time and at most 300,000 ms after approval. Never backdate or extend an expired proposal. The six required true acknowledgments are manually_verified_wallets, sole_signer_host_confirmed, maximum_one_entry, unverified_stop_risk_accepted, qualification_spread_limit_accepted and possible_manual_residual_recovery_accepted. The exact proposal binds the $25 cap, its smaller selected quantity, limits, one-entry/two-exit procedures and separate 50 bps qualification spread policy. No field was filled on your behalf.', '',
'Only after that explicit decision may the printed existing `run_testnet_qualification.py --execute` command be used. It revalidates the account, book, source, policy and approval; it may still refuse stale/changed conditions. It cannot resize/reprice the approved order to force a fill. It sends at most one entry and follows only the two bounded exact reduce-only exit attempts. The entry and exit fills must be matched to the registered team account and original cloid/oid. Actual fees/funding and final exchange positions/orders determine realized P&L and flatness; only then can genuine WHITELIST_TRADE_PROOF.json be saved. An actual fill still does not prove organizer acceptance/whitelisting.', '',
'For EMERGENCY_EXIT_REQUIRED or any unknown state: (1) stop new entries and preserve runtime/testnet/anchorium-bot-1/qualification.sqlite, nonces and original cloid/oid; (2) read original orderStatus, team userFills, frontendOpenOrders and par clearinghouseState; (3) reconcile the exact residual or label UNKNOWN when records disagree; (4) do not blindly resend the entry, erase the consumed attempt, enlarge a close, bypass the exit floor or resume revoked/expired permissions; (5) obtain a new explicit recovery authorization if the current permitted close cannot finish. There is no invented auto-recovery CLI flag.', '',
'## I. Remaining risks','',
'**Small-position protective-stop acceptance is still unverified. No stop will be submitted by this isolated qualification route.** IOC closing is not persistent stop protection. The proposal retains legacy stop_trigger/stop_limit field names for its existing price-bound schema; these values do not create or certify an exchange stop. Historical exact full-close evidence is narrow and does not promise future acceptance or liquidity. A partial fill, disappearing book, delayed order status, network loss, rejection or price moving outside approved bounds can leave unprotected exposure requiring manual intervention. Cross margin shares account collateral; a 25 USDPR entry cap is not a guaranteed total-loss cap. The account contains much more collateral than the bounded entry; no full-balance trade is authorized. Fees and funding remain distinct from principal.', '',
'No autonomous strategy trading, recurring task, new closing exception, production-threshold relaxation or scored-DEX switch was added. Normal protection certification, controlled funded LONG/SHORT/recovery certification, PRACTICE_READY and LIVE_READY remain false. The next action is the printed read-only watcher or exact human proposal review, depending on the actual handoff status.']
(OUT/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(dict(report=str(OUT/'report.md'),summary=str(OUT/'final_summary.json'),status=r['status']),indent=2))
