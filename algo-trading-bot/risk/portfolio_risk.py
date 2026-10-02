from decimal import Decimal

from exchange.base_exchange import ExchangeError, decimal
from exchange.perpetual_economics import estimate_trade
from strategy_contract import baseline_parameters
from .models import RiskDecision
from .position_sizer import PositionSizer
from .exposure_manager import ExposureManager
from .leverage_manager import LeverageManager
from .liquidation_guard import LiquidationGuard
from .funding_guard import FundingGuard


class PortfolioRisk:
    def __init__(self, policy, fees):
        self.policy=policy
        self.fees=fees
        self.parameters=baseline_parameters()

    def assess(self, spec, side, reference, atr, quote, portfolio, quotes, now_ms,
               *, daily_loss=Decimal(0), daily_setups=0):
        p=self.policy
        try:
            if side not in {'BUY','SELL'} or quote.symbol!=spec.symbol:
                raise ExchangeError('SIGNAL_IDENTITY_MISMATCH')
            if not 0<=now_ms-quote.timestamp_ms<=p.max_data_age_ms:
                raise ExchangeError('ORDERBOOK_STALE')
            if quote.mark_timestamp_ms is None:
                raise ExchangeError('MARK_TIMESTAMP_REQUIRED')
            if not 0<=now_ms-quote.mark_timestamp_ms<=p.max_mark_age_ms:
                raise ExchangeError('MARK_DATA_STALE')
            ref=decimal(reference,positive=True)
            atr=decimal(atr,positive=True)
            if quote.ask<quote.bid or quote.bid<=0 or quote.oracle<=0 or quote.mark<=0:
                raise ExchangeError('INVALID_QUOTE')
            mid=(quote.ask+quote.bid)/2
            if (quote.ask-quote.bid)/mid*10000>p.max_spread_bps:
                raise ExchangeError('SPREAD_TOO_WIDE')
            if abs(quote.mark-quote.oracle)/quote.oracle*10000>p.max_mark_oracle_bps:
                raise ExchangeError('MARK_ORACLE_DIVERGENCE')
            leverage=LeverageManager.validate(spec,p.leverage)
            snapshot=portfolio.snapshot(quotes,now_ms)
            if snapshot.equity<=0:
                raise ExchangeError('PAPER_EQUITY_EXHAUSTED')
            if daily_setups>=p.max_daily_setups:
                raise ExchangeError('MAX_NEW_SETUPS_REACHED')
            remaining=portfolio.starting_collateral*p.max_daily_loss_fraction-daily_loss
            if remaining<=0:
                raise ExchangeError('DAILY_RISK_EXHAUSTED')
            sign=Decimal(1) if side=='BUY' else Decimal(-1)
            # Only the stock's hardcoded two-decimal rounding is removed. Keep
            # baseline ATR multipliers and VWAP anchor exactly; exchange order
            # prices are normalized later using runtime MarketSpec.
            stop=ref-sign*decimal(self.parameters['SL_ATR_MULT'])*atr
            target=ref+sign*decimal(self.parameters['TP_ATR_MULT'])*atr
            unit=estimate_trade(side,1,ref,stop,target,quote,self.fees,
                                slippage_bps=p.slippage_bps,holding_hours=p.holding_hours)
            budget=min(snapshot.equity*p.risk_fraction,remaining)
            # Preserve headroom for existing orders/positions across one pool.
            headroom=min(snapshot.available_margin,
                snapshot.equity*p.max_margin_utilization-snapshot.initial_margin-snapshot.order_reservations)
            if headroom<=0:
                raise ExchangeError('PORTFOLIO_MARGIN_LIMIT')
            entry=quote.ask if side=='BUY' else quote.bid
            depth=quote.ask_quantity if side=='BUY' else quote.bid_quantity
            quantity=PositionSizer.size(spec,risk_budget=budget,per_unit_stop_risk=unit.stop_risk,
                free_margin=headroom,mark=max(quote.mark,entry),leverage=leverage,depth=depth,
                participation=p.depth_participation,entry_price=entry,fee_rate=self.fees.taker)
            # Notional minimum validates only. Never upsize to force acceptance.
            spec.normalize_order(side,quantity,entry)
            if leverage>spec.maximum_leverage_at(quantity*max(quote.mark,entry)):
                raise ExchangeError('LEVERAGE_EXCEEDS_RUNTIME_MARGIN_TIER')
            economics=estimate_trade(side,quantity,ref,stop,target,quote,self.fees,
                                    slippage_bps=p.slippage_bps,holding_hours=p.holding_hours)
            threshold=decimal(self.parameters['MIN_NET_RR_LOW_VOL'] if atr/ref<
                decimal(self.parameters['LOW_VOL_ATR_PCT']) else self.parameters['MIN_NET_RR_NORMAL'])
            if economics.net_profit<=0 or economics.net_rr<threshold:
                raise ExchangeError('NET_EDGE_OR_RR_INSUFFICIENT')
            ExposureManager.check(snapshot,portfolio,spec.symbol,quantity*quote.mark,p,side=side,quotes=quotes)
            FundingGuard.check(economics.funding_cost,quantity*quote.oracle,p.max_funding_cost_fraction)
            LiquidationGuard.check(snapshot,spec,quantity,quote.mark,economics.stop_risk,
                                   quantity*max(quote.mark,entry)/leverage,p)
            return RiskDecision(True,(),quantity,stop,target,economics)
        except ExchangeError as exc:
            return RiskDecision(False,(str(exc),))
