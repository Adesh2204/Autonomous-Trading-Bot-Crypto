"""Risk view over reported account equity and buying power; never a paper ledger."""
from decimal import Decimal
from .base_exchange import ExchangeError, decimal
from .paper_portfolio import PortfolioSnapshot


class ExchangePortfolioView:
    def __init__(self, recovery, specifications, starting_equity):
        self.recovery=recovery
        self.specs=specifications
        self.starting_collateral=decimal(starting_equity,positive=True)
        self.available_margin=None
        self.account_observed_ms=None

    @property
    def positions(self):
        return self.recovery.state.positions

    def observe_buying_power(self, active_asset, now_ms):
        if active_asset.get('user','').lower()!=self.recovery.account.team_address.lower():
            raise ExchangeError('ACCOUNT_IDENTITY_MISMATCH')
        values=active_asset['availableToTrade']
        if not isinstance(values,list) or len(values)!=2:
            raise ExchangeError('BUYING_POWER_UNAVAILABLE')
        self.available_margin=min(decimal(x,nonnegative=True) for x in values)
        self.account_observed_ms=now_ms

    def snapshot(self, quotes, now_ms):
        state=self.recovery.state
        if state.equity is None or self.available_margin is None or self.account_observed_ms is None or not 0<=now_ms-self.account_observed_ms<=5000:
            raise ExchangeError('LIVE_ACCOUNT_RISK_VIEW_UNAVAILABLE')
        realized=state.report()['realized']
        if realized['gross_closed_pnl'] is None:
            raise ExchangeError('ACTUAL_CLOSED_PNL_UNAVAILABLE')
        gross=maintenance=Decimal(0)
        for symbol,position in state.positions.items():
            q=quotes.get(symbol)
            if q is None or not 0<=now_ms-q.timestamp_ms<=5000 or q.mark_timestamp_ms is None or not 0<=now_ms-q.mark_timestamp_ms<=60000:
                raise ExchangeError('LIVE_PORTFOLIO_MARK_STALE')
            notional=abs(position.quantity)*q.mark
            gross+=notional
            maintenance+=self.specs[symbol].maintenance_margin(notional)
        return PortfolioSnapshot(now_ms,state.equity.collateral_balance,
            sum((p.unrealized_pnl for p in state.positions.values()),Decimal(0)),
            state.equity.reported_account_value,state.equity.margin_used,maintenance,
            Decimal(0),self.available_margin,gross,realized['gross_closed_pnl'],
            realized['actual_fill_fees'],realized['actual_funding_cashflow'])
