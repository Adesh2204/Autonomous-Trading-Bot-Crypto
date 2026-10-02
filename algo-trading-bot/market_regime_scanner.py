"""Periodic, direction-neutral selection from every active runtime par market."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import math
import time

from exchange.base_exchange import ExchangeError, decimal
from exchange.hyperliquid_market_data import make_quote
from exchange.market_snapshot import MarketSnapshot
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


@dataclass
class ScanResult:
    observed_at_ms: int
    diagnostics: list
    watchlist: list
    status: str


class MarketRegimeScanner:
    def __init__(self, market, policy, *, session=None):
        self.market=market
        self.client=market.client
        self.policy=policy
        self.session=session or SessionManager()
        self.brain=FrozenStrategy(market,self.session)

    def scan(self):
        require_paper_migration()
        self.client.startup()
        p=self.policy
        now=self.client.clock_ms()
        end=now//60000*60000-1
        anchor=int(self.session.get_vwap_anchor(datetime.fromtimestamp(now/1000,timezone.utc)).timestamp()*1000)
        start=min(end+1-p.history_bars*60000,anchor-14*60000)
        contexts=self.market.get_asset_contexts()
        context_observed=self.client.clock_ms()
        diagnostics=[]
        for symbol in sorted(self.client.markets):
            d=MarketDiagnostic(symbol)
            diagnostics.append(d)
            try:
                candles=self.market.get_candles(symbol,start,end,now_ms=now)
                d.candles=candles
                if len(candles)<p.history_bars:
                    raise ExchangeError('INSUFFICIENT_COMPLETED_HISTORY')
                if not 0<=now-(candles[-1].timestamp_ms+60000)<=p.max_candle_age_ms:
                    raise ExchangeError('COMPLETED_CANDLE_STALE')
                if self.client.clock_ms()-context_observed>60000:
                    raise ExchangeError('SCANNER_ASSET_CONTEXT_STALE')
                book=self.market.get_orderbook(symbol)
                d.snapshot=MarketSnapshot.from_book(book,contexts[symbol],self.client.clock_ms(),
                    mark_observed_at_ms=context_observed)
                quote=make_quote(book,contexts[symbol],self.client.clock_ms(),mark_timestamp_ms=context_observed)
                enriched=self.brain.evaluate_candles(candles)
                last=enriched.iloc[-1]
                close=decimal(last['Close'],positive=True)
                atr=decimal(last['ATR_14'],positive=True)
                ema9,ema21,vwap=(decimal(last[name],positive=True) for name in ('EMA_9','EMA_21','VWAP'))
                window=candles[-p.history_bars:]
                notional=sum((c.volume*c.close for c in window),Decimal(0))
                depth=min(quote.bid*quote.bid_quantity,quote.ask*quote.ask_quantity)
                spread=(quote.ask-quote.bid)/quote.mid*10000
                returns=[math.log(float(b.close/a.close)) for a,b in zip(window,window[1:])]
                mean=sum(returns)/len(returns)
                volatility=Decimal(str(math.sqrt(sum((r-mean)**2 for r in returns)/len(returns))))
                d.metrics=dict(atr_fraction=atr/close,atr_percent=atr/close*100,
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
                d.qualified=not d.reasons
            except (ExchangeError,ValueError) as exc:
                d.reasons.append(str(exc))
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
