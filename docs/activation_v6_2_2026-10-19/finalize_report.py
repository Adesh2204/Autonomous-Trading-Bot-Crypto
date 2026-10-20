"""Evidence-backed report only. Never creates acceptance or exchange authority."""
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import hashlib,json,sqlite3,subprocess,sys,time
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent;sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.configuration_isolation import local_evidence
from exchange.long_session import require_release,sha
from exchange.terminal_app import locked
def read(name):return json.loads((O/name).read_text())
def local_time(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()
source=active_source_hash(R);release=O/'regression_release_final/test_receipt.json';require_release(R,release,source,sha(release))
reg=read('regression_release_final/test_receipt.json');baseline=read('baseline.json');preserved={}
for relative,old in baseline['databases'].items():
 with sqlite3.connect((R/relative).resolve().as_uri()+'?mode=ro',uri=True) as db:
  digest=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
  preserved[relative]=dict(dump_sha256=digest,unchanged=digest==old['dump_sha256'],integrity=db.execute('pragma integrity_check').fetchone()[0])
if len(preserved)!=54 or not all(v['unchanged'] and v['integrity']=='ok' for v in preserved.values()):raise RuntimeError('ORIGINAL_EXECUTION_DATABASE_CHANGED')
original=local_evidence(R)
if original!=baseline['original']:raise RuntimeError('ORIGINAL_UNKNOWN_NONCE_OR_CONSUMED_MARKER_CHANGED')
atomic_json(O/'preservation_final.json',dict(all_unchanged=True,databases=preserved,original=original))
proposal=read('session_final/proposal.json');discovery=read('session_final/venue_discovery.json');isolation=read('isolation_final/policy.json')
fills=read('isolation_final/fills.json');ranking=read('ranking_final/ranking.json');launch=read('public_reader_launch.json')
state=Path(launch['state']);current=json.loads((state/'current.json').read_text());status=json.loads((Path(current['output'])/'status.json').read_text())
now=time.time_ns()//1000000
native={s:read(folder+'/qualification_proposal.json') for s,folder in (('pas:BTC','native_btc_final'),('pas:EWY','native_ewy_final'))}
leverage={r['symbol']:r['active_asset']['leverage'] for r in discovery['markets'] if r['symbol'] in ('pas:BTC','pas:EWY')}
if set(leverage)!={'pas:BTC','pas:EWY'} or any(v!={'type':'cross','value':1} for v in leverage.values()):raise RuntimeError('FRESH_CONFIGURATION_NOT_VERIFIED')
history=read('history_review_release/history_review.json')
wire=read('independent_candle_probe_final/probe.json')
raw_count=post_close_count=0
for line in (O/'independent_candle_probe_final/raw_ws.jsonl').read_text().splitlines():
 event=json.loads(line);message=event['message']
 if message.get('channel')=='candle':
  for bar in message['data'] if isinstance(message['data'],list) else [message['data']]:
   raw_count+=1;post_close_count+=int(bar['t']+60000<=event['received_ms'])
if (status.get('source_hash')!=source or launch['source_hash']!=source or not locked(state/'owner.lock')
        or not 0<=now-status['updated_ms']<=30000):raise RuntimeError('VERIFIED_PUBLIC_OBSERVER_NOT_CURRENT')
if (O/'session_final/mandate.json').exists() or (O/'isolation_final/acceptance.json').exists():raise RuntimeError('UNEXPECTED_AUTHORITY_ARTIFACT')
r=dict(observed_ms=now,observed_ist=local_time(now),source_hash=source,baseline_source_hash=baseline['source_hash'],
 git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),dirty_source=True,
 verdict='ENGINEERING_IMPLEMENTED_SIGNED_QUALIFICATION_BLOCKED',TRADING_AUTHORIZED=False,AUTO_TRADING_ACTIVE=False,
 configuration=dict(balance=discovery['funding']['balance'],collateral='USDP',account_mode=discovery['account_mode'],leverage=leverage,observed_ms=discovery['finished_ms']),
 historical=dict(original_state='UNKNOWN',order_status=[g['original_order_status'] for g in isolation['readbacks']['readbacks']],
  bounded_fills_count=len(fills['response']),fill_request=fills['request'],old_outcome_resolved=False,records_unchanged=True,
  isolation_policy_hash=isolation['policy_hash'],isolation_source=isolation['source_hash'],accepted=False,
  policy_expires_ms=isolation['expires_ms'],approval_deadline_ms=isolation['approval_deadline_ms'],
  runtime_scope='EXACT_SEPARATELY_ACCEPTED_PAS_SESSION_ONLY; qualification remains a separately reviewed scope',
  fresh_par_pas_flat_readbacks=isolation['readbacks']['readbacks']),
 native_qualification=dict(qualified=False,orders=[],fills=[],stops=[],plans=native,authoritative_pas_subminimum_exception_established=False),
 market_data=dict(old_collector_retirement=read('stalled_public_reader_retirement.json'),old_collector_stale_ms=read('stalled_public_reader_evidence.json')['stale_ms'],history_review=history,independent_wire_probe=str(O/'independent_candle_probe_final/probe.json'),
  independent_probe_source=wire['source_hash'],independent_ack_counts=[len(s['acks']) for s in wire['sockets']],
  independent_raw_sample_candles=raw_count,independent_post_close_ws_observations=post_close_count,
  limitation='Raw sample contained only open updates. Actual final-source history review is separate. Freshness may recur or lapse; no fabricated bar or finality is inferred.',
  current_markets=status.get('market_history'),current_signals=status.get('signals'),observer_status=status.get('status'),
  public_source_hash=status['source_hash'],status_updated_ms=status['updated_ms'],market_stream=status.get('stream_connected'),
  account_stream=status.get('account_stream_healthy'),reader_running=True,reader_state=str(state)),
 ranking=dict(observed_ms=ranking['observed_ms'],source_hash=ranking['source_hash'],rows=ranking['rows'],top_three=ranking['observational_top_three'],entry_scope=ranking['production_entry_markets']),
 session=dict(proposal=proposal,mandate_created=False,accepted=False,risk_denominator='ALLOCATED_20000_USDP',intended_trade_loss_usdp='100',session_loss_stop_usdp='200',
  notional_per_entry='1000',cumulative_notional='2000',maximum_entries=2,maximum_positions=1,maximum_actions=12,maximum_minutes=60,
  marked_loss_includes='OWNED_ACTUAL_CLOSED_PNL_FEES_FUNDING_PLUS_REPORTED_UNREALIZED_AND_ESTIMATED_EXIT_RESERVE',
  sampled_peak_preserved_after_close=True,automatic_renewal=False),
 regression=dict(totals=reg['totals'],passed=reg['passed'],source_hash=reg['source_hash'],source_hash_after=reg['source_hash_after'],receipt=str(release),
  strategy_freeze=reg['checks_after']['strategy_freeze']['result'],policy_lockout=reg['checks_after']['phase0']['result']),
 preservation=dict(original_database_count=54,all_unchanged=True,original_nonce_and_consumed_marker_unchanged=True),
 actual_wallet_signatures_this_continuation=0,exchange_writes_this_continuation=0,automatic_trading_activated=False,
 next_operator_action='Obtain original PAS-wide semantics for sub-$10 full-position IOC and fixed-size native stops, including partial-close coverage. Then review/implement the exact PAS qualification and accept its new finite scope interactively. General approval and the configuration acceptance cannot establish this evidence.',
 next_approval='A separately scoped PAS qualification acceptance after minimum/residual prerequisites; then a separate historical-isolation and finite-session acceptance. None is created here.')
