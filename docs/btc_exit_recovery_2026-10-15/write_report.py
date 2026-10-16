"""Document actual observations separately from proposed recovery authority."""
import json,hashlib,sqlite3,time,sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[2];BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import atomic_json,active_source_hash
IST=timezone(timedelta(hours=5,minutes=30))
def at(ms):return datetime.fromtimestamp(ms/1000,IST).isoformat()
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def table_rows(p,table):
 c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
 try:return c.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
 finally:c.close()
r=load(BASE/'regression_release/test_receipt.json')
ctx=load(BASE/'recovery_context_read_only_v2.json')
proposals={name:load(BASE/name/'proposal.json') for name in ('profit_proposal','immediate_close_proposal') if (BASE/name/'proposal.json').exists()}
latest=max([ctx,*proposals.values()],key=lambda p:p.get('observed_ms',0))
source=active_source_hash(ROOT)
changed=['algo-trading-bot/exchange/certification_runtime.py','algo-trading-bot/exchange/rate_limits.py','algo-trading-bot/exchange/exit_recovery.py','algo-trading-bot/test_exit_recovery.py','scripts/run_exit_recovery.py']
proofs=[ROOT/'docs/qualification_2026-10-15/WHITELIST_TRADE_PROOF.json',ROOT/'docs/qualification_2026-10-15/session_preparation/authorized_session/WHITELIST_TRADE_PROOF.json']
nonce_before=BASE/'before_nonces.sqlite';nonce_current=ROOT/'runtime/testnet/anchorium-bot-1/nonces.sqlite'
c=sqlite3.connect('file:'+str(nonce_before)+'?mode=ro',uri=True)
try:tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
finally:c.close()
nonce_unchanged=all(table_rows(nonce_before,t)==table_rows(nonce_current,t) for t in tables)
with sqlite3.connect('file:'+str(ROOT/'runtime/testnet/anchorium-bot-1/qualification.sqlite')+'?mode=ro',uri=True) as c:
 rows=c.execute('SELECT intent_key,state,oid,request FROM intents').fetchall()
 own_exits=[dict(intent_key=k,state=s,oid=o,request=json.loads(q)) for k,s,o,q in rows if k.endswith(':exit:0') or k.endswith(':exit:1')]
summary=dict(generated_ms=time.time_ns()//1000000,status='AWAITING_SEPARATE_EXACT_EXIT_APPROVAL',source_hash=source,
 regression=r,files_modified={p:sha(ROOT/p) for p in changed},latest_observation=latest,
 proposals=proposals,new_recovery_exit_intents=own_exits,nonce_tables_unchanged_since_task_start=nonce_unchanged,
 original_buy_proof_sha256={str(p.relative_to(ROOT)):sha(p) for p in proofs},
 qualification_fill_verified=True,organizer_whitelisting_confirmed=False,protection_verified=False,
 realized_roundtrip_pnl=None,production_mode='PAPER',allow_live_orders=False,practice_ready=False,live_ready=False)
if (BASE/'authorized_recovery/result.json').exists():
 result=load(BASE/'authorized_recovery/result.json');summary.update(status=result['status'],recovery=result,realized_roundtrip_pnl=result.get('realized_pnl'))
