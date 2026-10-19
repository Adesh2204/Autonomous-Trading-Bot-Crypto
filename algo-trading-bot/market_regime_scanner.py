"""Periodic, direction-neutral selection from every active runtime par market."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import math
import time

from exchange.base_exchange import ExchangeError, decimal
from exchange.event_timing import timing
from exchange.hyperliquid_market_data import make_quote
from exchange.market_snapshot import MarketSnapshot
from exchange.market_health import MarketHealthManager,validate_history
from exchange.scanner_numeric import scanner_number
from frozen_strategy import FrozenStrategy
from session_manager import SessionManager
from venue_config import require_paper_migration


@dataclass(frozen=True)
class ScannerPolicy:
    min_atr_fraction: Decimal
    max_spread_bps: Decimal
    min_window_notional: Decimal
    min_bbo_notional: Decimal
    history_bars: int=300
    top_n: int=3
    max_candle_age_ms: int=120000

    def __post_init__(self):
        for name in ('min_atr_fraction','max_spread_bps','min_window_notional','min_bbo_notional'):
            object.__setattr__(self,name,decimal(getattr(self,name),nonnegative=True))
        if (type(self.history_bars) is not int or not 30<=self.history_bars<=3000 or
                type(self.top_n) is not int or not 1<=self.top_n<=3 or
                type(self.max_candle_age_ms) is not int or not 0<self.max_candle_age_ms<=120000):
            raise ExchangeError('INVALID_SCANNER_POLICY')


@dataclass
class MarketDiagnostic:
    symbol: str
    qualified: bool=False
    reasons: list=field(default_factory=list)
    metrics: dict=field(default_factory=dict)
    score: Decimal=Decimal(0)
    signal: dict | None=None
    candles: list=field(default_factory=list,repr=False)
    snapshot: object=None
    timing: dict=field(default_factory=dict)
    evidence: dict=field(default_factory=dict)


@dataclass
class ScanResult:
    observed_at_ms: int
    diagnostics: list
    watchlist: list
    status: str


class MarketRegimeScanner:
    def __init__(self, market, policy, *, session=None, live_authorization=None,
                 team_address=None, signer_address=None, candidate_symbols=()):
        self.market=market
        self.client=market.client
        self.policy=policy
        self.candidate_symbols=tuple(candidate_symbols)
        self.session=session or SessionManager()
        self.brain=FrozenStrategy(market,self.session)
        self.diagnostic_sink=None
        self.live_authorization=live_authorization
        self.team_address=team_address
        self.signer_address=signer_address
        self.health_manager=None
        self.public_snapshot_sink=None
        self.public_failure_sink=None

    def require_runtime(self):
        # Public scanning cannot grant an exchange-write permit. The default
        # remains PAPER; the future owner must supply its exact authorization.
        if self.live_authorization is None:
            return require_paper_migration(getattr(self.client,'dex','par'))
        from exchange.execution_safety import LiveAuthorization
        if (type(self.live_authorization) is not LiveAuthorization or
                not isinstance(self.team_address,str) or not isinstance(self.signer_address,str)):
            raise ExchangeError('SCANNER_RUNTIME_AUTHORIZATION_REQUIRED')
        self.live_authorization.require(self.team_address,self.signer_address)

    def scan(self):
        self.require_runtime()
        self.client.startup()
        p=self.policy
        from exchange.entry_scope import signal_markets
        selected=tuple(sorted(signal_markets(self.client,self.candidate_symbols)))
        if self.health_manager is None:
            self.health_manager=MarketHealthManager(selected,history_bars=p.history_bars,
                max_candle_age_ms=p.max_candle_age_ms)
        now=self.client.clock_ms()
        end=now//60000*60000-1
        anchor=int(self.session.get_vwap_anchor(datetime.fromtimestamp(now/1000,timezone.utc)).timestamp()*1000)
        start=min(end+1-p.history_bars*60000,anchor-14*60000)
        try:
            contexts=self.market.get_asset_contexts()
        except Exception:
            failed=ScanResult(now,[MarketDiagnostic(s,reasons=['MARKET_DATA_UNAVAILABLE'],
                evidence=dict(root_cause='ASSET_CONTEXT_READ_FAILED',request_time_ms=None))
                for s in selected],[],'FAILED_SAFE')
            if self.diagnostic_sink is not None:self.diagnostic_sink.observe_scan(failed,p)
            raise
        context_observed=self.client.clock_ms()
        diagnostics=[]
        for symbol in selected:
            d=MarketDiagnostic(symbol)
            diagnostics.append(d)
            d.evidence=dict(request_time_ms=None,request_cycle_observed_ms=context_observed,
                            request_time_basis='EXACT_SEND_TIME_UNAVAILABLE_NO_ADDITIONAL_CLOCK_READ',
                            expected_last_completed_candle_ms=end//60000*60000,
                            actual_last_completed_candle_ms=None,lag_seconds=None,root_cause='UNDETERMINED',
                            source=type(self.market).__name__)
            try:
                candles=self.market.get_candles(symbol,start,end,now_ms=now)
                d.candles=candles
                if candles:
                    d.evidence.update(actual_last_completed_candle_ms=candles[-1].timestamp_ms,
                        source_timestamp_ms=candles[-1].timestamp_ms,
                        lag_seconds=(end//60000*60000-candles[-1].timestamp_ms)/1000,
                        received_timestamp_ms=candles[-1].received_timestamp_ms)
                if len(candles)<p.history_bars:
                    raise ExchangeError('INSUFFICIENT_COMPLETED_HISTORY')
                validate_history(symbol,candles,now,p.history_bars)
                if not 0<=now-(candles[-1].timestamp_ms+60000)<=p.max_candle_age_ms:
                    raise ExchangeError('COMPLETED_CANDLE_STALE')
                if self.client.clock_ms()-context_observed>60000:
                    raise ExchangeError('SCANNER_ASSET_CONTEXT_STALE')
                book=self.market.get_orderbook(symbol)
                d.snapshot=MarketSnapshot.from_book(book,contexts[symbol],self.client.clock_ms(),
                    mark_observed_at_ms=context_observed)
                quote=make_quote(book,contexts[symbol],self.client.clock_ms(),mark_timestamp_ms=context_observed)
                if self.public_snapshot_sink is not None:
                    self.public_snapshot_sink(symbol,candles,book,contexts[symbol],context_observed)
                health=self.health_manager.evaluate(symbol,candles,book,contexts[symbol],context_observed,
                    self.client.clock_ms(),source='SCANNER_REST')
                d.evidence['market_health']=health['state']
                if not health['healthy']:
                    raise ExchangeError(health['reasons'][0])
                from brain_observation import observe_frozen_call
                enriched,brain_evidence=observe_frozen_call(lambda:self.brain.evaluate_candles(candles))
                d.evidence['brain']=brain_evidence
                last=enriched.iloc[-1]
                close=scanner_number(last['Close'],'Close',d.evidence)
                # A real flat market has finite zero ATR. The unchanged floor
                # rejects it as unqualified, rather than invalid market data.
                atr=scanner_number(last['ATR_14'],'ATR_14',d.evidence,nonnegative=True)
                ema9,ema21,vwap=(scanner_number(last[name],name,d.evidence) for name in ('EMA_9','EMA_21','VWAP'))
                window=candles[-p.history_bars:]
                notional=sum((c.volume*c.close for c in window),Decimal(0))
                depth=min(quote.bid*quote.bid_quantity,quote.ask*quote.ask_quantity)
                spread=(quote.ask-quote.bid)/quote.mid*10000
                returns=[math.log(float(b.close/a.close)) for a,b in zip(window,window[1:])]
                mean=sum(returns)/len(returns)
                volatility=Decimal(str(math.sqrt(sum((r-mean)**2 for r in returns)/len(returns))))
                d.metrics=dict(vwap=vwap,ema9=ema9,ema21=ema21,atr=atr,close=close,atr_fraction=atr/close,atr_percent=atr/close*100,
                    spread_bps=spread,window_notional_approx=notional,bbo_notional=depth,
                    best_bid=quote.bid,best_ask=quote.ask,spread=quote.ask-quote.bid,
                    bid_depth_notional=d.snapshot.bid_depth_notional,ask_depth_notional=d.snapshot.ask_depth_notional,
                    orderbook_imbalance=d.snapshot.orderbook_imbalance,
                    ema_strength_fraction=abs(ema9-ema21)/close,trend='BULLISH' if ema9>=ema21 else 'BEARISH',
                    vwap_distance_fraction=(close-vwap)/vwap,realized_volatility=volatility,
                    hourly_funding=quote.hourly_funding,open_interest=quote.open_interest,
                    daily_notional_volume=quote.daily_notional_volume,candle_count=len(candles))
                if atr/close<p.min_atr_fraction:
                    d.reasons.append('ATR_BELOW_BASELINE_SCANNER_FLOOR')
                if spread>p.max_spread_bps:
                    d.reasons.append('SPREAD_TOO_WIDE')
                if notional<=0 or notional<p.min_window_notional:
                    d.reasons.append('WINDOW_LIQUIDITY_INSUFFICIENT')
                if depth<=0 or depth<p.min_bbo_notional:
                    d.reasons.append('BBO_DEPTH_INSUFFICIENT')
                from signal_brain import detect_daily_bias
                day=last['Timestamp'].date()
                current=enriched[enriched.Timestamp.dt.date==day]
                signal_type=last.get('Signal_Type')
                # Pandas uses NaN for an absent categorical signal in real
                # frames. Preserve "no signal" as a portable JSON null.
                signal_type=str(signal_type) if isinstance(signal_type,str) else None
                d.signal=dict(symbol=symbol,timestamp_ms=candles[-1].timestamp_ms,
                    reference=vwap,atr=atr,bias=detect_daily_bias(current),
                    long=bool(last.get('Buy_Signal',False) or last.get('Breakout_Signal',False)),
                    short=bool(last.get('Sell_Signal',False) or last.get('Breakdown_Sell_Signal',False)),
                    signal_type=signal_type)
                d.timing=timing(self.client.clock_ms(),received_ms=candles[-1].received_timestamp_ms,
                                source="LOCAL_FROZEN_STRATEGY")
                d.qualified=not d.reasons
            except (ExchangeError,ValueError) as exc:
                if self.public_failure_sink is not None:self.public_failure_sink(symbol,str(exc))
                d.reasons.append(str(exc))
                d.timing=timing(self.client.clock_ms())
        qualified=[d for d in diagnostics if d.qualified]
        # Equal percentile ranks remove the old share/rupee score denominators.
        # Four transparent selection factors; EMA/VWAP still produce no signal here.
        factors={'atr_fraction':1,'spread_bps':-1,'window_notional_approx':1,'bbo_notional':1}
        for d in qualified:
            ranks=[]
            for key,direction in factors.items():
                value=direction*d.metrics[key]
                below=sum(direction*x.metrics[key]<value for x in qualified)
                ties=sum(direction*x.metrics[key]==value for x in qualified)
                ranks.append((Decimal(below)+Decimal(ties)/2)/len(qualified))
            d.score=sum(ranks)/len(ranks)
        qualified.sort(key=lambda d:(-d.score,-d.metrics['atr_fraction'],d.symbol))
        for rank,d in enumerate(qualified,1):
            d.evidence['scanner_rank']=rank
        return ScanResult(self.client.clock_ms(),diagnostics,[d.symbol for d in qualified[:p.top_n]],
                          'ACTIVE' if qualified else 'NO_TRADE')

    def run(self, stop_event, interval_seconds):
        if not 1<=interval_seconds<=3600:
            raise ExchangeError('INVALID_SCAN_INTERVAL')
        while not stop_event.is_set():
            start=time.monotonic()
            yield self.scan()
            remaining=max(0,interval_seconds-(time.monotonic()-start))
            while remaining>0 and not stop_event.is_set():
                duration=min(remaining,60)
                stop_event.wait(duration)
                remaining-=duration
