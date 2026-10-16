"""Atomic local PAPER recovery. Typed JSON, no pickle, keys or exchange transport."""
from dataclasses import fields,is_dataclass
from datetime import date,datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from pathlib import Path
import sqlite3

from .base_exchange import ExchangeError,MarketSpec,NormalizedOrder,Quote
from .paper_execution import PaperFill,PaperOrder
from .paper_portfolio import PaperPosition,FundingSettlement
from .order_lifecycle import OrderRequest
from .paper_reconciliation import PaperReconciliation
from strategy_contract import ManagementState
from risk.circuit_breakers import RiskState
from venue_config import require_paper_migration

TYPES={c.__name__:c for c in (MarketSpec,NormalizedOrder,Quote,OrderRequest,PaperFill,PaperOrder,PaperPosition,FundingSettlement,ManagementState,RiskState)}
BOT_FIELDS=('_day','_day_start_equity','_daily_setups','_funding_hour','accounting_halt',
    'reserved_setup_risk','pending_exit_reasons','setup_baseline_cash','closed_trades','peak_equity',
    'max_drawdown_fraction','last_signals','candidate_ids','position_candidates','decisions')
EXEC_FIELDS=('orders','fills','positions','events','_client_ids','_liquidity_used','_alo_checked','order_candidates')
LEDGER_FIELDS=('cash','positions','realized_pnl','fees_paid','funding_cashflow','events','_fills','_funding','last_event_ms','reservations')
MANAGER_FIELDS=('_open_position','_state','daily_bias','candles_since_last_sl','candles_held','entry_atr','_day','last_candle_ms')
BREAK_FIELDS=('global_blocks','symbol_blocks','financial_reasons','financial_state','consecutive_order_errors',
    'reconnect_failures','transitions','operational_state')


def pack(v):
    if isinstance(v,Enum):return ['enum',type(v).__name__,v.value]
    if v is None or type(v) in (str,int,bool,float):return ['scalar',v]
    if isinstance(v,Decimal):return ['decimal',str(v)]
    if isinstance(v,datetime):return ['datetime',v.isoformat()]
    if isinstance(v,date):return ['date',v.isoformat()]
    if is_dataclass(v) and type(v).__name__ in TYPES:
        return ['record',type(v).__name__,{f.name:pack(getattr(v,f.name)) for f in fields(v)}]
    if isinstance(v,dict):return ['dict',[[pack(k),pack(x)] for k,x in v.items()]]
    if isinstance(v,(list,tuple,set)):return [type(v).__name__,[pack(x) for x in v]]
    raise ExchangeError('UNSUPPORTED_PAPER_CHECKPOINT_VALUE:'+type(v).__name__)


def unpack(v):
    tag=v[0]
    if tag=='scalar':return v[1]
    if tag=='decimal':return Decimal(v[1])
    if tag=='date':return date.fromisoformat(v[1])
    if tag=='datetime':return datetime.fromisoformat(v[1])
    if tag=='dict':return {unpack(k):unpack(x) for k,x in v[1]}
    if tag in ('list','tuple','set'):return {'list':list,'tuple':tuple,'set':set}[tag](unpack(x) for x in v[1])
    if tag=='record':return TYPES[v[1]](**{k:unpack(x) for k,x in v[2].items()})
    if tag=='enum':return TYPES[v[1]](v[2])
    raise ExchangeError('UNKNOWN_PAPER_CHECKPOINT_TYPE')


def capture(obj,names):return {name:getattr(obj,name) for name in names}
def restore(obj,values,names):
    if set(values)!=set(names):raise ExchangeError('PAPER_CHECKPOINT_SCHEMA_MISMATCH')
    for name in names:setattr(obj,name,values[name])


class PaperCheckpoint:
    def __init__(self,path,identity):
        require_paper_migration()
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.identity=identity
        self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS paper_state (id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL,sha256 TEXT NOT NULL)')
        self.db.commit()
        self.path.chmod(0o600)

    def save(self,bot,*,clean=False):
        require_paper_migration()
        e=bot.execution
        value=dict(version=1,identity=self.identity,clean=clean,observed_ms=bot.clock_ms(),specs=e.specs,
            bot=capture(bot,BOT_FIELDS),execution=capture(e,EXEC_FIELDS),ledger=capture(e.portfolio,LEDGER_FIELDS),
            managers={s:capture(m,MANAGER_FIELDS) for s,m in bot.managers.items()},
            breakers=capture(bot.breakers,BREAK_FIELDS),funnel=bot.funnel.traces)
        data=json.dumps(pack(value),separators=(',',':'),allow_nan=False)
        if len(data.encode())>128*1024*1024:raise ExchangeError('PAPER_CHECKPOINT_SIZE_LIMIT')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO paper_state VALUES (1,?,?)',(data,hashlib.sha256(data.encode()).hexdigest()))

    def load(self,bot):
        require_paper_migration()
        row=self.db.execute('SELECT data,sha256 FROM paper_state WHERE id=1').fetchone()
        if row is None:return dict(restored=False,exchange_account_verified=False)
        try:
            if hashlib.sha256(row[0].encode()).hexdigest()!=row[1]:raise ValueError('checksum')
            value=unpack(json.loads(row[0]))
            if value['version']!=1 or value['identity']!=self.identity or value['specs']!=bot.execution.specs:
                raise ExchangeError('PAPER_CHECKPOINT_IDENTITY_OR_POLICY_MISMATCH')
            restore(bot,value['bot'],BOT_FIELDS)
            restore(bot.execution,value['execution'],EXEC_FIELDS)
            restore(bot.execution.portfolio,value['ledger'],LEDGER_FIELDS)
            restore(bot.breakers,value['breakers'],BREAK_FIELDS)
            for s,fields_ in value['managers'].items():restore(bot._manager(s),fields_,MANAGER_FIELDS)
            bot.funnel.traces=value['funnel']
            held=bool(bot.execution.portfolio.positions)
            unresolved=any(o.status in {'OPEN','PARTIALLY_FILLED'} for o in bot.execution.orders.values())
            if held or unresolved:
                raise ExchangeError('PAPER_DOWNTIME_WITH_EXPOSURE_REQUIRES_REPLAY_REVIEW')
            # Rebuild quantities/cash from the same saved fill/funding facts.
            before=(bot.execution.portfolio.cash,dict(bot.execution.portfolio.positions))
            report=PaperReconciliation(bot.execution).recover(bot.managers)
            if report['entries_paused'] or before!=(bot.execution.portfolio.cash,dict(bot.execution.portfolio.positions)):
                raise ExchangeError('PAPER_CHECKPOINT_LEDGER_CONFLICT')
            # Lost observation time cannot be reconstructed from today's quote.
            bot.breakers.pause('stream','STREAM_RECOVERY_REQUIRED')
            return dict(restored=True,previous_clean_shutdown=value['clean'],observed_ms=value['observed_ms'],
                paper_reconciliation=report,exchange_account_verified=False,
                note='Same cumulative PAPER ledger; new evidence segment. Missing candles/funding never invented.')
        except ExchangeError:raise
        except Exception as exc:raise ExchangeError('PAPER_CHECKPOINT_CORRUPT') from exc

    def backup(self,path):
        target=Path(path)
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        destination=sqlite3.connect(target)
        try:self.db.backup(destination)
        finally:destination.close()
        target.chmod(0o600)

    def close(self):self.db.close()
