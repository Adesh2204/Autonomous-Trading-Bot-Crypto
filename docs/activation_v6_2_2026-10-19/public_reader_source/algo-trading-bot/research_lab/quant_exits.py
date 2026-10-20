"""Prespecified, isolated exit experiments on timestamped displayed L2 only.

No production strategy imports, SDK, signer, network or promotion operation.
These policies are research adaptations, not changes to frozen production exits.
"""
from dataclasses import dataclass
from decimal import Decimal as D
import math
from exchange.base_exchange import ExchangeError, decimal
from exchange.capital_allocation import validate_book, floor_quantity, walk_book, depth_capacity

POLICIES=('FIXED_RR','ATR_ADAPTIVE','TRAILING','MOMENTUM','TIME','PARTIAL')


@dataclass(frozen=True)
class ExitPolicy:
    name: str
    stop_atr: D=D('2')
    reward_risk: D=D('2')
    activation_atr: D=D('1')
    trail_atr: D=D('1')
    maximum_holding_ms: int=3600000
    minimum_trailing_net: D=D('.001')

    def __post_init__(self):
        if self.name not in POLICIES:raise ExchangeError('UNKNOWN_RESEARCH_EXIT_POLICY')
        for n in ('stop_atr','reward_risk','activation_atr','trail_atr'):
            object.__setattr__(self,n,decimal(getattr(self,n),positive=True))
        object.__setattr__(self,'minimum_trailing_net',decimal(self.minimum_trailing_net,nonnegative=True))
        if type(self.maximum_holding_ms) is not int or not 60000<=self.maximum_holding_ms<=14400000:
            raise ExchangeError('BOUNDED_RESEARCH_HOLDING_TIME_REQUIRED')


def decision(policy, *, direction, entry, current, mark, atr, initial_atr, peak,
             age_ms, quantity, entry_fee_per_unit, fee_rate, ema9=None, ema21=None,
             vwap_slope=None, partial_done=False):
    """Use only current/past observations; risk exits are permitted at a loss."""
    sign=D(1) if direction=='LONG' else D(-1)
    if direction not in {'LONG','SHORT'}:raise ExchangeError('RESEARCH_DIRECTION_REQUIRED')
    stop=entry-sign*policy.stop_atr*initial_atr
    favorable=sign*(current-entry)
    peak_favorable=max(peak,favorable)
    if sign*(mark-stop)<=0 or sign*(current-stop)<=0:return 'RISK_STOP',D(1),peak_favorable
    if age_ms>=policy.maximum_holding_ms:return 'MAXIMUM_HOLDING_TIME',D(1),peak_favorable
    target=policy.stop_atr*initial_atr*policy.reward_risk
    if policy.name=='FIXED_RR' and favorable>=target:return 'FIXED_TARGET',D(1),peak_favorable
    if policy.name=='ATR_ADAPTIVE' and favorable>=max(initial_atr,atr)*D(3):
        return 'ATR_TARGET',D(1),peak_favorable
    if policy.name=='MOMENTUM' and ema9 is not None and ema21 is not None and vwap_slope is not None:
        if sign*(ema9-ema21)<0 and sign*vwap_slope<0:return 'TWO_FACTOR_MOMENTUM_WEAKENING',D(1),peak_favorable
    if policy.name=='PARTIAL' and not partial_done and favorable>=D(2)*initial_atr:
        return 'PLANNED_PARTIAL_PROFIT',D('.5'),peak_favorable
    if policy.name in {'TRAILING','PARTIAL'} and peak_favorable>=policy.activation_atr*initial_atr:
        trail=peak_favorable-policy.trail_atr*max(initial_atr,atr)
        net_per_unit=favorable-entry_fee_per_unit-current*fee_rate
        if favorable<=trail and net_per_unit*quantity>=policy.minimum_trailing_net:
            return 'FEE_AWARE_TRAILING',D(1),peak_favorable
    return None,D(0),peak_favorable


