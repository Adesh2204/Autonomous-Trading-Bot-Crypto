"""Reproducible high-capital matrix with explicit evidence domains and no signer."""
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal as D
from pathlib import Path
import hashlib,json,math
from exchange.base_exchange import MarketSpec,OrderBook,BookLevel,ExchangeError
from exchange.capital_allocation import CapitalLimits,allocate,floor_quantity,depth_capacity
from exchange.quant_observation import restore_market,explain_market,rank_reports
from exchange.paper_operations import active_source_hash,atomic_json
from .quant_exits import ExitPolicy,POLICIES,episode,summarize

TIERS=(1000,2500,5000,10000,25000,50000)
REGIMES=('BULL','BEAR','SIDEWAYS','LOW_VOL','HIGH_VOL','SHARP_REVERSAL','LIQUIDITY_FAILURE','GAP')


def synthetic_path(regime, *, start_ms=1792108800000, steps=121):
    """Declared synthetic sensitivity inputs; never labelled market observations."""
    if regime not in REGIMES:raise ExchangeError('UNKNOWN_STRESS_REGIME')
    result=[];fast=slow=100.;prior_vwap=100.;running=0.
    for i in range(steps):
        if regime=='BULL':price=D(100)+D(i)*D('.08')
        elif regime=='BEAR':price=D(100)-D(i)*D('.08')
        elif regime=='LOW_VOL':price=D(100)+D(str(math.sin(i/9)))*D('.015')
        elif regime=='SIDEWAYS':price=D(100)+D(str(math.sin(i/5)))*D('.35')
        elif regime=='HIGH_VOL':price=D(100)+D(str(math.sin(i/2)))*D('2.5')
        elif regime=='SHARP_REVERSAL':price=D(100)+D(min(i,25))*D('.1')-D(max(0,i-25))*D('.22')
        elif regime=='GAP':price=D(100)+D(i)*D('.02')-(D(12) if i>=20 else D(0))
        else:price=D(100)+D(i)*D('.04')-(D(3) if i>=30 else D(0))
        at=start_ms+i*60000;quantity=D('.2') if regime=='LIQUIDITY_FAILURE' and i>=30 else D('10000')
        bids=tuple(BookLevel(price-D('.01')-D(j)*D('.01'),quantity/D(j+1)) for j in range(5))
        asks=tuple(BookLevel(price+D('.01')+D(j)*D('.01'),quantity/D(j+1)) for j in range(5))
        fast=fast*.8+float(price)*.2;slow=slow*(20/22)+float(price)*(2/22)
        running+=float(price);vwap=running/(i+1);slope=vwap-prior_vwap;prior_vwap=vwap
        result.append(dict(at_ms=at,book=OrderBook('par:BTC',at,bids,asks,at,at),
            mark=price,oracle=price,atr=D('.5'),hourly_funding=D('.0000125'),
            ema9=D(str(fast)),ema21=D(str(slow)),vwap_slope=D(str(slope)),features_available_ms=at,
            source='SYNTHETIC_STRESS_NOT_EXCHANGE_DATA'))
    return result


