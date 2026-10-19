"""Strict chronological public-read replay; no sockets, signer or OHLC fill invention."""
from copy import deepcopy
from enum import Enum
import hashlib
import json
from pathlib import Path
import time

from venue_config import require_paper_migration
from .base_exchange import ExchangeError
from .event_timing import timing
from .paper_execution import PaperExecution


class ExecutionMode(str,Enum):
    REPLAY='REPLAY'
    PAPER='PAPER'
    LIVE='LIVE'


def checksum(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class PublicReplayRecorder:
    """Bounded single-owner public REST tape with every logical clock observation."""
    def __init__(self,transport,clock_ms=None):
        self.transport=transport
        self.wall_clock=clock_ms or (lambda:time.time_ns()//1_000_000)
        self.operations=[]

    def clock_ms(self):
        value=self.wall_clock()
        self.operations.append(dict(kind='clock',value=value,**timing(value)))
        return value

    def __call__(self,payload):
        if any(k in payload for k in ('action','signature','nonce','user')):
            raise ExchangeError('REPLAY_RECORD_PUBLIC_MARKET_DATA_ONLY')
        value=self.transport(payload)
        self.operations.append(dict(kind='info',payload=deepcopy(payload),response=deepcopy(value),
            **timing(self.wall_clock(),source='PUBLIC_INFO_RESPONSE_EXCHANGE_CLOCK_UNKNOWN')))
        return value

    def save(self,path,parameters,provenance):
        body=dict(schema_version=1,cycles=1,parameters=parameters,provenance=provenance,
            clock_model='RECORDED_LOGICAL_CLOCK',operations=self.operations)
        Path(path).write_text(json.dumps(dict(body,sha256=checksum(body)),separators=(',',':'),allow_nan=False)+'\n')

    def close(self):
        self.transport.close()


class ReplayTape:
    def __init__(self,value):
        require_paper_migration()
        value=deepcopy(value)
        expected=value.pop('sha256',None)
        if checksum(value)!=expected or value.get('schema_version')!=1 or value.get('cycles')!=1:
            raise ExchangeError('REPLAY_TAPE_CHECKSUM_OR_SCHEMA_INVALID')
        if value.get('clock_model')!='RECORDED_LOGICAL_CLOCK' or not isinstance(value.get('operations'),list):
            raise ExchangeError('REPLAY_TAPE_SCHEMA_INVALID')
        self.parameters=value['parameters']
        self.provenance=value['provenance']
        self.operations=value['operations']
        self.cursor=0
        self.previous_clock=-1
        self.closed=False

    def _peek(self,kind):
        if self.cursor>=len(self.operations) or self.operations[self.cursor].get('kind')!=kind:
            raise ExchangeError('REPLAY_OPERATION_MISMATCH')
        return self.operations[self.cursor]

    def _next(self,kind):
        event=self._peek(kind)
        self.cursor+=1
        return event

    def clock_ms(self):
        value=self._next('clock')['value']
        if type(value) is not int or value<self.previous_clock:
            raise ExchangeError('REPLAY_NON_CAUSAL_CLOCK')
        self.previous_clock=value
        return value

    def __call__(self,payload):
        require_paper_migration()
        if any(k in payload for k in ('action','signature','nonce','user')):
            raise ExchangeError('REPLAY_PUBLIC_READ_ONLY')
        event=self._peek('info')
        if event['payload']!=payload:
            raise ExchangeError('REPLAY_REQUEST_MISMATCH_NO_FUTURE_DATA')
        self.cursor+=1
        return deepcopy(event['response'])

    def finish(self):
        if self.cursor!=len(self.operations):
            raise ExchangeError('REPLAY_UNCONSUMED_OPERATIONS')
        return dict(consumed_operations=self.cursor,source=self.provenance,exchange_orders_submitted=0)

    def close(self):
        self.closed=True


class ReplayExecution(PaperExecution):
    """Same precision, BBO fill and accounting kernel, with deterministic local IDs.

    Runtime safety settings stay PAPER/false. REPLAY describes the offline data
    source of this run; it never grants exchange-write permission.
    """
    execution_mode='REPLAY'

    def __init__(self,*args,**kwargs):
        self.sequence=0
        kwargs['id_factory']=self._id
        super().__init__(*args,**kwargs)

    def _id(self,prefix):
        self.sequence+=1
        return f'replay-{prefix}{self.sequence:08d}'