atomic_json(BASE/'final_summary.json',summary)
lines=['# BTC exit recovery — 15 October 2026','',
'The genuine qualification BUY is verified. A complete round trip and a flat account have not yet been demonstrated. The existing position has no verified protective stop. A new SELL requires its own exact human approval; the consumed entry session is not reused.','',
'## Actual entry and account evidence','',
'- Team account: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`. API signer: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`.',
'- Venue: Hyperliquid TESTNET, DEX `par`, symbol `par:BTC`, collateral TEST USDPR.',
'- Actual BUY: 0.0002 BTC at 81,512; notional 16.30240 USDPR; reported fee 0.014672 USDPR.',
'- Exchange order 62755970305; fill 800659111758533; 15 October 2026, 10:16:30.641 IST.',
'- The original BUY evidence remains in its original files. Organizer whitelisting remains unconfirmed.',
'- Latest report observation: '+at(latest['observed_ms'])+'. See the timestamped JSON for positions, orders, funding and book. These observations expire; mandatory fresh checks still precede any signing.','',
'## Why the previous exit stopped','',
'The original BUY was accepted and filled. The following direct account-recovery call halted with RATE_LIMITED before any exit intent or exit HTTP submission. The code uses this error for a local request-budget rejection; an actual /info HTTP 429 has the distinct INFO_HTTP_429 error and HTTP status evidence. There is no evidence here that an exchange outage caused the halt.',
'',
'The direct recovery bundle ran outside the provider wrapper that paces reads. Repeated serial account/history/metadata checks could consume the local rolling budget or reserved allowance. The historical error did not record its exact query, rolling weight or rejection branch, so those details cannot honestly be reconstructed. The fix paces the recovery bundle and records query, priority, weight, limit, reserve and backoff on any future local rejection. No budget is raised or reset.',
'',
'Authoritative API limits: [Hyperliquid rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).','',
'## Narrow changes','']
for p in changed:lines.append('- `'+p+'` — SHA-256 `'+summary['files_modified'][p]+'`.')
lines.extend(['',
'- `certification_runtime.py`: compare quantity, entry price and leverage during exposure reconciliation. Mark-valued unrealized P&L or margin changing alone no longer masquerades as a position change; real exposure/order changes still fail closed.',
'- `rate_limits.py`: persistent local read-budget rejection diagnostics. Existing limits and reserves remain enforced.',
'- `exit_recovery.py`: separate source-bound SELL-only mandate; exact actual 0.0002 LONG; new approval; one reduce-only IOC; existing validation, five-second signing boundary, nonce lease, durable journal and official SDK transport.',
'- CLI: read-only preparation is the default. Execution requires the exact new mandate, acceptance and matching full regression receipt.',
'- Tests: offline full/partial/zero fills, uncertain acknowledgments, changed accounts, fresh-data checks, price/depth bounds, all acknowledgments, expiry, source mutation, duplicate prevention and restart lockouts. Synthetic tests do not establish venue protective-stop support.','',
'## Fees and profitable price','',
'Net completed-roundtrip P&L = actual SELL proceeds − actual BUY cost − entry fee − exit fee + net reported funding. Before a SELL fill this is a conditional estimate, not realized profit.',
'',
'At an assumed 0.09% exit fee and zero funding, exact break-even is 81,658.85296767090381343208888 USDPR/BTC. A 0.001 USDPR positive buffer gives a valid rounded SELL floor of 81,664. The previous entry fee alone cannot prove the next exit fee.',
'',
'The actual testnet perpDexs response omits deployerFeeScale. The new path therefore uses the documented maximum all-in HIP-3 multiplier of six times the current userCrossRate when the scale is unavailable. It ignores discounts. At userCrossRate 0.00045 this is a conservative 0.00270 (0.27%) bound, not a claim about the actual next fee. Any rate above the approved 0.003 cap blocks signing. Funding is fetched from actual account history; it is not inferred from the displayed hourly rate.',
'',
'Fee formula source: [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees).','',
'## Exact separately approvable choices',''])
for name,p in proposals.items():
 lines.extend(['### '+name,'','- Mandate hash: `'+p['mandate_id']+'`.','- Observation: '+at(p['observed_ms'])+'; approval deadline: '+at(p['mandate']['approval_deadline_ms'])+'.',
 '- Existing position: '+str(p['position']['quantity'])+' BTC; open orders: '+str(len(p['orders']))+'.',
 '- Actual bid / ask: '+p['bid']+' / '+p['ask']+'; spread '+p['spread_bps']+' bps.',
 '- Minimum SELL: '+p['minimum_sell']+'; reviewed limit: '+p['planned_limit']+'; executable at observation: '+str(p['currently_executable'])+'.',
 '- Fee upper bound: '+p['conservative_exit_fee']+'; reported funding: '+p['funding']+'; conservative conditional net at reviewed bid: '+p['estimated_net_at_bid']+' USDPR.',
 '- Scope: '+p['mandate']['mode']+'; one SELL reduce-only IOC of exactly 0.0002 BTC; window '+str(p['mandate']['window_ms']//1000)+' seconds after valid acceptance.',
 '- No lower-price fallback or extension. Dynamic price is fresh bid minus 10 bps, rounded up, bounded by the approved floor and current 20-bps allowance. Profit mode can raise its floor as fees/funding change.',''])
lines.extend(['## Attempt, rejection and recovery policy','',
'A changed/closed position, any unexpected order, new fill, unhealthy signer/nonce/account state, stale evidence, insufficient depth, spread above the isolated 50-bps ceiling, or violated price/fee/source/time bound blocks the planned SELL. No BUY or leverage change is authorized. The production 15-bps scanner rule remains unchanged.',
'',
'One durable exit attempt consumes the recovery mandate. A rejected, zero-filled, partially filled or uncertain exit ends automated orders. There is no second SELL, replacement or exposure enlargement. If a 0.0001 BTC residual remains, this 0.0002 mandate cannot close it: obtain fresh authoritative records and separate exact recovery authority. The full-position subminimum closing evidence does not certify protective stops.',
'',
'A crash cannot resume writes with the old runtime token. Inspect the original close cloid/order ID, team fills, positions and frontend orders; resolve uncertainty using reads, never by blind resubmission. If a REST/WebSocket check fails, keep the account exposure flagged UNKNOWN until authoritative reconciliation. Revoke signing locally and escalate unresolved exposure to the operator.',
'',
'Profit-only monitoring lasts at most ten minutes from valid approval, reserving the final 15 seconds for management. If no qualifying profitable exit occurs, it stops and reports the position. The separately approved immediate-close mode lasts at most two minutes and permits a modeled net loss no worse than 0.50 USDPR at the approved limits; this is not a guaranteed maximum loss if an exit fails or exposure remains. Neither choice submits a protective stop.','',
'## Verification and limitations','',
'Early focused test failures and read-only report-formatting errors are preserved in their original logs. The first focused fixture omitted its shared rate manager; the corrected fixture uses the real budget and a deterministic clock. One diagnostic report called health() instead of report(); the corrected read-only v2 report completed. These were not exchange order failures and produced no signed action.',
'',
'- Full receipt: `regression_release/test_receipt.json`; tests '+str(r.get('totals'))+'; passed '+str(r.get('passed'))+'.',
'- Source before/after tests matches current source: '+str(r.get('source_hash')==r.get('source_hash_after')==source)+'.',
'- Before/after strategy-freeze and Phase-0 checks are recorded in the receipt. Frozen signal/state logic and PAPER/false defaults are preserved.',
'- Nonce tables unchanged since this task began: '+str(nonce_unchanged)+'. Any later approved exit will legitimately append one nonce and must be documented separately.',
'- No current-task exchange order is established by preparation or tests. Original real BUY evidence remains separate from offline fixtures and proposed SELL terms.',
'- A flat-account claim requires two fresh authoritative zero-position/zero-order readbacks and ready reconciliation. Realized net P&L requires the actual SELL fills, reported fees and funding.',
'- Protection VERIFIED = FALSE; normal protected controlled execution = FALSE; PRACTICE_READY = FALSE; LIVE_READY = FALSE.',''])
if summary.get('recovery'):
 lines.extend(['## Authorized recovery result','',json.dumps(summary['recovery'],indent=2,default=str),''])
(BASE/'report.md').write_text('\n'.join(lines))
print(json.dumps(dict(status=summary['status'],source_hash=source,regression=r.get('totals'),nonce_tables_unchanged=nonce_unchanged,proposals=list(proposals)),indent=2))
