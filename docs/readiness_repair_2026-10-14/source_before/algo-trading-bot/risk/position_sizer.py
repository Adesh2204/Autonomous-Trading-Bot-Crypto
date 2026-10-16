from decimal import Decimal
from exchange.base_exchange import ExchangeError, decimal


class PositionSizer:
    @staticmethod
    def size(spec, *, risk_budget, per_unit_stop_risk, free_margin, mark,
             leverage, depth, participation, entry_price, fee_rate):
        risk=decimal(risk_budget,positive=True)
        loss=decimal(per_unit_stop_risk,positive=True)
        margin=decimal(free_margin,positive=True)
        unit_margin=decimal(mark,positive=True)/leverage+decimal(entry_price,positive=True)*fee_rate
        quantity=min(risk/loss,margin/unit_margin,
                     decimal(depth,positive=True)*decimal(participation,positive=True))
        return spec.normalize_size(quantity)
