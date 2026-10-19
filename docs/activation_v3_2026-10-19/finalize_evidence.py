"""Read-only preservation and release report assembly; no exchange/client imports."""
from pathlib import Path
import json,hashlib,sqlite3,time,sys
from decimal import Decimal as D
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline.json').read_text());receipt=json.loads((O/'regression_release_final/test_receipt.json').read_text())
source=active_source_hash(R)
assert receipt.get('passed') and receipt['source_hash']==receipt['source_hash_after']==source
assert sha(O/'regression_release_final/regression.xml')==receipt['xml_sha256']
protected={p:dict(sha256=sha(R/p),matching=sha(R/p)==h) for p,h in b['protected'].items()}
databases={}
for p,prior in b['databases'].items():
 db=sqlite3.connect((R/p).as_uri()+'?mode=ro',uri=True)
 integrity=db.execute('pragma integrity_check').fetchone()[0];h=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest();db.close()
 databases[p]=dict(integrity=integrity,dump_sha256=h,unchanged=h==prior['dump_sha256'])
assert len(databases)==53 and all(x['integrity']=='ok' and x['unchanged'] for x in databases.values())
assert all(x['matching'] for x in protected.values())
current={str(p.relative_to(R)):sha(p) for d in ('scripts','algo-trading-bot') for p in (R/d).rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)}
reasons={
 'durable_history.py':'Crash-safe canonical completed-bar persistence, deduplication, conflicts, bounded retention and gap/warmup/freshness evidence',
 'pas_funding.py':'Unsigned exact-team canonical USDP and mode evidence, distinct zero/stale/unavailable/positive states, no double counting or inferred organizer credit',
 'pas_controller.py':'Independent diagnostic opening/readiness gates without execution capability or clock/funding activation',
 'pas_configuration.py':'Exact new configuration-only TTY approval and future source/plan-bound one-use SDK route with shared nonce and authoritative readback',
 'pas_configuration_plan.py':'Connect unsigned plan explanation to separate exact PAS configuration route; old par approval remains invalid',
 'leverage_configuration.py':'Reuse existing exact 1x SDK sink with PAS-only plan-hash action binding, finite signed expiry and transmitted-action consumption; preserve par behavior',
 'pas_native_plan.py':'Dedicated unsigned PAS qualification risk/cleanup proposal and separate telemetry milestones; unsupported subminimum behavior stays blocked',
 'pas_economics.py':'Separate documented PAS fee scenario from unchanged 6x stress guard and actual fill fees; expected PnL stays unknown',
 'pas_operations.py':'Public funding/configuration/native-preparation operator entry points, with bounded reads and preserved receipts',
 'terminal_app.py':'Expose reviewed CLI routes, exact public proof/release checks and readiness/funding/history/fee dashboard',
 'terminal_observer.py':'Integrate durable history, funding events and fresh post-backfill signal observations; refresh canonical metadata and report source drift',
 'terminal_evidence.py':'Include new configuration uncertainty in shared local-state diagnostics',
 'scored_session.py':'Permit only the current owned configuration management record at its own sink; foreign order uncertainty still blocks',
 'venue_discovery.py':'Persist canonical funding evidence alongside ten-market discovery and unsigned configuration plan',
 'test_activation_v3.py':'52 deterministic/adversarial V3 tests, ephemeral isolated SDK-only signing and explicit PAS test environment'}
