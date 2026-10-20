"""Final continuation report from actual receipts; no action or authority creation."""
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import hashlib,json,sqlite3,sys,time,subprocess
O=Path(__file__).resolve().parent;R=O.parents[1];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.long_session import require_release,sha
from exchange.configuration_isolation import local_evidence
from exchange.terminal_app import locked

def read(p):return json.loads((O/p).read_text())
def ist(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()
source=active_source_hash(R);release=O/'regression_release_final/test_receipt.json';require_release(R,release,source,sha(release))
reg=read('regression_release_final/test_receipt.json');b=read('baseline_after_human_configuration.json');preservation={}
for rel,prior in b['databases'].items():
 with sqlite3.connect((R/rel).resolve().as_uri()+'?mode=ro',uri=True) as db:
  digest=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
  preservation[rel]=dict(dump_sha256=digest,unchanged=digest==prior['dump_sha256'],integrity=db.execute('pragma integrity_check').fetchone()[0])
if not all(v['unchanged'] and v['integrity']=='ok' for v in preservation.values()):raise RuntimeError('EXECUTION_RECORD_CHANGED_AFTER_APPROVED_CONFIG')
atomic_json(O/'preservation_final.json',dict(databases=preservation,all_unchanged=True))
config=read('completed_configuration_verification.json');history=read('public_audit_final/audit.json');ranking=read('ten_market_ranking/ranking.json');isolation=read('isolation_review/isolation_policy.json')
ranking_directory='ten_market_ranking_refresh' if (O/'ten_market_ranking_refresh/ranking.json').exists() else 'ten_market_ranking'
ranking=read(ranking_directory+'/ranking.json')
probe=read('public_route_probe_retry/probe.json')
probe_summary=dict(status=probe['status'],path=str(O/'public_route_probe_retry/probe.json'),team_certified=False,
    sampled_users=len(probe['users']),trigger_records=sum(len(v['trigger_records']) for v in probe['users']),
    subminimum_reduce_only_records=sum(len(v['subminimum_reduce_only_records']) for v in probe['users']),
    any_history_at_limit=any(v['history_may_be_truncated'] for v in probe['users']))
proposal=read('scored_review_final/proposal.json');discovery=read('scored_review_final/venue_discovery.json')
state=R/'runtime/pas-btc-ewy-v6-public';current=json.loads((state/'current.json').read_text());snapshot=json.loads((Path(current['output'])/'status.json').read_text());now=time.time_ns()//1000000
native={s:read(path+'/qualification_proposal.json') for s,path in (('pas:BTC','native_btc_review'),('pas:EWY','native_ewy_review'))}
markets={}
for s,h in snapshot.get('market_history',{}).items():
 signal=next((r for r in snapshot.get('signals',[]) if r['symbol']==s),{})
 markets[s]=dict(history=h,completed_candle_age_ms=now-h['latest_completed_ms'] if h.get('latest_completed_ms') else None,
  decision=signal.get('decision'),reasons=signal.get('reasons'),signal_observed_ms=signal.get('observed_ms'))
leverage={r['symbol']:r['active_asset']['leverage'] for r in discovery['markets'] if r['symbol'] in ('pas:BTC','pas:EWY')}
assert all(v==dict(type='cross',value=1) for v in leverage.values())
r=dict(observed_ms=now,observed_ist=ist(now),source_hash=source,git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),dirty_source=True,
 verdict='SIGNED_PAS_TRADING_NOT_AUTHORIZED',configuration=config,latest_leverage=leverage,funding=discovery['funding'],account=discovery['account'],
 original_unknown=dict(cloid='0xac0eea156fcec80986dd67c9057b6ded',state='UNKNOWN',
  fresh_readbacks=history['final_readbacks'],bounded_historical_orders=history['own_historical_orders'],local=local_evidence(R),
  old_outcome_resolved=False,consumed_attempt_reset=False),
 trading_isolation=dict(status=isolation['status'],policy_hash=isolation['policy_hash'],path=str(O/'isolation_review/isolation_policy.json'),
  accepted=False,runtime_permission=False,maximum_minutes=60,proposed_ceilings=isolation['proposed_session_ceilings']),
 genuine_native_and_residual_qualification=False,native_reviews=native,
 public_route_probe=probe_summary,
 supplied_organizer_guidance=dict(source='https://perpetual-alpha26.github.io/docs/',under_ten_exception_established=False,
  note='Human supplied the general guide again; it states the ordinary $10 minimum and does not establish a subminimum stop/full-close exception.'),
 markets=markets,ten_market_ranking=dict(path=str(O/ranking_directory/'ranking.json'),source_hash=ranking['source_hash'],rows=ranking['rows'],
  top_three=ranking['observational_top_three'],entry_scope_unchanged=ranking['production_entry_markets']),
 regression=dict(passed=reg['passed'],totals=reg['totals'],source_hash=reg['source_hash'],source_hash_after=reg['source_hash_after'],receipt=str(release),
  strategy_freeze=reg['checks_after']['strategy_freeze']['result'],phase0=reg['checks_after']['phase0']['result']),
 observer=dict(worker_running=locked(state/'owner.lock'),status=snapshot.get('status'),updated_ms=snapshot.get('updated_ms'),
  source_hash=snapshot.get('source_hash'),state=str(state),market_stream=snapshot.get('stream_connected'),account_stream=snapshot.get('account_stream_healthy'),signing_authority='NONE'),
 finite_session_proposal=proposal,finite_session_mandate_created=(O/'scored_review_final/mandate.json').exists(),finite_session_acceptance=False,
 TRADING_AUTHORIZED=False,AUTO_TRADING_ACTIVE=False,signed_orders_this_continuation=0,configuration_actions_previously_approved=2,
 order_ids=[],fill_ids=[],native_stop_ids=[],all_execution_journals_unchanged_since_completed_configuration=True,execution_journal_count=len(preservation),
 remaining_blockers=[
  dict(blocker='UNRESOLVED_HISTORICAL_ORDER',next_action='Review the finite isolation design or obtain terminal original-order evidence. The draft is not consumed by execution; a separately accepted reviewed implementation is needed before use.'),
  dict(blocker='UNQUALIFIED_PAS_NATIVE_AND_RESIDUAL_SCOPE',next_action='Obtain the precise PAS rules in PAS_ROUTE_CLARIFICATION.md; then implement/validate and explicitly accept the bounded signed qualification. Do not reuse the PAR executors or a configuration-only acceptance.'),
  dict(blocker='CONDITIONAL_FROZEN_STRATEGY_READINESS',next_action='Continue genuine market collection until completed history is fresh and the unchanged strategy has an eligible setup.'),
  dict(blocker='NO_GENUINE_FINITE_SESSION_ACCEPTANCE',next_action='After qualification and history isolation pass, prepare and accept the exact source-bound finite mandate and use the existing conditional single-controller launch.')])
