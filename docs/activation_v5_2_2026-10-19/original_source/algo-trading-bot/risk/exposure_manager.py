from decimal import Decimal
from exchange.base_exchange import ExchangeError,decimal


class ExposureManager:
    @staticmethod
    def metrics(snapshot,portfolio,quotes):
        per_symbol={}
        long=short=Decimal(0)
        for symbol,p in portfolio.positions.items():
            if symbol not in quotes:
                raise ExchangeError('EXPOSURE_MARK_MISSING')
            value=p.quantity*decimal(quotes[symbol].mark,positive=True)
            per_symbol[symbol]=dict(signed_notional=value,gross_notional=abs(value))
            if value>0: long+=value
            else: short-=value
        gross=long+short
        return dict(total_gross_exposure=gross,total_net_exposure=long-short,
            long_notional=long,short_notional=short,directional_concentration=(max(long,short)/gross if gross else Decimal(0)),
            per_symbol_exposure=per_symbol,margin_utilization=(snapshot.initial_margin/snapshot.equity if snapshot.equity>0 else None),
            position_count=len(portfolio.positions),collateral='USDPR')

    @staticmethod
    def check(snapshot, portfolio, symbol, new_notional, policy, *, side=None,quotes=None):
        if len(portfolio.positions)>=policy.max_positions or symbol in portfolio.positions:
            raise ExchangeError('PORTFOLIO_POSITION_LIMIT')
        if snapshot.gross_notional+new_notional>snapshot.equity*policy.max_gross_equity_multiple:
            raise ExchangeError('PORTFOLIO_EXPOSURE_LIMIT')
        if new_notional>snapshot.equity*policy.max_symbol_equity_multiple:
            raise ExchangeError('SYMBOL_EXPOSURE_LIMIT')
        if side is not None:
            metrics=ExposureManager.metrics(snapshot,portfolio,quotes or {})
            delta=new_notional if side=='BUY' else -new_notional
            if abs(metrics['total_net_exposure']+delta)>snapshot.equity*policy.max_net_equity_multiple:
                raise ExchangeError('NET_EXPOSURE_LIMIT')
            directional=metrics['long_notional']+new_notional if side=='BUY' else metrics['short_notional']+new_notional
            if directional>snapshot.equity*policy.max_directional_equity_multiple:
                raise ExchangeError('DIRECTIONAL_EXPOSURE_LIMIT')