def episode(spec, observations, direction, target_notional, policy, *, fee_rate=D('.0027'),
            bankroll=D('1000000'), entry_fraction=D(1), fault=None):
    """A hypothetical finite-book episode; every fill is explicitly simulated.

    Oversized targets are rejected rather than shrunk into a falsely successful
    size test. Expected partial exits are distinct from unexpected partial IOC
    execution, which halts in RECOVERY_REQUIRED without another attempt.
    """
    if not observations:raise ExchangeError('RESEARCH_OBSERVATIONS_REQUIRED')
    if direction not in {'LONG','SHORT'}:raise ExchangeError('RESEARCH_DIRECTION_REQUIRED')
    fee_rate=decimal(fee_rate,nonnegative=True);target_notional=decimal(target_notional,positive=True)
    bankroll=decimal(bankroll,positive=True);entry_fraction=decimal(entry_fraction,nonnegative=True)
    if fee_rate>D('.003') or entry_fraction>1:raise ExchangeError('RESEARCH_COST_OR_FILL_FRACTION_INVALID')
    previous=-1
    for row in observations:
        if type(row['at_ms']) is not int or row['at_ms']<=previous:raise ExchangeError('RESEARCH_CHRONOLOGY_REQUIRED')
        previous=row['at_ms'];validate_book(row['book'],row['at_ms'])
        if row['book'].symbol!=spec.symbol:raise ExchangeError('RESEARCH_BOOK_IDENTITY_MISMATCH')
        if row.get('features_available_ms',row['at_ms'])>row['at_ms']:
            raise ExchangeError('FUTURE_RESEARCH_FEATURES_PROHIBITED')
    first=observations[0];opening='BUY' if direction=='LONG' else 'SELL'
    closing='SELL' if direction=='LONG' else 'BUY';sign=D(1) if direction=='LONG' else D(-1)
    reference=(first['book'].asks if opening=='BUY' else first['book'].bids)[0].price
    q=floor_quantity(spec,target_notional/reference)
    result=dict(direction=direction,target_notional=str(target_notional),exit_policy=policy.name,
        evidence_scope='HYPOTHETICAL_L2_REPLAY_NOT_EXCHANGE_EXECUTION',fills=[],funding=D(0),
        target_quantity=q,entry_notional=D(0),realized_net=None,remaining_quantity=D(0),
        entry_slippage_bps=None,exit_slippage_bps=None,mae=None,mfe=None,
        max_drawdown=None,sharpe=None,sortino=None,liquidation_price=None,
        liquidation_note='Cross-margin liquidation price cannot be inferred from sparse L2 snapshots',
        maximum_margin_used=D(0),minimum_maintenance_buffer=None,holding_ms=0,
        exchange_orders_submitted=0,statistical_confidence=None)
    cap=min(first['book'].bids[0].quantity,first['book'].asks[0].quantity)*D('.1')
    if not q or q*reference<10 or q>floor_quantity(spec,cap):
        return dict(result,status='ENTRY_CAPACITY_BLOCKED',capacity_quantity=floor_quantity(spec,cap))
    if q*reference*(1+2*fee_rate)>bankroll*D('.5'):
        return dict(result,status='ENTRY_MARGIN_BLOCKED')
    if fault=='rejected_entry':return dict(result,status='REJECTED',entry_attempts=1)
    if fault=='unknown_entry':return dict(result,status='UNKNOWN',entry_attempts=1,remaining_quantity=None)
    requested=floor_quantity(spec,q*entry_fraction)
    entry_walk=walk_book(first['book'],opening,requested,
        limit=depth_capacity(first['book'],opening)['limit'],participation=D('.1'))
    qty=floor_quantity(spec,entry_walk['filled_quantity'])
    if not qty:return dict(result,status='ENTRY_UNFILLED',entry_attempts=1)
    entry_walk=walk_book(first['book'],opening,qty,
        limit=depth_capacity(first['book'],opening)['limit'],participation=D('.1'))
    entry=entry_walk['vwap'];entry_fee=qty*entry*fee_rate;remaining=qty
    gross=exit_fees=D(0);peak=D(0);partial_done=False;exit_attempts=0;last_time=first['at_ms']
    entry_atr=decimal(first['atr'],positive=True);equity_path=[];excursions=[];exit_slips=[]
    result['entry_notional']=qty*entry
    result['entry_slippage_bps']=sign*(entry-reference)/reference*10000
    result['fills'].append(dict(side=opening,quantity=qty,price=entry,fee=entry_fee,at_ms=first['at_ms'],
        source='SIMULATED_FINITE_L2_FILL',reduce_only=False))
    status='END_OF_REPLAY_OPEN'
    for index,row in enumerate(observations[1:],1):
        book=row['book'];at=row['at_ms'];price=(book.bids if closing=='SELL' else book.asks)[0].price
        # Prospective rate must have been observed BEFORE the interval begins;
        # no account cashflow from a different size is rescaled into a real fill.
        prior=observations[index-1]
        if 'hourly_funding' not in prior:raise ExchangeError('OBSERVED_FUNDING_RATE_REQUIRED')
        rate=decimal(prior['hourly_funding']);oracle=decimal(prior['oracle'],positive=True)
        exit_rate=decimal(row.get('taker_fee',fee_rate),nonnegative=True)
        if exit_rate>D('.003'):raise ExchangeError('RESEARCH_COST_OR_FILL_FRACTION_INVALID')
        result['funding']+=-sign*remaining*oracle*rate*D(at-last_time)/D(3600000)
        last_time=at
        favorable=sign*(price-entry);excursions.append(favorable)
        mark=decimal(row['mark'],positive=True)
        margin=remaining*mark;maintenance=spec.maintenance_margin(margin)
        account_equity=bankroll+gross+sign*remaining*(mark-entry)-entry_fee-exit_fees+result['funding']
        buffer=account_equity-maintenance
        result['maximum_margin_used']=max(result['maximum_margin_used'],margin)
        result['minimum_maintenance_buffer']=min(buffer,result['minimum_maintenance_buffer']) if result['minimum_maintenance_buffer'] is not None else buffer
        liquidation=walk_book(book,closing,remaining,limit=depth_capacity(book,closing)['limit'],participation=D('.1'))
        estimated=gross+sign*remaining*(liquidation['vwap']-entry)-entry_fee-exit_fees-remaining*liquidation['vwap']*exit_rate+result['funding'] if liquidation['full_fill'] else None
        equity_path.append(estimated)
        reason,fraction,peak=decision(policy,direction=direction,entry=entry,current=price,mark=mark,
            atr=decimal(row['atr'],positive=True),initial_atr=entry_atr,peak=peak,age_ms=at-first['at_ms'],
            quantity=remaining,entry_fee_per_unit=entry_fee/qty,fee_rate=exit_rate,
            ema9=row.get('ema9'),ema21=row.get('ema21'),vwap_slope=row.get('vwap_slope'),partial_done=partial_done)
        if buffer<=0:reason,fraction='MARGIN_FAILURE_STRESS',D(1)
        if not reason:continue
        requested=floor_quantity(spec,remaining*fraction)
        if fraction<D(1) and (not requested or min(requested,remaining-requested)*price<10):
            continue  # Cannot fabricate a sub-minimum partial or resize a stop.
        exit_attempts+=1
        if fault=='unknown_exit':status='UNKNOWN';remaining=None;break
        if fault in {'rejected_exit','stop_rejected'}:status='UNPROTECTED_EXPOSURE';break
        walked=walk_book(book,closing,requested,limit=depth_capacity(book,closing)['limit'],participation=D('.1'))
        filled=floor_quantity(spec,walked['filled_quantity'])
        if fault=='partial_exit':filled=floor_quantity(spec,filled/D(2))
        if filled:
            exact=walk_book(book,closing,filled,limit=depth_capacity(book,closing)['limit'],participation=D('.1'))
            px=exact['vwap'];fee=filled*px*exit_rate
            result['fills'].append(dict(side=closing,quantity=filled,price=px,fee=fee,at_ms=at,
                source='SIMULATED_FINITE_L2_FILL',reduce_only=True,reason=reason))
            gross+=sign*filled*(px-entry);exit_fees+=fee;remaining-=filled
            exit_slips.append(-sign*(px-price)/price*10000)
        if filled<requested:status='RECOVERY_REQUIRED';break
        if not remaining:status='SIMULATED_CLOSED';break
        partial_done=True
    result.update(status=status,remaining_quantity=remaining,entry_attempts=1,exit_attempts=exit_attempts,
        entry_fee=entry_fee,exit_fee=exit_fees,gross_pnl=gross,holding_ms=last_time-first['at_ms'],
        funding_model='PRO_RATA_PRIOR_OBSERVED_RATE_SCENARIO_ESTIMATE_NOT_ACTUAL_ACCOUNT_CASHFLOW',
        mae=min(excursions) if excursions else None,mfe=max(excursions) if excursions else None,
        excursion_units='TEST_USDPR_PRICE_PER_BTC_OR_RUNTIME_CONTRACT_UNIT',
        maximum_adverse_pnl=qty*min(D(0),min(excursions)) if excursions else None,
        maximum_favorable_pnl=qty*max(D(0),max(excursions)) if excursions else None,
        exit_slippage_bps=sum(exit_slips)/len(exit_slips) if exit_slips else None,
        net_return_on_target=None,profit_capture=None,
        portfolio_path_complete=bool(equity_path) and all(x is not None for x in equity_path))
    if status=='SIMULATED_CLOSED':
        result['realized_net']=gross-entry_fee-exit_fees+result['funding']
        result['net_return_on_target']=result['realized_net']/target_notional
        if excursions and max(excursions)>0:result['profit_capture']=result['realized_net']/(qty*max(excursions))
    if result['portfolio_path_complete']:
        high=D(0);dd=D(0)
        for value in equity_path:high=max(high,value);dd=max(dd,high-value)
        result['max_drawdown']=dd
    result['tail_loss_exceeds_intended_stop']=bool(result['realized_net'] is not None and
        -result['realized_net']>qty*policy.stop_atr*entry_atr)
    return result


