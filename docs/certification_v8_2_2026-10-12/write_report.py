"""Read saved evidence only; no signer, API transport or source mutation."""
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import json,hashlib,sys,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash
from venue_config import require_paper_migration
from strategy_freeze import verify_strategy_freeze

def read(name):return json.loads((OUT/name).read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def local(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()
def link(path,label):return '['+label+'](<'+str(ROOT/path)+'>)'
receipt=read('regression_release/test_receipt.json');market=read('market_preflight_refresh/preflight.json');first=read('market_preflight_public/preflight.json');signer=read('signer_preflight.json');before=read('inspection_before.json')
assert receipt['passed'] and receipt['source_hash']==receipt['source_hash_after']==active_source_hash(ROOT)==market['source_hash']==signer['active_source_hash']
assert digest(OUT/'regression_release/regression.xml')==receipt['xml_sha256']
assert receipt['totals']==dict(tests=1487,failures=0,errors=0,skipped=0)
assert not market['final_positions'] and not market['final_orders']
safety=require_paper_migration();freeze=verify_strategy_freeze();assert freeze['passed'] and safety['ALLOW_LIVE_ORDERS'] is False
policy=json.loads((ROOT/'configs/reliability_policy.json').read_text());assert policy['protection']['enabled'] is False
wrapper=market['review_only_proposal'];p=wrapper['proposal'];assert not wrapper['executable'] and not wrapper['order_authorized']
quantity=D(p['quantity']);entry=quantity*D(p['entry_limit']);fees=quantity*(D(p['entry_limit'])+D(p['exit_bound']))*D(p['taker_fee_rate']);planned=quantity*abs(D(p['entry_limit'])-D(p['exit_bound']))+fees
rows=[]
for x in market['candidates']:
 q=x['quote'];sp=next(m for m in market['metadata'] if m['symbol']==x['symbol']);r=x['readiness']
 rows.append(dict(symbol=x['symbol'],observed_ms=x['observed_ms'],book_age_ms=x['observed_ms']-q['timestamp_ms'],
  spread_bps=str((D(q['ask'])-D(q['bid']))/D(q['mid'])*10000),mark_oracle_bps=str(abs(D(q['mark'])-D(q['oracle']))/D(q['oracle'])*10000),
  one_lot_mark_value=str(D(10)**(-sp['size_decimals'])*D(q['mark'])),readiness=r['status'],readiness_reasons=r['reasons'],
  clock=x['clock'],ordinary_proposed=x['proposed'],blocker=x.get('execution_blocker') or x.get('blocker')))
modified=read('modified_files.json');assert all(digest(ROOT/item['path'])==item['after_sha256'] for item in modified)
paths=list((ROOT/'scripts').glob('*.py'))+[p for p in (ROOT/'algo-trading-bot').rglob('*.py') if not {'venv','.venv','__pycache__'}&set(p.parts)]+list((ROOT/'configs').glob('*.json'))
manifest={str(path.relative_to(ROOT)):digest(path) for path in sorted(paths)}
(OUT/'source_manifest.json').write_text(json.dumps(dict(source_hash=receipt['source_hash'],files=manifest),indent=2)+'\n')
old=json.loads((ROOT/'docs/certification_v8_1_2026-10-12/source_manifest.json').read_text())['files']
different=[path for path,sha in old.items() if manifest[path]!=sha]
assert sorted(different)==sorted(item['path'] for item in modified if item['status']=='MODIFIED')
inv=json.loads((ROOT/'docs/legacy_dependency_inventory.json').read_text())
invproof={name:digest(ROOT/'docs'/name) for name in ['legacy_dependency_inventory.csv','legacy_dependency_inventory.json']}
attempts=[]
for name in ['targeted_initial.xml','targeted_v2.xml']:
 totals={k:0 for k in ('tests','failures','errors','skipped')}
 for suite in ET.parse(OUT/name).getroot().iter('testsuite'):
  for key in totals:totals[key]+=int(suite.attrib.get(key,0))
 attempts.append(dict(path=name,totals=totals,sha256=digest(OUT/name)))
(OUT/'test_attempts.json').write_text(json.dumps(attempts,indent=2)+'\n')
flags=dict(PARTIAL_FILL_EXIT_READY=False,ACTUAL_PROTECTION_READY=False,CONTROLLED_EXECUTION_READY=False,
 OFFLINE_RESIDUAL_HANDLING_TESTED=True,ACTUAL_PROTECTION_CERTIFIED=False,LONG_CERTIFIED=False,SHORT_CERTIFIED=False,
 FUNDED_RECOVERY_CERTIFIED=False,PRACTICE_READY=False,LIVE_READY=False,STRATEGY_FEED_RECERTIFIED=False)
summary=dict(status='PREFLIGHT_BLOCKED',authorization_status='NO_ORDER_AUTHORIZED',source_hash=receipt['source_hash'],source_hash_before=before['source_hash'],
 venue_full_close_below_minimum='NOT_ESTABLISHED_BY_AUTHORITATIVE_DOCUMENTATION',venue_stop_below_minimum='NOT_ESTABLISHED_BY_AUTHORITATIVE_DOCUMENTATION',
 actual_order_submissions=0,actual_wallet_signatures=0,actual_protection_acceptance=False,realized_pnl=None,realized_pnl_status='REALIZED_PNL_NOT_CERTIFIED',
 flags=flags,safety=safety,global_protection_enabled=False,tests=receipt,freeze=freeze,modified_files=modified,
 unchanged_other_v8_1_sources_and_configs=True,signer=signer,current_preflight=market,initial_public_preflight=first,markets=rows,
 review_only_proposal=wrapper,proposal_observed_ist=local(p['observed_ms']),entry_notional=str(entry),estimated_round_trip_fee=str(fees),
 planned_bound_loss_plus_fee=str(planned),legacy_inventory=dict(occurrences=inv['occurrences'],files=inv['files_with_occurrences'],hashes=invproof,previous_preserved='legacy_inventory_before/'),
 next_action='Obtain authoritative par full-close and protective-stop exception conditions below $10; question draft is unsent.')
(OUT/'final_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
lines=['# Team Anchorium — V8.2 partial-fill safety report','',
 '**Failure handling is improved and tested. Sub-$10 closing support is still unverified, so actual certification entry remains blocked.**','',
 'No real order, cancellation, transfer, leverage change or actual-wallet signature was made. The account remains flat at the saved public observations. There is no actual realized trade P&L to certify.','',
 '## Root cause and verified venue behavior','',
 'An entry request worth 25 USDPR can fill only one lot. A closing order can also leave one lot behind. Both existing local order boundaries enforce the published $10 minimum, including reduce-only exits and protective stops. Full requested entry size therefore cannot prove that every possible partial fill is closable.','',
 'The [participant guide](https://perpetual-alpha26.github.io/docs/) documents the minimum, reduce-only IOC closing and possible partial/rejected outcomes. [Hyperliquid error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) lists minimum-notional and reduce-only errors separately. The official SDK 0.24.0 market_close implementation uses an ordinary reduce-only IOC; it supplies no separate dust-close mechanism.','',
 '**The material inspected does not establish an exemption for either a complete sub-$10 close or a sub-$10 protective stop on par.** That is not proof of universal server rejection. It means we cannot safely code an exemption as fact. A fake exchange accepting such an order would not verify the venue.','',
 'The full evidence review is in '+link(OUT.relative_to(ROOT)/'venue_behavior.md','venue_behavior.md')+'. The precise implementation root causes are in '+link(OUT.relative_to(ROOT)/'root_cause.md','root_cause.md')+'.','',
 '## What changed','',
 '- Before entry, examine the smallest possible entry fill and last exit remainder using runtime lot size and reviewed bounded prices. Entry stays blocked if either requires an unverified subminimum exception.',
 '- Closing and protection use the exact observed full position, the opposite side and the approved size ceiling. Refuse unrepresentable dust, oversizing and price rounding that changes the reviewed limit.',
 '- Protection readback must cover the current full position. A previously prepared plan is insufficient if the position changed.',
 '- Save the real remaining exposure durably. A subminimum residual halts for operator review; restarting cannot invent flatness, create another entry or reuse an uncertain attempt.',
 '- Recover documented named terminal rejection/cancellation states using the original market/CLOID and actual fills. A partially filled order followed by cancellation remains partially filled. Missing orders and unknownOid remain unresolved.',
 '- Read-only preflight checks all ten 1x CROSS settings and can save an explicitly non-executable proposal wrapper when ordinary gates pass but partial safety fails.','',
 'No minimum validation was removed. No top-up, oversized reduce-only, zero-size stop, abnormal price or market helper was used as an assumed workaround.','',
 '| Source file | Change |','|---|---|']
purposes={'algo-trading-bot/exchange/partial_fill_safety.py':'New runtime-lot assessment, exact close sizing, durable residual observation and documented terminal status lists.',
'algo-trading-bot/exchange/testnet_certification.py':'Integrates exact sizing, current-position protection checks, persistent residual evidence and bounded exit outcomes.',
'algo-trading-bot/exchange/certification_runtime.py':'Resolves explicit terminal status with matched fills and retained uncertainty.',
'scripts/run_testnet_certification.py':'All-market leverage readback, partial-safety evidence and non-executable review proposal.',
'algo-trading-bot/test_partial_fill_safety_v8_2.py':'30 new offline partial-fill, precision, rejection, uncertainty, preflight and restart cases.'}
for item in modified:lines.append('| '+link(item['path'],item['path'])+' | '+purposes[item['path']]+' |')
lines += ['', 'Documentation, source-before copies, a patch, hashes and test/account receipts are saved in this V8.2 directory. The classified legacy inventory CSV/JSON was refreshed; earlier inventories were preserved.','',
 '## Tests and strategy integrity','',
 '**1,487 full-suite tests passed: 0 failures, 0 errors, 0 skipped.** This is the prior 1,457 baseline plus 30 new cases. The final focused suite passed all 82 cases; the earlier focused 80-case result is also preserved.','',
 'Phase-0 safety and frozen strategy verification passed. The full-suite source hash was identical before and after testing and matches the public preflight. All other source/configuration files in the V8.1 manifest remain unchanged. `signal_brain.py` and the frozen methods, VWAP/EMA/ATR, cooldown/direction state, 0.40% ATR floor, 15 bps spread, 300 completed UTC bars and Top-3 are preserved.','',
 'Offline cases cover small LONG/SHORT full closes, retained minimums, residuals below a lot, real remaining size, position changes during protection readback, entry/exit partials, rejected exits/protection, unknown acknowledgment, named terminal rejection, partial cancellation with actual fills, no blind retry and restart without another entry. SDK signing fixtures use ephemeral accounts and prohibit actual exchange HTTP.','',
 '```text\nSource before V8.2: '+before['source_hash']+'\nFinal tested source: '+receipt['source_hash']+'\nRegression XML SHA256: '+receipt['xml_sha256']+'\nFrozen brain SHA256: '+digest(ROOT/'algo-trading-bot/signal_brain.py')+'\n```','',
 '## Fresh read-only account and market observations','',
 'The first sandbox read failed with INFO_RETRY_BUDGET_EXHAUSTED; its evidence was preserved. The public read outside that sandbox succeeded, followed by one bounded refresh. Those reads did not exercise the exchange write endpoint.','',
 '| Account observation | Result |','|---|---|',
 '| Team wallet | '+p['team_wallet']+' |','| API wallet | '+p['api_wallet']+' |',
 '| Venue | Hyperliquid Testnet / par |',
 '| Capital | 1,000,000 test USDPR; not the proposed order size |',
 '| Mode / approval | unifiedAccount; API approval with valid expiry observed |',
 '| Leverage | All ten par markets 1x CROSS; no setting changed |',
 '| Positions / trigger-aware open orders | 0 / 0 at final saved snapshots |',
 '| Local API derivation / nonce owner | Matching public address; second owner rejected; zero nonce allocations; leases released |',
 '| Ownership scope | Current host/OS user only; sole remote signer ownership requires future human review |',
 '| Rate budget | Healthy; saved actual-account budget 13 used / 10,000 cap; no local signed actions |','',
 'Candidate observations are individually timestamped. ETH proposal observation: '+local(p['observed_ms'])+'. Every future execution needs a new preflight.','',
 '| Market | Book age | Spread | One-lot mark value | Current saved admission |','|---|---:|---:|---:|---|']
for x in rows:lines.append(f"| {x['symbol']} | {x['book_age_ms']} ms | {D(x['spread_bps']):.3f} bps | {D(x['one_lot_mark_value']):.6f} USDPR | {x['blocker']} |")
lines += ['', 'ETH passed ordinary proposal/account/price checks in the refresh. BTC remained below the required depth participation allowance. HYPE account readiness captured CLOCK_HEALTH_REQUIRED before the later fresh clock observations restored HEALTHY; the later clock result does not retroactively change that account-readiness verdict. The earlier ETH oracle-deviation rejection is a preserved earlier observation, not the refresh result.','',
 'Book times are exchange timestamps. Mark/oracle freshness in this path uses local REST receipt; upstream publication times are unavailable. These snapshots do not recertify continuous WebSocket operation or 300-candle strategy inputs.','',
 '## Exact LONG proposal — review only, blocked','',
 'This wrapper is saved in '+link(OUT.relative_to(ROOT)/'market_preflight_refresh/blocked_proposal.json','blocked_proposal.json')+'. It cannot deserialize as the executable proposal type. It is not an approval request while the partial safety gate fails, and its prices must not be reused for a later trade without a fresh review.','',
 '| Proposed item | Exact saved value |','|---|---|',
 '| Network / DEX / asset | testnet / par / '+p['symbol']+'; runtime asset ID '+str(p['asset_id'])+' |',
 '| Side / order | LONG / BUY, bounded limit IOC, one entry attempt |',
 '| Quantity | '+p['quantity']+' ETH |','| Maximum entry price | '+p['entry_limit']+' USDPR per ETH; at most 5 bps beyond the observed ask |',
 '| Entry notional / cap | '+str(entry)+' / 25 USDPR |','| Leverage / positions | 1x CROSS / one global par position maximum |',
 '| Test-only protection | Reduce-only stop-limit SELL for actual filled size; trigger '+p['stop_trigger']+'; limit '+p['stop_limit']+' |',
 '| Exit | Immediate bounded reduce-only IOC for exact remaining size; at most two attempts; SELL price at least '+p['exit_bound']+' and at most 20 bps below a fresh bid |',
 '| Fee estimate | '+str(fees)+' USDPR for entry plus closing at the bound, using 0.09% taker per fill; actual fees require exchange records |',
 '| Planned loss plus fees at the bound | '+str(planned)+' USDPR; this is an estimate, not a guaranteed maximum loss |',
 '| Proposed operational loss budget | 10 test USDPR; no safety override |',
 '| Protection semantics | Fixed plumbing-test stop based on observed bid, independent of frozen strategy/ATR |',
 '| Expiry / cancellation | Future exact human permit at most five minutes; at most six owned actions; clean up owned obsolete protection; no scheduled-cancel reliance |',
 '| Proposal hash | '+wrapper['proposal_hash']+' |',
 '| Actual order authorization | NONE |','',
 'The smallest possible ETH fill/remainder is 0.0001 ETH. At the proposed close limit it is worth '+wrapper['partial_fill_safety']['one_lot_notionals']['exit_bound']+' USDPR. That is the decisive blocker.','',
 'A stop-limit can be accepted yet fail to execute through a gap. Entry/exit can partly fill or be rejected; network/acknowledgment failure and expired permission can require urgent operator review. No order is held open to wait for profit. No approved maximum loss is an exchange guarantee.','',
 '## Readiness flags and remaining blockers','',
 '```ini\nPARTIAL_FILL_EXIT_READY = FALSE\nACTUAL_PROTECTION_READY = FALSE\nCONTROLLED_EXECUTION_READY = FALSE\nEXECUTION_MODE = PAPER\nALLOW_LIVE_ORDERS = false\nGLOBAL_PROTECTION_ENABLED = false\nREALIZED_PNL_STATUS = REALIZED_PNL_NOT_CERTIFIED\n```','',
 '- PARTIAL_FILL_EXIT_READY is false because a safe subminimum close/protection exception has not been verified. Conservative rejection/recovery behavior is tested; venue support is not.',
 '- ACTUAL_PROTECTION_READY is false because there has been no authorized actual stop acceptance/readback test. Configured or simulated protection is not actual proof.',
 '- CONTROLLED_EXECUTION_READY is false because partial safety remains blocked, no exact human order approval exists, and future current price/account/host checks are required.',
 '- Actual LONG/SHORT, funded restart/recovery, controlled execution, PRACTICE_READY and LIVE_READY remain false. The independent V7 strategy-feed blocker remains preserved.',
 '- No actual fills or realized P&L were generated. PAPER and offline-fixture accounting remain distinct from wallet truth.','',
 '## Exact next safe action','',
 '**Obtain authoritative par confirmation of the full-position reduce-only IOC and protective-stop rules below $10, including exact fields and conditions.** The '+link(OUT.relative_to(ROOT)/'organizer_question_draft.md','unsent question draft')+' is ready. No message was sent.','',
 'If support is confirmed, implement and test only that narrow path, then repeat source-bound regression and fresh preflight. Only after those gates pass can the operator approve an exact small test. The current blocker cannot be waived by approval, an environment flag or account funding.']
(OUT/'report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(dict(status=summary['status'],flags=flags,tests=receipt['totals'],source_hash=receipt['source_hash'],report=str(OUT/'report.md'))))
