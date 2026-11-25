"""Position sizing on after-tax equity (the compounding rule), shared by backtest, paper and live."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, Decimal


@dataclass(frozen=True)
class RiskParams:
    risk_fraction: float = 0.01         # equity lost if the hard stop fills at its trigger
    max_position_leverage: float = 1.0  # one position's notional <= this x after-tax equity
    max_gross_leverage: float = 3.0     # all notionals together <= this x after-tax equity
    leverage_setting: float = 5.0       # exchange cross-leverage setting (margin = notional / this)
    # Small-account options. None = off (the $1,000 profiles leave both off).
    min_size_max_risk: float | None = None  # take the venue-minimum order if its stop risk <= this x equity
    max_open_risk: float | None = None      # all open positions' stop risks together <= this x equity
    # Isolated margin (CoinDCX INR futures): per-trade leverage <= 1 / (liquidation_buffer x stop
    # distance), so the exchange's liquidation price always lies well beyond the bot's stop.
    liquidation_buffer: float | None = None


def stop_safe_leverage(risk: RiskParams, stop_distance: float, coin_max: float | None = None) -> int:
    """Whole-number leverage for one trade: never above the setting or the coin's maximum, and with
    ``liquidation_buffer`` low enough that liquidation sits beyond the stop."""
    cap = risk.leverage_setting if not coin_max else min(risk.leverage_setting, coin_max)
    if risk.liquidation_buffer and stop_distance > 0:
        cap = min(cap, 1.0 / (risk.liquidation_buffer * stop_distance))
    return max(1, int(cap))


def _dec(x: float) -> Decimal:
    return Decimal(repr(float(x)))   # float() first: numpy scalars repr as "np.float64(...)"


def _floor_step(qty: float, step: float) -> float:
    s = _dec(step)
    return float((_dec(qty) / s).to_integral_value(ROUND_FLOOR) * s)


def _ceil_step(qty: float, step: float) -> float:
    s = _dec(step)
    return float((_dec(qty) / s).to_integral_value(ROUND_CEILING) * s)


def size_order(tradable: float, fill: float, stop: float, gross_open: float, risk: RiskParams,
               min_notional: float, *, qty_step: float | None = None, open_risk: float = 0.0,
               free_margin: float | None = None, coin_leverage: float | None = None) -> float:
    """Quantity for a new position, or 0.0 if none is allowed.

    ``tradable`` is after-tax equity: mark-to-market equity minus the tax already reserved and the
    tax that open winners would owe if closed now. Every realized after-tax profit therefore
    enlarges the next position (compounding) and every loss shrinks it.

    With ``qty_step`` the result is already rounded DOWN to the venue's quantity step. If the
    risk-based size is below the venue minimum and ``risk.min_size_max_risk`` is set, the minimum
    order (rounded UP to the step) is taken instead, but only if its stop risk stays within that
    fraction of equity and every other cap still holds.
    """
    if tradable <= 0 or fill <= 0:
        return 0.0
    per_unit_risk = abs(fill - stop)
    if per_unit_risk <= 0:
        return 0.0
    caps = [risk.max_position_leverage * tradable / fill,
            max(0.0, risk.max_gross_leverage * tradable - gross_open) / fill]
    if free_margin is None:   # uniform leverage: margin room at the exchange setting
        caps.append(max(0.0, tradable * risk.leverage_setting - gross_open) / fill)
    else:                     # per-coin leverage: margin left x this coin's leverage
        caps.append(max(0.0, free_margin) * (coin_leverage or risk.leverage_setting) / fill)
    if risk.max_open_risk is not None:
        caps.append(max(0.0, risk.max_open_risk * tradable - open_risk) / per_unit_risk)
    cap = min(caps)
    qty = min(risk.risk_fraction * tradable / per_unit_risk, cap)
    if qty_step:
        qty = _floor_step(qty, qty_step)
    if qty > 0 and qty * fill >= min_notional:
        return qty
    if risk.min_size_max_risk is None:
        return 0.0
    q_min = min_notional / fill if min_notional > 0 else (qty_step or 0.0)
    if qty_step:
        q_min = _ceil_step(max(q_min, qty_step), qty_step)
    if q_min <= 0 or q_min > cap * (1 + 1e-9):
        return 0.0
    if q_min * per_unit_risk > risk.min_size_max_risk * tradable:
        return 0.0
    return q_min


def round_down(qty: float, size_decimals: int) -> Decimal:
    """Exchange quantity: rounded DOWN to the venue's size decimals (never up)."""
    step = Decimal(1).scaleb(-size_decimals)
    return _dec(qty).quantize(step, rounding=ROUND_DOWN)
