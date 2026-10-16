"""Report actual engineering/test/public evidence; never creates an approval."""
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime
from zoneinfo import ZoneInfo
import sys,json,hashlib,sqlite3,time,tomllib
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
from exchange.execution_journal import fingerprint
from exchange.qualification_intent_recovery import verified_qualification_view

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def when(ms):return datetime.fromtimestamp(ms/1000,ZoneInfo('Asia/Calcutta')).isoformat()

def preservation():
    baseline=json.loads((OUT/'source_before.json').read_text());prior=baseline['original_preservation']
    changes=[p for p,h in baseline['source_sha256'].items() if sha(ROOT/p)!=h]
    expected={'algo-trading-bot/exchange/bounded_daily_session.py','algo-trading-bot/exchange/live_recovery.py',
        'algo-trading-bot/test_production_reliability.py'}
    preserved={p:sha(ROOT/p)==r['actual'] for category in ('policy_sha256','preserved_evidence_sha256')
        for p,r in prior['preservation'][category].items()}
    runtime=ROOT/'runtime/testnet/anchorium-bot-1'
    with sqlite3.connect((runtime/'qualification.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        raw=[dict(r) for r in db.execute('SELECT * FROM intents ORDER BY created_ms,intent_key')]
        certificates=[dict(r) for r in db.execute('SELECT * FROM nontransmission_resolutions')]
        view=verified_qualification_view(db)
        checkpoints=[dict(seq=s,checksum=h,checksum_valid=fingerprint(json.loads(data))==h,
            last_clean_shutdown=json.loads(data).get('last_clean_shutdown'))
            for s,data,h in db.execute('SELECT seq,data,checksum FROM recovery_snapshots ORDER BY seq')]
        q=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            certificates=certificates,effective_view=view,recovery_snapshots=checkpoints)
    # Compare actual rows with the immutable baseline audit, not a previous bool.
    old=json.loads((ROOT/'docs/quant_engine_2026-10-16/baseline_preservation.json').read_text())
    q.update(raw_intents_unchanged=raw==old['qualification.sqlite']['raw_intents'],
        certificates_unchanged=certificates==old['qualification.sqlite']['certificates'],
        effective_view_unchanged=view==old['qualification.sqlite']['effective_view'])
    with sqlite3.connect((runtime/'nonces.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        nonce=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            nonces=[list(r) for r in db.execute('SELECT signer,last FROM nonces')],
            health=[list(r) for r in db.execute('SELECT * FROM nonce_health')])
    result=dict(observed_ms=time.time_ns()//1000000,source_hash=active_source_hash(ROOT),
        reviewed_existing_source_changes=changes,only_expected_changes=set(changes)==expected,
        preserved_policy_and_trade_proofs=preserved,qualification=q,nonces=nonce,
        nonce_history_unchanged=nonce==old['nonces.sqlite'],
        original_unknown_preserved=any(r['state']=='UNKNOWN' for r in raw))
    result['passed']=(result['only_expected_changes'] and all(preserved.values()) and nonce==old['nonces.sqlite']
        and q['integrity']=='ok' and q['raw_intents_unchanged'] and q['certificates_unchanged']
        and q['effective_view_unchanged'] and all(r['checksum_valid'] for r in checkpoints))
    atomic_json(OUT/'preservation_verification.json',result);return result

def liquidity(folder):
    audit=json.loads((folder/'audit.json').read_text());receipts=[json.loads(x) for x in (folder/'info_receipts.jsonl').read_text().splitlines()]
    bars={r['request']['req']['coin']:r for r in receipts if r['request']['type']=='candleSnapshot' and 'response' in r}
    result=[];tiers=[]
    for symbol in sorted({r['symbol'] for r in audit['samples']}):
        samples=[r for r in audit['samples'] if r['symbol']==symbol and r['status']=='OBSERVED']
        if not samples:result.append(dict(symbol=symbol,status='FAILED_SAFE'));continue
        last=samples[-1];book=last['book'];bid=D(book['bids'][0]['price']);ask=D(book['asks'][0]['price'])
        fee=D(last['fee_rate_bound']);q=D(last['directions']['LONG']['proposed_quantity'])
        lot=D(10)**(-int(last['spec']['size_decimals']));funding=D(last['context']['funding']);oracle=D(last['context']['oraclePx'])
        minimum=min(D(r['directions']['LONG']['capacity_notional']) for r in samples)
        maximum=max(D(r['directions']['LONG']['capacity_notional']) for r in samples)
        cache=bars.get(symbol);latest=max((c['t'] for c in cache['response']),default=None) if cache else None
        row=dict(symbol=symbol,samples=len(samples),first_ms=samples[0]['observed_ms'],last_ms=last['observed_ms'],
            long_capacity_min=str(minimum),long_capacity_max=str(maximum),long_capacity_last=last['directions']['LONG']['capacity_notional'],
            short_capacity_min=str(min(D(r['directions']['SHORT']['capacity_notional']) for r in samples)),
            short_capacity_max=str(max(D(r['directions']['SHORT']['capacity_notional']) for r in samples)),
            short_capacity_last=last['directions']['SHORT']['capacity_notional'],
            lot=str(lot),one_lot_at_bid=str(lot*bid),one_lot_stop_review_notional=last['one_lot_stop_notional'],
            best_bid=str(bid),best_ask=str(ask),bid_size=book['bids'][0]['quantity'],ask_size=book['asks'][0]['quantity'],
            spread_bps=last['spread_bps'],leverage=last['active_asset']['leverage'],
            runtime_max_trade_quantities=last['active_asset']['maxTradeSzs'],available_collateral=last['active_asset']['availableToTrade'],
            entry_walk=last['directions']['LONG']['entry'],exit_walk=last['directions']['LONG']['exit'],
            estimated_roundtrip_fee_bound=last['directions']['LONG']['estimated_roundtrip_fees'],fee_rate_bound=str(fee),
            long_hourly_funding_cashflow_estimate=str(-q*oracle*funding),
            short_hourly_funding_cashflow_estimate=str(q*oracle*funding),
            worst_sampled_ask_move_bps=str((max(D(r['book']['asks'][0]['price']) for r in samples)/min(D(r['book']['asks'][0]['price']) for r in samples)-1)*10000),
            candle_receipt_ms=cache.get('received_ms') if cache else None,
            cached_candle_age_ms=last['observed_ms']-cache['received_ms'] if cache else None,
            latest_candle_ms=latest,latest_completed_candle_age_ms=last['observed_ms']-(latest+60000) if latest else None,
            strategy_decision=last['signal']['decision'],strategy_reasons=last['signal']['reasons'],
            partial_protection_ready=all(r['partial_protection_qualified'] for r in samples),
            supports_1000_in_every_sample=minimum>=1000,proposed_safe_execution_notional='0',
            blockers=['NATIVE_PROTECTION_NOT_EXCHANGE_QUALIFIED','SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED',
                'NO_CURRENT_EXACT_OPERATOR_TRADING_APPROVAL',*last['signal']['reasons']],
            note='Displayed capacity, never a guaranteed executable or approved notional; SHORT is disabled')
        result.append(row)
        for size in (1000,2500,5000,10000,25000,50000):
            requested=(D(size)/ask).quantize(lot,rounding='ROUND_DOWN');n=requested*ask
            last_supported=n<=D(row['long_capacity_last']);persistent=n<=minimum
            tiers.append(dict(symbol=symbol,desired_notional=size,requested_quantity=str(requested),
                rounded_reference_notional=str(n),theoretical_1x_initial_margin=str(n),
                entry_fee_upper_estimate=str(n*fee),exit_fee_upper_estimate_at_same_notional=str(n*fee),
                current_book_supports_target=last_supported,all_samples_support_target=persistent,
                complete_finite_fill_cost=None if not last_supported else str(n),
                actual_fill=False,qualified=False,approved_bankroll=None,
                actual_liquidation_price=None,stop_risk=None,
                risk_status='NO_EXECUTION_WITHOUT_FRESH_VALID_STRATEGY_ATR_AND_NATIVE_PROTECTION',
                funding_scenario='Current hourly rate only; future rates/holding time unknown',
                closing_gap_and_stop_failure='Unquantified: displayed liquidity and stop orders do not cap realized loss'))
    atomic_json(OUT/'liquidity_capacity.json',dict(audit_source=str(folder.relative_to(ROOT)),
        audit_sha256=sha(folder/'audit.json'),receipts_sha256=sha(folder/'info_receipts.jsonl'),
        started_ms=audit['started_ms'],finished_ms=audit['finished_ms'],markets=result,tiers=tiers,
        signatures_created=0,exchange_writes=0,qualified_genuine_notional='0'))
    return audit,result

def main():
    preservation_result=preservation()
    folder=OUT/'afternoon_liquidity'
    if not (folder/'audit.json').exists() or not json.loads((folder/'audit.json').read_text()).get('finished_ms'):
        folder=OUT/'fresh_liquidity'
    audit,markets=liquidity(folder);now=time.time_ns()//1000000
    final=OUT/'final_account/audit.json'
    if final.exists():
        a=json.loads(final.read_text())
        if a.get('account') and len(a.get('readbacks',[]))==2:
            audit=dict(audit,account_final=a['account'],final_readbacks=a['readbacks'])
    current=audit['account_final'];day_start=1792089000000
    today_fills=[f for f in current['fills'] if f['timestamp_ms']>=day_start]
    today_funding=[f for f in current['funding_events'] if f['timestamp_ms']>=day_start]
    day_fees=sum((D(f['fee']) for f in today_fills),D(0))
    day_funding=sum((D(f['cashflow']) for f in today_funding),D(0))
    day_net=(str(sum((D(f['closed_pnl']) for f in today_fills),D(0))-day_fees+day_funding)
        if all(f.get('closed_pnl') is not None for f in today_fills) else None)
    flat=(len(audit['final_readbacks'])==2 and all(r['ready'] and not r['positions'] and not r['orders'] for r in audit['final_readbacks'])
        and audit['final_readbacks'][0]['observed_ms']<audit['final_readbacks'][1]['observed_ms'])
    receipt=json.loads((OUT/'regression_release/test_receipt.json').read_text())
    passed=receipt.get('passed') is True and receipt.get('source_hash_after')==active_source_hash(ROOT)
    automations={}
    for name in ('monitor-anchorium-three-hour-paper-run','monitor-oct16-public-quant-observer'):
        p=Path.home()/'.codex/automations'/name/'automation.toml'
        automations[name]=tomllib.loads(p.read_text()).get('status') if p.exists() else 'UNAVAILABLE'
    checks=[
        ('Old observer','PASS','Stopped cleanly; original worker/supervisor/caffeinate identities and two flat readbacks preserved in cleanup_receipt.json'),
        ('Exchange account','PASS' if flat else 'BLOCKED',f"Two authoritative readbacks at {when(audit['final_readbacks'][-1]['observed_ms'])}; flat/zero-orders verified: {flat}; snapshot ages remain explicit"),
        ('Execution bridge','PASS','Implemented and tested offline through the existing frozen strategy, central validator, SDK, management, native protection and closing reconciliation; actual exchange path NOT VERIFIED'),
        ('Native protective exit','BLOCKED','No genuine native-stop qualification. Every sampled market has one-lot notional below $10; the preserved partial-fill protection guard rejects a new entry'),
        ('LONG signal handoff','PASS','Unchanged frozen brain emits LONG from deterministic fixture candles; central provenance and risk checks receive that output'),
        ('Sequential cycles','PASS','Two complete offline LONG cycles, profitable and loss-making, with owned stop cleanup and two flat readbacks; actual repeated exchange cycles NOT VERIFIED'),
        ('Capital allocation','PASS','Runtime lot rounding, lower realistic sizes and tighter both-side BBO/L2/collateral/risk/approved ceilings enforced. Qualified actual unattended notional remains zero'),
        ('Full regression','PASS' if passed else 'IN PROGRESS',f"{receipt.get('totals',{}).get('tests','pending')} tests; final source/receipt/XML and Phase-0/freeze checks must match"),
        ('Historical proofs and persistence','PASS' if preservation_result['passed'] else 'BLOCKED','Original BUY/SELL proofs, raw UNKNOWN, verified certificate, nonce history and SQLite/checkpoint hashes checked'),
        ('Trading authorization','BLOCKED','Deferred by operator until tonight; native protection and fresh eligibility are still prerequisites. No acceptance created or old mandate reused'),
        ('Trading worker','NOT VERIFIED','Not launched, per current operator instruction; no signing service or replacement observer started'),
        ('Genuine new trades / today P&L','PASS' if not today_fills else 'BLOCKED',f"This task placed zero orders. Observed today fills: {len(today_fills)}; net {day_net}. Historical Oct15 verified net +0.050512 TEST USDPR stays separate"),
    ]
    summary=dict(created_ms=now,source_hash=active_source_hash(ROOT),status='ENGINEERING_VALIDATED_OFFLINE_ACTIVATION_BLOCKED' if passed and preservation_result['passed'] else 'ENGINEERING_VERIFICATION_IN_PROGRESS',
        operator_instruction='Fix, test and report only; do not start trading now',acceptance=[dict(requirement=r,status=s,evidence=e) for r,s,e in checks],
        regression=receipt,regression_receipt_sha256=sha(OUT/'regression_release/test_receipt.json'),
        actual_account=audit['account_final'],account_observed_ms=audit['final_readbacks'][-1]['observed_ms'],
        account_age_ms_at_report=now-audit['final_readbacks'][-1]['observed_ms'],final_readbacks=audit['final_readbacks'],
        actual_new_orders=0,actual_new_fills=0,observed_today_fills=today_fills,observed_today_funding=today_funding,
        today_net=day_net,today_fees=str(day_fees),today_funding=str(day_funding),historical_oct15_net='0.050512',
        original_buy=dict(order_id='62755970305',fill_id='800659111758533',quantity='0.0002',price='81512',fee='0.014672'),
        original_sell=dict(order_id='62805581662',fill_id='260274449763192',quantity='0.0002',price='81909',fee='0.014743'),
        native_protection_qualification='NOT_VERIFIED',actual_short='NOT_VERIFIED_DISABLED',
        actual_multi_cycle='NOT_VERIFIED',actual_high_notional='NOT_VERIFIED',
        new_mandate=None,new_acceptance=None,worker_pid=None,qualified_unattended_notional='0',
        automations=automations,supervision='No active observation or trading service; future local service depends on this Mac, app, power and internet',
        tonight_prerequisites=['Authoritative venue evidence for the subminimum native-protection behavior or a current market satisfying the unchanged partial-fill minimum guard',
            'A separately exact-approved tiny native-protection qualification with genuine opening/stop/recovery/cleanup evidence',
            'Fresh account, nonce lease, book persistence, completed-candle strategy, fee/funding and source-bound release checks',
            'New exact LONG-only mandate and genuine human approval; at most two sequential setups, one position, 1x, 0.5% trade risk and 1% daily loss ceiling',
            'Larger sizes only within independently observed entry and closing liquidity, approved bankroll and protection scope'],
        no_profit_guarantee=True,organizer_whitelist_status='UNKNOWN_NO_ORGANIZER_EVIDENCE')
    atomic_json(OUT/'release_summary.json',summary)
    atomic_json(OUT/'native_qualification_blocker.json',dict(status='BLOCKED_NOT_AN_APPROVABLE_MANDATE',source_hash=summary['source_hash'],
        reviewed_types=['Stop Market','Stop Limit'],trigger_reference='mark price',side='reduce-only SELL for actual LONG quantity',
        genuine_acceptance=False,genuine_trigger=False,new_order_authority=False,maximum_tiny_notional='25',
        existing_stop_limit_qualification='exchange/testnet_certification.py and exchange/qualification_protection.py',
        strategy_stop_market_manager='exchange/position_protection.py',
        important_scope='Daily execution uses Stop Limit with an explicit 0.5% limit. Documented Stop Market tolerance is 10%, outside the current allowance. IOC close evidence does not establish a native-stop minimum exemption',
        reason='SUB_MINIMUM_PARTIAL_FILL_EXIT_NOT_VERIFIED',markets=[dict(symbol=r['symbol'],lot=r.get('lot'),one_lot_at_bid=r.get('one_lot_at_bid')) for r in markets],
        next_action='Establish authoritative venue support for the exact small-stop behavior, or observe a market meeting the unchanged minimum guard; then prepare a separate exact tiny supervised test for human approval'))
    lines=['# Team Anchorium — LONG execution repair report','',f"Status: **{summary['status']}**. Report time: {when(now)}.",'',
        '**No trading started.** The operator asked for repairs, tests and this report, with any trading decision deferred until tonight. No new signing acceptance or executable mandate has been created.','',
        '| Requirement | Status | Evidence / limitation |','|---|---|---|']
    lines += [f'| {r} | {s} | {e} |' for r,s,e in checks]
    lines += ['', '## Engineering changes','',
        '`exchange/long_session.py` supplies a separate exact-approved TESTNET LONG adapter. `scripts/run_long_session.py` is distinct from the public observer command. It keeps global PAPER/false, requires a matching full release, native-stop evidence, an unchanged acceptance file and exact host/source/policy identities before loading the existing API signer. The original SDK transport, nonce and account leases, central compliance permits, risk checks, journal and account streams remain in the path.','',
        'The coordinator reserves an entry durably, binds its quantity and action identity, consumes attempts before HTTP, reconciles reported fills into the frozen manager, verifies exact native protection, and records actual closing cashflows/fees/funding. Two independent authoritative flat/zero-order readbacks and stop cleanup precede another cycle. Unknown or partial closing outcomes pause entries and cannot be blindly repeated. A stale cached stop receipt is refreshed before declaring lost coverage; a genuinely missing/rejected stop triggers the authorized recovery state and cannot be automatically rearmed.','',
        'The end-to-end offline venue uses a synthetic whole-unit lot worth more than $10 so that a genuinely admissible lifecycle can be tested. Actual par lot sizes are untouched and remain subject to the separate partial-fill minimum blocker. These fixture fills and stops never establish real exchange qualification.','',
        'The original recovery service now exposes an intent-view hook whose default preserves raw production UNKNOWN barriers. The isolated LONG recovery uses the existing verified nontransmission certificate view while retaining full strategy callbacks. Historical controlled-test fills remain in account truth and are excluded from the new mandate’s strategy transitions. No historical intent, certificate or nonce is erased.','',
        'Stops and targets retain the frozen VWAP/ATR formulas. Research trailing, reversal and holding-period policies remain isolated; synthetic policy comparisons do not promote an exit model. SHORT remains disabled. The session ceiling is two independent setups and one global position. No loss bound is guaranteed through a gap or failed stop.','',
        'The isolated adapter uses native **Stop Limit**, with the previously approved one-entry-ATR distance beyond the normal stop and an explicit 0.5% execution limit. Hyperliquid documents 10% tolerance for TP/SL market orders, so a Stop Market is not an approved substitute. A stop-limit can remain unfilled after a gap. Known settled residuals may use the approved reduce-only recovery path; uncertain or unresolved trigger children halt for authoritative review rather than allowing a competing order. The default generic protection manager is unchanged. Only the existing offline venue fixture gained a default-preserving order-type option.','',
        'The actual builder requires source-bound native Stop Limit trigger/closing evidence. Acceptance of an untriggered order alone is recorded as untriggered, not as proven trigger execution. The existing Stop Limit qualification infrastructure is reused. Actual fees, funding and reward/risk are recalculated in the fresh central entry preflight; a later funding spike cannot use an older risk approval. Native qualification is still a genuine prerequisite.','',
        '## Current recorded market capacity','',f"Bounded audit: {when(audit['started_ms'])} to {when(audit['finished_ms'])}; three samples per market. Account snapshot age at report: {summary['account_age_ms_at_report']/1000:.1f} seconds. Quotes must be read again before any later proposal.",'',
        '| Market | LONG min–max | Latest LONG | SHORT min–max | One lot at bid | All samples support 1,000? |','|---|---:|---:|---:|---:|---|']
    for r in markets:
        if r.get('status')=='FAILED_SAFE':continue
        f=lambda v:f'{D(v):.4f}'
        lines.append(f"| {r['symbol']} | {f(r['long_capacity_min'])}–{f(r['long_capacity_max'])} | {f(r['long_capacity_last'])} | {f(r['short_capacity_min'])}–{f(r['short_capacity_max'])} | {f(r['one_lot_at_bid'])} | {r['supports_1000_in_every_sample']} |")
    lines += ['', 'Values are TEST USDPR bounds from the displayed book under 10% of BOTH best levels and finite L2 limits, runtime max trade size and available collateral. They are neither fills nor safe approved sizes. A fleeting larger quote does not prove persistent entry and closing capacity. Full level data, lot precision, runtime sizes, estimated costs/funding, explicit cache ages and all 1,000/2,500/5,000/10,000/25,000/50,000 tiers are in `liquidity_capacity.json`. Unsupported full-size fill costs, strategy stop risk and liquidation price remain unavailable rather than extrapolated.','',
        'Signal explanations describe recorded frames. The audit caches its initially read completed bars and reports their ages; a late stale-bar rejection does not prove that a freshly refetched candle would also be stale. The execution scanner refetches completed bars and retains the original warmup, gap and freshness checks. No live qualifying setup is certified by this report.','',
        'Every market in this capture has a smallest runtime lot below the ordinary $10 order minimum. A valid total entry above $10 may still partially fill one lot; the existing guard therefore requires independently established native-protection/remaining-close behavior. No general stop exemption has been established for this registered account and DEX. The ordinary minimum and both-side liquidity guards are unchanged. Approved bankroll and actual qualified unattended notional remain **zero**.','',
        'The conservative fee bound is six times the reported base fee when current deployer scale is unavailable; this is an estimate, not the actual charged fee. Actual fees and funding come only from exchange account events. Current funding is not a forecast. The sampled adverse price range does not estimate the worst possible gap or stop loss.','',
        '## Actual accounting and preserved evidence','',
        f"Reported account equity/collateral: {audit['account_final']['reported_account_equity']['reported_account_value']} TEST USDPR, margin used {audit['account_final']['reported_account_equity']['margin_used']}. That balance is not an approved bankroll. The final two public readbacks show zero positions and zero open orders as of their recorded times.",'',
        f"Today’s observed fills: {len(today_fills)}; actual fees {day_fees}; funding {day_funding}; realized net {day_net} TEST USDPR. This task placed no orders. Historical October 15: BUY 62755970305 / fill 800659111758533 at 81,512; SELL 62805581662 / fill 260274449763192 at 81,909; quantity 0.0002 BTC; gross +0.0794; entry fee 0.014672; exit fee 0.014743; actual funding +0.000527; net **+0.050512 TEST USDPR**. This is not today’s trading profit or an organizer score. Original proof files remain untouched.",'',
        f"Preservation passed: {preservation_result['passed']}. Both SQLite integrity checks, recovery checksum validation, the repaired historical certificate, raw UNKNOWN preservation and nonce history are recorded in `preservation_verification.json`.",'',
        '## Release verification','',f"Final source: `{summary['source_hash']}`.",f"Full regression: `{receipt.get('totals','RUNNING')}`; matching final receipt passed: **{passed}**.",f"Receipt SHA-256: `{summary['regression_receipt_sha256']}`.",f"XML SHA-256: `{receipt.get('xml_sha256','PENDING')}`.",'',
        'The earlier 2,539-test run is preserved separately as a valid superseded engineering snapshot. Final release checks cover the later safety review fixes; no actual-wallet signature is generated by these offline tests. Freeze and Phase-0 are checked before and after the full suite. A passing test suite does not certify native venue execution or guarantee that software has no undiscovered defects.','',
        '## Conditions for tonight','',
        '1. Resolve the exact native-protection minimum/partial-fill prerequisite using authoritative venue evidence or a market satisfying the unchanged guard. Do not open exposure merely to bypass it.',
        '2. Prepare and explicitly approve a separate tiny controlled native test covering opening exposure, stop identity, loss-making emergency recovery and cleanup. Record an untriggered stop honestly if no genuine trigger occurs.',
        '3. After qualification, collect fresh account/market/fee/funding/clock/rate/nonce/source evidence and a valid frozen LONG setup. Recalculate the supported size; do not force a 1,000+ order.',
        '4. Present a new exact LONG-only multi-entry mandate with the verified proof and release hashes, operator bankroll, position/cumulative limits and loss-exit acknowledgments. No approval is requested now.',
        '5. Only after genuine exact approval, launch and verify the execution-enabled process and its supervision. No auto-start, extension or next-day renewal is authorized. Hard day limit in this release: 23:57 IST, October 16.','',
        'Both previous heartbeat schedules remain paused. No replacement observer or trading worker has been launched. Local operation and supervision depend on this Mac, the app, power and internet. A native stop does not guarantee a complete fill. Organizer whitelist/reset status is unknown without organizer evidence.','',
        '## Primary venue references','',
        '- [Participant guide — runtime precision, minimum and IOC/trigger rules](https://perpetual-alpha26.github.io/docs/)',
        '- [Hyperliquid TP/SL semantics](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)',
        '- [Hyperliquid order rejection definitions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses)','']
    (OUT/'implementation_report.md').write_text('\n'.join(lines))
    print(json.dumps(dict(source_hash=summary['source_hash'],status=summary['status'],regression_passed=passed,
        preservation_passed=preservation_result['passed'],actual_new_orders=0,report=str(OUT/'implementation_report.md'))))

if __name__=='__main__':main()
