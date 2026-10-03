"""Actual-account exports, independently labelled from PAPER/REPLAY results."""
import csv
from dataclasses import asdict
from pathlib import Path
import json
import subprocess
from exchange.execution_journal import canonical, safe_data
from exchange.event_timing import timing
from strategy_freeze import verify_strategy_freeze
from session_results import source_version, ROOT


class LiveSessionResults:
    TIME=('exchange_ts','received_ts','processed_ts')
    FIELDS={
        'equity':TIME+('timestamp_ms','reported_account_value','collateral_balance','margin_used','withdrawable','execution_mode','source'),
        'positions':TIME+('timestamp_ms','symbol','quantity','entry_price','unrealized_pnl','margin_used','liquidation_price','candidate_id','execution_mode','source'),
        'fees':TIME+('timestamp_ms','symbol','order_id','trade_id','fee','fee_token','candidate_id','execution_mode','source'),
        'funding':TIME+('timestamp_ms','symbol','event_hash','cashflow','position_quantity','funding_rate','collateral','execution_mode','source')}

    def __init__(self,path,session):
        self.path=Path(path)/'results'
        self.path.mkdir(parents=True,exist_ok=True)
        self.session=session
        self.journal=session.journal
        from exchange.sdk_transport import OfflineSDKTransport
        self.mode='OFFLINE_SIGNED_FIXTURE' if type(session.execution.transport) is OfflineSDKTransport else 'LIVE_TESTNET'
        self.event_seq=0
        self.fill_ids=set()
        self.fee_ids=set()
        self.funding_ids=set()
        for name in ('orders','fills','signals','rejected_signals','health_events','candidate_traces'):
            file=self.path/(name+'.jsonl')
            if file.exists():
                for line in file.read_text().splitlines():
                    record=json.loads(line)
                    if record.get('execution_mode')!=self.mode:
                        raise ValueError('RESULT_MODE_MISMATCH')
                    self.event_seq=max(self.event_seq,record.get('journal_seq',0))
                    if name=='fills':
                        self.fill_ids.add(tuple(record['identity']))
            else:
                file.touch()
        for name,fields in self.FIELDS.items():
            file=self.path/(name+'.csv')
            if file.exists():
                with file.open(newline='') as stream:
                    reader=csv.DictReader(stream)
                    if tuple(reader.fieldnames or ())!=fields:
                        raise ValueError('RESULT_SCHEMA_MISMATCH')
                    for row in reader:
                        if row['execution_mode']!=self.mode:
                            raise ValueError('RESULT_MODE_MISMATCH')
                        if name=='funding':
                            self.funding_ids.add((row['symbol'],int(row['timestamp_ms']),row['event_hash']))
                        elif name=='fees':
                            self.fee_ids.add((row['symbol'],int(row['timestamp_ms']),row['trade_id'],row['order_id']))
            else:
                with file.open('w',newline='') as stream:
                    csv.DictWriter(stream,fieldnames=fields).writeheader()
        data=dict(schema_version=1,execution_mode=self.mode,source='EXCHANGE_REPORTED',
                  team_wallet=session.execution.account.team_address,
                  api_wallet=session.execution.transport.signer_address,network='testnet',dex='par',
                  session_id=self.journal.session_id,sdk_version='0.24.0',strategy_freeze=verify_strategy_freeze(),
                  git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  git_branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
                  git_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                  risk_policy=asdict(session.risk.policy),
                  working_source_hash=source_version(list((ROOT/'algo-trading-bot').rglob('*.py'))),
                  accounting_origin_ms=session.recovery.initial_start_ms,
                  note='Reported fills/fees/funding only. Order summaries never create accounting fills. Offline fixtures are synthetic and are not real trading results.')
        (self.path/'session_manifest.json').write_text(json.dumps(safe_data(data),indent=2,default=str)+'\n')

    def _jsonl(self,name,record):
        with (self.path/(name+'.jsonl')).open('a') as stream:
            stream.write(canonical(safe_data(dict(record,execution_mode=self.mode)))+'\n')

    def _row(self,name,record):
        record=dict(timing(self.session.clock_ms()),**record)
        with (self.path/(name+'.csv')).open('a',newline='') as stream:
            csv.DictWriter(stream,fieldnames=self.FIELDS[name],extrasaction='ignore').writerow(
                safe_data(dict(record,execution_mode=self.mode)))

    def save(self):
        state=self.session.recovery.state
        for row in self.journal.db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq',(self.event_seq,)):
            record=dict(json.loads(row['data']),kind=row['kind'],timestamp_ms=row['timestamp_ms'],journal_seq=row['seq'])
            self._jsonl('candidate_traces',record)
            if row['kind']=='LIVE_SIGNAL':
                self._jsonl('signals',record)
            elif row['kind']=='ENTRY_REJECTED':
                self._jsonl('rejected_signals',record)
            elif row['kind'] in {'SIGNED_ATTEMPT','EXCHANGE_ORDER_RESULT','MANAGEMENT_ATTEMPT','MANAGEMENT_RESULT','CLOID_RECOVERY'}:
                self._jsonl('orders',record)
            else:
                self._jsonl('health_events',record)
            self.event_seq=row['seq']
        intents={str(r['oid']):r for r in self.journal.intents() if r['oid'] is not None}
        for fill in state.fills.values():
            candidate=(intents.get(fill.order_id) or {}).get('candidate')
            record=dict(asdict(fill),identity=fill.identity,candidate_id=candidate,source='EXCHANGE_REPORTED')
            if fill.identity not in self.fill_ids:
                self._jsonl('fills',record)
                self.fill_ids.add(fill.identity)
            if fill.identity not in self.fee_ids:
                self._row('fees',record)
                self.fee_ids.add(fill.identity)
        for funding in state.funding.values():
            if funding.identity not in self.funding_ids:
                self._row('funding',dict(asdict(funding),source='EXCHANGE_REPORTED'))
                self.funding_ids.add(funding.identity)
        now=self.session.clock_ms()
        for symbol,position in state.positions.items():
            self._row('positions',dict(asdict(position),timestamp_ms=now,
                candidate_id=self.session.position_candidates.get(symbol),source='EXCHANGE_REPORTED'))
        if not state.positions and state.initialized:
            self._row('positions',dict(timestamp_ms=now,symbol='ALL',quantity='0',source='EXCHANGE_REPORTED_FLAT'))
        if state.equity is not None:
            self._row('equity',dict(asdict(state.equity),timestamp_ms=now,source='EXCHANGE_REPORTED'))
        (self.path/'actual_account_report.json').write_text(json.dumps(safe_data(dict(
            state.report(),execution_mode=self.mode,source='EXCHANGE_REPORTED',
            exchange_orders_submitted=0 if self.mode=='OFFLINE_SIGNED_FIXTURE' else len(intents),
            confirmed_order_count=len(intents),
            signed_attempt_count=self.journal.db.execute("SELECT COUNT(*) FROM events WHERE kind='SIGNED_ATTEMPT'").fetchone()[0])),
            indent=2,default=str)+'\n')