atomic_json(O/'readiness_report.json',r)
lines=['# Team Anchorium V6.2 readiness report','',f'As of {local_time(now)}. **Engineering implemented and tested; signed PAS qualification remains blocked.**','',
 '| Area | Evidence-backed result |','|---|---|',
 f"| Funding / configuration | {discovery['funding']['balance']} USDP, Unified; fresh BTC and EWY readbacks both 1x CROSS. |",
 '| Live data | Post-close provenance, durable WS admissions and cache/REST lock ordering repaired. Raw REST/WS comparisons retained; no synthetic bars. Corrected public collector is running on the verified frozen V6.2 source. |',
 '| Historical UNKNOWN | Exact original remains UNKNOWN. Two fresh unknownOid/PAR/PAS flat, order-free observations and bounded fills retained. A finite, source/mandate/host-bound isolation implementation now exists and is unaccepted. Original consumed attempt is never reset. |',
 '| Native protection | No genuine PAS entry/stop/trigger/closing fill proof exists. Below-$10 native/IOC behavior remains unproven. Signed entry remains blocked. |',
 '| Session risk | 60 minutes, 20,000 allocation, 1,000 entry / 2,000 cumulative, two attempts, one position, twelve actions. 100 intended trade risk / 200 session loss stop. Original signer/nonce/permit/protection guards remain. |',
 f"| Validation | {reg['totals']['tests']} passed; zero failures/errors/skips; identical source hash before/after. Freeze and PAPER/false lockouts pass. All 54 original databases and nonce/consumed records unchanged. |",
 '| Activation | No PAS qualification signed, no order/fill/native-stop IDs, no accepted isolation/session mandate, no autonomous activation. |','',
 '## Actual data findings','',
 'The independent all-ten probe captured three REST rounds and two raw WebSocket connections. Both connections acknowledged all ten candle subscriptions and returned heartbeats. BTC/EWY REST bars advanced again; SP500/USDEUR/USDJPY remained older in that bounded sample. The local history matched or lagged by one polling interval. This establishes intermittent upstream availability, not a universal outage or a permanently fresh feed.',
 '', 'A later deployment check found that the old unsigned collector had stopped advancing for over 30 minutes while independent PAS data had advanced. That is an observed local stall. Its original state was retained; normal stop and SIGTERM did not release it, so only that identity-verified public process was terminated. No exact Python stack was sampled. The independently identified cache/REST lock inversion was corrected and tested before replacement.\n\nAll 24 raw candle events in that sample arrived while their bars were open. They cannot be promoted to final bars by clock passage. The final-source history review retains raw wire and durable observations separately. WebSocket persistence/late-event/conflict cases have offline coverage; the sample does not certify a post-close WS finalization event.', '',
 f"Final-source history review status: `{history['status']}`. Current collector snapshot: `{status.get('status')}`, updated {local_time(status['updated_ms'])}.",'']
