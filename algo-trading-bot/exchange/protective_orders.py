"""Disabled catastrophic-stop planning, separate from frozen candle-close exits."""
from dataclasses import dataclass
from .base_exchange import ExchangeError, decimal
from .order_lifecycle import OrderRequest
from .sdk_transport import sdk_number


@dataclass(frozen=True)
class CatastrophicStopPolicy:
    enabled: bool = False
    authorization_reference: str | None = None


class ProtectiveOrderPlanner:
    def __init__(self, validator, policy=None):
        self.validator=validator
        self.policy=policy or CatastrophicStopPolicy()

    def prepare(self, request, trigger_price, normal_strategy_stop, context, permission, now_ms):
        if not self.policy.enabled or not self.policy.authorization_reference:
            raise ExchangeError('CATASTROPHIC_STOP_POLICY_DISABLED')
        if not isinstance(request,OrderRequest) or not request.reduce_only:
            raise ExchangeError('PROTECTIVE_STOP_MUST_BE_REDUCE_ONLY')
        result=self.validator.validate(request,context,permission,now_ms)
        if not result.allowed:
            raise ExchangeError(result.code)
        trigger=context.spec.normalize_price(decimal(trigger_price,positive=True),request.side)
        normal=decimal(normal_strategy_stop,positive=True)
        mark=context.quote.mark
        if (request.side=='SELL' and not trigger<=normal<mark or
                request.side=='BUY' and not trigger>=normal>mark):
            raise ExchangeError('CATASTROPHIC_STOP_GEOMETRY_INVALID')
        from hyperliquid.utils.signing import order_request_to_order_wire
        normalized=result.normalized
        raw=dict(coin=request.symbol,is_buy=request.side=='BUY',sz=sdk_number(normalized.quantity),
                 limit_px=sdk_number(normalized.price),reduce_only=True,
                 order_type={'trigger':{'triggerPx':sdk_number(trigger),'isMarket':True,'tpsl':'sl'}})
        return dict(asset_id=context.spec.asset_id,wire=order_request_to_order_wire(raw,context.spec.asset_id),
                    trigger_price=str(trigger),source='EXPLICIT_CATASTROPHIC_POLICY',
                    normal_strategy_stop_unchanged=str(normal),exchange_submission=False)

    def activate(self, *args, **kwargs):
        raise ExchangeError('PROTECTIVE_ACTIVATION_REQUIRES_SEPARATE_FUTURE_IMPLEMENTATION_AND_AUTHORIZATION')
