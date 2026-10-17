"""Render final engineering evidence; no exchange calls, imports of keys or trading."""
from pathlib import Path
from decimal import Decimal as D
import json,hashlib,sqlite3,sys,datetime
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
base=json.loads((HERE/'baseline.json').read_text());receipt=json.loads((HERE/'regression_release_final/test_receipt.json').read_text())
current=json.loads((HERE/'soak_final/current.json').read_text());run=Path(current['output'])
terminal=json.loads((run/'terminal_result.json').read_text())
samples=[json.loads(l) for l in (HERE/'soak_resource_samples.jsonl').read_text().splitlines()]
if not receipt.get('passed') or receipt['source_hash']!=active_source_hash(ROOT):raise RuntimeError('FINAL_MATCHING_RELEASE_REQUIRED')
files={k:dict(expected=v,actual=sha(ROOT/k),unchanged=sha(ROOT/k)==v) for k,v in base['preserved'].items()}
dbs={}
for name,v in base['databases'].items():
 c=sqlite3.connect('file:'+str(ROOT/name)+'?mode=ro',uri=True)
 actual=hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()
 dbs[name]=dict(integrity=c.execute('pragma integrity_check').fetchone()[0],unchanged=actual==v['dump_sha256'],dump_sha256=actual);c.close()