atomic_json(O/'continuation_report.json',r)
lines=['# Team Anchorium V6.1 continuation report','',f'As of {ist(now)}. **Configuration is verified; signed trading is not authorized.**','',
 '| Item | Actual result |','|---|---|',
 f"| USDP/account | {discovery['funding']['balance']} USDP, Unified; observed {ist(discovery['funding']['observed_ms'])}. Positions and open orders empty in the retained account readbacks. |",
 '| BTC/EWY configuration | Genuine CLI acceptance, two acknowledged leverage actions and helper readbacks verified. Separate actual PAS query and final discovery confirm 1x CROSS for both. No trade was submitted by configuration. |',
 '| Original UNKNOWN | Still UNKNOWN, with two new `unknownOid`/flat/order-free readbacks. Original order and consumed attempt preserved. Original nonce store retained; the prior legitimate configuration advancement is preserved. |',
 '| Finite isolation | Separate 60-minute design saved with source/raw evidence, exact historical row, nonce and session ceilings. Unaccepted and not consumed by execution. |',
 '| Native stops/residuals | Not qualified. General guide does not establish sub-$10 exceptions. The bounded public sample supplied no usable stop/residual proof; it does not certify the team. Unsigned BTC/EWY reviews quantify all unproven sizes. |',
 '| Ten-market ranking | Implemented and run on all ten canonical PAS markets using the unchanged scanner/brain. BTC/EWY remain the only production entry markets. No entry authority or invented signals. |',
 f"| Regression | {reg['totals']['tests']} passed, zero failures/errors/skips; source {source} matches before/after. Frozen strategy and PAPER/false policy pass. |",
 '| Session/trading | Fresh finite session proposal retained with explicit ceilings and blockers. No valid executable mandate/acceptance, PAS stop IDs, trading order IDs or fill IDs. |',
 f"| Preservation | All {len(preservation)} execution databases unchanged since the approved configuration baseline and pass integrity checks. |",'',
 '## Current observed BTC/EWY readiness','']
for s,v in markets.items():lines.append(f"- {s}: {v['decision']}; {', '.join(v['reasons'] or [])}. Completed-candle age {v['completed_candle_age_ms']} ms; contiguous history {v['history'].get('contiguous_tail_bars')}.")
lines+=['','## All-ten observation snapshot','',f"Observed {ist(ranking['observed_ms'])}. No row grants order authority.",'', '| Market | Scanner qualification | Entry policy scope |','|---|---|---|']
for row in ranking['rows']:
 lines.append('| '+row['symbol']+' | '+('Qualified' if row['scanner_qualified'] else ', '.join(row['reasons']))+' | '+('BTC/EWY scope only' if row['production_entry_market'] else 'Observation only')+' |')
lines+=['','## Session ceilings proposed for review','',
 '60 minutes; 20,000 USDP allocated bankroll; at most 1,000 USDP per entry / 2,000 cumulative; two entry attempts; one concurrent position including partial/pending exposure; 12 signed actions; 0.5% risk per trade and a 200 USDP session loss stop. These ceilings grant no authority. Fresh account reconciliation, sole account/signer leases, source/evidence binding, native protection and exact acceptance remain mandatory.',
 '', '## Remaining actions','']
for x in r['remaining_blockers']:lines.append('- **'+x['blocker']+'**: '+x['next_action'])
lines+=['','See [verified operator commands](OPERATOR_COMMANDS.md), [completed configuration verification](completed_configuration_verification.json), [isolation design](isolation_review/isolation_policy.json), [venue clarification questions](PAS_ROUTE_CLARIFICATION.md), [all-ten ranking](ten_market_ranking/ranking.json), [full regression](regression_release_final/test_receipt.json), and [machine-readable report](continuation_report.json).',
 '', 'The public observer remains on its separate credential-free, verified frozen V5.3 source. Its ongoing collection does not authorize trading. Profits, first place, and an error-free future cannot be guaranteed.']
(O/'CONTINUATION_REPORT.md').write_text(('\n'.join(lines)+'\n').replace('[all-ten ranking](ten_market_ranking/ranking.json)',f'[all-ten ranking]({ranking_directory}/ranking.json)'))
print(json.dumps(dict(verdict=r['verdict'],regression=r['regression']['totals'],leverage=leverage,journals_preserved=len(preservation)),indent=2))
