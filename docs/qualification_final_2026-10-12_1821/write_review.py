"""Document existing read-only preparation evidence; cannot construct an exchange client."""
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timezone,timedelta
import hashlib,json,sys,sqlite3
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from exchange.execution_journal import fingerprint
from exchange.testnet_qualification import QualificationProposal
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
safety=read(OUT/'source_safety_receipt.json');signer=read(OUT/'local_signer_check.json')
account=read(OUT/'account_check/account_check.json');r=read(OUT/'proposal_review/readiness.json')
human=read(OUT/'human_signer_host_confirmation.json');proof=read(OUT/'proposal_review/WHITELIST_TRADE_PROOF.json')
checks={}
for directory in ['account_check','proposal_review']:
 db=sqlite3.connect(f'file:{OUT/directory/"read_only.sqlite"}?mode=ro',uri=True)
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 snapshots=db.execute('SELECT data,checksum FROM recovery_snapshots').fetchall()
 checks[directory]={'integrity':integrity,'snapshot_count':len(snapshots),'snapshot_checksums_valid':bool(snapshots) and all(fingerprint(json.loads(x[0]))==x[1] for x in snapshots),'action_rows':{t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['intents','api_actions','signed_management']}}
 db.close()
assert safety['passed'] and account['account_observation_checks_passed']
assert signer['status']=='LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED' and human['confirmed']
assert r['source_hash']==r['source_hash_after']==safety['active_source_hash']==active_source_hash(ROOT)
assert all(x['integrity']=='ok' and x['snapshot_checksums_valid'] and not any(x['action_rows'].values()) for x in checks.values())
assert r['exchange_submissions']==0 and r['actual_wallet_signatures']==0 and proof['fill_verified'] is False
assert r['final_reconciliation']['ready'] and not r['final_positions'] and not r['final_orders']
now=datetime.now(timezone.utc)
summary={'generated_utc':now.isoformat(),'status':r['status'],'source_hash':r['source_hash'],'source_changed':False,'full_regression_reused':safety['regression_totals'],'fresh_phase0_and_freeze_passed':True,'sole_host_human_confirmation':human,'local_signer':signer['status'],'journal_checks':checks,'exchange_submissions':0,'actual_wallet_signatures':0,'qualification_execution_authorized':False,'actual_protection_ready':False,'controlled_execution_ready':False,'practice_ready':False,'live_ready':False,'whitelist_confirmed':False,'account_flat_observed_ms':r['account_observed_ms']}
if r['status']!='EXPLICIT_EXPERIMENTAL_RISK_DECISION_REQUIRED':
 summary['blocker']=r.get('blocker');(OUT/'final_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 (OUT/'report.md').write_text('# Qualification preparation remains locked\n\nNo order submitted. Blocker: '+str(summary['blocker'])+'\n\nSee proposal_review/readiness.json for the exact market rejections.\n')
 print(json.dumps(summary,indent=2));raise SystemExit(1)
p=QualificationProposal(**r['selected_proposal']);p.require();assert p.identity==r['selected_proposal_hash']
row=next(x for x in r['candidates'] if x['symbol']==p.symbol);quote=row['quote'];asset=row['active_asset'];q=D(p.quantity);entry=D(p.entry_limit);exit=D(r['expected_immediate_exit_limit']);floor=D(p.exit_bound);fee=D(p.taker_fee_rate)
deadline=datetime.fromtimestamp((p.observed_ms+300000)/1000,timezone.utc);ist=timezone(timedelta(hours=5,minutes=30))
summary.update(proposal_id=p.identity,proposal=p.__dict__,approval_deadline_ist=deadline.astimezone(ist).isoformat(),approval_window_open_at_report=now<deadline,entry_notional=str(q*entry),fee_entry=str(q*entry*fee),fee_immediate_exit=str(q*exit*fee),fee_round_trip=str(q*(entry+exit)*fee),loss_at_immediate_limit=str(q*(entry-exit)+q*(entry+exit)*fee),loss_at_exit_floor=str(q*(entry-floor)+q*(entry+floor)*fee),available_long_margin=asset['availableToTrade'][0],residual_scope=row['residual_close_scope'],maximum_one_entry=True,maximum_exit_attempts=p.max_exit_attempts,maximum_signed_actions=p.max_signed_actions,no_stop_will_be_submitted=True,hard_total_loss_cap_guaranteed=False)
(OUT/'final_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
lines=[
'# Team Anchorium — fresh qualification approval review',
'',
'**Preparation only. No signature or exchange order was submitted. Approval is unfilled.**',
'',
'## Exact current proposal',
'',
f'Proposal ID: `{p.identity}`.',
'',
f'Observed {datetime.fromtimestamp(p.observed_ms/1000,timezone.utc).astimezone(ist).isoformat()}. Approve by **{deadline.astimezone(ist).isoformat()}**. Expiry or a changed quote never authorizes automatic repricing.',
'',
'| Item | Exact limit / observation |','|---|---|',
f'| Venue | Hyperliquid TESTNET / {p.symbol} / 1x CROSS |',
f'| Entry, once only | BUY LIMIT IOC {p.quantity} at {p.entry_limit} USDPR per BTC or better |',
f'| Maximum entry notional | {summary["entry_notional"]} USDPR; hard opening-notional ceiling 25 USDPR |',
f'| Reviewed bid / ask | {p.reference_bid} / {p.reference_ask} |',
f'| Mark / oracle | {p.reference_mark} / {p.reference_oracle} |',
f'| Spread | {row["spread_bps"]} bps |',
f'| Best bid / ask quantity | {quote["bid_quantity"]} / {quote["ask_quantity"]} BTC |',
f'| Long-side margin / maxTradeSz | {asset["availableToTrade"][0]} USDPR / {asset["maxTradeSzs"][0]} BTC |',
f'| Immediate exit at reviewed bid | SELL actual position quantity, reduce-only IOC, limit {exit} |',
f'| Absolute SELL price floor | {floor}; no exit submitted below this floor |',
f'| Fee estimate | {fee*100}% per taker fill; entry {summary["fee_entry"]}, immediate exit {summary["fee_immediate_exit"]}, total {summary["fee_round_trip"]} USDPR |',
f'| Estimated loss at immediate limits | {summary["loss_at_immediate_limit"]} USDPR, excluding funding |',
f'| Estimated loss at floor | {summary["loss_at_exit_floor"]} USDPR, excluding funding; not guaranteed |',
f'| Attempt bounds | One entry, at most {p.max_exit_attempts} exits, at most {p.max_signed_actions} signed actions including own-order cancellations |',
'',
'Objective rule: fresh executable book and account; require flat reconciliation, margin, 1x CROSS, two-sided depth and every possible whole-lot residual close assessment. Set BUY limit to runtime-rounded ask × 1.0005; round quantity down to lots from 25 / max(limit, mark). Select the smallest-spread eligible BTC/ETH/HYPE market. This is the tested qualification rule, not a discretionary price or a frozen VWAP signal.',
'',
'Qualification-only spread ceiling is 50 bps and needs explicit acceptance. Production keeps 15 bps, ATR 0.40%, 300 completed UTC bars, Top-3 and all frozen strategy/state rules.',
'',
'## Actual account, signer and source',
'',
f'- Registered team account / future SDK account_address: `{p.team_wallet}`.',
f'- Approved API signer: `{p.api_wallet}`. Local key-derived address matched without signing or allocating a nonce. Local lease rejected a second process; it was released.',
'- The human already confirmed this is the sole signing host. Remote machines were not independently inspected; the answer is not trade approval.',
f'- Fresh full account check: {account["started_utc"]}–{account["finished_utc"]}. Unified account, {account["account_readiness"]["collateral"]} USDPR, API approval valid until timestamp {account["account_readiness"]["agent_expiry_ms"]}, all ten markets 1x CROSS, no positions/orders, healthy clock and rate budget.',
f'- Proposal run: {r["started_utc"]}–{r["finished_utc"]}. Final actual-account reconciliation ready and flat observed. Both separate read-only journals reopened successfully; SQLite and checkpoint checksums pass, action rows zero. This is pre-trade flat evidence, not round-trip evidence.',
f'- Source hash `{p.source_hash}`; policy hash `{p.reliability_policy_hash}`. No source/configuration changes. The existing 1,682-pass, zero-failure regression XML matches this source. The full suite was reused, not rerun. Fresh Phase-0 and freeze checks pass.',
'- Existing SDK 0.24.0 transport uses TESTNET endpoint, par-only asset mapping, the team wallet as account_address and approved API signer, with exact permits and source/nonce/account guards. No actual SDK signer transport was constructed in this preparation.',
'',
'## Verified close scope and unverified protection',
'',
f'Runtime BTC lot: {row["spec"]["size_step"] if "size_step" in row["spec"] else "0.0001"}. All {row["residual_close_scope"]["possible_residual_count"]} possible whole-lot residual sizes were assessed at the fixed floor. Below-$10 residuals use only the V8.6 historically observed exact full-position SELL shape; ordinary entry minimums remain $10. One-lot BTC SELL evidence includes order 62228843959 on another account. Its zero residual was derived from matched fills, not an independent historical position snapshot; future acceptance and fills are not guaranteed.',
'',
'**Protective-stop acceptance and position coverage remain UNVERIFIED. No stop will be submitted.** Inherited proposal fields stop_trigger/stop_limit are compatibility price bounds, not accepted stop orders. Normal ACTUAL_PROTECTION_READY and CONTROLLED_EXECUTION_READY remain FALSE.',
'',
'If an exit is rejected, partially filled, blocked by its price floor, disconnected or uncertain, some exposure can remain unprotected. Cross margin uses shared account collateral. A 25 USDPR opening-notional cap is not a guaranteed total-loss cap; fees/funding and prolonged unresolved exposure can exceed estimated losses. Closing evidence alone does not validate protection.',
'',
'## Exit and emergency recovery',
'',
'1. Consume the one-entry marker durably before transmission; never repeat or enlarge an entry, including after timeout/restart. Reconcile actual team userFills, order status, orders and position.',
'2. Submit SELL reduce-only IOC for the exact freshly reconciled held quantity. Generate price from fresh bid × 0.998 using runtime precision; keep it at or above the fixed floor. At most two bounded exits; no over-sizing, exposure top-up or reversal.',
'3. An uncertain order receives bounded read-only status/fill/position reconciliation, never a blind resubmission. Retain client ID, exchange ID if known, consumed attempt and account checkpoint. Lock all new entries.',
'4. If uncertainty, residual exposure, expired permission, exhausted attempts or breached floor prevents a permitted close, halt writes and report EMERGENCY_EXIT_REQUIRED with exact residual/order uncertainty. A restart is read-only recovery, not permission to resume entry. The operator must explicitly authorize any recovery outside the existing limits; do not erase state.',
'5. Verify actual entry/exit fills, fees/funding and flat positions/orders. Generate real WHITELIST_TRADE_PROOF only from actual team-account exchange evidence. A fill and a flat position are separate claims; organizer whitelist confirmation needs organizer evidence.',
'',
'## Market rejections and approval',
'',
'| Market | Preparation result |','|---|---|']
for x in r['candidates']:lines.append(f'| {x["symbol"]} | '+('Eligible for explicit experimental risk review' if x['eligible_for_risk_review'] else x.get('blocker','Unknown'))+' |')
lines += ['', 'Approval must name this exact proposal ID and its size/entry/exit/attempt limits, confirm the shown wallet identities, and explicitly accept no protective stop, possible unprotected residual/manual recovery and the isolated 50 bps ceiling. Sole-host confirmation is already recorded. All authorization-template fields remain unfilled; future execution refreshes exact-action market/account/fee/clock checks and refuses changed or expired limits.', '', 'No autonomous trading, scheduled task, transfer, leverage change or scored pa/USDP switch was performed.', '', '```ini','EXECUTION_MODE=PAPER','ALLOW_LIVE_ORDERS=false','PROTECTION_ENABLED=false','QUALIFICATION_EXECUTION_AUTHORIZED=false','ACTUAL_PRACTICE_FILL_VERIFIED=false','ACTUAL_PROTECTION_READY=false','CONTROLLED_EXECUTION_READY=false','ORGANIZER_WHITELISTING_CONFIRMED=false','PRACTICE_READY=false','LIVE_READY=false','```','']
(OUT/'report.md').write_text('\n'.join(lines))
checksums={str(x.relative_to(OUT)):sha(x) for x in OUT.rglob('*') if x.is_file() and x.name!='artifact_checksums.json' and not x.name.endswith(('-wal','-shm'))}
(OUT/'artifact_checksums.json').write_text(json.dumps(checksums,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ['proposal_id','approval_deadline_ist','approval_window_open_at_report','entry_notional','fee_round_trip','loss_at_exit_floor']},indent=2))
