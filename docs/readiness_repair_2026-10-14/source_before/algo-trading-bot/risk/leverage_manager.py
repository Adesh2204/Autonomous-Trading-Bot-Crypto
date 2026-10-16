from exchange.base_exchange import ExchangeError


class LeverageManager:
    @staticmethod
    def validate(spec, leverage):
        if type(leverage) is not int or not 1<=leverage<=spec.max_leverage:
            raise ExchangeError('LEVERAGE_EXCEEDS_RUNTIME_LIMIT')
        return leverage
