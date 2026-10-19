"""Finalize only a passing source-matched release. No signer or exchange actions."""
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib,json,sqlite3,subprocess,sys,time,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.opening_audit import opening_check
from exchange.terminal_app import read_json
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=active_source_hash(ROOT);release=OUT/'regression_release_final/test_receipt.json'
r=read_json(release)
assert r['passed'] and r['source_hash']==r['source_hash_after']==source
assert r['totals']==dict(tests=3109,failures=0,errors=0,skipped=0)
assert sha(release.parent/'regression.xml')==r['xml_sha256']
assert all(r[stage][check]['result']['passed'] for stage in ('checks_before','checks_after') for check in ('phase0','strategy_freeze'))
state=ROOT/'runtime/pas-btc-ewy-v5-2';current=read_json(state/'current.json');snapshot=read_json(Path(current['output'])/'status.json')
atomic_json(OUT/'final_observer_snapshot.json',snapshot)
assert snapshot['source_hash']==source and snapshot['pid']==read_json(OUT/'public_observer_release_launch.json')['worker_pid']
assert snapshot['signing_authority']=='NONE' and not snapshot['TRADING_AUTHORIZED'] and not snapshot['AUTO_TRADING_ACTIVE']
check=opening_check(ROOT,SimpleNamespace(state=state,release=release))
atomic_json(OUT/'opening_status.json',check)
# Preserve and verify every original logical journal/checkpoint and proof, not just file sizes.
b=read_json(ROOT/'docs/btc_ewy_v4_2026-10-19/baseline.json');preservation=dict(protected={},databases={})
for relative,expected in b['protected'].items():
 preservation['protected'][relative]=dict(sha256=sha(ROOT/relative),unchanged=sha(ROOT/relative)==expected)
for relative,expected in b['databases'].items():
 with sqlite3.connect((ROOT/relative).resolve().as_uri()+'?mode=ro',uri=True) as db:
  digest=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
  preservation['databases'][relative]=dict(dump_sha256=digest,unchanged=digest==expected['dump_sha256'],integrity=db.execute('pragma integrity_check').fetchone()[0])
preservation['all_53_preserved']=(len(preservation['databases'])==53 and all(x['unchanged'] and x['integrity']=='ok' for x in preservation['databases'].values()) and all(x['unchanged'] for x in preservation['protected'].values()))
assert preservation['all_53_preserved'];atomic_json(OUT/'preservation_receipt.json',preservation)
files={str(p.relative_to(ROOT)):sha(p) for d in ('scripts','algo-trading-bot') for p in (ROOT/d).rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)}
baseline=read_json(OUT/'baseline.json')
manifest=dict(source_hash=source,git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
 starting_source=baseline['source_hash'],files=files,changed_or_added=[p for p,h in files.items() if baseline['source_files'].get(p)!=h],
 config_sha256={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'configs').glob('*.json')},requirements_sha256=sha(ROOT/'algo-trading-bot/requirements.txt'))
atomic_json(OUT/'source_manifest.json',manifest)
soak=read_json(OUT/'soak_result.json');assert soak['source_hash']==soak['source_hash_after']==source
assert all(x['alive'] is True and x['owner_lock'] and x['source_matches'] for x in soak['samples'])
assert all(v=='ok' for v in soak['integrity'].values())
original=read_json(OUT/'public_audit/audit.json')
assert original['status']=='BOUNDED_AUDIT_COMPLETE' and original['terminal_flat']
assert len(original['final_readbacks'])==2 and all(x['original_order_status']=={'status':'unknownOid'} for x in original['final_readbacks'])
assert original['own_historical_orders']['matched_original_cloid']==[]
# This repeated local invocation must fail before constructing any observer/client.
command=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/anchorium_cli.py'),'start','--venue','pas','--state',str(state),'--duration','1']
p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
assert p.returncode==1 and 'PAPER_OWNER_ALREADY_RUNNING' in p.stdout+p.stderr
atomic_json(OUT/'duplicate_worker_verification.json',dict(exit_code=p.returncode,stdout=p.stdout,stderr=p.stderr,exchange_writes=0))
cases=[dict(module=c.get('classname'),name=c.get('name')) for c in ET.parse(release.parent/'regression.xml').iter('testcase')]
atomic_json(OUT/'test_case_manifest.json',cases)
now=time.time_ns()//1000000;local=datetime.fromtimestamp(now/1000,ZoneInfo('Asia/Kolkata')).isoformat()
summary=dict(observed_ms=now,local_time=local,source_hash=source,git_commit=manifest['git_commit'],
 verdict=check['verdict'],statuses=check['statuses'],release=r,preservation=preservation['all_53_preserved'],
 actual_exchange_writes=0,actual_wallet_signatures=0,actual_acceptance_created=False,actual_configuration_applied=False,
 automatic_buy_sell_software='Implemented; no individual prompts inside an independently qualified, genuinely accepted finite mandate.',
 no_profit_or_error_free_guarantee=True,observer=dict(pid=snapshot['pid'],session=current['session_id'],state=str(state),signing_authority='NONE'),
 historical_status='UNKNOWN_REMAINS_EXTERNALLY_BLOCKED',protection='PAS_NATIVE_AND_RESIDUAL_ROUTES_NOT_QUALIFIED',
 bounded_soak_ms=soak['finished_ms']-soak['started_ms'],external_alert_delivery=soak['external_alert_delivery'],
 next_steps=check['failed_requirements'],evidence=check['evidence'])
