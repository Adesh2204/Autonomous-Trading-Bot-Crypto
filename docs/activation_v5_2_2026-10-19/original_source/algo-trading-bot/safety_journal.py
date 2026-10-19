"""Durable, environment-isolated, idempotent execution journal and risk reservations."""
import json
import sqlite3
import math
import config
from collections import Counter
from datetime import datetime
from pathlib import Path

class SafetyJournal:
    def __init__(self,path,environment):
        if environment not in {'TEST','BACKTEST','REPLAY','PAPER','SHADOW','LIVE'}:
            raise ValueError('INVALID_ENVIRONMENT')
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.environment=environment
        self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS budgets(day TEXT PRIMARY KEY,loss REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,day TEXT NOT NULL,risk REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,day TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY,day TEXT NOT NULL,payload TEXT NOT NULL);
        ''')
        old=self.db.execute("SELECT value FROM meta WHERE key='environment'").fetchone()
        if old and old[0]!=environment:
            self.db.close(); raise ValueError('ENVIRONMENT_MISMATCH')
        with self.db:self.db.execute("INSERT OR IGNORE INTO meta VALUES('environment',?)",(environment,))
        self.day=None

    def start_day(self,day):
        self.day=str(day)
        with self.db:self.db.execute('INSERT OR IGNORE INTO budgets(day) VALUES(?)',(self.day,))

    def budget(self):
        row=self.db.execute('SELECT loss,attempts FROM budgets WHERE day=?',(self.day,)).fetchone()
        return row or (0.,0)

    def remaining(self,limit):
        reserved=self.db.execute('SELECT COALESCE(SUM(risk),0) FROM reservations').fetchone()[0]
        return max(0.,limit-self.budget()[0]-reserved)

    def can_reserve(self,risk,limit): return risk<=self.remaining(limit)

    def reserve(self,id,risk,limit=None):
        if not math.isfinite(risk) or risk<=0:raise ValueError('INVALID_RISK_RESERVATION')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing=self.db.execute('SELECT id FROM reservations').fetchall()
            if any(row[0]!=id for row in existing):raise ValueError('POSITION_ALREADY_OPEN')
            if not existing and self.budget()[1]>=config.MAX_NEW_SETUPS:raise ValueError('MAX_NEW_SETUPS_REACHED')
            if limit is not None and not self.can_reserve(risk,limit): raise ValueError('DAILY_RISK_EXHAUSTED')
            cur=self.db.execute('INSERT OR IGNORE INTO reservations VALUES(?,?,?)',(id,self.day,risk))
            if cur.rowcount:self.db.execute('UPDATE budgets SET attempts=attempts+1 WHERE day=?',(self.day,))
            self.db.commit()
        except Exception:
            self.db.rollback(); raise

    def reservations(self):
        return list(self.db.execute('SELECT id,day,risk FROM reservations'))

    def release(self,id):
        with self.db:self.db.execute('DELETE FROM reservations WHERE id=?',(id,))

    def update_reservation(self,id,risk):
        with self.db:self.db.execute('UPDATE reservations SET risk=? WHERE id=?',(risk,id))

    def finish(self,id,pnl,trade=None):
        # Trade insertion and risk release are one transaction. Duplicate closes cannot spend risk twice.
        with self.db:
            cur=self.db.execute('INSERT OR IGNORE INTO trades VALUES(?,?,?)',(id,self.day,json.dumps(trade or {'net_pnl':pnl},default=str)))
            if cur.rowcount:
                self.db.execute('UPDATE budgets SET loss=loss+? WHERE day=?',(max(0.,-pnl),self.day))
                self.db.execute('DELETE FROM reservations WHERE id=?',(id,))
                self.db.execute("DELETE FROM meta WHERE key='position'")
            return bool(cur.rowcount)

    def save_position(self,position):
        with self.db:
            if position is None:self.db.execute("DELETE FROM meta WHERE key='position'")
            else:self.db.execute("INSERT OR REPLACE INTO meta VALUES('position',?)",(json.dumps(position,default=str),))

    def load_position(self):
        row=self.db.execute("SELECT value FROM meta WHERE key='position'").fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self,key,value):
        with self.db:self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value,default=str)))

    def get_meta(self,key):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def record_fill(self,fill):
        with self.db:
            key=str(fill['order_id'])+':'+str(fill['fill_id'])
            previous=self.db.execute('SELECT payload FROM fills WHERE id=?',(key,)).fetchone()
            if previous and json.loads(previous[0])!=fill:raise ValueError('CONFLICTING_DUPLICATE_FILL')
            cur=self.db.execute('INSERT OR IGNORE INTO fills VALUES(?,?,?)',
                (key,fill['order_id'],json.dumps(fill,default=str)))
            return bool(cur.rowcount)

    def fills(self):return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM fills')]

    def event(self,id,kind,payload):
        with self.db:self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',(id,self.day or '',kind,json.dumps(payload,default=str)))

    def trades(self):return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM trades WHERE day=?',(self.day,))]

    def report(self):
        events=list(self.db.execute('SELECT kind,payload FROM events WHERE day=?',(self.day,)))
        counts=Counter(k for k,_ in events); trades=self.trades()
        reasons=Counter(json.loads(p).get('reason','UNKNOWN') for k,p in events if k=='REJECTED')
        signals=[json.loads(p) for k,p in events if k=='SIGNAL']
        if not signals:signals=[json.loads(p) for k,p in events if k=='SIGNAL_CREATED']
        pnls=[t['net_pnl'] for t in trades]; positive=sum(p for p in pnls if p>0); loss=-sum(p for p in pnls if p<0)
        equity=peak=drawdown=0.
        for p in pnls: equity+=p; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
        counters={'symbols_scanned':counts['SCREENED'],'symbols_tradeable':counts['TRADEABLE'],
            'symbols_ranked':len({json.loads(p).get('symbol') for k,p in events if k=='WATCHLIST'}),'signals_generated':len(signals),
            'signals_long':sum(s.get('side')=='BUY' for s in signals),'signals_short':sum(s.get('side')=='SELL' for s in signals),
            'execution_rejections':sum(v for k,v in reasons.items() if k in {'QUOTE_STALE','NO_VALID_BID_ASK','SPREAD_TOO_WIDE','DEPTH_INSUFFICIENT'}),
            'friction_rejections':reasons['FRICTION_FAILED']+reasons['NO_ECONOMICALLY_VALID_QUANTITY'],
            'risk_rejections':reasons['DAILY_RISK_EXHAUSTED']+reasons['MAX_NEW_SETUPS_REACHED'],
            'orders_submitted':counts['ORDER_SUBMITTED'],'orders_filled':counts['FILLED']+counts['PARTIALLY_FILLED'],
            'broker_rejections':reasons['BROKER_ORDER_REJECTED'],'partial_fills':counts['PARTIALLY_FILLED']+counts['PARTIALLY_EXITED'],
            'trades_completed':len(trades),'unexpected_exceptions':counts['EXCEPTION']}
        watchlist={}
        for k,p in events:
            if k=='WATCHLIST':
                row=json.loads(p); symbol=row.get('symbol')
                watchlist[symbol]=dict(watchlist.get(symbol,{}),**row)
        mark=self.get_meta('intraday_mark') or {}
        if mark.get('day')!=self.day:mark={}
        position_id=(self.load_position() or {}).get('trade_id')
        reservations=self.reservations()
        return {'market_date':self.day,'environment':self.environment,'counts':dict(counts),'counters':counters,
            'watchlist':sorted(watchlist.values(),key=lambda row:(row.get('rank',999),row.get('symbol',''))),
            'rejections':dict(reasons),'completed_trades':len(trades),
            'gross_pnl':sum(t.get('gross_pnl',0) for t in trades),
            'fees':sum(t.get('entry_fees',0)+t.get('exit_fees',0) for t in trades),
            'net_pnl':sum(pnls),'net_expectancy':sum(pnls)/len(pnls) if pnls else None,
            'profit_factor':positive/loss if loss else None,'largest_win':max((p for p in pnls if p>0),default=0),
            'largest_loss':min((p for p in pnls if p<0),default=0),'realized_peak_drawdown':drawdown,
            'peak_intraday_drawdown':mark.get('drawdown',0.),'intraday_mark_basis':mark.get('basis'),
            'risk_consumed':self.budget()[0],'attempts':self.budget()[1],
            'reserved_or_open_risk':sum(r[2] for r in reservations),
            'pending_order_risk':sum(r[2] for r in reservations if r[0]!=position_id),
            'current_open_risk':sum(r[2] for r in reservations if r[0]==position_id),
            'pending_operation':self.get_meta('pending_operation'),
            'quarantine':self.get_meta('quarantine'),
            'recovered_exposure':self.get_meta('recovered_exposure'),
            'fee_basis':'BROKER_OR_ESTIMATED_PENDING' if self.environment=='LIVE' else 'SIMULATED_STANDARD',
            'fees_pending_broker_confirmation':self.environment=='LIVE' and any(t.get('entry_fee_source')!='BROKER' or
                any(s!='BROKER' for s in t.get('exit_fee_sources',[])) for t in trades),
            'maximum_adverse_excursion':min((t.get('mae',0.) for t in trades),default=0.),
            'maximum_favourable_excursion':max((t.get('mfe',0.) for t in trades),default=0.),
            'average_entry_slippage':sum(t.get('entry_slippage',0.) for t in trades)/len(trades) if trades else None,
            'no_trade_explanation':dict(reasons) if not trades else None}

    def close(self):self.db.close()
