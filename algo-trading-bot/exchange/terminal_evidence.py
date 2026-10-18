"""Unsigned operator diagnostics. No function here creates trading authority."""
from decimal import Decimal as D
from pathlib import Path
import sqlite3

from .base_exchange import ExchangeError, decimal
from .capital_allocation import validate_book, depth_capacity, floor_quantity


def local_execution_state(root):
    """Read the real intent barrier without opening/migrating a trading journal."""
    result=dict(status='UNKNOWN',unresolved=[],native_protection='UNQUALIFIED',signing_authority='NONE')
    try:
        for name in ('certification','qualification','pas'):
            p=Path(root)/'runtime/testnet/anchorium-bot-1'/(name+'.sqlite')
            if not p.exists():continue
            with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ExchangeError('TRADING_JOURNAL_INTEGRITY_FAILED')
                if name=='qualification':
                    from .qualification_intent_recovery import effective_rows
                    rows=effective_rows(db)
                else:
                    names=[x[1] for x in db.execute('PRAGMA table_info(intents)')]
                    rows=[dict(zip(names,r)) for r in db.execute('SELECT * FROM intents')]
                result['unresolved'] += [dict(journal=name,cloid=r['cloid'],state=r['state'],
                    intent_key=r['intent_key']) for r in rows if r['state'] not in {'FILLED','CANCELLED','REJECTED','EXPIRED'}]
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='signed_management'").fetchone():
                    result['unresolved'] += [dict(journal=name,management_id=i,state=state)
                        for i,state in db.execute("SELECT id,state FROM signed_management WHERE state='UNKNOWN'")]
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='intent_audit'").fetchone():
                    result.setdefault('dispatch_evidence',[]).extend(dict(journal=name,stage=stage,observed_ms=at)
                        for stage,at in db.execute('SELECT stage,timestamp_ms FROM intent_audit ORDER BY seq DESC LIMIT 12'))
        result['status']='BLOCKED_UNRESOLVED_INTENT' if result['unresolved'] else 'NO_LOCAL_UNRESOLVED_INTENT'
    except (OSError,sqlite3.Error,ExchangeError,ValueError) as exc:
        result.update(status='UNKNOWN_REQUIRES_REVIEW',error=type(exc).__name__)
    return result


def opportunity_capacity(spec,book,active,row,*,now_ms,active_ms,fee_rate,fee_ms,maker_fee_rate=None):
    """Independent two-sided upper bound; a target scenario is not expected P&L."""
    result=dict(symbol=spec.symbol,liquidity_only_quantity='0',liquidity_only_notional='0',
        economically_viable_notional='0',authorized_executable_notional='0',expected_net_pnl=None,
        expected_return_probability=None,decision='OBSERVE',reasons=[],observed_ms=now_ms)
    try:
        if book.symbol!=spec.symbol:raise ExchangeError('CAPACITY_VENUE_MARKET_IDENTITY_MISMATCH')
        validate_book(book,now_ms)
        if not 0<=now_ms-active_ms<=5000:raise ExchangeError('ACTIVE_ACCOUNT_LIMITS_STALE')
        if fee_ms is None or not 0<=now_ms-fee_ms<=360000:raise ExchangeError('FEE_OBSERVATION_STALE')
        fee=decimal(fee_rate,nonnegative=True)
        if fee>D('.003'):raise ExchangeError('FEE_BOUND_EXCEEDED')
        if active.get('leverage')!={'type':'cross','value':1}:raise ExchangeError('ONE_X_CROSS_REQUIRED')
        buy,sell=depth_capacity(book,'BUY'),depth_capacity(book,'SELL')
        limits=dict(entry_bbo=buy['best_quantity']*D('.1'),exit_bbo=sell['best_quantity']*D('.1'),
            entry_five_bps=buy['raw_l2_quantity']*D('.1'),exit_five_bps=sell['raw_l2_quantity']*D('.1'),
            account=decimal(active['maxTradeSzs'][0],nonnegative=True),
            margin=min(decimal(x,nonnegative=True) for x in active['availableToTrade'])/(buy['best_price']*(1+2*fee)),
            proposed_upper_cap=D(10000)/buy['best_price'])
        q=floor_quantity(spec,min(limits.values()));notional=q*buy['best_price']
        spread=(book.asks[0].price-book.bids[0].price)/((book.asks[0].price+book.bids[0].price)/2)*10000
        result.update(liquidity_only_quantity=str(q),liquidity_only_notional=str(notional),
            quantity_bounds={k:str(v) for k,v in limits.items()},spread_bps=str(spread),
            entry_capacity=str(floor_quantity(spec,min(limits['entry_bbo'],limits['entry_five_bps']))),
            exit_capacity=str(floor_quantity(spec,min(limits['exit_bbo'],limits['exit_five_bps']))),
            book_age_ms=now_ms-book.timestamp_ms,fee_age_ms=now_ms-fee_ms,
            funding_rate=str(row.get('metrics',{}).get('hourly_funding')),
            conditional_target_net=None,stressed_conditional_target_net=None)
        if notional<10:result['reasons'].append('BELOW_MINIMUM_WITHIN_BOTH_SIDE_CAPACITY')
        if spread>15:result['reasons'].append('SPREAD_EXCEEDS_15_BPS')
        economics=row.get('economics_per_unit')
        if not 0<=now_ms-row.get('observed_ms',-1)<=5000:
            economics=None
            result['reasons'].append('SIGNAL_ECONOMIC_EVIDENCE_STALE')
        if row.get('decision')=='LONG' and economics and q>0:
            required=('gross_profit','fees','spread_cost','slippage_cost','funding_cost','net_profit')
            costs={k:decimal(economics[k]) for k in required}
            base=q*costs['net_profit']
            metrics=row.get('metrics',{})
            adverse_funding=max(costs['funding_cost']*2,
                abs(decimal(metrics['hourly_funding']))*decimal(metrics['oracle'],positive=True)*2)
            stress=q*(costs['gross_profit']-2*sum(costs[k] for k in ('fees','spread_cost','slippage_cost'))-adverse_funding)
            result.update(conditional_target_net=str(base),stressed_conditional_target_net=str(stress),
                conditional_target_return_on_notional_pct=str(100*base/notional),
                estimate_basis='Frozen target geometry with observed friction; NOT a probability-weighted expected return',
                conditional_costs={k:str(q*v) for k,v in costs.items()})
            if maker_fee_rate is not None:
                maker=decimal(maker_fee_rate)
                result['passive_comparison']=dict(maker_rate_bound=str(maker),taker_rate_bound=str(fee),
                    entry_fee_saving_if_filled=str(q*buy['best_price']*(fee-maker)),
                    queue_position=None,fill_probability=None,adverse_selection=None,route_changed=False,
                    limitation='Fee difference only; passive expected net return is UNKNOWN without fills and selection evidence')
            if base>0 and stress>0 and not result['reasons']:
                result['economically_viable_notional']=str(notional)
            else:result['reasons'].append('CONDITIONAL_EDGE_OR_STRESS_INSUFFICIENT')
        else:result['reasons'].append('NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL')
        result['reasons'] += ['EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED','NATIVE_RESIDUAL_PROTECTION_UNQUALIFIED','NO_EXACT_SESSION_AUTHORITY']
    except (ExchangeError,ValueError,KeyError,IndexError,ArithmeticError) as exc:
        result['reasons'].append(str(exc) if isinstance(exc,ExchangeError) else 'INVALID_CAPACITY_EVIDENCE')
    return result