def size_matrix(snapshot):
    rows=[];signals=[]
    equity=D(snapshot['account']['reported_account_equity']['reported_account_value'])
    base_fee=D(snapshot['fees']['userCrossRate']);scale=snapshot.get('deployer_fee_scale')
    fee=base_fee*(6 if scale is None else 1+D(str(scale)) if D(str(scale))<1 else 2*D(str(scale)))
    for symbol,row in sorted(snapshot['markets'].items()):
        if row['status']!='OBSERVED':continue
        spec,book,candles=restore_market(row);now=row['observed_ms']
        signal=explain_market(spec,book,candles,row['context'],now_ms=now,
            context_ms=row['context_observed_ms'],fee_rate=fee);signals.append(signal)
        for direction,side in (('LONG','BUY'),('SHORT','SELL')):
            entry=depth_capacity(book,side);close=depth_capacity(book,'SELL' if side=='BUY' else 'BUY')
            cap=floor_quantity(spec,min(entry['best_quantity'],close['best_quantity'],
                entry['raw_l2_quantity'],close['raw_l2_quantity'])*D('.1'))
            best=entry['best_price'];active=row['active_asset'];free=min(D(x) for x in active['availableToTrade'])
            # Capacity is observable even if candle gaps prevent a strategy ATR.
            atr=signal.get('metrics',{}).get('atr')
            for target in TIERS:
                requested=floor_quantity(spec,D(target)/best)
                capacity=cap*best
                r=dict(symbol=symbol,direction=direction,target_notional=target,requested_quantity=requested,
                    observed_ms=now,route='BASELINE_10_PERCENT_BOTH_BEST_LEVELS',
                    liquidity_capacity_quantity=cap,liquidity_capacity_notional=capacity,
                    target_supported_by_current_liquidity=requested>0 and requested<=cap,
                    depth_participation='0.1',free_collateral_observed=free,account_equity=equity,
                    approved_bankroll=None,unattended_execution_qualified_notional=D(0),
                    genuine_order_authorized=False,risk_sizing=None)
                if atr and active.get('leverage')=={'type':'cross','value':1}:
                    stop=best-(D(1) if side=='BUY' else D(-1))*D(2)*atr
                    if stop>0:
                        r['risk_sizing']=allocate(spec,book,side,stop,
                            CapitalLimits(min(equity,D(1000000)),D(target),D(target),D(target)*2),
                            now_ms=now,free_collateral=free,equity=equity,entry_fee=fee,exit_fee=fee,
                            maximum_trade_quantity=active['maxTradeSzs'][0 if side=='BUY' else 1],
                            funding_cost_per_unit=abs(D(row['context']['funding']))*D(row['context']['oraclePx']))
                r['risk_note']='Research capital assumptions only; missing ATR/gapped data stays unavailable'
                rows.append(r)
    return rows,rank_reports(signals)


def historical_capacity(tape,expected_sha,*,maximum_frames=1000):
    """Inspect preserved actual L2 tape, without treating it as strategy labels."""
    tape=Path(tape);actual=hashlib.sha256(tape.read_bytes()).hexdigest()
    if actual!=expected_sha:raise ExchangeError('HISTORICAL_L2_TAPE_CHANGED')
    samples=[];last=-60000;count=0;first=None;end=None
    with tape.open() as f:
        for line in f:
            r=json.loads(line);count+=1
            if not r.get('fresh_book') or not r.get('book_depth'):continue
            at=r['at_ms'];first=at if first is None else first;end=at
            if at-last<60000 or len(samples)>=maximum_frames:continue
            if not 0<=at-r['book_exchange_ms']<=5000:continue
            b=r['book_depth'];bid=D(b['bids'][0]['price']);ask=D(b['asks'][0]['price'])
            cap=(min(D(b['bids'][0]['quantity']),D(b['asks'][0]['quantity']))*D('.1')).quantize(D('.0001'),rounding='ROUND_DOWN')
            samples.append(dict(at_ms=at,bid=bid,ask=ask,maximum_long_notional=cap*ask,
                maximum_short_notional=cap*bid,quantity=cap));last=at
    return dict(source='PRESERVED_PUBLIC_PAR_BTC_L2_OBSERVATION_TAPE',sha256=actual,
        tape_rows=count,first_ms=first,last_ms=end,sampled_frames=len(samples),samples=samples,
        size_tiers={str(t):dict(frames_supporting_full_long=sum(s['maximum_long_notional']>=t for s in samples),
            frames_supporting_full_short=sum(s['maximum_short_notional']>=t for s in samples)) for t in TIERS},
        strategy_backtest_status='NOT_A_STRATEGY_BACKTEST; no as-of signal/complete funding labels',
        hypothetical_pnl=None,exchange_fills_inferred_from_candles=0)


