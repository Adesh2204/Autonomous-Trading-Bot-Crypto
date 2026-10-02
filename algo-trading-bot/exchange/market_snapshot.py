"""Explicit execution, valuation and trade observations with independent clocks."""
from dataclasses import dataclass
from decimal import Decimal

from .base_exchange import ExchangeError, decimal
from .hyperliquid_market_data import make_quote


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    bid: Decimal
    ask: Decimal
    mid: Decimal
    mark_price: Decimal
    oracle_price: Decimal
    funding: Decimal
    open_interest: Decimal | None
    bid_quantity: Decimal
    ask_quantity: Decimal
    spread: Decimal
    spread_bps: Decimal
    bid_depth_notional: Decimal
    ask_depth_notional: Decimal
    orderbook_imbalance: Decimal
    orderbook_timestamp_ms: int
    mark_observed_at_ms: int
    last_trade_price: Decimal | None = None
    last_trade_timestamp_ms: int | None = None

    @classmethod
    def from_book(cls,book,context,now_ms,*,mark_observed_at_ms,last_trade=None,max_book_age_ms=5000):
        if (type(mark_observed_at_ms) is not int or not 0<=now_ms-mark_observed_at_ms<=60000):
            raise ExchangeError('ASSET_CONTEXT_STALE')
        quote=make_quote(book,context,now_ms,max_book_age_ms,mark_timestamp_ms=mark_observed_at_ms)
        bid_depth=sum((level.price*level.quantity for level in book.bids),Decimal(0))
        ask_depth=sum((level.price*level.quantity for level in book.asks),Decimal(0))
        trade_price=trade_time=None
        if last_trade is not None:
            if last_trade['coin']!=book.symbol:
                raise ExchangeError('TRADE_IDENTITY_MISMATCH')
            trade_price=decimal(last_trade['px'],positive=True)
            trade_time=last_trade['time']
            if type(trade_time) is not int or not 0<=trade_time<=now_ms:
                raise ExchangeError('INVALID_TRADE_TIMESTAMP')
        return cls(book.symbol,quote.bid,quote.ask,quote.mid,quote.mark,quote.oracle,
            quote.hourly_funding,quote.open_interest,quote.bid_quantity,quote.ask_quantity,
            quote.ask-quote.bid,(quote.ask-quote.bid)/quote.mid*10000,
            bid_depth,ask_depth,(bid_depth-ask_depth)/(bid_depth+ask_depth),
            book.timestamp_ms,mark_observed_at_ms,trade_price,trade_time)