def diagnostic_rank(rows):
    """Observation-only lexicographic ranking; production Top-3 is untouched."""
    return sorted(rows,key=lambda r:(-D(r.get('economically_viable_notional','0')),
        -D(r.get('liquidity_only_notional','0')),D(r.get('spread_bps','Infinity')),r['symbol']))


def complete_scan_frame(signals,capacity,opportunities,*,market_count,at,cancelled=False):
    """Only a complete scan advances the durable table/funnel clock."""
    if cancelled or len(signals)!=market_count:return None
    candidates={r['symbol'] for r in signals if r.get('baseline_long')}
    return dict(signals=signals,liquidity=capacity,capacity_ranking=diagnostic_rank(opportunities),
        latest_scan_ms=at,scan_in_progress=False,capacity_ranking_scope='OBSERVATION_ONLY_NOT_PRODUCTION_TOP3',
        opportunity_counts=dict(candidate_occurrences=len(candidates),
            markets_with_two_sided_capacity=sum(D(r['liquidity_only_notional'])>=10 for r in opportunities),
            candidates_passing_capacity=sum(r['symbol'] in candidates and D(r['liquidity_only_notional'])>=10 for r in opportunities),
            conditional_friction_and_stress=sum(D(r['economically_viable_notional'])>0 for r in opportunities),
            qualified_protection=0,authorized=0,statistical_expected_edge_verified=0))


class SessionPerformance:
    """Actual reported cashflows, with explicit session/equity bases."""
    def __init__(self,started_ms):
        self.started_ms=started_ms;self.initial=None;self.initial_ms=None;self.peak=None;self.drawdown=D(0)

    def observe(self,account,observed_ms):
        equity=(account.get('reported_account_equity') or {}).get('reported_account_value')
        current=decimal(equity,nonnegative=True) if equity is not None else None
        if current is not None and current>0 and self.initial is None:
            self.initial=current;self.initial_ms=observed_ms;self.peak=current
        if current is not None and self.peak is not None:
            self.peak=max(self.peak,current)
            if self.peak:self.drawdown=max(self.drawdown,(self.peak-current)/self.peak*100)
        fills=[f for f in account.get('fills',[]) if self.started_ms<=f['timestamp_ms']<=observed_ms]
        funding=[f for f in account.get('funding_events',[]) if self.started_ms<=f['timestamp_ms']<=observed_ms]
        complete=not account.get('entries_paused',True) and not account.get('reasons')
        known=all(f.get('closed_pnl') is not None for f in fills)
        gross=sum((decimal(f['closed_pnl']) for f in fills),D(0)) if known else None
        fees=sum((decimal(f['fee']) for f in fills),D(0));cash=sum((decimal(f['cashflow']) for f in funding),D(0))
        net=gross-fees+cash if complete and known else None
        return dict(source='EXCHANGE_REPORTED_FILLS_FEES_FUNDING',session_started_ms=self.started_ms,
            initial_equity=str(self.initial) if self.initial is not None else None,initial_equity_observed_ms=self.initial_ms,
            current_equity=str(current) if current is not None else None,as_of_ms=observed_ms,
            actual_gross_realized=str(gross) if complete and gross is not None else None,
            actual_fees=str(fees) if complete else None,actual_funding=str(cash) if complete else None,
            actual_net_realized=str(net) if net is not None else None,
            realized_net_on_initial_equity_pct=str(net/self.initial*100) if net is not None and self.initial else None,
            equity_change_pct=str((current/self.initial-1)*100) if current is not None and self.initial else None,
            return_basis='First verified session equity; equity change is not cash-flow-adjusted or an official competition return',
            sampled_maximum_drawdown_pct=str(self.drawdown) if self.initial is not None else None,
            fill_count=len(fills),funding_event_count=len(funding),official_score=None,daily_return_volatility=None,
            accounting_complete=complete,unrealized_pnl_source='See exchange-reported position fields; no synthetic valuation added')
