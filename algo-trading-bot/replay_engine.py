"""Explicit research replay. Synthetic fixtures never become historical profitability evidence."""
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import hashlib
import json
import uuid
import numpy as np
import pandas as pd

import config
from execution_engine import PaperTrader
from execution_safety import InstrumentIdentity, MarketQuote, SafetyError
from signal_brain import generate_vwap_signal, detect_daily_bias
from atr_firewall import ATRFirewall

@dataclass(frozen=True)
class ResearchVariant:
    name: str
    timeframe_minutes: int = 1
    @property
    def id(self):
        core=hashlib.sha256((Path(__file__).parent/'signal_brain.py').read_bytes()).hexdigest()
        return f'{self.name}:{self.timeframe_minutes}m:{core}'

def replay(source,instrument,provenance,output_dir,total_capital=config.TOTAL_CAPITAL,variant=None):
    if not isinstance(instrument,InstrumentIdentity):raise SafetyError('REPLAY_INSTRUMENT_REQUIRED')
    if not provenance or provenance.upper() in {'UNKNOWN','SYNTHETIC'}:raise SafetyError('REPLAY_DATA_PROVENANCE_REQUIRED')
    variant=variant or ResearchVariant('frozen-baseline')
    if variant.timeframe_minutes<1:raise SafetyError('INVALID_RESEARCH_VARIANT')
    data=pd.read_csv(source) if isinstance(source,(str,Path)) else source.copy()
    required={'Timestamp','Open','High','Low','Close','Volume'}
    if data.empty or not required<=set(data):raise SafetyError('INVALID_REPLAY_DATA')
    numeric=data[['Open','High','Low','Close','Volume']].apply(pd.to_numeric,errors='coerce')
    if not np.isfinite(numeric.to_numpy()).all() or (numeric[['Open','High','Low','Close']]<=0).any().any():
        raise SafetyError('INVALID_REPLAY_DATA')
    data['Timestamp']=pd.to_datetime(data['Timestamp'])
    if data['Timestamp'].dt.tz is None:data['Timestamp']=data['Timestamp'].dt.tz_localize('Asia/Kolkata')
    else:data['Timestamp']=data['Timestamp'].dt.tz_convert('Asia/Kolkata')
    if not data['Timestamp'].is_monotonic_increasing or data['Timestamp'].duplicated().any():raise SafetyError('NON_CAUSAL_REPLAY_DATA')
    if ((data['High']<data[['Open','Close','Low']].max(axis=1)) |
        (data['Low']>data[['Open','Close','High']].min(axis=1)) | (data['Volume']<0)).any():raise SafetyError('INVALID_REPLAY_DATA')
    if variant.timeframe_minutes!=1:
        data=data.set_index('Timestamp').resample(f'{variant.timeframe_minutes}min',origin='start_day',offset='15min').agg(
            {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna().reset_index()
    output=Path(output_dir)/str(uuid.uuid4()); output.mkdir(parents=True)
    clock=[data['Timestamp'].iloc[0].to_pydatetime()]
    trader=PaperTrader(total_capital=total_capital,environment='REPLAY',clock=lambda:clock[0],csv_log_path=str(output/'trades.csv'))
    trades=[]; equity=[]; pending=None; firewall=ATRFirewall()
    try:
        for day,session in data.groupby(data['Timestamp'].dt.date,sort=True):
            clock[0]=session['Timestamp'].iloc[0].to_pydatetime(); trader.check_day_reset(clock[0])
            # Archive instrument mapping for each historical session. This is explicitly research-only.
            identity=InstrumentIdentity(instrument.symbol,instrument.exchange,instrument.token,instrument.trading_symbol,
                instrument.series,instrument.tick_size,instrument.lot_size,instrument.instrument_type,clock[0],instrument.intraday_eligible)
            enriched=generate_vwap_signal(session)
            pending=None
            observed_volume=0
            for index,row in enriched.iterrows():
                ts=row['Timestamp'].to_pydatetime(); clock[0]=ts
                def observation(price,when):
                    # Candle-only approximation: full assumptions are recorded below.
                    spread=price*config.REPLAY_HALF_SPREAD_PCT
                    depth=max(1,int(observed_volume))
                    return MarketQuote(price-spread,price+spread,depth,depth,when,price)
                open_quote=observation(float(row['Open']),ts)
                trader.set_quote(identity,open_quote)
                if pending and trader.schedule.can_enter_new_positions(ts):
                    pending['instrument']=identity; pending['quote']=open_quote
                    trader.execute_trade(pending,timestamp=ts,side=pending['side'])
                pending=None
                # Deterministic bar path, not an assertion that OHLC reveals the tick sequence.
                for price in (float(row['Open']),float(row['Low']),float(row['High']),float(row['Close'])):
                    trader.set_quote(identity,observation(price,ts))
                    result=trader.check_exit(price,ts)
                    if result:trades.append(result)
                trader.set_quote(identity,observation(float(row['Close']),ts))
                result=trader.notify_candle_close({'Timestamp':ts,'Close':float(row['Close'])})
                if result:trades.append(result)
                # Volume is known only after the completed bar. It is a research
                # depth proxy for the NEXT bar, never an observed order-book claim.
                observed_volume=float(row['Volume'])
                atr=float(row['ATR_14']); close=float(row['Close'])
                gate=firewall.validate_pre_entry(atr,close,feed_health='HEALTHY',spread_pct=2*config.REPLAY_HALF_SPREAD_PCT*100,
                    depth_available=True,is_new_entry=True)
                long=bool(row.get('Buy_Signal')) or bool(row.get('Breakout_Signal'))
                short=bool(row.get('Sell_Signal')) or bool(row.get('Breakdown_Sell_Signal'))
                bias=detect_daily_bias(enriched.loc[:index])
                if bias=='LONG_BIAS':short=False
                elif bias=='SHORT_BIAS':long=False
                if (long or short) and gate.execution_allowed:
                    pending={'symbol':identity.symbol,'VWAP':float(row['VWAP']),'Close':close,'ATR_14':atr,
                        'side':'BUY' if long else 'SELL','signal_timestamp':str(ts),'signal_type':row.get('Signal_Type'),
                        'signal_id':f'{identity.token}:{ts}'}
                    trader._event('SIGNAL',side=pending['side'],symbol=identity.symbol,
                        signal_id=pending['signal_id'],reference_price=pending['VWAP'])
                elif long or short:trader._event('REJECTED',reason=gate.rejection_reason,signal_timestamp=ts)
            pending=None
            if trader.has_open_position:
                result=trader.square_off_all_positions(timestamp=clock[0],latest_price=float(session.iloc[-1]['Close']))
                if result:trades.append(result)
            equity.append({'Timestamp':clock[0],'Total_Capital':total_capital+sum(t['net_pnl'] for t in trades),
                'Working_Capital':trader.working_capital,'Backup_Capital':trader.backup_capital,'Session_Daily_PnL':trader.daily_pnl})
        metadata={'variant_id':variant.id,'provenance':provenance,'unattended_live_eligible':False,
            'assumptions':['Signals execute on next bar observation','Bid/ask/depth approximated from OHLCV; not observed',
                'Entry depth proxy uses only the previously completed bar volume',
                'Fixed open-low-high-close path; tick sequencing unknown','Single supplied symbol; does not validate dynamic universe selection'],
            'trades':len(trades),'output_dir':str(output)}
        (output/'research_metadata.json').write_text(json.dumps(metadata,indent=2))
        (output/'research_metrics.json').write_text(json.dumps(research_metrics(trades),indent=2,default=str))
        return trades,pd.DataFrame(equity),metadata
    finally:trader.shutdown()

def rejected_opportunity_outcomes(events,future_candles):
    """Post-session excursions only; no values are fed into live decisions."""
    output=[]
    for event in events:
        candle=event.get('candle',{})
        if 'Timestamp' not in candle or 'Close' not in candle:continue
        subsequent=future_candles[future_candles['Timestamp']>pd.Timestamp(candle['Timestamp'])]
        if subsequent.empty:continue
        ref=float(candle['Close'])
        result={'reason':event.get('reason'),'timestamp':str(candle['Timestamp']),
            'maximum_up_move':float(subsequent['High'].max())-ref,'maximum_down_move':float(subsequent['Low'].min())-ref,
            'research_only':True,'basis':'CANDLE_EXCURSIONS; NOT A FILLED NET TRADE'}
        atr=event.get('atr')
        if atr is not None and float(atr)>0 and event.get('side') in {'BUY','SELL'}:
            distance=round(config.SL_ATR_MULT*float(atr),2)
            if distance>0:
                up=result['maximum_up_move']; down=result['maximum_down_move']
                result['maximum_favourable_r']=(up if event['side']=='BUY' else -down)/distance
                result['maximum_adverse_r']=(down if event['side']=='BUY' else -up)/distance
        output.append(result)
    return output

def research_metrics(trades):
    def group(key,transform=None):
        values={}
        for t in trades:
            value=t.get(key,'UNKNOWN')
            if transform:value=transform(value)
            values.setdefault(str(value),[]).append(t['net_pnl'])
        return {k:{'count':len(v),'net_expectancy':sum(v)/len(v),'net_pnl':sum(v)} for k,v in values.items()}
    pnls=[t['net_pnl'] for t in trades]; wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<0]
    rs=[t['net_pnl']/t['reserved_risk'] for t in trades if t.get('reserved_risk',0)>0]
    streak=maximum=0; equity=peak=drawdown=0
    for p in pnls:
        streak=streak+1 if p<0 else 0; maximum=max(maximum,streak)
        equity+=p; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    slippage=pd.Series([t['entry_slippage'] for t in trades if 'entry_slippage' in t],dtype=float)
    gross=sum(abs(t.get('gross_pnl',0)) for t in trades)
    return {'count':len(pnls),'net_expectancy':sum(pnls)/len(pnls) if pnls else None,
        'win_rate':len(wins)/len(pnls) if pnls else None,'average_winner':sum(wins)/len(wins) if wins else None,
        'average_loser':sum(losses)/len(losses) if losses else None,
        'profit_factor':sum(wins)/-sum(losses) if losses else None,'maximum_drawdown':drawdown,'consecutive_losses':maximum,
        'average_r':sum(rs)/len(rs) if rs else None,'median_r':float(pd.Series(rs).median()) if rs else None,
        'by_side':group('side'),'by_symbol':group('symbol'),'by_setup':group('signal_type'),
        'by_day':group('timestamp',lambda value:str(value)[:10]),
        'by_entry_hour':group('signal_timestamp',lambda value:str(value)[11:13]),
        'entry_slippage_distribution':{'min':float(slippage.min()),'median':float(slippage.median()),
            'p95':float(slippage.quantile(.95)),'max':float(slippage.max())} if not slippage.empty else None,
        'fee_to_absolute_gross_pnl_ratio':sum(t.get('entry_fees',0)+t.get('exit_fees',0) for t in trades)/gross if gross else None}
