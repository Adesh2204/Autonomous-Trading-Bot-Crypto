"""Append-only session evidence with source hashes and labelled local accounting."""
import csv
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess

from exchange.event_timing import timing, utc_ms

ROOT=Path(__file__).resolve().parents[1]
TIME=('exchange_ts','received_ts','processed_ts')
CSV_FIELDS={
    'equity':TIME+('timestamp_ms','cash','unrealized_pnl','equity','oracle_equity_estimate','initial_margin',
        'maintenance_margin_estimate','available_margin','realized_pnl','fees_paid','funding_cashflow','collateral','source'),
    'positions':TIME+('timestamp_ms','symbol','quantity','entry_price','leverage','candidate_id','source'),
    'funding':TIME+('timestamp_ms','symbol','cashflow','oracle_price','hourly_rate','source'),
    'fees':TIME+('timestamp_ms','symbol','order_id','fill_id','candidate_id','fee','fee_token','source'),
    'daily_metrics':('utc_day','first_observed_ts','last_observed_ts','last_mark_equity','last_oracle_equity_estimate',
        'observed_daily_return','observed_oracle_daily_return','sample_std_observed_daily_returns',
        'cumulative_fees','cumulative_funding','local_fill_count','closed_trade_count','status','valuation_method')}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),default=str,allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_version(paths):
    return digest({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)})


def manifest(bot,provenance,start_timestamp):
    def git(*args):
        return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
    sources=[p for p in (ROOT/'algo-trading-bot').rglob('*.py') if '__pycache__' not in p.parts]
    scripts=list((ROOT/'scripts').glob('*.py'))
    parameters=dict(starting_collateral=bot.execution.portfolio.starting_collateral,
        fees=asdict(bot.execution.fees),scanner=asdict(bot.scanner.policy),risk=asdict(bot.risk.policy))
    configuration=dict(parameters=parameters,network='testnet',dex='par',safety_execution_mode='PAPER',
        execution_mode=bot.execution.execution_mode,allow_live_orders=False)
    result=dict(schema_version=1,start_timestamp=start_timestamp,
        git_commit=git('rev-parse','HEAD'),git_branch=git('branch','--show-current'),
        git_dirty=bool(git('status','--porcelain')),working_source_hash=source_version(sources+scripts),
        configuration_hash=digest(configuration),configuration=configuration,parameter_set=parameters,
        strategy_version=dict(name='VWAP_FROZEN_NSE_BASELINE',freeze=__import__('strategy_freeze').verify_strategy_freeze(),
                              sha256=source_version([ROOT/'algo-trading-bot/signal_brain.py'])),
        exchange_adapter_version=source_version(list((ROOT/'algo-trading-bot/exchange').glob('*.py'))),
        risk_version=source_version(list((ROOT/'algo-trading-bot/risk').glob('*.py'))),
        provenance=provenance,collateral='USDPR',exchange_orders_submitted=0,
        timing_note='Exchange timestamps are null for local decisions/fills and timestamp-free API contexts. Exchange-to-receive is observation age, not proven network latency.',
        metrics_note='Mark equity is the paper risk valuation. Oracle equity is a local estimate. Daily returns use last observed UTC-day samples; incomplete days and sample volatility are not official scores.')
    return result