for signal in status.get('signals',[]):
 s=signal['symbol'];h=(status.get('market_history') or {}).get(s,{})
 lines.append(f"- {s}: {signal['decision']}; {', '.join(signal.get('reasons',[])) or 'See unchanged strategy trace'}. Genuine tail {h.get('contiguous_tail_bars')}; completed close {h.get('latest_completed_ms')}; age {now-h['latest_completed_ms'] if h.get('latest_completed_ms') else None} ms. Read-time history gate: {'FRESH' if h.get('latest_completed_ms') and 0<=now-h['latest_completed_ms']<=120000 else 'STALE_OR_MISSING'}.")
lines+=['','## Minimum residual review','', '| Market | Smallest lot | Reviewed stop limit | Lot notional | Subminimum sizes |','|---|---|---|---|---|']
for s,p in native.items():
 v=p['residual_coverage_requirements']['routes']['native_stop'];lines.append(f"| {s} | {v['size_step']} | {v['limit_price']} | {v['smallest_residual_notional']} USDP | {v['number_of_subminimum_sizes']} |")
lines+=['','These are observed unsigned proposal bounds, not accepted stop orders. Refresh them before a new qualification scope. The ordinary $10 rule and SDK reduce-only IOC helper do not prove subminimum acceptance, trigger execution or complete closure. A rejection/partial/unknown close preserves exposure and stops blind retry.', '',
 '## Remaining blockers and next action','',
 '1. Obtain the exact applicable PAS native-stop and full-position minimum rules in [the clarification questions](../activation_v6_1_2026-10-19/PAS_ROUTE_CLARIFICATION.md). This is the next operator action; no organizer message was sent.',
 '2. With those semantics established, implement/review a new bounded PAS qualification scope and obtain its exact interactive approval before signing. The old PAR consumed invocation cannot be reused. Preserve entry/stop/closing IDs, genuine fills, fees/funding and two flat readbacks.',
 '3. The original UNKNOWN still lacks terminal disposition. The implemented finite isolation can only be used after its separate exact acceptance bound to a valid PAS session. It does not itself authorize a qualification or order.',
 '4. After genuine protection/residual qualification, accept the new finite autonomous session and all existing source/account/ownership/risk guards. A current eligible frozen signal is also required; the ranking authorizes no extra markets.', '',
 'Risk percentages use the 20,000 USDP allocation, not the 100,000 account balance or 1,000 entry cap. Estimated fee/slippage/funding reserves affect sizing and loss-stop decisions; actual PnL uses reported fills/fees/funding only. Sampled peak drawdown survives a close. Loss stops and stop-limit prices cannot guarantee realized loss through gaps or unavailable liquidity.', '',
 'See [verified commands](OPERATOR_COMMANDS.md), [source-change review](CHANGE_REVIEW.md), [native evidence review](NATIVE_EVIDENCE_REVIEW.md), [regression receipt](regression_release_final/test_receipt.json), [original-record preservation](preservation_final.json), [finite isolation policy](isolation_final/policy.json), [session proposal](session_final/proposal.json), [all-ten ranking](ranking_final/ranking.json), and [machine-readable report](readiness_report.json).', '',
 f'Current verified source: `{source}`. Fifty-six new tests are offline fixtures; they do not certify exchange behavior. Earlier interrupted test runs are retained separately and are not release evidence.']
(O/'READINESS_REPORT.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(dict(verdict=r['verdict'],tests=reg['totals'],source_hash=source,databases_preserved=54,reader_running=True,automatic_trading_active=False),indent=2))
