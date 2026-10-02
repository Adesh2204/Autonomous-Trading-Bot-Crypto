"""Order interface and precision preview. All signed actions remain disabled."""
import order_guard


class HyperliquidExecution:
    is_live = True
    venue = 'HYPERLIQUID_TESTNET'

    def __init__(self, client):
        self.client = client

    def preview_order(self, symbol, side, quantity, price, *, reduce_only=False, tif='Gtc'):
        return self.client.market(symbol).normalize_order(
            side, quantity, price, reduce_only=reduce_only, tif=tif)

    def preview_request(self, request):
        return self.preview_order(request.symbol,request.side,request.quantity,request.price,
                                  reduce_only=request.reduce_only,tif=request.tif)

    def submit(self, request):
        order_guard.require_exchange_orders(self.venue)
        raise AssertionError('Signed transport is not implemented')

    def place_order(self, symbol, side=None, quantity=None, price=None, *, reduce_only=False, tif='Gtc'):
        order_guard.require_exchange_orders(self.venue)
        raise AssertionError('Signed transport is not implemented')

    def cancel_order(self, symbol, order_id):
        order_guard.require_exchange_orders(self.venue)
        raise AssertionError('Signed transport is not implemented')

    def modify_order(self, symbol, order_id, **parameters):
        order_guard.require_exchange_orders(self.venue)
        raise AssertionError('Signed transport is not implemented')
