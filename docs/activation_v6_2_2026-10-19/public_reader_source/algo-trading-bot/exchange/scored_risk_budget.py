"""PAS session budget diagnostics and loss stop; no indicator or order authority."""
from decimal import Decimal as D
from .base_exchange import decimal,ExchangeError


def budget(limits):
    limits.require()
    bankroll=decimal(limits.bankroll,positive=True)
    return dict(denominator='ALLOCATED_SESSION_BANKROLL_USDP',allocated_bankroll=str(bankroll),
        intended_trade_loss=str(bankroll*decimal(limits.risk_fraction)),
        session_loss_stop=str(bankroll*decimal(limits.daily_loss_fraction)),
        entry_notional=str(decimal(limits.maximum_notional)),
        cumulative_entry_notional=str(decimal(limits.maximum_cumulative_allocation)),
        account_balance_is_risk_denominator=False,fee_funding_slippage_included=True,guaranteed_loss_cap=False)


def marked_loss(limits,*,prior_realized,prior_peak,positions,cycle_fills,cycle_funding,maximum_fee,slippage_bps):
    """Actual owned cycle accounting, reported unrealized PnL, estimated exit costs."""
    b=decimal(limits.bankroll,positive=True);fee=decimal(maximum_fee,nonnegative=True)
    slip=decimal(slippage_bps,nonnegative=True)
    if fee>D('.003') or slip>5:raise ExchangeError('PAS_SESSION_FRICTION_CEILINGS_REQUIRED')
    for f in cycle_fills:
        if f.symbol not in limits.markets or f.closed_pnl is None or f.fee_token!='USDP':
            raise ExchangeError('PAS_SESSION_ACTUAL_ACCOUNTING_REQUIRED')
    if (len(positions)>1 or any(p.symbol not in limits.markets or decimal(p.quantity)<=0 for p in positions.values())
            or any(f.symbol not in limits.markets for f in cycle_funding)):
        raise ExchangeError('PAS_SESSION_UNOWNED_EXPOSURE')
    actual=decimal(prior_realized)+sum((decimal(f.closed_pnl)-decimal(f.fee) for f in cycle_fills),D(0))
    actual+=sum((decimal(f.cashflow) for f in cycle_funding),D(0))
    unrealized=sum((decimal(p.unrealized_pnl) for p in positions.values()),D(0))
    reserve=sum((decimal(p.quantity)*max(decimal(p.entry_price,positive=True),
        decimal(p.entry_price)+decimal(p.unrealized_pnl)/decimal(p.quantity))*(fee+slip/10000) for p in positions.values()),D(0))
    equity=b+actual+unrealized;peak=max(b,decimal(prior_peak),equity)
    loss=max(D(0),b-equity,peak-equity)+reserve;ceiling=b*decimal(limits.daily_loss_fraction)
    return dict(actual_net_before_unrealized=str(actual),reported_unrealized=str(unrealized),estimated_exit_reserve=str(reserve),
        sampled_equity=str(equity),sampled_peak=str(peak),loss_with_exit_reserve=str(loss),loss_stop=str(ceiling),
        halt_entries=loss>=ceiling,loss_stop_hit=loss>=ceiling,
        basis='ACTUAL_OWNED_FILL_FEES_FUNDING_PLUS_REPORTED_UNREALIZED; EXIT_RESERVE_IS_ESTIMATE')
