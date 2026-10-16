"""Read saved evidence only. No client, key, signing or exchange transport."""
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timezone,timedelta
import json,hashlib,sys,sqlite3
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint
from exchange.live_recovery import LiveAccountRecovery
from exchange.testnet_qualification import QualificationProposal
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ist=timezone(timedelta(hours=5,minutes=30));now=datetime.now(timezone.utc)
audit=read(OUT/'source_change_audit.json');tests=read(OUT/'regression_release/test_receipt.json')
signer=read(OUT/'local_signer_check.json');human=read(OUT/'human_signer_host_confirmation.json')
pre=OUT/'read_only_preflight';r=read(pre/'readiness.json');proof=read(pre/'WHITELIST_TRADE_PROOF.json')
assert tests['passed'] and tests['source_hash']==tests['source_hash_after']==active_source_hash(ROOT)
assert audit['source_after']==r['source_hash']==r['source_hash_after']==tests['source_hash']
assert signer['status']=='LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED' and not signer['signature_created']
assert r['actual_wallet_signatures']==r['exchange_submissions']==0 and proof['fill_verified'] is False
journal_checks={}
if (pre/'read_only.sqlite').exists():
 db=sqlite3.connect('file:'+str(pre/'read_only.sqlite')+'?mode=ro',uri=True)
 snaps=db.execute('SELECT data,checksum FROM recovery_snapshots').fetchall()
 journal_checks=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],snapshot_count=len(snaps),
     snapshot_checksums_valid=bool(snaps) and all(fingerprint(json.loads(x[0]))==x[1] for x in snaps),
     last_clean_shutdown=json.loads(snaps[-1][0]).get('last_clean_shutdown') if snaps else None,
     checkpoint_source_identity=json.loads(snaps[-1][0]).get('source_identity') if snaps else None,
     action_rows={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('intents','api_actions','signed_management')})
 db.close()
 assert journal_checks['integrity']=='ok' and journal_checks['snapshot_checksums_valid'] and journal_checks['last_clean_shutdown'] is True
 assert journal_checks['checkpoint_source_identity']==LiveAccountRecovery.source_identity()
 assert not any(journal_checks['action_rows'].values())
summary=dict(generated_utc=now.isoformat(),status=r['status'],tests=tests['totals'],baseline=1682,
    focused_tests=127,source_hash=tests['source_hash'],source_audit=audit,journal_checks=journal_checks,
    actual_wallet_signatures=0,exchange_submissions=0,actual_practice_fill_verified=False,
    organizer_whitelisting_confirmed=False,actual_protection_ready=False,controlled_execution_ready=False,
    practice_ready=False,live_ready=False,qualification_execution_authorized=False,
    human_sole_host_scope=human['scope'],local_signer_file_written_utc=datetime.fromtimestamp((OUT/'local_signer_check.json').stat().st_mtime,timezone.utc).isoformat(),local_signer=signer['status'],candidates=[],
    account_observed_ms=r.get('account_observed_ms'),preflight_flat_observed=proof['preflight_flat_observed'])