def summarize(rows):
    closed=[x for x in rows if x.get('status')=='SIMULATED_CLOSED']
    nets=[D(x['realized_net']) for x in closed];wins=[x for x in nets if x>0];losses=[x for x in nets if x<0]
    ordered=sorted(nets);tail=ordered[:max(1,math.ceil(len(ordered)*.05))]
    return dict(episodes=len(rows),completed_simulated_trades=len(closed),
        blocked=sum(x['status'].endswith('BLOCKED') for x in rows),
        unresolved=sum(x['status'] in {'UNKNOWN','RECOVERY_REQUIRED','UNPROTECTED_EXPOSURE','END_OF_REPLAY_OPEN'} for x in rows),
        net_pnl=sum(nets,D(0)),win_rate=D(len(wins))/len(nets) if nets else None,
        average_win=sum(wins,D(0))/len(wins) if wins else None,
        average_loss=sum(losses,D(0))/len(losses) if losses else None,
        expectancy=sum(nets,D(0))/len(nets) if nets else None,
        profit_factor=sum(wins,D(0))/-sum(losses,D(0)) if losses else None,
        expected_shortfall_5pct=sum(tail,D(0))/len(tail) if tail else None,
        sharpe=None,sortino=None,uncertainty='No calibrated confidence or annualized ratios from short dependent stress scenarios',
        exchange_execution_proven=False)
