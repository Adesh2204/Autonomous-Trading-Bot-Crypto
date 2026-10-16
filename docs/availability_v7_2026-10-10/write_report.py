"""Source-bound A–M V7 report from completed actual evidence. No network."""
from pathlib import Path
from collections import Counter
from statistics import median
import hashlib,json,sys,sqlite3,fcntl,os,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
os.environ.update(ANCHORIUM_PUBLIC_ONLY='true',EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS='false',SIGNAL_DATA_MODE='PAR_NATIVE_ONLY',EXTERNAL_SIGNAL_LIVE_APPROVED='false')
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.paper_checkpoint import unpack
from strategy_freeze import verify_strategy_freeze

def fmt(value):
 if value is None:return 'Unknown / not evaluated'
 if isinstance(value,float):return f'{value:.3f}' if abs(value)>=.01 or value==0 else f'{value:.3g}'
 return str(value)

def read(path):return json.loads(Path(path).read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def link(label,path):return '['+label+'](<'+str(path.resolve())+'>)'

baseline=read(BASE/'baseline.json');tests=read(BASE/'regression_release/test_receipt.json')
sequence=read(BASE/'validation_sequence.json');receipt=read(BASE/'short_15m/short_15m_paper_receipt.json')
cert=read(BASE/'short_15m/short_15m_certification.json');health=receipt['final_health']
segment=Path(health['segment']);avail=read(segment/'candle_availability.json');stream=health['public_stream']
report=read(segment/'report.json');tape=Path(receipt['health_samples_path'])
samples=[json.loads(line) for line in tape.read_text().splitlines()]
xml=BASE/'regression_release/regression.xml'
source_findings=read(BASE/'native_source_findings.json')
price_analysis=read(BASE/'external_price_analysis.json')
assert tests['passed'] and tests['totals']['failures']==tests['totals']['errors']==tests['totals']['skipped']==0
assert digest(xml)==tests['xml_sha256']
assert active_source_hash(ROOT)==tests['source_hash']==tests['source_hash_after']==receipt['source_hash_before']==receipt['source_hash_after']
assert verify_strategy_freeze()['passed']
assert digest(ROOT/'algo-trading-bot/signal_brain.py')==baseline['strategy_sha256']
assert digest(tape)==receipt['health_samples_sha256']
assert sequence['phase']=='COMPLETED' and receipt['exit_code']==0 and health['status']=='STOPPED'
assert stream['workers_stopped_cleanly'] is True
assert all(s['execution_mode']=='PAPER' and s['allow_live_orders'] is False and s['exchange_orders_submitted']==0 for s in samples)
assert all(s['segment']==str(segment) for s in samples)
state=Path(receipt['state_directory']);checkpoints=[]
for path in (state/'paper.sqlite',state/'backups/paper-latest.sqlite'):
 db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 text,checksum=db.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone();db.close()
 assert hashlib.sha256(text.encode()).hexdigest()==checksum
 value=unpack(json.loads(text));assert value['clean'] is True
 assert value['identity']['active_source_hash']==tests['source_hash']
 assert len(value['execution']['fills'])==health['local_fills']
 assert len(value['ledger']['positions'])==health['local_positions']
 for field in ('cash','realized_pnl','fees_paid','funding_cashflow'):
  assert str(value['ledger'][field])==str(report['portfolio'][field])
 checkpoints.append(dict(path=str(path),integrity='ok',checksum=checksum,clean=True,source=tests['source_hash'],paper_fills=len(value['execution']['fills']),paper_positions=len(value['ledger']['positions'])))
assert checkpoints[0]['checksum']==checkpoints[1]['checksum']
for path in (ROOT/'runtime/paper').rglob('*owner.lock'):
 with path.open('r') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
traces=[json.loads(s) for s in (segment/'results/opportunity_traces.jsonl').read_text().splitlines()]
first=Counter(t.get('first_blocking_reason') or 'NONE' for t in traces)
funnel={}
for stage in ('MARKET_DATA_HEALTHY','ENOUGH_HISTORY','LIQUIDITY_PASS','SPREAD_PASS','ATR_PASS','SCANNER_QUALIFIED','TOP3_SELECTED','STRATEGY_EVALUATED','SIGNAL_GENERATED','FRICTION_PASS','RISK_PASS'):
 evaluated=[t['stages'][stage]['status'] for t in traces if stage in t['stages'] and t['stages'][stage]['status'] in {'PASS','FAIL'}]
 funnel[stage]=dict(evaluated=len(evaluated),passed=evaluated.count('PASS'),failed=evaluated.count('FAIL'),
  pass_percent=100*evaluated.count('PASS')/len(evaluated) if evaluated else None)
# Reconnect success is a completed post-disconnect account barrier, not any REST reconciliation.
waiting=False;reconnect_successes=0
for e in stream.get('events',[]):
 if e['phase']=='DISCONNECTED':waiting=True
 elif e['phase']=='PAPER_ACCOUNT_RECONCILED' and waiting:reconnect_successes+=1;waiting=False
comparisons=read(BASE/'external_capture/comparison.json') if (BASE/'external_capture/comparison.json').exists() else {'results':[],'counterfactual_verdict':'NOT ENOUGH EVIDENCE'}
external_receipt=read(BASE/'external_capture/receipt.json') if (BASE/'external_capture/receipt.json').exists() else {}
if external_receipt:
 assert external_receipt['source_hash_before']==external_receipt['source_hash_after']==tests['source_hash']
 assert external_receipt['exchange_orders_submitted']==0
flags=dict(STRATEGY_FREEZE=True,FULL_TEST_SUITE=True,CANDLE_MONITOR_IMPLEMENTED=True,
 CANDLE_PUBLICATION_TRACKING='OBSERVATION_DELAY_TRACKED; EXCHANGE_PUBLICATION_TIME_UNKNOWN',
 REST_RECOVERY_VALIDATED='OFFLINE_AND_BOUNDED_PUBLIC_EVIDENCE; READINESS_NOT_IMPLIED',
 CANDLE_PROVENANCE_VALIDATED=True,MARKET_HEALTH_READY=bool(cert['feed_certified']),
 NATIVE_FEED_READY=bool(cert['feed_certified']),EXTERNAL_PROVIDER_RESEARCH='COMPLETE_DOCUMENT_REVIEW',
 EXTERNAL_ASSET_MAPPING='TEN_REFERENCES_IDENTIFIED; EQUIVALENCE_UNVERIFIED',
 EXTERNAL_SOURCE_COMPARISON='PRICE_OBSERVATIONS_ONLY; COUNTERFACTUAL_NOT_ENOUGH_EVIDENCE',
 EXTERNAL_SIGNAL_LIVE_APPROVED=False,PAPER_READY=bool(cert['feed_certified']),
 CONTROLLED_EXECUTION_READY=False,PRACTICE_READY=False,LIVE_READY=False,
 EXECUTION_MODE='PAPER',ALLOW_LIVE_ORDERS=False,PROTECTION_ENABLED=False)
modified=list(read(BASE/'modified_files.json'))
modified_hashes={p:digest(ROOT/p) for p in modified}
new_tests=[t for t in ET.parse(xml).getroot().iter('testcase') if any(s in t.attrib.get('classname','') for s in ('test_candle_availability_v7','test_external_data_v7'))]
summary=dict(verdict='NATIVE_FEED_READY' if cert['feed_certified'] else 'NATIVE_FEED_NOT_READY',
 implementation='IMPLEMENTED_AND_TESTED',external_research='DOCUMENT_REVIEW_COMPLETE; EMPIRICAL_SIGNAL_VALIDATION_INCOMPLETE',
 source_hash=tests['source_hash'],strategy_sha256=baseline['strategy_sha256'],flags=flags,tests=tests,
 previous_tests=1356,new_tests=len(new_tests),modified_files=modified_hashes,sequence=sequence,
 receipt=receipt,certification=cert,availability=avail,funnel_independent=funnel,funnel_authoritative=cert['funnel']['session'],first_rejections=dict(first),paper_portfolio=report['portfolio'],
 reconnect_successes=reconnect_successes,checkpoints=checkpoints,
 external_comparisons=comparisons,external_receipt=external_receipt,actual_orders=0,
 source_findings=source_findings,external_price_analysis=price_analysis,restoration_timing=read(BASE/'restoration_timing.json'),limitations=['Exchange publication time is unknown; observed delay includes network/polling.',
 'Startup history is left-censored, still-absent live intervals are right-censored.',
 'Current covered-response absence is not permanent absence or proof of an exchange defect.',
 'Monitor/scanner/cache observations differ; actual scanner traces remain authoritative.',
 'PAPER reconciliation and equity do not certify the funded account.',
 'No external equivalent VWAP, production signal mode or counterfactual profitability is certified.'])
atomic_json(BASE/'final_summary.json',summary)
lines=['# Team Anchorium — V7 native availability and external research report','',
 '## A. Executive verdict','',
 '**EXTERNAL_RESEARCH_COMPLETE** for permission/provider review, candidate mappings and an isolated price comparison. Volume equivalence, external signal validation and licensing suitability remain unverified.', '', '**'+summary['verdict']+'**. Implementation and the full regression are complete. External provider research is complete as a document review; production-equivalent external signals remain unvalidated and disabled.',
 '', 'A candle is one minute of genuine prices and volume. The new monitor explains missing minutes, when they arrive, whether they reach cache and why a market is excluded. It does not manufacture bars or authorize trading.',
 '', '## B. Files inspected and modified','',
 'Discovery was saved before edits: '+link('discovery table',BASE/'discovery.md')+'. Existing validators, one repair worker, quarantine manager, request budgets and frozen scanner were extended or reused. Original NSE files were untouched.',
 '', '| Exact file | Change and evidence |','|---|---|']
notes={
 'candle_availability.py':'New source-aware observations, live/left/right censoring, bounded interval history, recovery counters, cache/UTC distinction; native monitor tests.',
 'hyperliquid_market_data.py':'Observe real REST/WS rows; share monitor; report repair outcomes; preserve proven full-window repair and merge guard.',
 'market_health.py':'Optional sufficient-sample retry hints only increase bounded backoff; no threshold or health formula edits.',
 'market_stream.py':'Throttled availability snapshots alongside existing transport/account/market health.',
 'paper_operations.py':'Explicit native/scanner/signal flags while PAPER trading remains locked.',
 'check_practice_health.py':'Timestamped availability table, exact reasons, queue/restorations, latency/censoring, independent transport flags; existing exit meanings retained.',
 'run_crypto_paper.py':'Share one native monitor between public clients; save detailed final availability after workers stop.',
 'venue_config.py':'Reject external production source mode and self-declared external live approval; keep public-only dotenv bypass.',
 'external_data.py':'Offline library, immutable research types, strict mapping and UTC/as-of validation; no network/live imports.',
 'compare_external_data.py':'Standalone bounded public-only research capture; fixed read endpoint, separate namespace and immutable output.',
 'test_candle_availability_v7.py':'OFFLINE_FIXTURE native availability/recovery/freshness/retention tests; cannot certify a venue.',
 'test_external_data_v7.py':'OFFLINE_FIXTURE isolation, mapping, volume, UTC, source outage and production-gate tests.',
 'external_research.example.json':'Unloaded false/null placeholders; no API credentials or paid service activated.'}
function_manifest=read(BASE/'modified_function_manifest.json')
for p in modified:
 functions=function_manifest.get(p,[])
 detail=(' Functions: `'+', '.join(functions)+'`.' if functions and not Path(p).name.startswith('test_') else '')
 lines.append('| '+link(p,ROOT/p)+' | '+notes.get(Path(p).name,'Scoped change; see source hash manifest')+detail+' |')
lines+=['','Generated legacy inventory was refreshed with the existing script, with the previous inventory saved before regeneration. It records source locations and matched terms, not credentials. The two generated files are '+link('inventory CSV',ROOT/'docs/legacy_dependency_inventory.csv')+' and '+link('inventory summary',ROOT/'docs/legacy_dependency_inventory.json')+'.', '',
 'Full scope and limits: '+link('implementation notes',BASE/'implementation_scope.md')+'.',
 '','## C. Candle availability report','',
 'Final observations use the same latest 300 expected completed UTC intervals. Cache counts are separate from full UTC scanner history; 299 in this view can coexist with a still-fresh earlier 300-bar tail under the unchanged two-minute policy. Eligibility is not inferred from this table alone.',
 '', '| Market | Expected | Present | Missing | Contiguous tail | REST / WS live delay n; median / p95 ms | Quarantine reason | Status |',
 '|---|---:|---:|---:|---:|---|---|---|']
for s,r in sorted(avail['markets'].items()):
 stats=[]
 for source in ('REST','WS'):
  d=r['latency'][source];stats.append(source+': '+str(d['observation_count'])+'; '+fmt(d['median_ms'])+' / '+fmt(d['p95_ms']))
 lines.append('| '+s+' | '+str(r['expected_bars'])+' | '+str(r['present'])+' | '+str(r['missing'])+' | '+str(r['contiguous_valid_tail'])+' | '+'; '.join(stats)+' | '+', '.join(r['quarantine_reason'])+' | '+r['status']+' |')
lines+=['','`null` means unobserved/unknown, not zero latency. Detailed REST/WS first/last reception, rejected/conflicting duplicates, longest run, close age, exact missing timestamps, full-history checks, right-censored intervals and next retry are in '+link('availability snapshot',segment/'candle_availability.json')+'. Startup history is excluded from live percentiles. Small samples do not support stable latency conclusions.',
 '','| Source / market | Live completed samples | Median ms | P90 ms | P95 ms | P99 ms | Max ms | Still unobserved live intervals |',
 '|---|---:|---:|---:|---:|---:|---:|---:|']
for symbol,m in sorted(avail['markets'].items()):
 for source in ('REST','WS'):
  d=m['latency'][source]
  lines.append('| '+source+' '+symbol+' | '+' | '.join(fmt(d[k]) for k in ('observation_count','median_ms','p90_ms','p95_ms','p99_ms','max_ms','never_observed_intervals'))+' |')
lines+=['',('![Observed REST arrivals](<'+str(BASE/'native_rest_delay.png')+'>)' if (BASE/'native_rest_delay.png').exists() else ''), '',
 'These are local arrival measurements. With fewer than 20 live intervals, adaptive hints remain off. Still-unobserved intervals are censored at shutdown; no zero delay is invented.',
 '','| Market | Full UTC requested minutes (last scanner read) | Completed received | Missing | Last validation reason | Still current at shutdown |',
 '|---|---:|---:|---:|---|---|']
for symbol,m in sorted(avail['markets'].items()):
 h=m['strategy_history']
 lines.append('| '+symbol+' | '+str(h.get('requested_interval_count'))+' | '+str(h.get('completed_count'))+' | '+str(h.get('requested_window_missing_count'))+' | '+str(h.get('reason'))+' | '+str(m['strategy_history_current'])+' |')
lines+=['','This snapshot follows the worker stop. Quote/book-age reasons can include aging during shutdown; candle gaps and stale completed history also appear in the earlier operating observations. These post-stop ages are not proof of a transport failure.', '',
 'Plain meanings: insufficient history means too few consecutive genuine completed minutes; stale means the newest completed close exceeds the unchanged two-minute allowance; a gap means missing minutes inside the input; quarantine means the symbol is excluded until the required checks recover.',
 '', ('![Native availability](<'+str(BASE/'native_availability.png')+'>)' if (BASE/'native_availability.png').exists() else 'Exact tables and interval CSV are preserved; plotting libraries are unavailable in the supplied runtimes.'),
 '','## D. Root causes','',
 '- Verified historical client defects remain documented in V6: zero-ATR validation, repair-before-merge and completed-candle conflict handling. V7 does not reassign old stale cases without original wire evidence.',
 '- A current missing minute absent from a covering decoded REST response is an observed source-response absence. Its underlying venue cause remains unknown; quiet trading and delayed publication are not automatically API defects.',
 '- A previously absent exact minute later observed is classified delayed availability. Its reception-minus-close time includes network, request schedule and processing; an exchange publication timestamp is unavailable.',
 '- Source-observed bars missing from cache, validator rejection, merge conflict, incomplete request coverage, unobserved WS events and rate deferrals are separate reasons.',
 '- Market volatility/spread and strategy/economics rejection remain distinct from missing data. No threshold was reduced to obtain trades.',
 '','| Market | Distinct intervals absent in a covered decoded REST response | Those later observed completed through REST | Conflicting observed intervals |',
 '|---|---:|---:|---:|']
for symbol,m in sorted(source_findings['markets'].items()):
 lines.append('| '+symbol+' | '+str(m['intervals_absent_in_at_least_one_covered_rest'])+' | '+str(m['those_later_observed_completed_through_rest'])+' | '+str(m['conflicting_intervals'])+' |')
lines+=['','These are distinct intervals across retained observations in this fresh run, not just the final 300-minute view. Source absence and underlying cause are different findings. Exact timestamps and requests remain in the public capture and '+link('organizer evidence',BASE/'organizer_missing_minute_evidence.json')+'.',
 '','## E. Recovery performance','',
 'Recovery uses the existing single worker, coalesced reads, 30-second–five-minute exponential cooldown and weighted budget with safety reserves. Twenty live REST completed samples are required for optional delay hints; insufficient samples keep conservative backoff. Old due cohorts lead; near-ready markets break ties without excluding other due markets.',
 '', '| Market | Attempts | Incomplete/failed input recoveries | First REST arrivals after prior absence | Cache holes filled during recovery (includes warmup) | Last successful input recovery ms | Next retry ms |',
 '|---|---:|---:|---:|---:|---:|---:|']
for s,r in sorted(avail['markets'].items()):
 rec=r['recovery'];lines.append('| '+s+' | '+str(rec['attempts'])+' | '+str(rec['failures'])+' | '+str(rec['recovered_missing'])+' | '+str(sum(e.get('cache_holes_filled',0) for e in rec['events']))+' | '+str(rec['last_success_ms'])+' | '+str(r['next_recovery_at_ms'])+' |')
lines+=['','The first-REST-arrival column includes startup minutes previously marked not-yet-observed. It must not be read as thousands of repaired exchange gaps. The separate covered-response table above is the narrower evidence of later arrivals after decoded response absences.', '',
 'Cache holes filled are actual admissions during a recovery window; simultaneous WS activity is not assumed to be caused by REST. First REST arrival counters are cumulative within this fresh run, not counts of every duplicate download. Failures include successful HTTP responses that did not restore usable input; they are not all transport errors.',
 '','The shared local public-read limit is 1,200 weight/minute with 120 reserved. The highest sampled usage was '+str(cert['maximum_sampled_local_ip_weight'])+'; shutdown usage was '+str(stream['public_rate_budget']['ip_weight'])+'. The exact unsampled/exchange-wide peak is unknown. Pending reads at shutdown: '+str(stream['public_rate_budget']['public_reads']['pending'])+'. Coalesced reads: '+str(stream['public_rate_budget']['public_reads']['coalesced'])+'. Recorded read deferrals/errors: '+json.dumps(stream['public_rate_budget']['public_reads']['failures'])+'. These can be local budget deferrals, not venue HTTP throttling. Account-action capacity is unobserved. Full budgeting and request counts are retained in the receipt.',
 '', '| Market | Retained quarantine-to-healthy transitions | Median observed restoration time (seconds) | Maximum (seconds) |',
 '|---|---:|---:|---:|']
for symbol,values in sorted(read(BASE/'restoration_timing.json')['cycles'].items()):
 latencies=[v['observed_transition_latency_ms']/1000 for v in values]
 lines.append('| '+symbol+' | '+str(len(values))+' | '+fmt(median(latencies))+' | '+fmt(max(latencies))+' |')
lines+=['','These are observed health-state transitions, not exchange publication latency or proof of lasting stability. The retained transition tape can omit earlier cycles; actual timestamps are preserved in '+link('restoration timing',BASE/'restoration_timing.json')+'.',
 '','## F. External provider comparison','',
 (BASE/'external_research.md').read_text().split('## Provider comparison\n',1)[1].split('## Asset mapping',1)[0].strip(), '',
 'The ranked six-provider matrix, verified limits/cost qualifications, licensing unknowns and confidence are in '+link('external research',BASE/'external_research.md')+'. Hyperliquid mainnet references are the first price-comparison candidate; no provider is certified as a production fallback. Paid subscriptions and keys were not activated.',
 '','## G. Ten-asset compatibility matrix','',
 (BASE/'external_research.md').read_text().split('## Asset mapping\n',1)[1].split('## Architecture',1)[0].strip(), '',
 'The asset-by-asset matrix in '+link('external research — asset mapping',BASE/'external_research.md')+' identifies crypto basis/volume differences, ETF sessions/adjustments, futures roll/multiplier issues, gold tick-volume limits, and FX direction. USDEUR is USD per EUR. Reference identity is not volume or signal equivalence.',
 '', '| Asset | Empirical comparison outcome |','|---|---|']
by_symbol={r['native_symbol']:r for r in comparisons['results']}
for s in sorted(avail['markets']):
 r=by_symbol.get(s,{})
 lines.append('| '+s+' | '+(str(r.get('matched_count','NOT_CAPTURED'))+' matched; '+str(r.get('reason',r.get('verdict','UNVERIFIED'))))+' |')
lines+=['','| Market | Matched closes | Median / P95 close difference bps | Native / external missing % | Adjacent return pairs | Native / external 1m return SD |',
 '|---|---:|---|---|---:|---|']
for symbol,m in sorted(price_analysis['markets'].items()):
 d=m.get('close_difference_bps',{});v=m.get('realized_volatility',{})
 lines.append('| '+symbol+' | '+str(m['matched'])+' | '+fmt(d.get('median'))+' / '+fmt(d.get('p95'))+' | '+fmt(m.get('native_missing_percent'))+' / '+fmt(m.get('external_missing_percent'))+' | '+str(v.get('adjacent_matched_return_pairs'))+' | '+fmt(v.get('native_log_return_sample_sd'))+' / '+fmt(v.get('external_log_return_sample_sd'))+' |')
lines+=['','All OHLC absolute/relative differences are retained in the comparison CSV. Volatility uses only adjacent matched genuine minutes, with no bridging of missing minutes. External capture is a single current reception: historic publication latency, signal timing advantage and live provider reliability remain unknown.',
 '', ('![External close differences](<'+str(BASE/'external_close_basis.png')+'>)' if (BASE/'external_close_basis.png').exists() else 'The OHLC CSV preserves every comparable point; no image is substituted for missing plot dependencies.'),
 '', 'Experiment A is the actual native PAPER baseline. Experiment B cannot produce an equivalent VWAP signal until instrument and volume semantics pass review. Experiment C signal agreement, hypothetical execution, fees/slippage and risk-adjusted outcomes remain **NOT ENOUGH EVIDENCE**. A fresh venue quote alone does not supply a missing signal or historical fill.',
 '', 'The standalone comparison occurs after the PAPER collector stopped. Its later native REST snapshot can be more complete (GOLD and SP500 were complete in that later request); it was never inserted into the prior PAPER cache or used to rewrite its failed certificate. Provider capture timing is retained separately.', '',
 'No inversion, rescaling, split adjustment, volume invention or contract roll was applied. Mapping uncertainty remains visible. Frozen-feature/signal comparisons are blocked when comparable volume and full UTC/as-of evidence are absent. Detailed price differences are in '+link('external comparison',BASE/'external_capture/comparison.json')+'.',
 '','## H. External data legal/compliance findings','',
 (BASE/'external_research.md').read_text().split('## Competition permission\n',1)[1].split('## Provider comparison',1)[0].strip(), '',
 'Current organizer permission and disclosure wording was verified from primary sources on 10 October 2026. Source provenance/processing should accompany the code and report. Provider-specific licenses and jury redistribution permissions remain unverified; public API access is not a redistribution license. No rule-revision history was available to prove every rule unchanged. See the cited primary sources in '+link('compliance research',BASE/'external_research.md')+'.',
 '','## I. Source-isolation proof','',
 'Production has no import of the external module. Native cache validation rejects research records because their symbols are explicitly external. The research library imports no HTTP client and exposes no order/account API. Only the standalone collector can issue fixed public `/info` metadata/candle reads; it has no signer or `/exchange` action path. Production rejects external mode/self-approval flags. Existing tests also enforce no network/live imports throughout research.',
 '', 'As-of joins require real reception before the comparison decision. Old downloads cannot be inserted at earlier decisions. External source outages leave native state intact. Native quotes/mark context must be fresh; native account remains accounting truth. Unsupported fees, funding, fills, signal agreement and risk-adjusted outcomes remain null. No automatic promotion exists.',
 '','## J. Tests','',
 f'Previous total: **1356**. New tests: **{len(new_tests)}**. Final total/passed: **{tests["totals"]["tests"]}**. Failed/errors/skipped: **0/0/0**. Strategy freeze and Phase-0 pass. One frozen file, eight protected methods and 32 protected parameters remain unchanged.',
 '', 'Final active source: `'+tests['source_hash']+'`; XML SHA256: `'+tests['xml_sha256']+'`. Receipt: '+link('release regression',BASE/'regression_release/test_receipt.json')+'. All earlier failed/intermediate attempts are retained and explained in '+link('test attempts',BASE/'test_attempt_notes.md')+'. Synthetic tests are OFFLINE_FIXTURE, including ephemeral SDK tests; V6 also retains two RECORDED_EXCHANGE_REPLAY cases. This run is LIVE_PUBLIC_READ_ONLY plus local PAPER simulation, not actual exchange execution.',
 '','## K. PAPER results','',
 f'Actual duration: **{cert["duration_seconds"]:.3f} seconds**. Fresh state: `{state}`. Final usable markets: **{len(health["healthy_markets"])} / {health["total_markets"]}**. Local fills/positions: **{health["local_fills"]}/{health["local_positions"]}**. Actual orders: **0**. Verdict: **{cert["verdict"]}**; blockers: `{cert["blockers"]}`.',
 '', 'Frozen UTC strategy, 0.40% ATR floor, 15 bps spread, 300 completed bars, Top-3 and one global position were preserved. Numerical rejections: '+str(sum('SCANNER_NUMERIC_INVALID' in str(t.get('raw_reasons',[])) for t in traces))+'. First rejection categories: `'+json.dumps(dict(first))+'`.',
 '', '| Independent stage | Evaluated | Passed | Failed | Pass % |','|---|---:|---:|---:|---:|']
for k,v in funnel.items():lines.append('| '+k+' | '+str(v['evaluated'])+' | '+str(v['passed'])+' | '+str(v['failed'])+' | '+fmt(v['pass_percent'])+' |')
lines+=['','| Sequential stage | Admitted | Evaluated among previous survivors | Failed | Unobserved |','|---|---:|---:|---:|---:|']
for v in cert['funnel']['session']['stages']:
 lines.append('| '+v['stage']+' | '+str(v['admission_passed'])+' | '+str(v['admission_evaluated'])+' | '+str(v['admission_failed'])+' | '+str(v['admission_unobserved'])+' |')
lines+=['','Rejections by category: `'+json.dumps(cert['funnel']['session']['first_rejection_categories'])+'`. Local PAPER portfolio: `'+json.dumps(report['portfolio'])+'`.',
 '','Denominators are independently evaluated stage outcomes. Not-evaluated stages are not failures; sequential admissions and detailed rejection categories remain in the original opportunity traces/report. Cumulative older-run counters are not merged into this fresh session.',
 '', f'Usable-feed samples: {cert["ready_samples"]}; observed usable span: {cert["ready_sample_span_seconds"]} seconds. Scanner observations: {cert["this_run_observations"]}.', '',
 f'WS disconnects: {cert["disconnect_count"]}; completed corresponding reconnect/account barriers: {reconnect_successes}. Socket uptime: {cert["transport_uptime_seconds"]} seconds. Completed lifetime median: {cert["median_completed_connection_lifetime_seconds"]}. Close codes/reasons and receiver gaps come from actual transport records, not assumptions.',
 '', 'The preserved inherited certificate reports two post-initial account barriers, including an in-place REST/account recovery. The V7 reconnect count above is one, derived only after an actual disconnect. See '+link('counter scope note',BASE/'counter_scope_note.json')+'.', '',
 'Receiver gap maximum: `'+str(cert['maximum_receiver_gap_seconds'])+'` seconds. Close records: `'+json.dumps(cert['close_records'])+'`. Maximum sampled local IP weight: `'+str(cert['maximum_sampled_local_ip_weight'])+'`. Account-action budget remains unobserved; no funded readiness is inferred.', '',
 'Clean shutdown, worker completion, primary/backup SQLite integrity, checkpoint checksums/source identity, health tape digest and released ownership locks were independently verified. Local PAPER equity/accounting is separate from the funded wallet. No funded LONG/SHORT/protection/recovery test occurred. No wallet key, leverage/account change, cancellation, transfer, automatic three-hour run or recurring Codex task occurred.',
 '','## L. Final readiness flags','','```ini']
for k,v in flags.items():lines.append(k+' = '+('TRUE' if v is True else 'FALSE' if v is False else str(v)))
lines+=['```','','These are evidence verdicts for the completed bounded run, not a claim that a feed remains connected after the process stops. A later run needs fresh native checks. SIGNAL_AVAILABLE in the dashboard is a latest-scan diagnostic; entry permission still requires the independent current health and safety gates.', '',
 'Boolean PAPER_READY here requires the existing feed certificate; it does not authorize funded practice. Protection configuration is still not tested protective-order acceptance. Research/ML promotion flags remain unsupported; production strategy is unchanged.',
 '','## M. Exact next action','']
if cert['feed_certified']:
 lines+=['Review the concrete risk budget and prerequisites for a separately authorized controlled testnet certification. This report grants no funded activation.']
else:
 lines+=['Ask the organizers to clarify native missing-minute, backfill and candle-WebSocket semantics using '+link('this prepared unsent draft',BASE/'organizer_clarification_draft.md')+' and '+link('exact minute evidence',BASE/'organizer_missing_minute_evidence.json')+'. This is the single highest-priority next action. No shell command can establish the undocumented venue behavior. The message has **not been sent**.']
(BASE/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(dict(verdict=summary['verdict'],tests=tests['totals'],new_tests=len(new_tests),final_usable=len(health['healthy_markets']),report=str(BASE/'report.md')),indent=2))
