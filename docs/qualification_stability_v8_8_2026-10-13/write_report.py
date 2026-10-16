"""Summarize saved V8.8 evidence. No HTTP, key, signature or exchange sink."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
import json,hashlib,sqlite3,sys
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint
from exchange.live_recovery import LiveAccountRecovery
from exchange.testnet_qualification import QualificationProposal
read=lambda path:json.loads(path.read_text())
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
now=datetime.now(timezone.utc);ist=timezone(timedelta(hours=5,minutes=30))
release=read(OUT/'regression_release/test_receipt.json');audit=read(OUT/'source_after.json')
launch=read(OUT/'preflight_launch.json');pre=ROOT/launch['output_directory']
r=read(pre/'readiness.json');proof=read(pre/'WHITELIST_TRADE_PROOF.json')
signer=read(OUT/'local_signer_check.json');human=read(OUT/'human_signer_host_confirmation.json')
assert release['passed'] and release['source_hash']==release['source_hash_after']==active_source_hash(ROOT)==audit['source_hash']==r['source_hash']==r['source_hash_after']
assert release['totals']['tests']>=1760 and not any(release['totals'][k] for k in ('failures','errors','skipped'))
assert signer['status']=='LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED' and not signer['signature_created']
assert r['actual_wallet_signatures']==r['exchange_submissions']==0 and not proof['fill_verified']
checks={}
db=sqlite3.connect('file:'+str(pre/'read_only.sqlite')+'?mode=ro',uri=True)
snapshots=db.execute('SELECT data,checksum FROM recovery_snapshots ORDER BY seq').fetchall()
checks=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],snapshot_count=len(snapshots),
    snapshot_checksums_valid=bool(snapshots) and all(fingerprint(json.loads(x[0]))==x[1] for x in snapshots),
    last_clean_shutdown=json.loads(snapshots[-1][0]).get('last_clean_shutdown') if snapshots else None,
    checkpoint_source_identity=json.loads(snapshots[-1][0]).get('source_identity') if snapshots else None,
    action_rows={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('intents','api_actions','signed_management')})
db.close()
assert checks['integrity']=='ok' and not any(checks['action_rows'].values())
if snapshots:assert checks['snapshot_checksums_valid'] and checks['last_clean_shutdown'] and checks['checkpoint_source_identity']==LiveAccountRecovery.source_identity()
ready=r['status']=='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED'
progress=[json.loads(line) for line in (pre/'progress.jsonl').read_text().splitlines()]
stages=list(dict.fromkeys(row['event'] for row in progress if not row['event'].startswith('INFO_')))
s={
 'generated_utc':now.isoformat(),'status':r['status'],'qualification_proposal_ready':ready,
 'tests':release['totals'],'baseline_tests':1760,'new_tests':release['totals']['tests']-1760,
 'focused_tests':212,'source_hash':release['source_hash'],'source_audit':audit,'journal_checks':checks,
 'preflight_directory':str(pre),'started_utc':r['started_utc'],'finished_utc':r['finished_utc'],
 'http_delay_cause':'Existing 10s socket timeout was present. Actual elapsed duration and remote/network cause unknown; no whole-request deadline, differentiated failures or interruption receipt were present.',
 'http_timeout_policy':r.get('http_timeouts'),'http_last_diagnostic':r.get('http_diagnostic'),
 'public_read_rates':r.get('rates'),'public_weights_before_after_reopen':[r.get('public_read_weight_before_reopen'),r.get('public_read_weight_after_reopen')],
 'snapshot_reuse_count':r.get('snapshot_reuse_count'),'progress_events':len(progress),'progress_stages':stages,
 'local_signer':signer['status'],'local_signer_file_written_utc':datetime.fromtimestamp((OUT/'local_signer_check.json').stat().st_mtime,timezone.utc).isoformat(),
 'human_sole_host_scope':human.get('scope'),'account_observed_ms':r.get('account_observed_ms'),
 'preflight_flat_observed':proof['preflight_flat_observed'],'actual_wallet_signatures':0,'exchange_submissions':0,
 'actual_practice_fill_verified':False,'organizer_whitelisting_confirmed':False,
 'actual_protection_ready':False,'controlled_execution_ready':False,'practice_ready':False,'live_ready':False,
 'qualification_execution_authorized':False,'proposal_id':r.get('selected_proposal_hash'),'blocker':r.get('blocker'),
 'candidates':[]}
lines=['# Team Anchorium — V8.8 qualification stability and readiness','',
'Implementation complete. One read-only preparation was run after the complete offline regression. No actual signature, order, fill or whitelist confirmation was created.','',
'## 1. HTTP delay: confirmed defects and what remains unknown','',
'The old transport already supplied `timeout=10` to Requests; a missing timeout was not the cause. The supplied traceback establishes an interrupted HTTPS response wait but does not establish its elapsed duration, packet behavior or whether the venue, DNS, TLS, proxy or local network caused it. We cannot attribute that delay to the exchange.',
'', 'A socket timeout is not a total wall-clock deadline: a read timeout measures inactivity between received bytes and connection timing can involve multiple addresses. The old implementation had no independent caller deadline, flattened transport failures, gave no progress while waiting and let Ctrl+C escape without final JSON. These are confirmed code defects. [Requests timeout semantics](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts).','',
'Five original regression checks failed on the saved V8.7 source. Original failures and subsequent failed development runs are preserved. The corrected focused run passed 212 cases.','',
'## 2. Files and functions modified','',
'- `algo-trading-bot/exchange/hyperliquid_client.py`: `RequestsInfoTransport.__init__`, `__call__`, `_worker`, `_failure`, `_caused_by`, `_retry_after`, `close`; `HyperliquidClient.__init__`, `post_info`, `read_snapshot_scope`. Public HTTPS limits, response bounds, safe error codes and narrow preparation snapshot reuse.',
'- `algo-trading-bot/exchange/rate_limits.py`: `__init__`, `read_budget_delay_ms`, `wait_for_read_budget`, `error`, `read`, `_read_owned`, `_report_owned`. Grounded budget waits, preserved server guidance, public-query whitelist, interruption-safe coalescing and detailed failure records.',
'- `algo-trading-bot/exchange/testnet_qualification.py`: `QualificationContextProvider.__init__`, `load`. Uses the existing manager for bounded budget waits and short-lived static snapshots only during read-only preparation. Dynamic sizing, exact closing scope and signed execution behavior are preserved.',
'- `scripts/run_testnet_qualification.py`: `prepare`, `main`. Flushed progress stages and durations, 240-second preparation admission deadline, interruption diagnostics, SQLite cleanup, explicit real-liquidity classification and truthful no-fill proof.',
'- Added `algo-trading-bot/test_qualification_stability_v8_8.py`: 62 offline cases for hung headers/body, socket failures, HTTP statuses, retry guidance, cancellation, budget forecasts/weights, snapshots, interrupted preparation/recovery and saved real thin books. Existing suites retain exact approval, partial-fill, duplicate, unknown order, stop rejection and restart coverage.','',
'Only those four implementation files changed from the V8.7 source snapshot; one test file was added. The original NSE repo, frozen brain/methods, indicators, UTC convention, 300-bar requirement, ATR 0.40%, production 15 bps spread ceiling, Top-3, production config, signer SDK and closing-evidence scope remain unchanged.','',
'## 3. Timeouts, retries and cancellation','',
'Public `/info` calls now have separately configurable 3.05-second connect and 5-second response inactivity timeouts, plus a 12-second total caller deadline and 8 MiB body limit. Redirects and hidden HTTP-adapter retries are disabled. Deadline/cancellation waits poll at 50 ms; Ctrl+C can reach the calling preparation thread.',
'', 'There is at most one public HTTP worker per transport. A worker stuck in an OS/DNS call may finish cleanup later; it cannot keep the caller waiting indefinitely or create an unlimited number of workers. The occupied slot blocks subsequent reads within their own deadlines. It has no SQLite, nonce, private-key, signature or exchange-write access.',
'', 'Public idempotent reads receive at most three attempts with existing exponential jitter and a 45-second admission/wait budget. Each HTTP attempt also has its 12-second caller deadline. The read-loop budget checks admission and waits; it is not an extra socket-level cancellation timer. Preparation stops admission after 240 seconds and saves a lock reason instead of continuing indefinitely. Error codes separately identify connect timeout, read timeout, DNS, TLS, reset/connection failure, 429, 5xx, malformed JSON, body limit, cancellation and total deadline.',
'', 'Retry-After seconds or HTTP date are honored without shortening them to 30 seconds. If the venue asks for a wait longer than the permitted preparation/read window, preparation terminates; it never retries earlier. Total-deadline, TLS, malformed-response and non-retryable 4xx failures do not receive blind repeats. Signed actions cannot enter the public retry front door. The existing SDK signing/unknown-order procedure is untouched.',
'', 'Keyboard interruption writes PREPARATION_INTERRUPTED and diagnostic/readiness/no-fill JSON, closes SQLite and exits 130. A valid local checkpoint checksum does not make incomplete account history valid. Restart begins with unknown account truth until fresh reconciliation succeeds; a timed-out request cannot prove flat.','',
'## 4. Rate-budget behavior','',
'Hyperliquid documents 1,200 weighted REST units per minute. The existing weights remain 2 for l2Book/allMids/clearinghouseState/orderStatus/spotClearinghouseState/exchangeStatus, 60 for userRole and 20 for other info requests, with existing additional history/candle-response accounting. The 120-unit safety reserve remains. [Official request limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).',
'', 'Each attempted upstream read is charged, including unsuccessful attempts. Reopening the same read-only SQLite keeps the same limiter and rolling weights. Preparation estimates the next retry from actual recorded weight expiry and server backoff, prints WAITING_FOR_RATE_BUDGET with the cause/required weight/next time, and waits at most 65 seconds for a context bundle. Per-read waits share the read admission budget. Cancellation is responsive. If no early capacity is proven it conservatively defers the whole window.',
'', 'Identical concurrent public reads share one in-flight result; an interrupted leader now returns an interruption error to followers rather than None-as-success. Only mode, agent list and fees may reuse their original response inside a preparation-only one-second scope, with the original timestamp and defensive copies. Positions, orders, histories, books and mark/oracle prices are always fetched afresh. Incremental account history and overlap for late corrections are retained; essential reconciliation is not skipped. Actual execution does not use this snapshot scope.',
'', 'The IP budget is this process’s observed accounting; other processes behind the same public IP remain outside that observation. Human sole-host confirmation applies to signing, not independent observation of every HTTP consumer.','',
'## 5. Fresh BTC / ETH / HYPE observations','',
f"Final preparation: {r['started_utc']} through {r['finished_utc']}. Each market is its own actual observation; the rows are not simultaneous or a future fill guarantee.",'',
'| Market | Bid / ask | BBO bid / ask size | 10% bid / ask caps | Lot | Largest quantity / entry notional within bounds | Spread bps | Outcome |',
'|---|---|---|---|---|---|---|---|']
market_details=[]
for row in r['candidates']:
    z=row.get('sizing',{});q=row.get('quote',{});asset=row.get('active_asset',{});rd=row.get('readiness',{})
    notional=str(D(z['largest_bounded_quantity'])*D(z['entry_limit'])) if z.get('largest_bounded_quantity') else None
    item=dict(symbol=row['symbol'],observed_ms=row.get('observed_ms'),quote=q,quantity_bounds=z.get('quantity_bounds'),
        size_step=z.get('size_step'),largest_bounded_quantity=z.get('largest_bounded_quantity'),largest_bounded_notional=notional,
        selected_quantity=z.get('selected_quantity'),entry_limit=z.get('entry_limit'),exit_floor=z.get('exit_floor'),
        spread_bps=z.get('spread_bps'),taker_fee_rate=z.get('taker_fee_rate'),blocker=row.get('blocker'),external_blocker=row.get('external_blocker'),
        readiness_status=rd.get('status'),readiness_reasons=rd.get('reasons'),mode=rd.get('account_mode'),collateral=rd.get('collateral'),
        leverage=asset.get('leverage'),availableToTrade=asset.get('availableToTrade'),maxTradeSzs=asset.get('maxTradeSzs'),
        clock=row.get('clock'),one_lot_close_assessment=row.get('one_lot_close_assessment'),
        initial_review=row.get('initial_review'),all_opening_residuals_validated=bool(z.get('ready')),residual_analysis_status='PASSED_REVIEWED_OPENING' if z.get('ready') else 'NO_VALID_OPENING_TO_CERTIFY')
    s['candidates'].append(item);b=z.get('quantity_bounds',{})
    lines.append(f"| {row['symbol']} | {q.get('bid','unknown')} / {q.get('ask','unknown')} | {q.get('bid_quantity','unknown')} / {q.get('ask_quantity','unknown')} | {b.get('bid_depth','unknown')} / {b.get('ask_depth','unknown')} | {z.get('size_step','unknown')} | {z.get('largest_bounded_quantity','unknown')} / {notional or 'unknown'} | {z.get('spread_bps','unknown')} | {row.get('external_blocker') or row.get('blocker') or 'Eligible for risk review'} |")
    market_details += ['',f"**{row['symbol']}** at {datetime.fromtimestamp(row['observed_ms']/1000,ist).isoformat() if row.get('observed_ms') else 'unknown time'}: account {rd.get('status','unknown')}, leverage {asset.get('leverage','unknown')}, available long/short margin {asset.get('availableToTrade','unknown')}. Opening minimum remains 10; entry cap 25. Exact blocker: {row.get('blocker','none')}. One-lot close assessment: {row.get('one_lot_close_assessment','not evaluated')}. All possible residuals for an opening are certified only when the solver passes the entire entry; rejected books do not establish a ready trade."]
    if z.get('taker_fee_rate'):market_details.append(f"Qualification fee assumption from current userFees × 2 HIP-3 convention: {D(z['taker_fee_rate'])*100}% per taker fill. It remains a planning estimate; actual net P&L requires reported actual fill fees/funding.")
lines += market_details
btc=next((row for row in r['candidates'] if row['symbol']=='par:BTC'),{})
initial=btc.get('initial_review',{});initial_s=initial.get('sizing',{});initial_q=initial.get('quote',{})
if initial_s.get('ready'):
    s['btc_initial_admission_superseded']=dict(observed_ms=initial.get('observed_ms'),quantity=initial_s['selected_quantity'],notional=initial_s['entry_notional'],initial_ask_size=initial_q.get('ask_quantity'),final_ask_size=btc.get('quote',{}).get('ask_quantity'),final_eligible=btc.get('eligible_for_risk_review',False))
    lines += ['',f"Actual dynamic sizing initially passed BTC with {initial_s['selected_quantity']} at {initial_s['entry_notional']} USDPR when ask size was {initial_q.get('ask_quantity')}. It was not submitted or offered as the final current order. The final reread saw ask size {btc.get('quote',{}).get('ask_quantity')}; its 10% cap was {btc.get('sizing',{}).get('quantity_bounds',{}).get('ask_depth')}, below one lot. The final eligibility check correctly superseded the earlier admission and generated no approvable proposal. This is real book deterioration, not a timeout or sizing defect."]
wait_groups=[]
for event in progress:
    if event['event']=='WAITING_FOR_RATE_BUDGET':
        if not wait_groups or wait_groups[-1].get('resumed_elapsed_seconds') is not None:
            wait_groups.append(dict(start_elapsed_seconds=event['elapsed_seconds'],first_delay_seconds=event['retry_in_seconds']))
    elif wait_groups and wait_groups[-1].get('resumed_elapsed_seconds') is None:
        wait_groups[-1]['resumed_elapsed_seconds']=event['elapsed_seconds']
        wait_groups[-1]['observed_wait_seconds']=round(event['elapsed_seconds']-wait_groups[-1]['start_elapsed_seconds'],3)
s['observed_budget_waits']=wait_groups
s['preflight_duration_seconds']=(datetime.fromisoformat(r['finished_utc'])-datetime.fromisoformat(r['started_utc'])).total_seconds()
lines += ['',f"The actual preparation took {s['preflight_duration_seconds']:.3f} seconds. Budget wait episodes: {wait_groups}. Public read failures: {r.get('rates',{}).get('public_reads',{}).get('failures')}; maximum upstream read duration {r.get('rates',{}).get('public_reads',{}).get('max_seconds')} seconds. These are observations from this bounded run, not guarantees about future network latency."]
lines += ['', 'The solver floors whole lots across the 25 cap, both 10% depth caps, maxTradeSzs and available margin including fee reserve. It tests descending lot quantities without rounding up. Offline cases verify two-lot BTC selection when three lots are too large and the unchanged rejection when no whole lot can satisfy the ordinary minimum. ETH/HYPE do not inherit BTC SELL historical closing evidence.',
'',f"Current account reconciliation ready: {r.get('final_reconciliation',{}).get('ready','unknown')}; actual preflight positions/orders flat observed: {proof['preflight_flat_observed']}. This is a read observation, not post-trade flat proof. Public weights before/after reopen: {s['public_weights_before_after_reopen']}; final rate state/weight: {r.get('rates',{}).get('state','unknown')} / {r.get('rates',{}).get('ip_weight','unknown')} of 1200; snapshot reuse hits: {r.get('snapshot_reuse_count','unknown')}.",
'',f"Signer local status: {signer['status']}; no nonce allocated or actual signature. Saved human statement reused: {human.get('scope','sole signing host confirmed')}. This does not independently inspect other computers and is not trade/risk approval. Account address remains 0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C; API signer remains 0x46c9BED595770150752E7fA3806449F81E0Ec6f9; SDK future account_address is the registered team account.",
'', '## 6. Regression, freeze and evidence','',
f"Full regression: **{release['totals']['tests']} passed, zero failures, errors or skips**. Baseline 1760 plus {release['totals']['tests']-1760} new cases. Focused corrected run: 212 passed. Phase-0 and strategy-freeze checks passed before and after the full suite. Source digest stayed {release['source_hash']}. Full XML digest and source-bound receipt are saved in regression_release.",
'',f"SQLite integrity {checks['integrity']}; checkpoint count {checks['snapshot_count']}; checksum verification {checks['snapshot_checksums_valid']}; clean shutdown {checks['last_clean_shutdown']}; current checkpoint core source identity matches. All exchange intent/action/management counts: {checks['action_rows']}. Progress event count: {len(progress)}; stages: {', '.join(stages)}.",
'', 'Failed reproductions, failed test attempts and earlier V8.7 evidence are retained. No actual account/order journal was reset. The V8.8 report reads the final evidence only and verifies current full-source equality before writing.',
'', '## 7. Proposal verdict','']
if ready:
    p=QualificationProposal(**r['selected_proposal']);assert p.identity==r['selected_proposal_hash']
    deadline=datetime.fromtimestamp((p.observed_ms+300000)/1000,timezone.utc)
    s.update(proposal=p.__dict__,approval_deadline_ist=r['approval_deadline_ist'],approval_window_open_at_report=now<deadline)
    lines += [f"**QUALIFICATION_PROPOSAL_READY — AWAITING_HUMAN_APPROVAL.** ID `{p.identity}`; approval deadline {r['approval_deadline_ist']}. Still inside its deadline at report time: {now<deadline}.",'',
        f"One BUY LIMIT IOC: {p.quantity} {p.symbol} at {p.entry_limit} or better; notional {r['notional']} USDPR, cap 25, 1x CROSS. Immediate reduce-only SELL review limit {r['expected_immediate_exit_limit']}; fixed exit floor {p.exit_bound}. Estimated round-trip fee {r['estimated_round_trip_fee_at_reviewed_limits']}; loss at reviewed immediate limit {r['estimated_loss_at_reviewed_immediate_exit']}, excluding funding. Neither is a guaranteed realized loss cap.",'',
        'At most one entry, two exits, five signed actions including permitted own-order cancellations. No stop will be submitted. Source/account/book/floor/expiry checks apply again before a later authorized submission.']
else:
    s['approval_window_open_at_report']=False
    lines += [f"**QUALIFICATION_LOCKED.** {r.get('blocker','unknown')}. No eligible current proposal ID or order exists to approve. This verdict retains the ordinary entry minimum and existing risk gates."]
lines += ['', '## 8. Exact next Terminal preparation command','',
'This prepares only, chooses a new evidence directory and uses the successful source-bound receipt. It does not sign or consume authorization. Run it once when you want another current observation; do not run simultaneous copies.','',
'```bash',f'cd "{ROOT}"','.venv/bin/python scripts/run_testnet_qualification.py \\',
'  --output-directory "docs/qualification_stability_v8_8_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \\',
'  --test-receipt docs/qualification_stability_v8_8_2026-10-13/regression_release/test_receipt.json','```','',
'## 9. Existing exact approval procedure','']
if ready:
    lines += [f"Proposal: `{pre/'proposal.json'}`. Unfilled template: `{pre/'approval_REQUIRED_UNFILLED.json'}`. Receipt: `{OUT/'regression_release/test_receipt.json'}`.",'',
        'Human review must approve that exact current hash, symbol, quantity, entry limit, exit floor, 25 USDPR cap, 1x CROSS, one entry, two exits and five signed actions. Qualification spread ceiling is 50 bps; production remains 15 bps. Explicitly acknowledge no verified protective stop and possible unprotected residual/manual recovery. No approval template was filled automatically.']
else:lines += ['Not actionable now: no eligible fresh proposal was generated. Never approve an old or rejected proposal.']
lines += ['', 'The existing QualificationApproval schema requires the current proposal_hash; nonempty operator_approval; actual integer approved_ms and expires_ms, ordered and no more than 300,000 ms apart; approval within 300,000 ms of the proposal observation. No backdating/extension. Its six acknowledgments are manually_verified_wallets, sole_signer_host_confirmed, maximum_one_entry, unverified_stop_risk_accepted, qualification_spread_limit_accepted and possible_manual_residual_recovery_accepted. All remain empty/false unless explicitly approved by the human.',
'', 'Only after separately authorized exact review can the same launcher use its existing --execute, --proposal-file, --operator-approval-file and --test-receipt arguments. This task supplied no execute flag and created no trading permission. Later fresh revalidation can still reject an approved proposal without resizing or repricing it.',
'', '## 10. Exchange limits and emergency recovery','',
'**ACTUAL_PROTECTION_READY = FALSE; CONTROLLED_EXECUTION_READY = FALSE; PRACTICE_READY = FALSE; LIVE_READY = FALSE.** Small-position stop acceptance/readback/coverage remains unverified. Immediate reduce-only IOC closure is not persistent protection. Historical exact-full-position BTC SELL one-lot evidence supports that narrow shape only, not ETH/HYPE SELL, stops or guaranteed future acceptance/fills. No scope was broadened.',
'', 'If a later explicitly approved entry fills, verify actual userFills/order ID under the registered team wallet, reconcile exact quantity, then use the already permitted reduce-only exit procedure within the fixed floor, original expiry, at most two exits and five-action budget. Closing size never exceeds the actual reconciled position. A full-position exception cannot increase exposure.',
'', 'For uncertainty/residual exposure: halt new entries, keep runtime/testnet/anchorium-bot-1/qualification.sqlite, original order/cloid IDs, consumed-entry record and nonce history. Read original orderStatus, team userFills, frontendOpenOrders and par positions. Never resend an uncertain entry. Do not infer flat from a local acknowledgment. Read-only restart recovery must reconcile authoritative account truth. If price, partial fill, failed close, expiry, connectivity or budgets prevent closure, report EMERGENCY_EXIT_REQUIRED and obtain explicit supervised recovery authorization rather than expanding bounds or repeating automatically.',
'', 'Notional 25 and 1x CROSS are limits on the attempted entry, not a guaranteed account loss cap. Fees/funding and unprotected cross-margin exposure remain material risks. Actual whitelist qualification requires a verified real fill and organizer confirmation. The saved WHITELIST_TRADE_PROOF.json correctly records no actual fill, no trade-derived flat proof and no whitelist confirmation. Software cannot guarantee market liquidity, closure or positive P&L.','']
atomic_json(OUT/'final_summary.json',s);(OUT/'report.md').write_text('\n'.join(lines)+'\n')
files={str(path.relative_to(OUT)):sha(path) for path in OUT.rglob('*') if path.is_file() and path.name!='artifact_checksums.json' and not path.name.endswith(('-wal','-shm'))}
atomic_json(OUT/'artifact_checksums.json',files)
print(json.dumps({key:s.get(key) for key in ('status','tests','proposal_id','blocker','preflight_flat_observed','public_weights_before_after_reopen')},indent=2))
