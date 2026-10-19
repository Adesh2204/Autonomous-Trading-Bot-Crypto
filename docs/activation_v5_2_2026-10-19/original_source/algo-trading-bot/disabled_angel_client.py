"""Replacement for the legacy live SDK client; never imports an order SDK."""
from order_guard import OrderRoutingBlocked


class DisabledAngelOneClient:
    def __init__(self, *args, **kwargs):
        raise OrderRoutingBlocked("ANGEL_ONE_EXECUTION_DISABLED")
