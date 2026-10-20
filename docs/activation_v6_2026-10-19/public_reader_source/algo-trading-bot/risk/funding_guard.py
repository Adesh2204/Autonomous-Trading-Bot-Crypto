from exchange.base_exchange import ExchangeError


class FundingGuard:
    @staticmethod
    def check(expected_cost, notional, maximum_fraction):
        if expected_cost>notional*maximum_fraction:
            raise ExchangeError('FUNDING_COST_LIMIT')