changes=[dict(file=p,before_sha256=b['files'].get(p),after_sha256=h,reason=reasons.get(Path(p).name,'Review supporting change'),release_source_hash=source,regression_xml_sha256=receipt['xml_sha256']) for p,h in sorted(current.items()) if b['files'].get(p)!=h]
assert all(Path(x['file']).name in reasons for x in changes)
preservation=dict(observed_ms=time.time_ns()//1000000,starting_source=b['source_hash'],source_hash=source,protected=protected,databases=databases,all_original_journals_unchanged=True,all_protected_files_unchanged=True,changed_python_files=len(changes))
(O/'preservation_receipt.json').write_text(json.dumps(preservation,indent=2)+'\n')
(O/'change_manifest.json').write_text(json.dumps(dict(source_hash=source,changes=changes,regression_receipt='regression_release_final/test_receipt.json',supporting_change=dict(file='docs/legacy_dependency_inventory.csv',sha256=sha(R/'docs/legacy_dependency_inventory.csv'),reason='Regenerated required legacy occurrence inventory; classifications remain reference/migration dispositions')),indent=2)+'\n')
d=json.loads((O/'native_qualification_release/fresh_discovery/discovery.json').read_text())
n=json.loads((O/'native_qualification_release/qualification_proposal.json').read_text())
h=json.loads((O/'historical_disposition.json').read_text())
c=json.loads((R/'runtime/pas-v3-public/current.json').read_text());v=json.loads((Path(c['output'])/'status.json').read_text())
assert v['source_hash']==source
from exchange.pas_funding import current_funding
latest_funding=current_funding(v.get('funding'),time.time_ns()//1000000)
# Use a full completed table for market summaries, not an in-progress scan.
frame_text=(Path(c['output'])/'events.jsonl').read_text()
frame_lines=frame_text.splitlines()
if frame_text and not frame_text.endswith('\n'):frame_lines=frame_lines[:-1]
frames=[json.loads(line) for line in frame_lines]
complete=[f for f in frames if len(f.get('signals',[]))==10 and len(f.get('liquidity',{}))==10]
f=complete[-1] if complete else v
market=[]
for x in d['markets']:
 s=x['symbol'];history=(v.get('market_history') or {}).get(s,{})
 signal=next((r for r in f.get('signals',[]) if r['symbol']==s),{})
 market.append(dict(symbol=s,asset_id=x['spec']['asset_id'],leverage=x['active_asset']['leverage'],observed_ms=x['observed_ms'],
  book_only_quantity=x['displayed_book_only_quantity'],book_only_notional=x['displayed_book_only_notional'],
  spread_bps=str((D(x['book']['asks'][0]['price'])-D(x['book']['bids'][0]['price']))/((D(x['book']['asks'][0]['price'])+D(x['book']['bids'][0]['price']))/2)*10000),
  history=history,decision=signal.get('decision','UNKNOWN'),reasons=signal.get('reasons',[]),
  authorized_executable_notional='0',actual_native_protection_qualified=False,expected_net_pnl=None))
(O/'market_readiness.json').write_text(json.dumps(dict(discovery_source=d['source_hash'],observed_ms=d['finished_ms'],market_rows=market),indent=2)+'\n')
rows=[
 ('Release consistency','Changed code cannot use the old 2927-test release','Source-matched full regression and preserved old XML',str(receipt['totals']),source,'None for offline release','VERIFIED_RESOLVED'),
 ('Funding detection','Practice USDPR cannot fund PAS','Canonical unsigned USDP/mode watcher and durable events','Funding arrival/disappearance/token/mode/age tests',str(d['funding']['balance'])+' USDP, '+d['funding']['status'],'Actual USDP credit and original organizer origin record','SOFTWARE_READY_EXTERNAL_PROOF_MISSING'),
 ('PAS 1x CROSS','Current market leverage is 10x/20x','Exact configuration-only plan, genuine TTY approval and one-use SDK route','Ephemeral PAS SDK wire/expiry/exact-action/repeat rejection; existing ten-market configuration regression',str(sum(x['active_asset']['leverage']==dict(type='cross',value=1) for x in d['markets']))+'/10 actually 1x CROSS','Fresh funded clean account, separate approval and authoritative final readbacks','AUTHORIZATION_REQUIRED'),
 ('Historical UNKNOWN outcome A','Original causal/transmission evidence incomplete','Preserved forensic review; no fabricated certificate','Shared barriers and original certificate classifier regression',h['disposition']+'; exact original CLOID remains UNKNOWN','Admissible original terminal/causal record','BLOCKED'),
 ('Independent PAS isolation B','Shared account/API/nonce domain','No automatic DEX isolation bypass','Foreign UNKNOWN and shared order barriers retained','No independent isolation proof or approval','Independently justified and explicitly authorized policy; preserve original row and nonce','BLOCKED'),
 ('Consumed native attempt','Prior terminal do_not_restart marker','Preserved and reviewed; no reset/relaunch','Consumed-attempt tests retained','Original marker unchanged','Independent review; no authority inherited by a new test','BLOCKED'),
 ('PAS native/residual qualification','No genuine PAS trigger/residual proof; subminimum cleanup unsupported','Dedicated unsigned test proposal and separate milestone telemetry; par repairs retained','PAS lifecycle fault suite plus V3 plan/milestone tests','UNQUALIFIED; no actual PAS test submitted','Admissible PAS residual cleanup scope, funded/1x/clean account, permission and new exact test approval; future narrow integration review','BLOCKED'),
 ('History and frozen signal readiness','Sparse/stale PAS candles and memory-only cache','Crash-safe authentic cache, incremental updates, conflict/gap/age reports; post-backfill fresh quotes','Restart/dedup/numeric-format/conflict/future/gap/mapping tests','See market_readiness.json; no manufactured bars','Sufficient fresh authentic 300-bar history and a valid frozen LONG signal','SOFTWARE_READY_EXTERNAL_PROOF_MISSING'),
 ('Executable economics','Book movement or target estimate is not a qualified edge','Both-side caps remain; published fee scenario separate from unchanged stress guard','Existing risk/liquidity tests and V3 fee/report checks','Actual authorized capacity zero; no qualified executable setup','Qualified protection, funding/margin, fresh signal and exact approved risk bounds','SOFTWARE_READY_EXTERNAL_PROOF_MISSING'),
 ('Scored calendar','Outdated practice rules must not gate the open scored phase','Shared exact UTC boundaries preserved; verified official schedule','Start/end-minus-one/exact-boundary tests','Preopening at preparation; no clock-based authority','Official opening plus independent account eligibility requirements','SOFTWARE_READY_EXTERNAL_PROOF_MISSING'),
 ('October 17–18 special practice permission on PAS','Practice exception has a distinct venue/date scope','Never imposed on open PAS scored trading','Existing scored boundary/proposal tests','Official schedule identifies scored interval; no par session launched','Not applicable to open PAS scored phase; team provenance remains separate','NOT_APPLICABLE_WITH_PROOF'),
 ('Finite autonomous signing','Public readiness cannot create a signer','Existing exact source-bound noninteractive two-entry/twelve-action lifecycle preserved','Full crash/nonce/clock/loss/expiry/partial/protection/reconcile tests; V3 report cannot manufacture acceptance','No actual session acceptance or signer created','Fresh genuine exact session approval after every prerequisite','AUTHORIZATION_REQUIRED'),
 ('Standalone observation','Codex/app must not be the worker runtime','Independent public process with owner/source guards, persistent logs/history and process-bound caffeinate','Actual complete ten-market scans, owner rejection and status/command/source/output verification','See public_observer_verification.json','Mac/Python/power/internet/exchange must remain available','VERIFIED_RESOLVED')]
truth=[dict(blocker=a,initial_cause=b,code_repair=c,offline_verification=d,current_exchange_evidence=e,external_requirement=f,status=g) for a,b,c,d,e,f,g in rows]
(O/'blocker_truth_table.json').write_text(json.dumps(truth,indent=2)+'\n')
summary=dict(observed_ms=time.time_ns()//1000000,final_status='BLOCKED_EXTERNAL_EVIDENCE',observation_capability='READY_FOR_OBSERVATION',trading_verdict='NO_GO',source_hash=source,regression=receipt,original_53_preserved=True,
 actual_funding=latest_funding,discovery_funding=d['funding'],one_x_verified=sum(x['active_asset']['leverage']==dict(type='cross',value=1) for x in d['markets']),
 historical_unknown='BLOCKED',safe_pas_isolation='BLOCKED',native_qualification='UNQUALIFIED',native_proposal_hash=n['proposal_hash'],
 account=d.get('account'),terminal_discovery_flat=d.get('terminal_flat'),terminal_discovery_readbacks=d.get('terminal_readbacks'),
 actual_pas_fills=d.get('account',{}).get('fills'),actual_pas_realized=d.get('account',{}).get('realized'),
 actual_funding_events=d.get('account',{}).get('funding_events'),historical_oct15_par_net='0.050512 TEST USDPR; separate from PAS',
 observer=dict(pid=c['pid'],session_id=c['session_id'],output=c['output'],source=v['source_hash'],status=v['status'],status_observed_ms=v['updated_ms'],complete_frame_count=len(complete),
  stream_connected=v.get('stream_connected'),account_stream_healthy=v.get('account_stream_healthy'),actual_errors=v.get('actual_errors'),
  terminal_flat='NOT_CLAIMED_WHILE_RUNNING',signing_authority='NONE'),
 preparation_exchange_writes=0,actual_wallet_signatures_created=0,actual_approval_created=False,
 remaining_external_conditions=[x for x in truth if x['status'] not in {'VERIFIED_RESOLVED','NOT_APPLICABLE_WITH_PROOF'}],
 known_implementation_limit='Dedicated PAS native execution exception remains unavailable until admissible residual cleanup policy and exact authority are independently established; preparation does not certify or bypass that integration.',
 dependencies='Standalone public observation depends on Mac, Python, power, internet and exchange, independent of Codex/app; no unattended recovery/signing can be guaranteed through interruption.')
(O/'release_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(dict(source=source,tests=receipt['totals'],xml=receipt['xml_sha256'],all_53_preserved=True,protected_preserved=True,changed_files=len(changes),final_status=summary['final_status'])))