class SessionResults:
    def __init__(self,path,provenance):
        self.path=path/'results'
        self.path.mkdir()
        self.provenance=provenance
        self.start_timestamp=datetime.now(timezone.utc).isoformat()
        (self.path/"session_manifest.json").write_text(canonical(dict(start_timestamp=self.start_timestamp,provenance=provenance,status="INITIALIZING",signed_actions="DISABLED"))+"\n")
        for name in ('orders','fills','signals','rejected_signals','health_events','candidate_traces'):
            (self.path/(name+'.jsonl')).touch()
        for name,fields in CSV_FIELDS.items():
            with (self.path/(name+'.csv')).open('w',newline='') as f:
                csv.DictWriter(f,fieldnames=fields).writeheader()
        self.initialized=False
        self.cursors=dict(orders=0,ledger=0,fills=0,decisions=0,transitions=0,stream=0)
        self.days={}
        self.last_equity_ms=None
        self.submission_times={}
        self._trace_buffer=[]

    def jsonl(self,name,event):
        event={k:v for k,v in event.items() if k!='observed_ns'}
        if name=='candidate_traces':
            self._trace_buffer.append(event)
            return
        with (self.path/(name+'.jsonl')).open('a') as f:
            f.write(canonical(event)+'\n')

    def row(self,name,event):
        with (self.path/(name+'.csv')).open('a',newline='') as f:
            csv.DictWriter(f,fieldnames=CSV_FIELDS[name],extrasaction='ignore').writerow(event)

    def flush_events(self,bot):
        """Also used on halt; equity is written only after successful valuation."""
        self.bind(bot)
        e=bot.execution
        if bot.latest_scan:
            bot.audit_scan(bot.latest_scan)
        for event in e.events[self.cursors['orders']:]:
            if event['state']=='SUBMITTED':
                self.submission_times[event['order_id']]=event['processed_ts']
            self.jsonl('orders',event)
            self.jsonl('candidate_traces',dict(stage='ORDER',**event))
        for fill in e.fills[self.cursors['fills']:]:
            value=dict(asdict(fill),source='LOCAL_BBO_SIMULATION',execution_mode=e.execution_mode)
            submitted=self.submission_times.get(fill.order_id)
            value['simulated_submit_to_fill_ms']=int((datetime.fromisoformat(fill.processed_ts)-datetime.fromisoformat(submitted)).total_seconds()*1000) if submitted and fill.processed_ts else None
            self.jsonl('fills',value)
            self.jsonl('candidate_traces',dict(stage='FILL',**value))
            self.row('fees',dict(value,fee_token='USDPR'))
        for event in e.portfolio.events[self.cursors['ledger']:]:
            if event['kind']=='FUNDING':
                self.row('funding',event)
            self.jsonl('candidate_traces',dict(stage='POSITION_AND_PNL' if event['kind']=='FILL_ACCOUNTED' else 'FUNDING',**event))
            if event['kind']=='FILL_ACCOUNTED':
                self.row('positions',dict(event,quantity=event['quantity_after'],entry_price=event['entry_price_after'],source='LOCAL_FILL_ACCOUNTING'))
        for event in bot.decisions[self.cursors['decisions']:]:
            self.jsonl('candidate_traces',dict(event,stage=event['kind']))
            kind=event['kind']
            if kind=='SIGNAL':
                self.jsonl('signals',event)
            elif kind=='ENTRY_REJECTED' or kind=='RISK_DECISION' and not event['decision']['allowed']:
                self.jsonl('rejected_signals',event)
            elif kind not in {'MARKET_DATA','EXECUTION_DECISION','ENTRY_FILL','EXIT_FILL','TRADE_PNL','ENTRY_UNFILLED'}:
                self.jsonl('health_events',event)
        transitions=bot.breakers.transitions
        for event in transitions[self.cursors['transitions']:]:
            self.jsonl('health_events',dict(kind='RISK_STATE_CHANGE',**event))
        events=(bot.stream_report or {}).get('events',[])
        for event in events[self.cursors['stream']:]:
            # Legacy fixture clocks may be absent; local publication gets real local clocks.
            self.jsonl('health_events',dict(timing(event.get('timestamp_ms')),kind='STREAM_LIFECYCLE',**event))
        priority={name:i for i,name in enumerate(('MARKET_DATA','SIGNAL','RISK_DECISION','EXECUTION_DECISION','ENTRY_REJECTED','ORDER','FILL','ENTRY_FILL','EXIT_FILL','POSITION_AND_PNL','TRADE_PNL'))}
        with (self.path/'candidate_traces.jsonl').open('a') as f:
            for event in sorted(self._trace_buffer,key=lambda e:(e.get('processed_ts') or '',priority.get(e['stage'],20))):
                f.write(canonical(event)+'\n')
        self._trace_buffer.clear()
        self.cursors=dict(orders=len(e.events),ledger=len(e.portfolio.events),fills=len(e.fills),
            decisions=len(bot.decisions),transitions=len(transitions),stream=len(events))
        bot.funnel.export(self.path)

    def bind(self,bot):
        if not self.initialized:
            data=manifest(bot,self.provenance,self.start_timestamp)
            (self.path/'session_manifest.json').write_text(json.dumps(data,indent=2,default=str,allow_nan=False)+'\n')
            self.initialized=True
            from exchange.startup_recovery import read_only_startup_report,write_startup_report
            write_startup_report(self.path,read_only_startup_report(account_configured=bool(bot.team_address),
                                 market_ready=bot.market.client.ready))

    def save(self,bot,snapshot):
        self.bind(bot)
        self.flush_events(bot)
        if self.last_equity_ms==snapshot.timestamp_ms:
            return
        self.last_equity_ms=snapshot.timestamp_ms
        oracle_equity=snapshot.cash+sum((p.quantity*(bot.quotes[s].oracle-p.entry_price)
            for s,p in bot.execution.portfolio.positions.items()),Decimal(0))
        value=dict(asdict(snapshot),**timing(snapshot.timestamp_ms),oracle_equity_estimate=oracle_equity,
            source='LOCAL_PAPER_MARK_VALUATION' if bot.execution.execution_mode=='PAPER' else 'LOCAL_REPLAY_MARK_VALUATION')
        self.row('equity',value)
        # An explicit FLAT row distinguishes zero positions from missing samples.
        positions=bot.execution.portfolio.positions
        for s,p in positions.items():
            self.row('positions',dict(asdict(p),**timing(snapshot.timestamp_ms),timestamp_ms=snapshot.timestamp_ms,
                candidate_id=bot.position_candidates.get(s),source='LOCAL_PORTFOLIO_SNAPSHOT'))
        if not positions:
            self.row('positions',dict(timing(snapshot.timestamp_ms),timestamp_ms=snapshot.timestamp_ms,
                symbol='ALL',quantity='0',source='LOCAL_PORTFOLIO_FLAT'))
        day=datetime.fromtimestamp(snapshot.timestamp_ms/1000,timezone.utc).date().isoformat()
        prior=self.days.get(day)
        self.days[day]=dict(utc_day=day,first_observed_ts=prior['first_observed_ts'] if prior else utc_ms(snapshot.timestamp_ms),
            last_observed_ts=utc_ms(snapshot.timestamp_ms),last_mark_equity=snapshot.equity,
            last_oracle_equity_estimate=oracle_equity,cumulative_fees=snapshot.fees_paid,
            cumulative_funding=snapshot.funding_cashflow,local_fill_count=len(bot.execution.fills),
            closed_trade_count=len(bot.closed_trades),status='PROVISIONAL',valuation_method='LAST_OBSERVED_UTC_DAY_LOCAL_SIMULATION')
        rows=[dict(self.days[k]) for k in sorted(self.days)]
        returns=[]
        for i,row in enumerate(rows):
            if i:
                previous=rows[i-1]
                consecutive=(datetime.fromisoformat(row['utc_day'])-datetime.fromisoformat(previous['utc_day'])).days==1
                if consecutive and previous['last_mark_equity']>0:
                    row['observed_daily_return']=row['last_mark_equity']/previous['last_mark_equity']-1
                    returns.append(row['observed_daily_return'])
                if consecutive and previous['last_oracle_equity_estimate']>0:
                    row['observed_oracle_daily_return']=row['last_oracle_equity_estimate']/previous['last_oracle_equity_estimate']-1
            if i<len(rows)-1:
                row['status']='LAST_OBSERVATION_RECORDED'
            if len(returns)>=2:
                mean=sum(returns)/len(returns)
                row['sample_std_observed_daily_returns']=(sum((r-mean)**2 for r in returns)/(len(returns)-1)).sqrt()
        tmp=self.path/'daily_metrics.csv.tmp'
        with tmp.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=CSV_FIELDS['daily_metrics']);writer.writeheader();writer.writerows(rows)
        tmp.replace(self.path/'daily_metrics.csv')
