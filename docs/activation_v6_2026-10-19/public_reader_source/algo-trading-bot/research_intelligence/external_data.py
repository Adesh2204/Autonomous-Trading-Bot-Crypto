"""Isolated, opt-in source comparison. No native cache, wallet or execution API.

Research candles intentionally do not use par symbols or the native Candle type.
Provider keys are not read here. All observed times remain original provenance.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal
import json
from typing import Protocol

from exchange.base_exchange import ExchangeError, decimal

NATIVE_UNITS={'par:BTC':'USD_PER_BTC','par:ETH':'USD_PER_ETH','par:HYPE':'USD_PER_HYPE',
    'par:SP500':'INDEX_POINTS','par:EWY':'USD_PER_SHARE','par:EWJ':'USD_PER_SHARE',
    'par:BRENT':'USD_PER_BARREL','par:GOLD':'USD_PER_TROY_OUNCE',
    'par:USDEUR':'USD_PER_EUR','par:USDJPY':'JPY_PER_USD'}


@dataclass(frozen=True)
class ResearchCandle:
    source_id: str
    symbol: str
    timestamp_ms: int
    close_timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    volume_units: str
    price_units: str
    observed_at_ms: int
    validation_status: str = 'VALIDATED_PUBLIC_RESEARCH_RECORD'
    interval: str = '1m'

    def __post_init__(self):
        if (not self.source_id or not self.symbol or self.symbol.startswith('par:') or
                self.interval!='1m' or type(self.timestamp_ms) is not int or self.timestamp_ms%60000 or
                self.close_timestamp_ms not in {self.timestamp_ms+59999,self.timestamp_ms+60000} or
                type(self.observed_at_ms) is not int or self.observed_at_ms<self.timestamp_ms+60000 or
                not self.price_units or not self.volume_units or
                self.validation_status!='VALIDATED_PUBLIC_RESEARCH_RECORD'):
            raise ExchangeError('EXTERNAL_PROVENANCE_OR_BOUNDARIES_INVALID')
        for k in ('open','high','low','close'):
            object.__setattr__(self,k,decimal(getattr(self,k),positive=True))
        if self.high<max(self.open,self.low,self.close) or self.low>min(self.open,self.high,self.close):
            raise ExchangeError('EXTERNAL_OHLC_INVALID')
        if self.volume is not None:object.__setattr__(self,'volume',decimal(self.volume,nonnegative=True))


@dataclass(frozen=True)
class AssetMapping:
    native_symbol: str
    source_id: str
    source_symbol: str
    price_units: str
    fx_direction: str | None = None
    volume_units: str = 'UNVERIFIED'
    comparable_volume: bool = False
    review_reference: str | None = None
    instrument_status: str = 'EXTERNAL_SOURCE_UNVERIFIED'

    def validate(self, candle, *, for_vwap=False):
        if (self.native_symbol not in NATIVE_UNITS or self.source_symbol.startswith('par:') or
                candle.source_id!=self.source_id or candle.symbol!=self.source_symbol or
                not self.review_reference or self.instrument_status not in {
                    'EXTERNAL_SOURCE_VALIDATED_FOR_RESEARCH','EXTERNAL_SOURCE_POTENTIALLY_COMPATIBLE'}):
            raise ExchangeError('EXTERNAL_INSTRUMENT_MAPPING_UNVERIFIED')
        if candle.price_units!=self.price_units or self.price_units!=NATIVE_UNITS[self.native_symbol]:
            raise ExchangeError('EXTERNAL_PRICE_UNITS_MISMATCH')
        expected={'par:USDEUR':'USD_PER_EUR','par:USDJPY':'JPY_PER_USD'}
        if self.native_symbol in expected and (self.fx_direction!=expected[self.native_symbol] or
                                               self.price_units!=expected[self.native_symbol]):
            raise ExchangeError('EXTERNAL_FX_DIRECTION_MISMATCH')
        if for_vwap and (self.comparable_volume is not True or candle.volume is None or
                candle.volume_units!=self.volume_units or candle.volume_units in {'TICK','UNKNOWN','UNVERIFIED','NONE'}):
            raise ExchangeError('EXTERNAL_VOLUME_NOT_COMPARABLE_FOR_VWAP')


class MarketDataSource(Protocol):
    source_id: str
    def get_candles(self, symbol: str, start_ms: int, end_ms: int) -> tuple[ResearchCandle,...]: ...


class RecordedMarketDataSource:
    def __init__(self, candles, *, research_enabled=False):
        if research_enabled is not True:raise ExchangeError('EXTERNAL_RESEARCH_DISABLED')
        self.records=tuple(candles)
        if not self.records or len({c.source_id for c in self.records})!=1:
            raise ExchangeError('EXTERNAL_SOURCE_ID_REQUIRED')
        self.source_id=self.records[0].source_id

    def get_candles(self, symbol, start_ms, end_ms):
        return tuple(c for c in self.records if c.symbol==symbol and start_ms<=c.timestamp_ms<=end_ms)


class HyperliquidReferenceSource:
    """Bounded public mainnet reads for research; a distinct trust boundary.

    Only two metadata reads plus one candle read per requested reference. Uses
    the established weighted rate manager supplied by a research-only runner.
    No /exchange URL, signer, account query, mutable cache or fallback exists.
    """
    source_id='HYPERLIQUID_MAINNET_REFERENCE'
    URL='https://api.hyperliquid.xyz/info'
    ALLOWED=('BTC','ETH','HYPE','xyz:SP500','xyz:EWY','xyz:EWJ','xyz:BRENTOIL','xyz:GOLD','xyz:EUR','xyz:JPY')

    def __init__(self, *, rates, clock_ms, research_enabled=False, transport=None):
        if research_enabled is not True:raise ExchangeError('EXTERNAL_RESEARCH_DISABLED')
        self.rates=rates;self.clock_ms=clock_ms;self._transport=transport;self.reads=0
        self.evidence=[];self.metadata={}

    def _read(self, payload):
        if payload.get('type') not in {'meta','candleSnapshot'} or self.reads>=12:
            raise ExchangeError('EXTERNAL_PUBLIC_READ_SCOPE_OR_BUDGET')
        self.reads+=1
        def operation():
            if self._transport:return self._transport(payload)
            raise ExchangeError('EXTERNAL_PUBLIC_TRANSPORT_REQUIRED')
        req=payload.get('req',{})
        expected=(req.get('endTime',0)-req.get('startTime',0))//60000+1 if req else 0
        result=self.rates.read(payload['type'],operation,request_key='external:'+json.dumps(payload,sort_keys=True),expected_items=expected)
        self.evidence.append(dict(request=payload,response=result,observed_at_ms=self.clock_ms(),
            source_id=self.source_id,network='mainnet',purpose='RESEARCH_ONLY'))
        return result

    def get_candles(self, symbol, start_ms, end_ms):
        if (symbol not in self.ALLOWED or type(start_ms) is not int or type(end_ms) is not int or
                start_ms%60000 or end_ms<start_ms or (end_ms-start_ms)//60000+1>5000):
            raise ExchangeError('EXTERNAL_REFERENCE_RANGE_OR_SYMBOL_INVALID')
        dex='xyz' if symbol.startswith('xyz:') else ''
        if dex not in self.metadata:
            meta=self._read(dict(type='meta',dex=dex))
            if not isinstance(meta,dict) or not isinstance(meta.get('universe'),list):
                raise ExchangeError('EXTERNAL_REFERENCE_METADATA_INVALID')
            self.metadata[dex]={r['name']:r for r in meta['universe'] if not r.get('isDelisted')}
        if symbol not in self.metadata[dex]:raise ExchangeError('EXTERNAL_REFERENCE_NOT_LISTED')
        raw=self._read(dict(type='candleSnapshot',req=dict(coin=symbol,interval='1m',startTime=start_ms,endTime=end_ms)))
        if not isinstance(raw,list):raise ExchangeError('EXTERNAL_RESPONSE_INVALID')
        observed=self.clock_ms();bars={}
        # Price/volume units must be independently reviewed before strategy use.
        units={'BTC':'USD_PER_BTC','ETH':'USD_PER_ETH','HYPE':'USD_PER_HYPE',
            'xyz:SP500':'INDEX_POINTS','xyz:EWY':'USD_PER_SHARE','xyz:EWJ':'USD_PER_SHARE',
            'xyz:BRENTOIL':'USD_PER_BARREL','xyz:GOLD':'USD_PER_TROY_OUNCE',
            'xyz:EUR':'USD_PER_EUR','xyz:JPY':'JPY_PER_USD'}
        for r in raw:
            if r.get('s')!=symbol or r.get('i')!='1m' or not start_ms<=r.get('t',-1)<=end_ms:
                raise ExchangeError('EXTERNAL_REFERENCE_IDENTITY_INVALID')
            if r['t']+60000>observed:continue
            c=ResearchCandle(self.source_id,symbol,r['t'],r['T'],r['o'],r['h'],r['l'],r['c'],
                r['v'],'REFERENCE_CONTRACT_UNITS_UNVERIFIED',units[symbol],observed)
            prior=bars.get(c.timestamp_ms)
            if prior is not None and prior!=c:raise ExchangeError('EXTERNAL_COMPLETED_CONFLICT')
            bars[c.timestamp_ms]=c
        return tuple(bars[t] for t in sorted(bars))


def require_feature_history(candles, decision_ms):
    """Same UTC request scope and freshness contract, never a 300-bar shortcut."""
    from datetime import datetime,timezone
    from session_manager import SessionManager
    if len(candles)<300:raise ExchangeError('EXTERNAL_FEATURE_HISTORY_INSUFFICIENT')
    end=decision_ms//60000*60000-1
    anchor=int(SessionManager().get_vwap_anchor(datetime.fromtimestamp(decision_ms/1000,timezone.utc)).timestamp()*1000)
    required_start=min(end+1-300*60000,anchor-14*60000)
    if candles[0].timestamp_ms>required_start:
        raise ExchangeError('EXTERNAL_FULL_UTC_HISTORY_INCOMPLETE')
    if not 0<=decision_ms-(candles[-1].timestamp_ms+60000)<=120000:
        raise ExchangeError('EXTERNAL_FEATURE_HISTORY_STALE')


def frozen_features(candles, mapping, *, decision_ms):
    """Only isolated research calls the frozen calculations; no strategy state."""
    require_feature_history(candles,decision_ms)
    for c in candles:mapping.validate(c,for_vwap=True)
    from strategy_freeze import verify_strategy_freeze
    from candle_normalizer import candles_to_frame
    from signal_brain import generate_vwap_signal
    verify_strategy_freeze()
    return generate_vwap_signal(candles_to_frame(candles))


def compare_sources(native, external, mapping, *, decision_ms, quote=None, max_external_age_ms=120000):
    """An as-of comparison; late downloads cannot be inserted at earlier decisions."""
    for c in external:mapping.validate(c)
    n={c.timestamp_ms:c for c in native if c.symbol==mapping.native_symbol and
        c.timestamp_ms+60000<=decision_ms and c.received_timestamp_ms is not None and c.received_timestamp_ms<=decision_ms}
    e={c.timestamp_ms:c for c in external if c.timestamp_ms+60000<=decision_ms and c.observed_at_ms<=decision_ms}
    times=sorted(set(n)&set(e))
    stale=not e or not 0<=decision_ms-(max(e)+60000)<=max_external_age_ms
    matches=[dict(timestamp_ms=t,native_close=str(n[t].close),external_close=str(e[t].close),
        absolute_difference=str(e[t].close-n[t].close),
        difference_bps=str((e[t].close/n[t].close-1)*10000)) for t in times]
    indicators=None;reason='NOT ENOUGH EVIDENCE'
    try:
        if stale:raise ExchangeError('EXTERNAL_SOURCE_STALE_OR_UNAVAILABLE_AS_OF_DECISION')
        if not times:raise ExchangeError('NO_AS_OF_OVERLAP')
        last_matched=times[-1]
        external_features=frozen_features([e[t] for t in sorted(e) if t<=last_matched],mapping,decision_ms=decision_ms)
        from frozen_strategy import FrozenStrategy
        native_bars=[n[t] for t in sorted(n) if t<=last_matched]
        require_feature_history(native_bars,decision_ms)
        native_features=FrozenStrategy(None).evaluate_candles(native_bars)
        metrics=('VWAP','EMA_9','EMA_21','ATR_14')
        a=native_features.iloc[-1];b=external_features.iloc[-1]
        indicators={k:dict(native=float(a[k]),external=float(b[k]),difference=float(b[k]-a[k])) for k in metrics}
        reason=None
    except (ExchangeError, ValueError, KeyError, IndexError) as exc:reason=str(exc)
    native_quote=None
    if (quote is not None and quote.symbol==mapping.native_symbol and 0<=decision_ms-quote.timestamp_ms<=5000 and
            quote.mark_timestamp_ms is not None and 0<=decision_ms-quote.mark_timestamp_ms<=60000):
        native_quote={k:str(getattr(quote,k)) for k in ('bid','ask','mark','oracle')}
    return dict(label='EXTERNAL_RESEARCH_ONLY_NO_EXECUTION',native_symbol=mapping.native_symbol,
        external_source=mapping.source_id,external_symbol=mapping.source_symbol,decision_ms=decision_ms,
        mapping=asdict(mapping),matched_count=len(times),native_available_count=len(n),external_available_count=len(e),
        external_stale=stale,matched=matches,indicator_comparison=indicators,
        reason=reason,verdict='EXTERNAL_SOURCE_POTENTIALLY_COMPATIBLE' if matches else 'EXTERNAL_SOURCE_UNVERIFIED',
        volume_comparable=mapping.comparable_volume,live_signal_approved=False,
        native_execution_quote=native_quote,execution_truth='NATIVE_PAR_ONLY',accounting_truth='NATIVE_EXCHANGE_ONLY',
        hypothetical_fills=None,fees=None,funding_cashflows=None,risk_adjusted_outcomes=None,
        signal_count=None,signal_agreement=None,signal_timing_divergence=None,
        limitation='Reception provenance required. No retrospective replacement, inferred depth, fill or P&L. Volume-equivalence and sufficient contiguous history gate frozen-feature comparisons.')