atomic_json(OUT/'release_summary.json',summary)
# Evidence for each failed requirement is independent of any proposed action.
evidence={
 'AUTOMATION_IMPLEMENTED':'Full current-source offline lifecycle and conditional-activation suites passed; this is software evidence only.',
 'RELEASE_VERIFIED':f"{r['totals']['tests']} passed, 0 failures/errors/skips; receipt and XML match the current dirty source hash.",
 'OBSERVER_HEALTHY':f"Public worker {snapshot['pid']}, owner lock, current source, market/account streams and fresh account read; bounded soak and SQLite integrity retained.",
 'FUNDING_VERIFIED':f"Fresh public USDP observation: {check['evidence']['funding'].get('status')}, balance {check['evidence']['funding'].get('balance')}; automatic detection grants no authority.",
 'ACCOUNT_IDENTITY_VERIFIED':'Configured API address is publicly approved. Official public leaderboard names Team Anchorium but publishes no wallet binding; no retained operator-reviewed scored wallet record was supplied. Local signer ownership is not certified here.',
 'BTC_1X_VERIFIED':f"Latest actual BTC leverage: {check['evidence']['leverage'].get('pas:BTC')}; no configuration was submitted.",
 'EWY_1X_VERIFIED':f"Latest actual EWY leverage: {check['evidence']['leverage'].get('pas:EWY')}; no configuration was submitted.",
 'HISTORICAL_ORDER_SAFE':'Original CLOID 0xac0eea156fcec80986dd67c9057b6ded still has two unknownOid replies, no matching historical order, and no admissible isolation. Original journal/nonce/attempt untouched.',
 'BTC_NATIVE_AND_RESIDUAL_QUALIFIED':'No genuine PAS trigger-to-linked-closing-fill proof. Fresh unsigned proposal: minimum lot 0.00001 BTC, about 0.81 USDP at reviewed stop, below ordinary $10 policy; no supported subminimum stop/cleanup exception.',
 'EWY_NATIVE_AND_RESIDUAL_QUALIFIED':'No genuine PAS trigger-to-linked-closing-fill proof. Fresh unsigned proposal: minimum lot 0.001 EWY, about 0.157 USDP at reviewed stop, below ordinary $10 policy; no supported subminimum stop/cleanup exception.',
 'MARKET_DATA_FRESH':'Warmup is sufficient (959 BTC / 4053 EWY contiguous retained bars), but authentic upstream candles/trades remain stale. Detailed current ages and raw REST/stream diagnostics are in opening_status.json and history_review_network/.',
 'EXACT_SESSION_ACCEPTED':'No genuine exact current-source finite PAS acceptance exists or was created. Current user intent does not complete the earlier required post-funding account verification or missing route evidence.',
 'TRADING_AUTHORIZED':'The worker is public-only with no signer or mandate. Funding, a date, a process, and synthetic tests cannot activate it.',
 'AUTO_TRADING_ACTIVE':'No authorized worker or matching owned transmitted PAS order/fill exists in this run.'}
