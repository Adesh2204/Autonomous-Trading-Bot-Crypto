from exchange.base_exchange import ExchangeError


class LiquidationGuard:
    @staticmethod
    def check(snapshot, spec, quantity, mark, worst_loss, initial_margin, policy):
        if (snapshot.initial_margin+snapshot.order_reservations+initial_margin>
                snapshot.equity*policy.max_margin_utilization):
            raise ExchangeError('PORTFOLIO_MARGIN_LIMIT')
        maintenance=snapshot.maintenance_margin_estimate+spec.maintenance_margin(quantity*mark)
        if snapshot.equity-worst_loss<=maintenance*policy.maintenance_buffer_multiple:
            raise ExchangeError('LIQUIDATION_BUFFER_INSUFFICIENT')