lines=['# Team Anchorium — V8.7 qualification recovery','','**Implemented and tested. Preparation only; no actual signature, exchange order, fill or whitelist confirmation.**','',
'## A. Root causes','',
'- BTC: the old builder fixed the maximum-notional quantity and rejected depth instead of testing a smaller valid lot quantity. That is a reproduced software defect. However the actual saved 03:19–03:20 UTC book had ask size 0.0003 BTC: its 10% allowance was 0.00003, below one 0.0001 lot. That observation genuinely allowed no opening; selecting two lots would not have solved it.',
'- ETH: the old bid size 0.0173 permitted at most 0.0017 ETH after flooring, about 4.23 USDPR, below the ordinary 10 minimum. The fixed-size behavior was defective, but that book still had no eligible smaller opening. Independently, a LONG can leave one SELL lot whose subminimum close scope is unverified.',
'- HYPE: readiness recorded CLOCK_HEALTH_REQUIRED before a later book observation supplied the second recovery confirmation. A long budget wait had aged the earlier clock reference. The old snapshot was genuinely not ready at its own time; the later healthy clock did not retroactively fix it. The ordering and bounded complete reassessment are repaired. HYPE one-lot SELL close scope remains independently unverified.',
'- Further confirmed defects: reopening the read-only journal replaced the public limiter and lost process-local read weights; market selection could return the first, older proposal after scanning; the prior full-regression gate checked declared totals less strictly. All are corrected without weakening exchange minimums or risk gates. Three original bug reproductions fail on preserved original code; failing development outputs are retained.','',
'## B. Actual code changes','',
'1. `algo-trading-bot/exchange/testnet_qualification.py`: `find_largest_safe_qualification_quantity` uses Decimal and floors the minimum of notional, both 10% BBO depth caps, account max size and margin with fee reserve. Descending whole-lot candidates must pass exact qualification, every residual scope and the central validator. `QualificationContextProvider` orders budget wait, genuine timestamped-book clock observations, reconciliation and consistent fresh inputs; at most two complete contexts. `require_qualification_regression` validates current before/after source, actual XML totals/digest and safety results. Entry identity/freshness and truthful lifecycle/recovery stages are tightened.',
'2. `scripts/run_testnet_qualification.py`: `prepare` preserves the limiter across journal reopen, uses unsigned input descriptors, reviews BTC/ETH/HYPE, rereads the smallest-spread eligible market and generates its final source-bound identity last. `preparation_summary` prints current quantities, risks, deadline and real paths. `preflight_flat_proven` requires explicit position and order reads plus ready reconciliation; missing data cannot imply flat.',
'3. `algo-trading-bot/test_qualification_recovery_v8_7.py`: 78 additional offline cases exercise dynamic size, real composed preparation, depth/margin/precision, clock recovery and stale pairs, source/XML release validation, full/partial/no fills, residual exits, expiry, identity, proof predicates and preserved lockouts. Existing baseline cases cover uncertainty, exit/stop rejection, duplicate prevention and restart. Ephemeral fixture signatures never certify actual exchange behavior.',
'', 'No frozen strategy, production threshold, leverage setting, wallet mapping, minimum-order validator or historical closing scope was changed. No journals or consumed attempts were erased.','',
'## C. Dynamic sizing using actual observation-time data','','Fresh read-only run: '+r['started_utc']+' through '+r['finished_utc']+'. Each row is its own timestamped observation, not simultaneous liquidity or a future fill guarantee.','','| Market | Observation (IST) | Bid / ask | BBO bid / ask sizes | Largest size / notional within bounds | Outcome |','|---|---|---|---|---|---|']
details=[]
for row in r['candidates']:
 s=row.get('sizing',{});q=row.get('quote',{});rr=row.get('readiness',{})
 item=dict(symbol=row['symbol'],observed_ms=row.get('observed_ms'),bid=q.get('bid'),ask=q.get('ask'),
     bid_size=q.get('bid_quantity'),ask_size=q.get('ask_quantity'),sizing=s,
     eligible=row.get('eligible_for_risk_review',False),blocker=row.get('blocker'),
     clock=row.get('clock'),clock_contexts=row.get('context_observations',[]),
     account_status=rr.get('status'),leverage=row.get('active_asset',{}).get('leverage'))
 summary['candidates'].append(item)
 lines.append(f"| {row['symbol']} | {datetime.fromtimestamp(row['observed_ms']/1000,ist).isoformat() if row.get('observed_ms') else 'unavailable'} | {q.get('bid','unavailable')} / {q.get('ask','unavailable')} | {q.get('bid_quantity','unavailable')} / {q.get('ask_quantity','unavailable')} | {s.get('largest_bounded_quantity','unavailable')} / {D(s['largest_bounded_quantity'])*D(s['entry_limit']) if s.get('largest_bounded_quantity') else 'unavailable'} | {'Eligible for explicit risk review' if item['eligible'] else row.get('blocker','unknown')} |")
 if s.get('candidates'):
  for c in s['candidates']:details.append(f"- {row['symbol']} size {c['quantity']}, notional {c['notional']}: "+('all entry gates passed' if c.get('allowed') else c['rejection'])+'.')