def run_campaign(snapshot_path,output,*,historical_tape=None,historical_sha=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    snapshot=json.loads(Path(snapshot_path).read_text());matrix,signals=size_matrix(snapshot)
    spec=MarketSpec('par:BTC',4,40,2670000)  # Explicit synthetic fixture contract only.
    details=[]
    for regime in REGIMES:
        path=synthetic_path(regime)
        for tier in TIERS:
            for direction in ('LONG','SHORT'):
                for policy in POLICIES:
                    item=episode(spec,path,direction,tier,ExitPolicy(policy))
                    item.update(regime=regime,input_domain='SYNTHETIC_SCENARIO',fit_policy='PRESPECIFIED_NO_PARAMETER_SELECTION')
                    details.append(item)
    faults=[]
    for tier in TIERS:
        for direction in ('LONG','SHORT'):
            for fault in ('rejected_entry','unknown_entry','unknown_exit','rejected_exit','partial_exit','stop_rejected'):
                item=episode(spec,synthetic_path('BULL'),direction,tier,ExitPolicy('TIME'),fault=fault)
                item.update(fault=fault,input_domain='SYNTHETIC_FAILURE_SCENARIO');faults.append(item)
    grouped={}
    for tier in TIERS:
        grouped[str(tier)]={direction:{p:summarize([r for r in details if r['target_notional']==str(tier)
            and r['direction']==direction and r['exit_policy']==p]) for p in POLICIES} for direction in ('LONG','SHORT')}
    historical=historical_capacity(historical_tape,historical_sha) if historical_tape else None
    from strategy_freeze import verify_strategy_freeze
    verify_strategy_freeze()
    source=active_source_hash(Path(__file__).resolve().parents[2])
    report=dict(source_hash=source,source_snapshot_sha256=hashlib.sha256(Path(snapshot_path).read_bytes()).hexdigest(),
        source_snapshot=str(Path(snapshot_path).resolve()),size_tiers=TIERS,market_capacity_matrix=matrix,
        signal_reports=signals,synthetic_exit_comparison=grouped,synthetic_episodes=len(details),
        synthetic_fault_episodes=len(faults),historical_l2=historical,
        actual_exchange_account=snapshot['account'],actual_account_observed_ms=snapshot['account_observed_ms'],
        genuine_execution_qualified_notional='0',
        research_readiness=dict(status='MORE_REPRESENTATIVE_AS_OF_DATA_REQUIRED',
            chronological_policy='PRESPECIFIED_POLICIES; no fit or selection on the evaluation set',
            prospective_walk_forward_required=True,unseen_holdout_consumed_for_tuning=False,
            sharpe=None,sortino=None,statistical_confidence=None,
            reasons=['Sparse local captured L2 history is not a multi-regime strategy-performance dataset',
                'Synthetic scenarios are sensitivity tests, not out-of-sample market profitability',
                'No SHORT or native-stop exchange qualification exists',
                'No automatic strategy or capital promotion']),
        actual_exchange_orders_submitted=0,production_strategy_changed=False)
    atomic_json(output/'capital_and_exit_report.json',report)
    atomic_json(output/'synthetic_episode_details.json',details)
    atomic_json(output/'synthetic_fault_details.json',faults)
    lines=['# Capital and exit research — isolated development evidence','',
        'All 1k–50k figures below are virtual targets. No exchange orders were submitted. Production strategy and route limits are unchanged.','',
        '| Market | LONG raw liquidity capacity | SHORT raw liquidity capacity | 1000 target supported |','|---|---:|---:|---|']
    for symbol in sorted(snapshot['markets']):
        rows=[r for r in matrix if r['symbol']==symbol and r['target_notional']==1000]
        if len(rows)==2:lines.append(f"| {symbol} | {rows[0]['liquidity_capacity_notional']} | {rows[1]['liquidity_capacity_notional']} | {all(r['target_supported_by_current_liquidity'] for r in rows)} |")
    lines+=['','Capacity is a timestamped displayed-book bound, not a guarantee or current authorization. Both directions retain 10% of BOTH best levels plus the tighter in-bound L2 capacity. Qualified unattended genuine notional is **0** until exchange protection, direction qualification and exact session authorization exist.','',
        '## Synthetic stress results','',
        '| Target | Direction | Exit method | Closed scenarios | Net scenario sum | Unresolved scenarios |','|---:|---|---|---:|---:|---:|']
    for tier,directions in grouped.items():
        for direction,policies in directions.items():
            for name,s in policies.items():lines.append(f"| {tier} | {direction} | {name} | {s['completed_simulated_trades']} | {s['net_pnl']} | {s['unresolved']} |")
    lines+=['','These sums compare separate synthetic scenarios; they are not one investable portfolio, exchange P&L or evidence of strategy edge. Full episode records include finite-depth fills, costs, prospective funding assumptions, intended risk overruns, MAE/MFE, margin buffers, drawdown availability and unresolved exposure.','',
        '## Research limits','',
        'No policy is promoted. Real multi-market/multi-regime chronological walk-forward evidence is insufficient; Sharpe, Sortino and calibrated confidence remain null. Historical OHLC is never used to invent an execution. The preserved Oct15 L2 tape is used for size-capacity evidence only; causal signal and complete prospective funding labels are absent.','',
        f'Synthetic policy episodes: {len(details)}; separate fault episodes: {len(faults)}. Actual orders submitted by this research: 0. Source: `{source}`.']
    (output/'capital_stress_report.md').write_text('\n'.join(lines)+'\n')
    return report
