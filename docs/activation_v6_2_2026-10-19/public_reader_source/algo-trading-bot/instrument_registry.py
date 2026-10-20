"""Authoritative broker-master resolution; no downstream token reconstruction."""
import json
from datetime import datetime
from pathlib import Path
from execution_safety import InstrumentIdentity, SafetyError
import config

class InstrumentRegistry:
    def __init__(self,records,source_timestamp,intraday_symbols,restricted_symbols=()):
        self.by_symbol={}; self.by_token={}
        eligible=set(intraday_symbols)-set(restricted_symbols)
        for row in records:
            if row.get('exch_seg')!='NSE' or not str(row.get('symbol','')).endswith('-EQ'):continue
            trading=row['symbol']; symbol=trading[:-3]
            if symbol not in eligible:continue
            identity=InstrumentIdentity(symbol,'NSE',str(row['token']),trading,'EQ',float(row['tick_size'])/100.,
                int(row['lotsize']),row.get('instrumenttype') or 'CASH',source_timestamp,True)
            identity.validate(symbol,now=source_timestamp)
            if symbol in self.by_symbol or identity.token in self.by_token:raise SafetyError('AMBIGUOUS_INSTRUMENT_MASTER')
            self.by_symbol[symbol]=identity; self.by_token[identity.token]=identity

    @classmethod
    def load(cls,path,now):
        if not path:raise SafetyError('INSTRUMENT_MASTER_UNAVAILABLE')
        data=json.loads(Path(path).read_text()); stamp=datetime.fromisoformat(data['source_timestamp'])
        registry=cls(data['records'],stamp,data['intraday_symbols'],data.get('restricted_symbols',[]))
        for identity in registry.by_symbol.values():identity.validate(identity.symbol,now=now)
        if not registry.by_symbol:raise SafetyError('EMPTY_ELIGIBLE_UNIVERSE')
        return registry

    def resolve(self,symbol,token=None,now=None):
        base=symbol[:-3] if symbol.endswith('-EQ') else symbol
        identity=self.by_symbol.get(base)
        if identity is None:raise SafetyError('INSTRUMENT_IDENTITY_MISMATCH')
        identity.validate(symbol,token,now=now); return identity

    def candidates(self,preferred=()):
        # Include configured symbols first, then expand deterministically from verified eligibility.
        ordered=list(dict.fromkeys(list(preferred)+sorted(self.by_symbol)))
        return [{'symbol':i.symbol,'trading_symbol':i.trading_symbol,'token':i.token,'exchange':i.exchange,'instrument':i}
                for s in ordered if (i:=self.by_symbol.get(s))][:config.MAX_DISCOVERY_CANDIDATES]