if not all(r['unchanged'] for r in files.values()) or not all(r['unchanged'] and r['integrity']=='ok' for r in dbs.values()):raise RuntimeError('ORIGINAL_EVIDENCE_CHANGED')
preservation=dict(files=files,databases=dbs,passed=True);atomic_json(HERE/'preservation.json',preservation)
ready=[r for r in samples if r.get('account_stream_healthy') and r.get('stream_connected')]
mem=[r['rss_high_watermark_mb'] for r in samples if r.get('rss_high_watermark_mb') is not None]
late=[r['rss_high_watermark_mb'] for r in samples[len(samples)//2:] if r.get('rss_high_watermark_mb') is not None]
soak=dict(status=terminal['status'],duration_seconds=(json.loads((run/'status.json').read_text())['updated_ms']-json.loads((run/'status.json').read_text())['started_ms'])/1000,
 shutdown_reconciliation_error=terminal.get('terminal_reconciliation_error'),sample_count=len(samples),healthy_both_stream_samples=len(ready),
 memory_high_watermark_mb=max(mem),late_high_watermark_growth_mb=max(late)-min(late) if late else None,
 public_info_requests=terminal.get('public_receipt_count'),actual_errors=terminal.get('actual_errors'),account_stream_last_error=terminal.get('account_stream_error'),market_stream_last_error=terminal.get('stream_last_error'),
 terminal_flat=terminal.get('terminal_flat'),terminal_readbacks=terminal.get('terminal_readbacks'),
 execution_intents=terminal.get('execution_intents'),journal_integrity=terminal.get('journal_integrity'),threads_stopped=terminal.get('threads_stopped'),
 final_log_bytes=samples[-1].get('total_bytes'),receipt_rotations=terminal.get('receipt_rotations'),source_hash=terminal['source_hash'])
atomic_json(HERE/'soak_audit.json',soak)
post=json.loads((HERE/'final_account/audit.json').read_text())
readbacks=post['readbacks']
post_flat=len(readbacks)==2 and readbacks[0]['observed_ms']<readbacks[1]['observed_ms'] and all(x['ready'] and not x['positions'] and not x['orders'] for x in readbacks)
if not post_flat:raise RuntimeError('FRESH_POST_STOP_ACCOUNT_REVIEW_REQUIRED')
account=post['account'];start=int(datetime.datetime(2026,10,16,tzinfo=datetime.timezone(datetime.timedelta(hours=5,minutes=30))).timestamp()*1000)
fills=[f for f in account.get('fills',[]) if f['timestamp_ms']>=start];funding=[e for e in account.get('funding_events',[]) if e['timestamp_ms']>=start]
today=dict(actual_fills=len(fills),gross=sum((D(f['closed_pnl']) for f in fills),D(0)),fees=sum((D(f['fee']) for f in fills),D(0)),funding=sum((D(e['cashflow']) for e in funding),D(0)))
today['net']=today['gross']-today['fees']+today['funding']
complete=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines() if len(json.loads(line).get('liquidity',{}))==10]
liquidity=complete[-1]['liquidity'] if complete else terminal.get('liquidity',{})
report=dict(status='STANDALONE_ENGINEERING_VALIDATED_GENUINE_ACTIVATION_BLOCKED',source_hash=active_source_hash(ROOT),
 receipt='regression_release_final/test_receipt.json',receipt_sha256=sha(HERE/'regression_release_final/test_receipt.json'),
 regression=receipt['totals'],xml_sha256=receipt['xml_sha256'],soak=soak,original_evidence_preserved=True,
 observer_requires_codex=False,ordinary_runtime_llm_calls=0,new_session_approved=False,new_actual_orders=0,
 genuine_long_cycles_historical=1,genuine_strategy_generated_long_cycles_qualified=0,approved_new_entry_attempts=0,
 proposed_limits=dict(bankroll='20000',target_notional=['1000','2500','5000','10000'],stress_only=['25000','50000'],leverage=1,positions=1,attempts=2,daily_loss_fraction='.01'),
 genuine_qualified_unattended_notional='0',commit=base['commit'],native_stop='BLOCKED_SUBMINIMUM_PARTIAL_PATH_AND_NO_ACTUAL_TRIGGER_PROOF',
 final_flat_verified=post_flat,post_stop_authoritative_readbacks=readbacks,final_account_receipt_sha256=sha(HERE/'final_account/info_receipts.jsonl'),final_positions=account.get('positions'),final_open_orders=account.get('open_orders'),today=today,
 historical_oct15_verified_net='0.050512',liquidity=liquidity,
 limitations=['No new genuine trading or protection qualification was authorized or executed',
 'Development soak is not multi-day host-outage or long-session trading qualification',
 'Actual SHORT and all six alternate research exits remain unpromoted',
 'STOP cannot create closure authority; expired signing leaves residual exposure for human review',
 'A Stop Limit may remain unfilled after a gap; Mac/Python/power/internet required for local management',
 'No organizer whitelist/reset evidence'])
atomic_json(HERE/'release_summary.json',report)
lines=['# Team Anchorium standalone terminal — release report','',
 '## A. Application readiness','',
 'The local CLI is implemented at `scripts/anchorium_cli.py`: doctor, research, simulate, prepare, approve, start, status, report and stop. Default start is public-only. Exact-authorized start reuses the existing frozen manager, central execution/SDK, native Stop Limit adapter and daily coordinator. No new unrestricted submission path was added. No new trading session was started.','',
 '## B. Codex independence','',
 'Normal runtime is deterministic local Python. It has no paid-model dependency or API call and does not need the Codex app, a chat or a heartbeat. Both historical automations remain PAUSED. The Mac, Python process, power and internet are still dependencies. Public and authorized exchange APIs remain necessary.','',
 '## C. LONG readiness','',
 'Execution-capable integration exists, but genuine unattended strategy LONG qualification is BLOCKED. The historical controlled BTC round trip is one genuine cycle; it does not qualify a new strategy session. No new exact mandate or acceptance was created. SHORT stays disabled.','',
 '## D. Native protection','',
 '`exchange.partial_fill_safety.partial_path_assessment` checks the smallest runtime lot at entry, protective stop limit and closing bound. Increasing the proposed opening quantity cannot remove possible one-lot partials. Sampled one-lot bid notionals below are all under $10. The ordinary order minimum is $10. The separately evidenced historical IOC full-position closure is not evidence of a native-stop exception. `DailyLimitProtection` preserves normal stop minus one entry ATR and a 0.5% Stop Limit execution allowance. An accepted untriggered stop does not satisfy the actual linked trigger-fill/two-flat-readback proof gate.','',
 'The shortest valid path is authoritative venue clarification/evidence for subminimum native residual handling, or a genuinely minimum-compliant market/lot at the reviewed frozen stop/close prices, then separately approved tiny qualification using unchanged partial guards. The existing qualification and child/identity/cleanup infrastructure must be used; no actual qualification is possible under the sampled guard. Native Stop Market has a different documented 10% tolerance and was not substituted. Stop Limit can rest after a gap. No guard was disabled.','',
 'Primary sources: [competition guide](https://perpetual-alpha26.github.io/docs/), [venue errors](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses), [native TP/SL behavior](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl).','',
 '## E. Multiple trades','',
 'The terminal simulation executes two sequential fixture cycles with a win and a loss, plus rejection, uncertain entry, partial entry and partial exit episodes. Every event is SIMULATION, with no HTTP/socket access and ephemeral SDK keys only. Fault exposure remains visible and the same uncertain candidate is not blindly repeated. The synthetic whole-unit lot fixture is not actual par metadata. Real complete cycles remain one historical BTC cycle; currently approved new entry attempts are zero. A future independently accepted session can permit at most two attempts and one concurrent position.','',
 '## F. Capital','',
 'Proposed bankroll: 20,000 TEST USDPR. Approved bankroll: none. Qualified unattended notional: zero. Reported current collateral: '+str((account.get('reported_account_equity') or {}).get('collateral_balance'))+'. Account balance is not approval. Targets 1,000/2,500/5,000/10,000 and offline stresses 25,000/50,000 remain proposals/research. The allocator uses the minimum of mandate/risk/margin/runtime size limits and both-sided best-level/L2/exit capacity, rounding down without order splitting. SP500 is independently runtime-eligible but that does not establish strategy or protective qualification.','',
 '| Market | Last observed route capacity USDPR | One-lot bid notional |','|---|---:|---:|']
for s,c in sorted(liquidity.items()):lines.append(f"| {s} | {c['notional']} | {c['one_lot_bid_notional']} |")
lines += ['', 'Prices/capacities are explicitly time-stamped in the machine report; they are observations, not current executable promises or approved sizes.','','## G. Autonomy','',
 'The observer runs until STOP/Ctrl+C/fatal interruption. Signing is independently bounded to one explicit IST day ending by 23:57, with a five-minute human acceptance window and no automatic renewal/restart/day rollover. The CLI hands a stopped signer back to a separate public client without a signer. This transition is tested offline; it has not been exercised with new real exchange orders.','',
 '## H. Risk, shutdown and repairs','',
 'Source/dependency/clock/rate/account/stream/reconciliation/UNKNOWN/protection/persistence and loss-budget gates halt entries. STOP revokes entry permission at the final signing check, while original exact risk recovery and owned cancellation may remain possible until expiry. Unknown or partial outcomes are reconciled by identity, never blindly resubmitted. Expired signing does not block read-only terminal reconciliation. Two authoritative flat/zero-order snapshots are required; unresolved exposure remains EXPOSED/UNKNOWN.','',
 'The real public soak found and repaired account WebSocket TLS trust configuration: it now uses the same verified Requests CA bundle and hostname checks as the market stream. The account receiver now runs independently of scanner REST waits, with event sequence checks preventing a concurrent notification from being cleared by reconciliation. Earlier soak attempts were stopped and preserved as diagnostic evidence. An earlier regression candidate changed source during these repairs and is not the release receipt.','',
 'The copied virtual-environment activation scripts also selected the original NSE environment; only the clone’s activation paths were repaired and the documented activation command was checked against its own Python prefix. No original-repository file or dependency installation was changed.','',
 'Internal logs rotate with documented retention; SQLite/memory/disk guards halt safely. Reports separate observed historical account P&L, current session events and simulation. UI states never turn submitted orders into fills.','','## I. Full regression and soak','',
 f"Full offline regression: **{receipt['totals']['tests']} tests, {receipt['totals']['failures']} failures, {receipt['totals']['errors']} errors, {receipt['totals']['skipped']} skips**. Phase-0 and strategy freeze passed before and after; source hashes match.",'',
 f"Source SHA-256: `{report['source_hash']}`. Receipt SHA-256: `{report['receipt_sha256']}`. XML SHA-256: `{receipt['xml_sha256']}`.",'',
 f"Final public soak: {soak['duration_seconds']:.1f} seconds, {soak['sample_count']} resource samples, {soak['healthy_both_stream_samples']} samples with both streams healthy; peak memory {soak['memory_high_watermark_mb']:.2f} MB; late high-watermark growth {soak['late_high_watermark_growth_mb']} MB; {soak['public_info_requests']} public requests; recorded REST/HTTP errors {soak['actual_errors']}; account stream last recovery label {soak['account_stream_last_error']}; market stream last error {soak['market_stream_last_error']}. Journal integrity {soak['journal_integrity']}; execution intents {soak['execution_intents']}; background threads stopped {soak['threads_stopped']}; terminal flat {soak['terminal_flat']}.",'',
 'The worker shutdown’s full reconciliation returned ExchangeError before two authoritative terminal readbacks; it retained UNKNOWN. Its guard allows only a 5-second local rate wait within a 40-second terminal read window; the precise exception message was not retained. No HTTP429 was recorded. The separate 90-second bounded public audit after the process stopped obtained two fresh ready/zero-position/zero-order readbacks. The raw worker outcome remains unchanged; final flatness is established by final_account/audit.json and its raw receipts.','',
 'This is a bounded development soak, not a multi-day unattended execution certificate. Original policies, source freeze, proofs, certificate and all original testnet database dumps remain unchanged. Requirements were aligned to the already-installed tested versions; no dependency installation was needed.','','## J. Exact terminal commands','',
 'See [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) for every tested command and explicit future approval/start paths. Safe command checks, real CLI simulations/research, public diagnostics/proposal and STOP/status/report evidence are retained in this directory. The actual authorized start was deliberately not executed without its prerequisites and exact human mandate.','','## K. Genuine P&L','',
 'Original verified October 15 BTC: BUY 0.0002 at 81,512, order 62755970305 / fill 800659111758533, fee 0.014672; SELL 0.0002 at 81,909, order 62805581662 / fill 260274449763192, fee 0.014743. Gross +0.0794, total fees 0.029415, actual funding +0.000527: **net +0.050512 TEST USDPR**. Original BUY/SELL proofs were preserved byte-for-byte.','',
 f"October 16 actual observed fills: {today['actual_fills']}; gross {today['gross']}; fees {today['fees']}; funding {today['funding']}; net {today['net']}. New actual exchange submissions by this release: zero. Final positions {account.get('positions')}; final open orders {account.get('open_orders')}. No organizer whitelist/reset claim is made."]
(HERE/'implementation_report.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:report[k] for k in ('status','source_hash','regression','native_stop','final_positions','final_open_orders')},indent=2))
