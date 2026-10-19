"""Crash-safe authentic completed candles; no filling gaps or changing indicators."""
from dataclasses import asdict
from pathlib import Path
import json, sqlite3, threading
from .base_exchange import Candle, ExchangeError, decimal, decimal_string
from .execution_journal import fingerprint


class DurableHistory:
    def __init__(self,path,client,receipt_path):
        self.path=Path(path);self.lock=threading.RLock();self.client=client;self.receipt_path=str(receipt_path)
        self.db=sqlite3.connect(self.path,check_same_thread=False)
        self.db.execute('pragma journal_mode=WAL');self.db.execute('pragma synchronous=FULL')
        if self.db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ExchangeError('HISTORY_INTEGRITY_FAILED')
        self.db.execute('create table if not exists identity (id integer primary key check(id=1), binding text not null)')
        binding=fingerprint(dict(venue=client.dex,token=client.collateral_token_id,
            markets={s:dict(asset=client.market(s).asset_id,decimals=client.market(s).size_decimals) for s in client.markets}))
        self.binding=binding
        prior=self.db.execute('select binding from identity where id=1').fetchone()
        if prior and prior[0]!=binding:
            self.db.close();raise ExchangeError('HISTORY_CANONICAL_MARKET_BINDING_CHANGED')
        self.db.execute('insert or ignore into identity values(1,?)',(binding,))
        self.db.execute('create table if not exists bars (symbol text, t integer, payload text not null, payload_hash text not null, observed_ms integer not null, primary key(symbol,t))')
        self.db.execute('create table if not exists observations (seq integer primary key, symbol text, observed_ms integer, raw_count integer, valid_count integer, provenance text)')
        self.db.commit()

    def require_binding(self):
        current=fingerprint(dict(venue=self.client.dex,token=self.client.collateral_token_id,
            markets={s:dict(asset=self.client.market(s).asset_id,decimals=self.client.market(s).size_decimals) for s in self.client.markets}))
        if current!=self.binding:raise ExchangeError('HISTORY_CANONICAL_MARKET_BINDING_CHANGED')

    def record(self,stage,**value):
        # Existing normalizer invokes this only for real normalized REST data.
        if stage!='NORMALIZED_REST':return
        self.ingest(value['symbol'],value['candles'],now_ms=value['as_of_ms'],raw_count=value['raw_count'],source='NORMALIZED_REST')

    def ingest(self,symbol,candles,*,now_ms,raw_count=None,source='NORMALIZED_STREAM_OR_REST'):
        self.require_binding();self.client.market(symbol)
        if type(now_ms) is not int:raise ExchangeError('HISTORY_CLOCK_REQUIRED')
        rows={}
        for c in candles:
            if (c.symbol!=symbol or c.interval!='1m' or type(c.timestamp_ms) is not int or c.timestamp_ms%60000
                or c.close_timestamp_ms not in (c.timestamp_ms+59999,c.timestamp_ms+60000) or c.timestamp_ms+60000>now_ms
                or not decimal(c.low,positive=True)<=decimal(c.open,positive=True)<=decimal(c.high,positive=True)
                or not c.low<=decimal(c.close,positive=True)<=c.high):raise ExchangeError('INVALID_COMPLETED_HISTORY_BAR')
            decimal(c.volume,nonnegative=True)
            payload={k:decimal_string(v) if k in ('open','high','low','close','volume') else v for k,v in asdict(c).items()
                if k not in ('received_timestamp_ms','processed_timestamp_ms')}
            payload['close_timestamp_ms']=c.timestamp_ms+59999
            h=fingerprint(payload)
            if c.timestamp_ms in rows and rows[c.timestamp_ms][1]!=h:raise ExchangeError('HISTORY_COMPLETED_CONFLICT')
            rows[c.timestamp_ms]=(json.dumps(payload,sort_keys=True),h)
        with self.lock,self.db:
            for t,(payload,h) in rows.items():
                prior=self.db.execute('select payload,payload_hash from bars where symbol=? and t=?',(symbol,t)).fetchone()
                if prior:
                    old=json.loads(prior[0])
                    if fingerprint(old)!=prior[1]:raise ExchangeError('HISTORY_PAYLOAD_HASH_MISMATCH')
                    old={k:decimal_string(v) if k in ('open','high','low','close','volume') else v for k,v in old.items()}
                    if fingerprint(old)!=h:raise ExchangeError('HISTORY_COMPLETED_CONFLICT')
                self.db.execute('insert or ignore into bars values(?,?,?,?,?)',(symbol,t,payload,h,now_ms))
            self.db.execute('insert into observations(symbol,observed_ms,raw_count,valid_count,provenance) values(?,?,?,?,?)',
                (symbol,now_ms,raw_count,len(rows),json.dumps(dict(receipts=self.receipt_path,source=source,payload_hash=fingerprint(rows)),sort_keys=True)))
            # At most 6,000 genuine minutes per market; no synthetic retention.
            self.db.execute('delete from bars where symbol=? and t not in (select t from bars where symbol=? order by t desc limit 6000)',(symbol,symbol))
            self.db.execute('delete from observations where seq not in (select seq from observations order by seq desc limit 10000)')

    def read(self,symbol,now_ms):
        self.require_binding();self.client.market(symbol)
        with self.lock:
            rows=self.db.execute('select payload,payload_hash from bars where symbol=? order by t',(symbol,)).fetchall()
        bars=[]
        for payload,h in rows:
            p=json.loads(payload)
            if fingerprint(p)!=h:raise ExchangeError('HISTORY_PAYLOAD_HASH_MISMATCH')
            if p['timestamp_ms']+60000>now_ms:continue
            bars.append(Candle(**{k:decimal(v) if k in ('open','high','low','close','volume') else v for k,v in p.items()}))
        return bars

    def report(self,symbol,now_ms):
        bars=self.read(symbol,now_ms)
        with self.lock:
            obs=self.db.execute('select observed_ms,raw_count,valid_count from observations where symbol=? order by seq desc limit 1',(symbol,)).fetchone()
            raw=self.db.execute('select raw_count from observations where symbol=? and raw_count is not null order by seq desc limit 1',(symbol,)).fetchone()
            raw_total=self.db.execute('select sum(raw_count) from observations where symbol=?',(symbol,)).fetchone()[0]
        gaps=[dict(start_ms=a.timestamp_ms+60000,end_ms=b.timestamp_ms-60000,count=(b.timestamp_ms-a.timestamp_ms)//60000-1)
            for a,b in zip(bars,bars[1:]) if b.timestamp_ms-a.timestamp_ms!=60000]
        contiguous=0
        for c in reversed(bars):
            if contiguous and bars[-contiguous].timestamp_ms-c.timestamp_ms!=60000:break
            contiguous+=1
        age=now_ms-(bars[-1].timestamp_ms+60000) if bars else None
        relevant_start=min(now_ms//60000*60000-900*60000,(now_ms-1)//86400000*86400000-14*60000)
        relevant_gap=any(g['end_ms']>=relevant_start for g in gaps)
        return dict(raw_returned_last=raw[0] if raw else None,raw_returned_in_retained_snapshots=raw_total,valid_returned_last=obs[2] if obs else None,
            valid_deduplicated_completed=len(bars),contiguous_tail_bars=contiguous,missing_intervals=gaps,
            earliest_ms=bars[0].timestamp_ms if bars else None,latest_ms=bars[-1].timestamp_ms if bars else None,
            latest_completed_ms=bars[-1].timestamp_ms+60000 if bars else None,cache_age_ms=age,
            last_collection_ms=obs[0] if obs else None,warmup_required=300,
            strategy_history_ready=contiguous>=300 and not relevant_gap and age is not None and 0<=age<=120000,
            provenance='CANONICAL_EXCHANGE_COMPLETED_CANDLES_ONLY',database=str(self.path))

    def close(self):
        with self.lock:
            self.db.execute('pragma wal_checkpoint(TRUNCATE)');self.db.close()
