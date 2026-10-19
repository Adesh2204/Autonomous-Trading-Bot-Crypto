"""Isolated signal explanations around the unchanged production scanner contract."""
from dataclasses import fields
from decimal import Decimal as D
import math
from .base_exchange import Candle,BookLevel,OrderBook,MarketSpec,ExchangeError,decimal
from .capital_allocation import validate_book


def restore_market(row):
    spec=MarketSpec(**row['spec'])
    b=row['book'];book=OrderBook(**dict(b,
        bids=tuple(BookLevel(D(x['price']),D(x['quantity'])) for x in b['bids']),
        asks=tuple(BookLevel(D(x['price']),D(x['quantity'])) for x in b['asks'])))
    candles=[Candle(**{k:D(v) if k in {'open','high','low','close','volume'} else v for k,v in c.items()})
        for c in row['candles']]
    return spec,book,candles


def completed_higher_timeframe(candles,now_ms,*,minutes=15):
    """Only complete, contiguous UTC buckets; no forward fill or partial bucket."""
    if type(minutes) is not int or minutes<1:raise ExchangeError('INVALID_RESEARCH_TIMEFRAME')
    width=minutes*60000;groups={}
    for c in candles:
        if c.timestamp_ms+60000>now_ms:raise ExchangeError('INCOMPLETE_RESEARCH_CANDLE')
        groups.setdefault(c.timestamp_ms//width*width,[]).append(c)
    closes=[];times=[]
    for start,rows in sorted(groups.items()):
        if start+width>now_ms:continue
        if [c.timestamp_ms for c in rows]!=list(range(start,start+width,60000)):continue
        closes.append(float(rows[-1].close));times.append(start+width)
    if len(closes)<30:return dict(status='WARMUP_INSUFFICIENT',completed_bars=len(closes),trend=None)
    if any(b-a!=width for a,b in zip(times[-30:],times[-29:])):
        return dict(status='HIGHER_TIMEFRAME_GAP',completed_bars=len(closes),trend=None)
    def ema(span):
        value=closes[0];alpha=2/(span+1)
        for x in closes[1:]:value=alpha*x+(1-alpha)*value
        return value
    fast,slow=ema(9),ema(21)
    return dict(status='READY',completed_bars=len(closes),ema9=fast,ema21=slow,
        trend='BULLISH' if fast>slow else 'BEARISH' if fast<slow else 'NEUTRAL',
        latest_complete_ms=times[-1],scope='RESEARCH_CONFIRMATION_VETO_ONLY')


def classify_signal(*,baseline_long,baseline_short,higher_trend,eligible,reasons):
    result=list(reasons)
    if baseline_long and baseline_short:result.append('CONTRADICTORY_BASELINE_SIGNALS')
    elif not baseline_long and not baseline_short:result.append('NO_FROZEN_STRATEGY_SETUP')
    direction='LONG' if baseline_long and not baseline_short else 'SHORT' if baseline_short and not baseline_long else None
    if direction and higher_trend!=('BULLISH' if direction=='LONG' else 'BEARISH'):
        result.append('HIGHER_TIMEFRAME_CONFIRMATION_ABSENT')
    return dict(decision=direction if eligible and direction and not result else 'NO_TRADE',
        reasons=result,confidence_probability=None,baseline_long=baseline_long,baseline_short=baseline_short)


def explain_market(spec,book,candles,context,*,now_ms,context_ms,fee_rate=D('.0027')):
    from frozen_strategy import FrozenStrategy
    from strategy_contract import baseline_parameters
    from .hyperliquid_market_data import make_quote
    from .perpetual_economics import estimate_trade,FeeSchedule
    report=dict(symbol=spec.symbol,observed_ms=now_ms,decision='NO_TRADE',reasons=[],metrics={},
        baseline_strategy_unchanged=True,order_submission_enabled=False,confidence_probability=None)
    try:
        validate_book(book,now_ms)
        if len(candles)<300:raise ExchangeError('BASELINE_300_BAR_WARMUP_REQUIRED')
        if any(c.timestamp_ms+60000>now_ms or c.received_timestamp_ms is not None and c.received_timestamp_ms>now_ms for c in candles):
            raise ExchangeError('FUTURE_OR_INCOMPLETE_CANDLE_PROHIBITED')
        if not 0<=now_ms-(candles[-1].timestamp_ms+60000)<=120000:
            raise ExchangeError('COMPLETED_CANDLE_STALE')
        if not 0<=now_ms-context_ms<=60000:raise ExchangeError('MARK_ORACLE_FUNDING_CONTEXT_STALE')
        frame=FrozenStrategy(None).evaluate_candles(candles);last=frame.iloc[-1]
        def number(name):
            value=float(last[name])
            if not math.isfinite(value):raise ExchangeError('INDICATOR_WARMUP_INSUFFICIENT')
            return D(str(value))
        atr,close,vwap,ema9,ema21=(number(n) for n in ('ATR_14','Close','VWAP','EMA_9','EMA_21'))
        quote=make_quote(book,context,now_ms,mark_timestamp_ms=context_ms)
        spread=(quote.ask-quote.bid)/quote.mid*10000
        divergence=abs(quote.mark-quote.oracle)/quote.oracle*10000
        higher=completed_higher_timeframe(candles,now_ms)
        volumes=[c.volume for c in candles[-21:-1]];average=sum(volumes,D(0))/len(volumes)
        returns=[math.log(float(b.close/a.close)) for a,b in zip(candles[-61:-1],candles[-60:])]
        vol=math.sqrt(sum((x-sum(returns)/len(returns))**2 for x in returns)/len(returns))
        bids=sum((x.quantity for x in book.bids),D(0));asks=sum((x.quantity for x in book.asks),D(0))
        slope=number('VWAP_Slope')
        metrics=dict(atr=atr,atr_fraction=atr/close,close=close,vwap=vwap,vwap_slope=slope,
            ema9=ema9,ema21=ema21,trend='BULLISH' if ema9>ema21 else 'BEARISH' if ema9<ema21 else 'NEUTRAL',
            volume_ratio=candles[-1].volume/average if average else None,realized_volatility=vol,
            spread_bps=spread,mark_oracle_bps=divergence,book_imbalance=(bids-asks)/(bids+asks),
            bid_depth_notional=sum((x.price*x.quantity for x in book.bids),D(0)),
            ask_depth_notional=sum((x.price*x.quantity for x in book.asks),D(0)),
            bbo_notional=min(quote.bid*quote.bid_quantity,quote.ask*quote.ask_quantity),
            window_notional_approx=sum((c.close*c.volume for c in candles[-300:]),D(0)),
            hourly_funding=quote.hourly_funding,mark=quote.mark,oracle=quote.oracle)
        reasons=[]
        if atr/close<D('.004'):reasons.append('ATR_BELOW_UNCHANGED_0_40_PERCENT_FLOOR')
        if spread>15:reasons.append('SPREAD_EXCEEDS_BASELINE_15_BPS')
        if divergence>50:reasons.append('MARK_ORACLE_DIVERGENCE')
        if metrics['bbo_notional']<10:reasons.append('BBO_BELOW_BASELINE_LIQUIDITY')
        flags=lambda names:any(bool(last.get(n)) for n in names if last.get(n) is not None and str(last.get(n)) not in {'nan','None','<NA>'})
        long=flags(('Buy_Signal','Breakout_Signal'));short=flags(('Sell_Signal','Breakdown_Sell_Signal'))
        classification=classify_signal(baseline_long=long,baseline_short=short,higher_trend=higher.get('trend'),eligible=not reasons,reasons=reasons)
        report.update(classification,metrics=metrics,higher_timeframe=higher,candle_count=len(candles),
            latest_completed_candle_ms=candles[-1].timestamp_ms,source='HASH_VERIFIED_FROZEN_STRATEGY_PLUS_ISOLATED_HTF_VETO')
        direction='BUY' if long and not short else 'SELL' if short and not long else None
        if direction:
            p=baseline_parameters();sign=D(1) if direction=='BUY' else D(-1)
            stop=vwap-sign*D(str(p['SL_ATR_MULT']))*atr;target=vwap+sign*D(str(p['TP_ATR_MULT']))*atr
            from dataclasses import asdict
            economics=estimate_trade(direction,1,vwap,stop,target,quote,FeeSchedule(0,fee_rate,'CONSERVATIVE_RESEARCH_BOUND'),
                slippage_bps=5,holding_hours=1)
            report.update(baseline_stop=stop,baseline_target=target,economics_per_unit=asdict(economics))
            threshold=D(str(p['MIN_NET_RR_LOW_VOL'] if atr/vwap<D(str(p['LOW_VOL_ATR_PCT'])) else p['MIN_NET_RR_NORMAL']))
            if economics.net_profit<=0 or economics.net_rr<threshold:
                report['decision']='NO_TRADE';report['reasons'].append('BASELINE_FEE_ADJUSTED_REWARD_RISK_INSUFFICIENT')
    except (ExchangeError,ValueError,KeyError,IndexError) as exc:
        report['decision']='NO_TRADE'
        report['reasons'].append(str(exc));report['data_status']='FAILED_SAFE'
    return report


def rank_reports(reports):
    valid=[r for r in reports if r.get('metrics') and r['decision']!='NO_TRADE']
    factors={'atr_fraction':1,'spread_bps':-1,'window_notional_approx':1,'bbo_notional':1}
    for r in valid:
        ranks=[]
        for name,direction in factors.items():
            value=direction*r['metrics'][name]
            below=sum(direction*x['metrics'][name]<value for x in valid)
            ties=sum(direction*x['metrics'][name]==value for x in valid)
            ranks.append((D(below)+D(ties)/2)/len(valid))
        r['ranking_score']=sum(ranks)/len(ranks)
        r['ranking_score_scope']='DESCRIPTIVE_SELECTION_RANK_NOT_CONFIDENCE_OR_PROFIT_PROBABILITY'
    return sorted(reports,key=lambda r:(r['decision']=='NO_TRADE',-r.get('ranking_score',D(0)),r['symbol']))