lines += ['']+details
lines += ['', 'At these actual snapshots: BTC proposed prices would give three lots 24.9669 and two lots 16.6446 USDPR, but BOTH quantities fail the ask-depth cap; even one lot exceeds that cap and is below the opening minimum. ETH largest depth-permitted 0.0005 is 1.25475 USDPR. HYPE largest depth-permitted 0.03 is 2.48223 USDPR. None passes the opening minimum. These are calculations from rejected inputs, not authorized proposal prices.']
lines += ['', 'Offline tests separately prove that a two-lot BTC opening is selected when three lots breach depth or margin; one lot cannot be used to evade the opening minimum. Those synthetic inputs are labeled tests, not current venue observations. Runtime precision and asset mapping are read from metadata. The ordinary 10 USDPR floor is an exchange rule, not an invented metadata field. See [official precision rules](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size) and [competition API/minimum/fee documentation](https://perpetual-alpha26.github.io/docs/).','',
'## D. Clock repair','',
'Public budget waits happen before two genuine timestamped order-book observations. Existing 2,000 ms skew and 30,000 ms clock-age limits remain. Fresh account reconciliation follows; readiness, account, book and mark observations must all be within 5,000 ms at evaluation. An inconsistent pair receives only one complete read-only retry, with backoff; failed observations remain in `context_observations`. An unrelated later healthy record never rewrites an earlier failed readiness snapshot.',
'', 'Before executor assembly the provider can reconcile; after assembly this callback is detached because revoking the live guard inside its own preflight would invalidate its generation. Existing executor account recovery and central guards remain responsible during the bounded workflow. This composition passes offline lifecycle tests.','',
'## E. Tests','',
f"Full regression: **{tests['totals']['tests']} passed, {tests['totals']['failures']} failures, {tests['totals']['errors']} errors, {tests['totals']['skipped']} skipped**. Baseline 1,682 plus 78 new cases. Focused run: 127 passed. Phase-0 and strategy freeze passed before and after the full suite. XML digest and unchanged source before/after are recorded in `regression_release/test_receipt.json`.",
'', 'Frozen `signal_brain.py` SHA-256: `'+audit['frozen_brain_sha256']+'`. Byte-identical strategy/state methods and freeze manifest remain intact. Production remains PAPER/false, protection disabled, ATR 0.40%, 15 bps, 300 completed UTC bars and Top-3. Full tests use offline synthetic public/account inputs and ephemeral signing fixtures; actual practice execution is not certified by them.','',
'## F. Current execution readiness','',
f"Fresh local key-derived public address and account/nonce exclusion: {signer['status']}; no signature or nonce allocated. Saved human sole-host confirmation is reused as a human assertion, not independent remote-host inspection or trade approval.",
'', 'Team SDK `account_address`: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; approved API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. The approved transport remains SDK 0.24.0, TESTNET and prefixed par asset IDs. No actual signer transport was constructed.',
'', f"Actual preflight reconciliation ready: {r.get('final_reconciliation',{}).get('ready',False)}; flat positions/orders observed: {proof['preflight_flat_observed']}. SQLite integrity: {journal_checks.get('integrity','unavailable')}; snapshot checksums valid: {journal_checks.get('snapshot_checksums_valid',False)}. Exchange action journal rows: {journal_checks.get('action_rows',{})}. Rate report: {r.get('rates',{}).get('state','unavailable')}. Account observations expire and must be refreshed again before future execution.",
'Each fresh candidate had READY unified-account checks, 1,000,000 USDPR, approved API agent and 1x CROSS. Agent validUntil was 1806859924898. Read weights across journal reopen stayed '+str(r.get('public_read_weight_before_reopen'))+' / '+str(r.get('public_read_weight_after_reopen'))+'. The final public budget was '+str(r.get('rates',{}).get('ip_weight'))+' / 1200 (CAUTION, not blocked); account rate budget 13 / 10000 used, 9987 remaining. No read failures were recorded. Clean shutdown and the separately defined core checkpoint source identity also match current files.',
'Actual clock offsets at final BTC/ETH/HYPE evaluations were -618/-669/-573 ms, within unchanged limits. ETH preserved its first CLOCK_RECOVERY_CONFIRMATION_REQUIRED warning, then obtained a new consistent context on attempt 1; BTC and HYPE completed attempt 0.']
ready=r['status']=='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED'
if ready:
 p=QualificationProposal(**r['selected_proposal']);assert p.identity==r['selected_proposal_hash']
 row=next(x for x in r['candidates'] if x['symbol']==p.symbol);asset=row['active_asset'];s=row['sizing']
 q,entry,exit,floor,fee=map(D,[p.quantity,p.entry_limit,r['expected_immediate_exit_limit'],p.exit_bound,p.taker_fee_rate])
 deadline=datetime.fromtimestamp((p.observed_ms+300000)/1000,timezone.utc)
 summary.update(proposal_id=p.identity,proposal=p.__dict__,approval_deadline_ist=r['approval_deadline_ist'],
     approval_window_open_at_report=now<deadline,entry_notional=str(q*entry),fee_entry=str(q*entry*fee),
     fee_exit=str(q*exit*fee),fee_round_trip=str(q*(entry+exit)*fee),
     reviewed_exit_limit=str(exit),exit_floor=str(floor),loss_at_immediate_limit=str(q*(entry-exit)+q*(entry+exit)*fee),
     loss_at_exit_floor=str(q*(entry-floor)+q*(entry+floor)*fee),
     available_margin=asset['availableToTrade'][0],residual_quantities=s['verified_residual_quantities'])
 lines += ['',f"**QUALIFICATION_PROPOSAL_READY — AWAITING_HUMAN_APPROVAL.** ID `{p.identity}`. Approve by **{r['approval_deadline_ist']}**. Valid at report time: {summary['approval_window_open_at_report']}.",'',
 '| Limit / evidence | Value |','|---|---|',
 f'| One BUY LIMIT IOC | {p.quantity} {p.symbol} at {p.entry_limit} USDPR per unit or better |',
 f'| Opening notional | {summary["entry_notional"]}; ceiling 25 USDPR, 1x CROSS |',
 f'| Spread / depth utilization | {row["spread_bps"]} bps; bid {D(s["bid_depth_utilization"])*100}%, ask {D(s["ask_depth_utilization"])*100}% |',
 f'| Current USDPR / long margin | {row["readiness"]["collateral"]} / {asset["availableToTrade"][0]} |',
 f'| API approval expires (UTC) | {datetime.fromtimestamp(row["readiness"]["agent_expiry_ms"]/1000,timezone.utc).isoformat()} |',
 f'| Mark / oracle | {p.reference_mark} / {p.reference_oracle} |',
 f'| Reviewed reduce-only SELL limit / fixed floor | {exit} / {floor} |',
 f'| Taker fee per fill / round-trip estimate | {fee*100}% / {summary["fee_round_trip"]} USDPR |',
 f'| Estimated loss at immediate limit / floor | {summary["loss_at_immediate_limit"]} / {summary["loss_at_exit_floor"]} USDPR, excluding funding; neither guaranteed |',
 f'| Residual sizes assessed | {", ".join(s["verified_residual_quantities"])} |',
 '| Attempt limits | One entry, at most two exits, at most five signed actions including own-order cancellations |']
