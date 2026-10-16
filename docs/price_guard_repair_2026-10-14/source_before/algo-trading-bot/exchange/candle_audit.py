"""Optional bounded public-candle provenance. Never records account or key data."""
from dataclasses import asdict, is_dataclass
from decimal import Decimal
import json
from pathlib import Path
import threading
import time

from .base_exchange import ExchangeError


class PublicCandleAudit:
    def __init__(self, path, *, max_bytes=256*1024*1024):
        self.path=Path(path)
        self.max_bytes=max_bytes
        self.lock=threading.Lock()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.bytes=self.path.stat().st_size if self.path.exists() else 0
        self.sequence=0

    def record(self, stage, **data):
        def encode(v):
            if is_dataclass(v):return asdict(v)
            if isinstance(v,Decimal):return str(v)
            raise TypeError(type(v).__name__)
        with self.lock:
            row=dict(stage=stage,sequence=self.sequence,observed_ms=time.time_ns()//1000000,**data)
            text=json.dumps(row,default=encode,allow_nan=False,separators=(',',':'))+'\n'
            size=len(text.encode())
            if self.bytes+size>self.max_bytes:raise ExchangeError('PUBLIC_CANDLE_AUDIT_SIZE_LIMIT')
            with self.path.open('a') as stream:stream.write(text)
            self.bytes+=size;self.sequence+=1


def merge_candle(previous, incoming, now_ms):
    """A previously observed completed fact cannot silently change OHLCV.

    A row observed while open may still evolve. Unknown receive times are
    treated conservatively as completed when its exchange interval has ended.
    """
    if previous is None:return incoming
    fields=('symbol','interval','timestamp_ms','open','high','low','close','volume')
    identical=all(getattr(previous,k)==getattr(incoming,k) for k in fields)
    previous_final=previous.timestamp_ms+60000<=min(now_ms,previous.received_timestamp_ms
        if previous.received_timestamp_ms is not None else now_ms)
    incoming_final=incoming.timestamp_ms+60000<=min(now_ms,incoming.received_timestamp_ms
        if incoming.received_timestamp_ms is not None else now_ms)
    if previous_final and incoming_final and not identical:
        raise ExchangeError('CONFLICTING_COMPLETED_CANDLES')
    if previous_final and not incoming_final:return previous
    if incoming_final and not previous_final:return incoming
    return incoming if (incoming.received_timestamp_ms or 0)>=(previous.received_timestamp_ms or 0) else previous
