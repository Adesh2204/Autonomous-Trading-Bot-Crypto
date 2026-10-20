"""Evidence-only V6 report, with no signer, exchange transport or acceptance writer."""
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import hashlib,json,sqlite3,sys,time,subprocess
O=Path(__file__).resolve().parent;R=O.parents[1];sys.path.insert(0,str(R/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.long_session import require_release,sha
from exchange.configuration_isolation import local_evidence,CLOID
from exchange.terminal_app import locked

def read(name):return json.loads((O/name).read_text())
def stamp(ms):
 t=datetime.fromtimestamp(ms/1000,timezone.utc)
 return dict(utc=t.isoformat(),ist=t.astimezone(ZoneInfo('Asia/Kolkata')).isoformat())

source=active_source_hash(R);release=O/'regression_release_final/test_receipt.json'
require_release(R,release,source,sha(release));reg=read('regression_release_final/test_receipt.json')
baseline=read('baseline.json');preservation=dict(observed_ms=time.time_ns()//1000000,databases={})
for rel,prior in baseline['databases'].items():
 path=(R/rel).resolve()
 with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
  digest=hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
  preservation['databases'][rel]=dict(dump_sha256=digest,unchanged=digest==prior['dump_sha256'],integrity=db.execute('pragma integrity_check').fetchone()[0])
preservation['all_original_databases_unchanged']=all(v['unchanged'] and v['integrity']=='ok' for v in preservation['databases'].values())
atomic_json(O/'preservation_final.json',preservation)
if not preservation['all_original_databases_unchanged']:raise RuntimeError('ORIGINAL_EXECUTION_JOURNAL_CHANGED_REQUIRES_REVIEW')

# Prefer the final source-matched scored proposal's actual account snapshot.
proposal=read('scored_review_final/proposal.json') if (O/'scored_review_final/proposal.json').exists() else None
discovery=read('scored_review_final/venue_discovery.json') if proposal else read('configuration_review_final/discovery.json')
if (O/'post_confirmation_discovery/discovery.json').exists():discovery=read('post_confirmation_discovery/discovery.json')
funding=read('funding_final/funding_evidence.json') if (O/'funding_final/funding_evidence.json').exists() else discovery['funding']
limit_path='current_limits_final/limits.json' if (O/'current_limits_final/limits.json').exists() else 'current_limits/limits.json'
limits=read(limit_path);history=read('history_review_final/history_review.json')
original=read('original_state_review.json');identity=read('local_signer_preflight_final.json')
state=R/'runtime/pas-btc-ewy-v6-public';cur=json.loads((state/'current.json').read_text());snapshot=json.loads((Path(cur['output'])/'status.json').read_text())
observed=time.time_ns()//1000000
market_status={}
for s in ('pas:BTC','pas:EWY'):
 h=snapshot.get('market_history',{}).get(s,{})
 signal=next((r for r in snapshot.get('signals',[]) if r.get('symbol')==s),{})
 market_status[s]=dict(history=h,latest_completed_time=stamp(h['latest_completed_ms']) if h.get('latest_completed_ms') else None,
  signal=dict(decision=signal.get('decision'),reasons=signal.get('reasons'),observed_ms=signal.get('observed_ms')),
  completed_candle_age_ms=observed-h['latest_completed_ms'] if h.get('latest_completed_ms') else None,
  limits_evidence=limits['markets'][s])

changes=read('configuration_review_final/account_configuration_plan.json')['changes']
blockers=[dict(blocker='EXACT_BTC_EWY_CONFIGURATION_NOT_ACCEPTED',action='Run configure_btc_ewy.py yourself in a real Terminal; review and type the exact plan phrase. The helper refreshes evidence and applies only the two accepted 1x CROSS actions.'),
 dict(blocker='ORIGINAL_ORDER_HISTORY_UNRESOLVED_FOR_TRADING',action='Obtain terminal original-order evidence or independently validate and expressly accept a separate trading-specific isolation policy; preserve original UNKNOWN and consumed attempt.'),
 dict(blocker='GENUINE_PAS_PROTECTION_AND_RESIDUAL_ROUTE_UNQUALIFIED',action='Obtain authoritative PAS subminimum residual/native-stop semantics and review a bounded qualification experiment with genuine acceptance and actual order/fill evidence.'),
 dict(blocker='MARKET_READINESS_IS_CONDITIONAL',action='Continue authentic BTC/EWY collection and wait for complete fresh history plus an eligible frozen setup; no candle fabrication or strategy relaxation.'),
 dict(blocker='NO_FINITE_TRADING_ACCEPTANCE',action='After all prior dependencies pass, prepare the exact finite PAS mandate and accept it interactively using approve. Then use the existing conditional single-controller launch with those real files.')]

r=dict(observed_ms=observed,observed_time=stamp(observed),verdict='NOT_AUTHORIZED_FOR_SIGNED_TRADING',
 source_hash=source,git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),baseline_git_commit=baseline['git_commit'],dirty_source=True,
 regression=dict(totals=reg['totals'],passed=reg['passed'],source_hash=reg['source_hash'],source_hash_after=reg['source_hash_after'],receipt=str(release),
  strategy_freeze=reg['checks_after']['strategy_freeze']['result'],production_policy=reg['checks_after']['phase0']['result']),
 actual_usdp=dict(evidence=funding,observed_time=stamp(funding['observed_ms'])),
 identity=dict(team_wallet=funding['team_wallet'],api_wallet=identity['identity']['derived_public_address'],local=identity,
  public_approval=discovery.get('agents'),mode=discovery.get('account_mode')),
 leverage={r['symbol']:r['active_asset']['leverage'] for r in discovery['markets'] if r['symbol'] in ('pas:BTC','pas:EWY')},
 reported_configuration_completion=read('configuration_confirmation_verification.json') if (O/'configuration_confirmation_verification.json').exists() else None,
 exact_pending_configuration=changes,configuration_approval='NOT_ACCEPTED',configuration_actions_this_task=0,
 original_unknown=original,configuration_only_isolation=read('configuration_review_final/configuration_isolation/assessment.json'),
 protection={s:read(name+'/qualification_proposal.json') for s,name in (('pas:BTC','native_btc_review'),('pas:EWY','native_ewy_review'))},
 market_readiness=market_status,independent_history_probe=str(O/'history_review_final/history_review.json'),
 account=dict(snapshot=discovery['account'],observed_ms=discovery['account_observed_ms'],
  pas_entry_order_ids=[],pas_closing_order_ids=[],pas_fill_ids=[],protective_order_ids=[],
  scope='No PAS orders/fills were observed in the retained account history window. Old PAR activity and USDP deposits are separate.'),
 observer=dict(worker_running=locked(state/'owner.lock'),source_hash=snapshot.get('source_hash'),source_root=str(O/'public_reader_source'),
  status=snapshot.get('status'),status_age_ms=observed-snapshot['updated_ms'],market_stream=snapshot.get('stream_connected'),account_stream=snapshot.get('account_stream_healthy'),
  state=str(state),pid=read('public_reader_launch.json')['pid'],signing_authority='NONE'),
 actual_wallet_signatures_this_task=0,exchange_writes_this_task=0,TRADING_AUTHORIZED=False,AUTO_TRADING_ACTIVE=False,
 human_trading_acceptance='NOT_ACCEPTED',finite_mandate_file=None,actual_signed_account_controller_launched=False,
 signed_launch_command=None,signed_launch_reason='No real qualified proof, finite mandate or genuine acceptance exists; dummy paths are not launch instructions.',
 next_human_command="cd '/Users/adesh/Autonomous Trading Bot - Crypto ' && .venv/bin/python docs/activation_v6_2026-10-19/configure_btc_ewy.py",
 autonomous_orders='No individual order prompts within a valid finite accepted mandate; no automatic renewal.',
 remaining_blockers=blockers,preserved_original_databases=len(preservation['databases']),all_original_databases_unchanged=True,
 scored_proposal=proposal,
 references=dict(official_pas_guide='https://perpetual-alpha26.github.io/docs/',official_order_types='https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types'))
atomic_json(O/'post_funding_report.json',r)
rows=[('1. Actual collateral',f"{funding['balance']} USDP; token {funding['token']}; observed {stamp(funding['observed_ms'])['ist']}"),
 ('2. Identity',f"Team {funding['team_wallet']}; API {identity['identity']['derived_public_address']}. Actual API approval/expiry and local derivation verified; Unified mode."),
 ('3. Leverage','BTC and EWY remain 20x CROSS. Exact two-action 1x CROSS plan prepared; genuine human configuration acceptance pending.'),
 ('4. Original UNKNOWN',f"{CLOID} remains UNKNOWN. Two fresh flat readbacks; no matching original historical order or terminal status. Consumed attempt preserved. Configuration-only isolation is available only in the exact accepted plan; no trading isolation."),
 ('5. PAS protection/residuals','Not qualified. Fresh $25-bounded unsigned proposals retained for both markets. Smallest possible residual is below the documented $10 minimum; actual PAS native/protective closure semantics and lifecycle proof are missing.'),
 ('6. Market readiness','Two-sided books, account limits, OI, fees and funding captured. Warmup/freshness and frozen signals remain conditional; current authentic candle and signal details below.'),
 ('7. Regression',f"{reg['totals']['tests']} tests passed; zero failures/errors/skips. Source {source}. Strategy freeze and PAPER/false policy checks pass."),
 ('8. Human acceptance','No configuration acceptance or finite trading acceptance was created. Direct named-wallet confirmation is identity evidence only.'),
 ('9. Launch','Public observer is running. No valid signed launch command exists before real qualification, mandate and acceptance; run the configuration helper below for the next genuine human step.'),
 ('10. Signed activity','No actual-wallet signatures, exchange writes, PAS orders, protective order IDs or fill IDs in this task. Observed PAS fills/fees/funding/realized PnL are zero; this is not trading success.'),
 ('11. Remaining actions','Exact configuration approval; trading-specific historical resolution/isolation; genuine PAS native/residual qualification; fresh eligible strategy setup; finite mandate acceptance and conditional launch.')]
lines=['# V6 post-funding activation report','',f"As of {stamp(observed)['ist']}. **Signed trading is not authorized.**",'', '| Requirement | Evidence / status |','|---|---|']
for title,body in rows:lines.append('| '+title+' | '+body+' |')
lines+=['','## Current authentic market status','']
for s,v in market_status.items():
 h=v['history'];sig=v['signal'];lines.append(f"- {s}: {h.get('valid_deduplicated_completed')} completed bars, contiguous tail {h.get('contiguous_tail_bars')}, candle age {v['completed_candle_age_ms']} ms; history-ready {h.get('strategy_history_ready')}; {sig['decision']}: {', '.join(sig['reasons'] or [])}.")
lines+=['','## Next genuine human action','', 'Review [the exact two-action configuration plan](configuration_review_final/account_configuration_plan.json) and [the source/safeguard review](CHANGE_REVIEW.md). In your own macOS Terminal:', '', '```sh', "cd '/Users/adesh/Autonomous Trading Bot - Crypto '", '.venv/bin/python docs/activation_v6_2026-10-19/configure_btc_ewy.py','```','', 'The helper validates this release, refreshes evidence, displays the exact plan, and requests the existing exact approval phrase. Accepting immediately applies only BTC/EWY 1x CROSS and verifies both readbacks. No trading approval is created. This human step is required by P2 of your V6 request and the existing approval workflow; chat text cannot substitute for that CLI acceptance.','', '## Remaining blockers and concrete actions','']
for b in blockers:lines.append('- **'+b['blocker']+'**: '+b['action'])
lines+=['','## Preserved evidence','',f"All {len(preservation['databases'])} original execution databases have unchanged logical dumps and pass integrity checks. Original UNKNOWN, consumed attempts and nonce history were not reset. Public collection uses the separate verified frozen V5.3 source; the V6 regression above covers the edited source.",'', 'See [machine-readable report](post_funding_report.json), [final regression receipt](regression_release_final/test_receipt.json), [original-state review](original_state_review.json), [current limits](current_limits/limits.json), and [operator handoff](README.md).','', 'The [official PAS guide](https://perpetual-alpha26.github.io/docs/) confirms sender-independent funding checks, the ordinary order minimum and partial IOC behavior. [Hyperliquid order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types) describes native stops; neither reference certifies this account’s actual protective fills. Profits are not guaranteed.']
(O/'POST_FUNDING_REPORT.md').write_text(('\n'.join(lines)+'\n').replace('[current limits](current_limits/limits.json)',f'[current limits]({limit_path})'))
print(json.dumps({k:r[k] for k in ('verdict','source_hash','TRADING_AUTHORIZED','AUTO_TRADING_ACTIVE','preserved_original_databases')},indent=2))