lines=['# V5.3 final opening-day release audit','',
 '**NO-GO for autonomous PAS trading, including when funding alone is excluded.**', '',
 f'As of {local}. The requested engineering fixes are verified; remaining venue/account evidence has not been fabricated. No exchange write, actual-wallet signature, configuration application or human acceptance was created.', '',
 f'Source `{source}`; Git `{manifest["git_commit"]}` with the exact dirty-source manifest retained. **{r["totals"]["tests"]} tests passed**, zero failures/errors/skips. Frozen signal_brain and all manifested strategy methods/parameters pass against nse-working-baseline. All 53 original journals and 20 protected proof files remain unchanged.', '',
 '## Software repairs','',
 '- Reproduced dead-worker output reporting INTERRUPTED_UNCLEAN while TRADING_AUTHORIZED and AUTO_TRADING_ACTIVE remained true. Status/report/dashboard now invalidate cached authority on dead/stalled/expired/mismatched workers, retain historical fill evidence, and refresh source/account/fee/funding/candle ages at read time without changing stored evidence.',
 '- Incomplete public history and configuration discovery now return a nonzero exit status. Their failure JSON remains available for diagnosis.',
 '- Added opening-check, a read-only 14-status checklist with failed requirements and executable next steps. It cannot create permission or bypass any execution guard. No new execution gate was introduced.',
 '- Existing accepted-session BUY/SELL lifecycle needs no individual order prompts. Source-bound human session activation, risk exits, one-position rule, strict expiry, frozen strategy and PAPER/false migration defaults remain.', '',
 '## Independent statuses','', '| Requirement | Value | Supporting evidence |','|---|---|---|']
for key,value in check['statuses'].items():lines.append(f'| {key} | {str(value).upper()} | {evidence[key]} |')
lines += ['', 'Every false requirement has its next step in [opening_status.json](opening_status.json); exact verified CLI commands are in [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md).', '',
 '## Why the remaining gates stay','',
 'The fresh native proposals show that larger entry sizing does not eliminate a possible one-lot partial fill or final exit remainder. The [official order-error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) lists the ordinary $10 minimum. A PAS subminimum fixed native-stop route is not independently established. Removing the guard would assert an exit capability that has not been demonstrated.', '',
 'The [official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes mark triggers, fixed-size stops and partially filled parent-order behavior. An application watcher does not supply exchange-resident outage protection. Switching to Stop Market would also change the approved execution allowance. No independently validated replacement was found; no synthetic test was relabeled as genuine venue qualification.', '',
 'The original action is older than the documented nonce horizon and the account is currently flat. Those facts constrain future replay risk but do not establish the original historical outcome or complete accounting. The exact original causal/terminal record or a separately reviewed, expressly accepted finite isolation policy remains necessary. No generic UNKNOWN bypass or reset was introduced.', '',
 'The official public leaderboard was inspected through its declared data URLs. Team Anchorium is listed, but those rows have no public wallet address. The configured wallet therefore cannot be certified from a team-name match. Retained page/JSON hashes and matching rows are in public_registration_review/.', '',
 '## Continuous-operation and opening drill','',
 f'The actual bounded soak lasted {soak["finished_ms"]-soak["started_ms"]} ms with {len(soak["samples"])} samples: worker liveness/owner lock/source verified, healthy market/account streams, account reconciliation ages and REST timings retained, SQLite integrity ok, local event delivery observed. External alert delivery was not configured or tested. The first sandbox PID probe was unavailable and is retained separately; the independent host probe verified liveness. No overnight uptime or crash-survival guarantee is claimed.', '',
 'A duplicate worker was actually rejected before client construction. The source-change shutdown of the previous observer completed with two flat readbacks and healthy persistence; its history cache was reused without resetting the original execution state. Crash/restart, expiry, disconnect, partial-fill and signing-barrier behavior is covered by the offline regression, not represented as a destructive production crash experiment.', '',
 'The 17-scenario pure readiness drill had zero prompts, no network, no signer and zero signatures/writes. Every omitted prerequisite blocked the simulated handoff. Separate PAS offline SDK tests exercised frozen LONG entry, reported fixture fills, protection, partial exits, accounting and expiry with ephemeral keys and no HTTP. They do not qualify an actual account, residual route or profitable edge.', '',
 '## Opening and operation','',
 'The [published scored interval](https://perpetual-alpha26.github.io/schedule) starts October 19 at 12:00 UTC / 17:30 IST and ends November 6 at that same UTC time. Calendar opening and funding do not resolve the other statuses. No unnecessary practice-date permission gate was added.', '',
 f'The standalone public worker is PID {snapshot["pid"]}, session {current["session_id"]}, state runtime/pas-btc-ewy-v5-2. It detects funding automatically, normally with up to one 300-second account polling interval of delay. It cannot sign. A real session can operate without per-BUY/SELL prompts only after all prerequisites and its exact finite acceptance pass. The current contract cannot accept missing funding/qualification in advance. No profit, error-free operation or deadline launch is guaranteed.', '',
 'Review the runbook for funding/history/configuration/qualification preparation, exact session acceptance, conditional launch, stop and actual P&L reconciliation. Read-only monitoring continues; the Mac, process, power, network and exchange remain dependencies.']
(OUT/'FINAL_RELEASE_REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(dict(verdict=summary['verdict'],source_hash=source,tests=r['totals'],statuses=check['statuses'],all_53_preserved=True),indent=2))
