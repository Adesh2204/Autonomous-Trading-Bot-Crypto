from dataclasses import dataclass
from decimal import Decimal

from exchange.base_exchange import ExchangeError, decimal


@dataclass(frozen=True)
class RiskPolicy:
    risk_fraction: Decimal
    max_daily_loss_fraction: Decimal
    max_gross_equity_multiple: Decimal
    max_margin_utilization: Decimal
    maintenance_buffer_multiple: Decimal
    max_funding_cost_fraction: Decimal
    max_mark_oracle_bps: Decimal
    max_spread_bps: Decimal
    depth_participation: Decimal
    slippage_bps: Decimal
    holding_hours: Decimal
    leverage: int
    max_positions: int=1
    max_daily_setups: int=2
    max_drawdown_fraction: Decimal=Decimal('0.05')
    max_symbol_equity_multiple: Decimal=Decimal(1)
    max_net_equity_multiple: Decimal=Decimal(1)
    max_directional_equity_multiple: Decimal=Decimal(1)
    max_data_age_ms: int=5000
    max_mark_age_ms: int=60000
    max_candle_age_ms: int=120000
    max_consecutive_order_errors: int=3
    max_reconnect_failures: int=5

    def __post_init__(self):
        positive={'risk_fraction','max_daily_loss_fraction','max_gross_equity_multiple',
                  'max_margin_utilization','maintenance_buffer_multiple','depth_participation',
                  'max_drawdown_fraction','max_symbol_equity_multiple','max_net_equity_multiple',
                  'max_directional_equity_multiple'}
        for name in ('risk_fraction','max_daily_loss_fraction','max_gross_equity_multiple',
                     'max_margin_utilization','maintenance_buffer_multiple','max_funding_cost_fraction',
                     'max_mark_oracle_bps','max_spread_bps','depth_participation','slippage_bps','holding_hours',
                     'max_drawdown_fraction','max_symbol_equity_multiple','max_net_equity_multiple',
                     'max_directional_equity_multiple'):
            object.__setattr__(self,name,decimal(getattr(self,name),positive=name in positive,
                                               nonnegative=name not in positive))
        if (any(getattr(self,n)>1 for n in ('risk_fraction','max_daily_loss_fraction',
                'max_margin_utilization','depth_participation','max_drawdown_fraction')) or self.maintenance_buffer_multiple<1 or
                any(type(getattr(self,n)) is not int or getattr(self,n)<1 for n in
                    ('leverage','max_positions','max_daily_setups'))):
            raise ExchangeError('INVALID_RISK_POLICY')
        if self.max_positions!=1 or self.max_daily_setups>2:
            raise ExchangeError('BASELINE_PORTFOLIO_STATE_LIMIT_REQUIRED')
        for name,upper in (('max_data_age_ms',5000),('max_mark_age_ms',60000),('max_candle_age_ms',120000),
                           ('max_consecutive_order_errors',100),('max_reconnect_failures',100)):
            if type(getattr(self,name)) is not int or not 1<=getattr(self,name)<=upper:
                raise ExchangeError('INVALID_CIRCUIT_BREAKER_POLICY')


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str,...]
    quantity: Decimal=Decimal(0)
    stop: Decimal | None=None
    target: Decimal | None=None
    economics: object | None=None