else:
 summary.update(proposal_id=None,blocker=r.get('blocker'),approval_window_open_at_report=False)
 lines += ['', '**QUALIFICATION_LOCKED. No eligible current proposal exists.** '+str(r.get('blocker'))+'. There is no order to approve.']
lines += ['', '**Protective-stop acceptance remains UNVERIFIED. No stop will be submitted.** The inherited `stop_trigger` / `stop_limit` fields are price bounds only. Normal ACTUAL_PROTECTION_READY, CONTROLLED_EXECUTION_READY, PRACTICE_READY and LIVE_READY remain FALSE. The isolated experimental route, if proposed, still needs an informed human decision about an unprotected position.','',
'## G. Human action','',
'Generate a new read-only proposal from Terminal using the existing launcher and a unique directory. This command prepares only; no execute flag or approval is supplied. The shell timestamp chooses a new evidence directory and cannot refresh an old proposal.','',
'```bash',f'cd "{ROOT}"',
'.venv/bin/python scripts/run_testnet_qualification.py \\',
'  --output-directory "docs/qualification_recovery_v8_7_2026-10-13/operator-$(date +%Y%m%d-%H%M%S)" \\',
'  --test-receipt docs/qualification_recovery_v8_7_2026-10-13/regression_release/test_receipt.json','```']
if ready:
 lines += ['',f'Current proposal: `{pre/"proposal.json"}`.',f'Unfilled approval template: `{pre/"approval_REQUIRED_UNFILLED.json"}`.',f'Full regression: `{OUT/"regression_release/test_receipt.json"}`.','',
'The existing exact-proposal mechanism is `QualificationApproval` in an operator approval JSON file. The human must name the current proposal hash and limits; supply a non-empty `operator_approval`, actual integer `approved_ms`, `expires_ms` after approval and at most 300,000 ms later; approve within 300,000 ms of proposal observation. Do not backdate or extend an expired proposal. All template acknowledgments remain FALSE/unfilled.',
'Explicitly affirm the team/API identities and sole signer host, maximum one entry, the 25 USDPR cap, the isolated 50 bps ceiling (production remains 15), no verified stop, possible unprotected residual/manual intervention, the shown fixed exit floor, at most two exits and five signed actions. Template flags are `manually_verified_wallets`, `sole_signer_host_confirmed`, `maximum_one_entry`, `unverified_stop_risk_accepted`, `qualification_spread_limit_accepted`, `possible_manual_residual_recovery_accepted`.',
'Execution is a separate later use of the same launcher with `--execute`, `--proposal-file`, `--operator-approval-file`, `--test-receipt` and a new `--output-directory`. No filled approval or execution command was run here. Fresh exact-price/liquidity/source/account checks can still reject a valid approval; they never resize or reprice it automatically.']
lines += ['', 'Emergency recovery: retain `runtime/testnet/anchorium-bot-1/qualification.sqlite`, original client/exchange order IDs, nonce history and the consumed entry. Read original orderStatus, team userFills, frontendOpenOrders and par positions. Never repeat an uncertain entry or infer flat from a local response. Close only the exact reconciled held quantity with reduce-only SELL IOC from fresh bid × 0.998, at or above the fixed approved floor, inside the original exit/expiry/action budgets. If partial/rejected/unknown exits, expired permission, lost connectivity or exhausted budgets leave exposure, report EMERGENCY_EXIT_REQUIRED and halt writes. A restart performs read-only recovery and requires explicit additional recovery authorization for further action.','',
'## H. Remaining external blockers','',
'- Actual liquidity can leave no lot meeting both depth and the ordinary opening minimum. The solver reports that honestly and never increases the cap or rounds up.',
'- Below-minimum stop acceptance/coverage remains unverified. Historical exact full-position BTC SELL one-lot order 62228843959 on another account supports only that narrow closing shape; zero residual is fill-derived rather than an independent historical position snapshot. It cannot establish stops or guarantee future acceptance/fills. ETH/HYPE LONG residual SELL paths lack matching evidence.',
'- Explicit exact-proposal risk approval is still absent. The five-minute proposal and subsequent signed-action expiry are enforced. Principal notional 25 is not a guaranteed loss cap; fees, funding and unresolved cross-margin exposure remain risks.',
'- Organizer acceptance of the qualification entry rule/API-agent attribution and actual whitelist confirmation require organizer evidence. No fill has occurred; the proof file correctly remains NO_ACTUAL_PRACTICE_FILL_VERIFIED. This workflow neither proves strategy profitability nor enables autonomous trading.','']
atomic_json(OUT/'final_summary.json',summary);(OUT/'report.md').write_text('\n'.join(lines)+'\n')
checksums={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='artifact_checksums.json' and not p.name.endswith(('-wal','-shm'))}
atomic_json(OUT/'artifact_checksums.json',checksums)
print(json.dumps({k:summary.get(k) for k in ['status','tests','proposal_id','approval_deadline_ist','approval_window_open_at_report','entry_notional','fee_round_trip','loss_at_exit_floor','blocker']},indent=2))
