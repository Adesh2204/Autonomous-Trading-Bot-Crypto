"""Actual-account exports, independently labelled from PAPER/REPLAY results."""
import csv
from dataclasses import asdict
from pathlib import Path
import json
import subprocess
from datetime import datetime,timezone
from exchange.execution_journal import fingerprint
from exchange.execution_journal import canonical, safe_data
from exchange.event_timing import timing
from strategy_freeze import verify_strategy_freeze
from session_results import source_version, ROOT


class LiveSessionResults:
    TIME=('exchange_ts','received_ts','processed_ts')
    TRACE=('session_id','candidate_id','symbol','event_type','execution_source')
    FIELDS={
        'equity':TIME+TRACE+('timestamp_ms','reported_account_value','collateral_balance','margin_used','withdrawable','execution_mode','source'),
        'positions':TIME+TRACE+('timestamp_ms','quantity','entry_price','unrealized_pnl','margin_used','liquidation_price','execution_mode','source'),
        'fees':TIME+TRACE+('timestamp_ms','order_id','trade_id','fee','fee_token','execution_mode','source'),
        'funding':TIME+TRACE+('timestamp_ms','event_hash','cashflow','position_quantity','funding_rate','collateral','execution_mode','source')}

    def __init__(self,path,session):
        self.path=Path(path)/'results'
        self.path.mkdir(parents=True,exist_ok=True)
        self.session=session
        self.journal=session.journal
        from exchange.sdk_transport import OfflineSDKTransport
        self.mode='OFFLINE_SIGNED_FIXTURE' if type(session.execution.transport) is OfflineSDKTransport else 'LIVE_TESTNET'
        self.source='SYNTHETIC_SIGNED_FIXTURE' if self.mode=='OFFLINE_SIGNED_FIXTURE' else 'EXCHANGE_REPORTED'
        self.event_seq=0
        self.fill_ids=set()
        self.fee_ids=set()
        self.funding_ids=set()
        for name in ('orders','fills','signals','rejected_signals','health_events','candidate_traces','protection_events'):
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
        scanner_policy=getattr(session.scanner,'policy',None)
        from exchange.venue_profiles import venue_profile
        from exchange.entry_scope import PAS_ENTRY_MARKETS
        profile=venue_profile(session.market.client.dex)
        mandate=getattr(getattr(session,'daily_authority',None),'m',None)
        entry_markets=sorted(mandate.daily.markets if mandate else PAS_ENTRY_MARKETS if profile.dex=='pas' else session.market.client.markets)
        configuration=dict(collateral=profile.collateral,venue_identity=profile.identity,
            entry_markets=entry_markets,account_reconciliation_markets=sorted(session.market.client.markets),network='testnet',competition_market=session.market.client.competition_market,
            dex=(session.market.client.api_dex if getattr(session.market.client,'competition_mode',False) else session.market.client.dex),
            api_market=(session.market.client.api_market if getattr(session.market.client,'competition_mode',False)
                        else session.market.client.venue.prefix+'BTC'),
            collateral_token=session.market.client.collateral_token_name,execution_mode=self.mode,
            risk_policy=asdict(session.risk.policy),scanner_policy=asdict(scanner_policy) if scanner_policy is not None else None,
            vwap_policy='UTC_MIDNIGHT_BASELINE',model_version=None,
            protection_policy=asdict(session.execution.protection.policy) if session.execution.protection is not None else None,
            rate_policy=asdict(session.execution.rate_limits.policy))
        data=dict(schema_version=3,execution_mode=self.mode,source=self.source,
                  competition_market=session.market.client.competition_market,
                  api_dex=(session.market.client.api_dex if getattr(session.market.client,'competition_mode',False) else session.market.client.dex),
            api_market=(session.market.client.api_market if getattr(session.market.client,'competition_mode',False)
                        else session.market.client.venue.prefix+'BTC'),
                  collateral_token=session.market.client.collateral_token_name,
                  team_wallet=session.execution.account.team_address,
                  api_wallet=session.execution.transport.signer_address,network='testnet',
                  dex=session.market.client.api_dex,collateral=profile.collateral,venue_identity=profile.identity,
                  session_id=self.journal.session_id,sdk_version='0.24.0',strategy_freeze=verify_strategy_freeze(),
                  git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  git_branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
                  git_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                  risk_policy=asdict(session.risk.policy),
                  configuration=configuration,configuration_hash=fingerprint(configuration),
                  scanner_policy_hash=fingerprint(configuration['scanner_policy']),
                  risk_policy_hash=fingerprint(configuration['risk_policy']),
                  strategy_source_hash=__import__('hashlib').sha256((ROOT/'algo-trading-bot/signal_brain.py').read_bytes()).hexdigest(),
                  working_source_hash=source_version(list((ROOT/'algo-trading-bot').rglob('*.py'))+list((ROOT/'scripts').glob('*.py'))),
                  start_timestamp=datetime.now(timezone.utc).isoformat(),
                  accounting_origin_ms=session.recovery.initial_start_ms,
                  note='Reported fills/fees/funding only. Order summaries never create accounting fills. Offline fixtures are synthetic and are not real trading results.')
        previous=self.path/'session_manifest.json'
        if previous.exists():
            prior=json.loads(previous.read_text())
            keys=('schema_version','session_id','team_wallet','api_wallet','execution_mode','source',
                  'competition_market','api_dex','api_market','collateral_token',
                  'configuration_hash','working_source_hash','strategy_source_hash')
            if any(prior.get(k)!=data.get(k) for k in keys):
                raise ValueError('RESULT_MANIFEST_IDENTITY_OR_POLICY_CHANGED')
            data['start_timestamp']=prior['start_timestamp']
        (self.path/'session_manifest.json').write_text(json.dumps(safe_data(data),indent=2,default=str)+'\n')

    def _jsonl(self,name,record):
        with (self.path/(name+'.jsonl')).open('a') as stream:
            stream.write(canonical(safe_data(dict(self._source_labels(record),execution_mode=self.mode,
                execution_source=self.source,session_id=self.journal.session_id)))+'\n')

    def _source_labels(self,value):
        """Fixture account objects use the same schema; their evidence is synthetic."""
        if isinstance(value,dict):
            return {k:self.source if k=='source' and isinstance(v,str) and v.startswith('EXCHANGE_REPORTED')
                    else self._source_labels(v) for k,v in value.items()}
        if isinstance(value,list):
            return [self._source_labels(v) for v in value]
        return value

    def _row(self,name,record):
        record=dict(timing(self.session.clock_ms()),**record)
        record.update(session_id=self.journal.session_id,event_type=name.upper(),execution_source=self.source)
        record.setdefault('candidate_id',None)
        record.setdefault('symbol',None)
        with (self.path/(name+'.csv')).open('a',newline='') as stream:
            csv.DictWriter(stream,fieldnames=self.FIELDS[name],extrasaction='ignore').writerow(
                safe_data(dict(record,execution_mode=self.mode)))

    def save(self):
        state=self.session.recovery.state
        for row in self.journal.db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq',(self.event_seq,)):
            record=dict(json.loads(row['data']),kind=row['kind'],timestamp_ms=row['timestamp_ms'],journal_seq=row['seq'])
            self._jsonl('candidate_traces',record)
            if row['kind'].startswith('PROTECTION_'):
                self._jsonl('protection_events',record)
            if row['kind']=='LIVE_SIGNAL':
                self._jsonl('signals',record)
            elif row['kind']=='ENTRY_REJECTED':
                self._jsonl('rejected_signals',record)
            elif row['kind'] in {'SIGNED_ATTEMPT','EXCHANGE_ORDER_RESULT','MANAGEMENT_ATTEMPT','MANAGEMENT_RESULT','CLOID_RECOVERY'}:
                self._jsonl('orders',record)
            else:
                self._jsonl('health_events',record)
            self.event_seq=row['seq']
        rows=self.journal.intents()
        intents={str(r['oid']):r for r in rows if r['oid'] is not None}
        intents.update((str(oid),r) for r in rows for oid in json.loads(r['outcome'] or '{}').get('child_order_ids',[]))
        for fill in state.fills.values():
            candidate=(intents.get(fill.order_id) or {}).get('candidate')
            record=dict(asdict(fill),identity=fill.identity,candidate_id=candidate,source=self.source)
            if fill.identity not in self.fill_ids:
                self._jsonl('fills',record)
                self.fill_ids.add(fill.identity)
            if fill.identity not in self.fee_ids:
                self._row('fees',record)
                self.fee_ids.add(fill.identity)
        for funding in state.funding.values():
            if funding.identity not in self.funding_ids:
                self._row('funding',dict(asdict(funding),source=self.source))
                self.funding_ids.add(funding.identity)
        now=self.session.clock_ms()
        for symbol,position in state.positions.items():
            self._row('positions',dict(asdict(position),timestamp_ms=now,
                candidate_id=self.session.position_candidates.get(symbol),source=self.source))
        if not state.positions and state.initialized:
            self._row('positions',dict(timestamp_ms=now,symbol='ALL',quantity='0',source=self.source+'_FLAT'))
        if state.equity is not None:
            self._row('equity',dict(asdict(state.equity),timestamp_ms=now,source=self.source))
        (self.path/'actual_account_report.json').write_text(json.dumps(safe_data(dict(
            self._source_labels(state.report()),execution_mode=self.mode,source=self.source,
            exchange_orders_submitted=0 if self.mode=='OFFLINE_SIGNED_FIXTURE' else None,
            submission_count_note='Actual exchange submission count requires authoritative acceptance evidence; intents are not submissions.',
            durable_intent_count=len(rows),
            confirmed_order_count=len(intents),
            signed_attempt_count=self.journal.db.execute("SELECT COUNT(*) FROM events WHERE kind='SIGNED_ATTEMPT'").fetchone()[0])),
            indent=2,default=str)+'\n')
        from exchange.safety_report import production_safety_report,format_safety_report
        safety=production_safety_report(self.session.execution)
        (self.path/'production_safety.json').write_text(json.dumps(safety,indent=2,default=str)+'\n')
        (self.path/'production_safety.txt').write_text(format_safety_report(safety))
        from exchange.startup_recovery import write_startup_report
        write_startup_report(self.path,self.session.startup_recovery.report())
        self.session.funnel.export(self.path)
        from exchange.compliance_report import export_compliance
        export_compliance(self.path,self.journal,mode=self.mode,
                          position_guard=self.session.execution.position_guard)
        # Account totals include every actual reported event. Strategy statistics
        # explicitly exclude controlled tests and unattributed manual fills.
        classes={json.loads(r['data']).get('cloid'):json.loads(r['data']).get('order_classification')
            for r in self.journal.db.execute("SELECT data FROM events WHERE kind='COMPLIANCE_ACTION_AUTHORIZED'")}
        classified={str(r['oid']):classes.get(r['cloid']) for r in self.journal.intents() if r['oid'] is not None}
        classified.update((str(oid),classes.get(r['cloid'])) for r in self.journal.intents()
                          for oid in json.loads(r['outcome'] or '{}').get('child_order_ids',[]))
        allowed={'STRATEGY_ENTRY','STRATEGY_EXIT','CATASTROPHIC_STOP','PROTECTIVE_EXIT'}
        strategy_fills=[f for f in state.fills.values() if classified.get(str(f.order_id)) in allowed]
        controlled=[f for f in state.fills.values() if classified.get(str(f.order_id))=='CONTROLLED_TEST_ORDER']
        from decimal import Decimal
        statistics=dict(execution_mode=self.mode,execution_source=self.source,
            scope='CLASSIFIED_SYNTHETIC_FILL_RECORDS_ONLY' if self.mode=='OFFLINE_SIGNED_FIXTURE' else 'CLASSIFIED_ACTUAL_FILLS_ONLY',
            strategy_fill_count=len(strategy_fills),controlled_test_fill_count=len(controlled),
            excluded_fill_count=len(state.fills)-len(strategy_fills),
            strategy_reported_closed_pnl=sum((f.closed_pnl for f in strategy_fills),Decimal(0))
                if all(f.closed_pnl is not None for f in strategy_fills) else None,
            strategy_actual_fees=sum((f.fee for f in strategy_fills),Decimal(0)),
            strategy_net_pnl=None,note='Funding attribution across manual/test exposure is not certified; no net strategy P&L is inferred.')
        (self.path/'strategy_performance.json').write_text(json.dumps(safe_data(statistics),indent=2,default=str)+'\n')
