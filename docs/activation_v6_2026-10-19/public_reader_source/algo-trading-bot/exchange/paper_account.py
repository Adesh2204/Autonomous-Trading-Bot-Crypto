"""Generic account reads for a local USDPR ledger; no wallet or exchange calls."""
from decimal import Decimal

from .base_exchange import AccountEquity,ExchangeError,Fill,Position


class PaperAccount:
    def __init__(self,execution):
        if execution.is_live or execution.portfolio is None:
            raise ExchangeError('ACCOUNTED_PAPER_EXECUTOR_REQUIRED')
        self.execution=execution

    def get_position(self,symbol):
        if symbol not in self.execution.specs:
            raise ExchangeError('UNKNOWN_PAPER_MARKET')
        portfolio=self.execution.portfolio
        portfolio.snapshot(self.execution.quotes,self.execution.clock_ms())
        position=portfolio.positions.get(symbol)
        if position is None:
            return None
        quote=self.execution.quotes[symbol]
        return Position(symbol,position.quantity,position.entry_price,
            position.quantity*(quote.mark-position.entry_price),
            abs(position.quantity)*quote.mark/position.leverage,None)

    def get_fills(self):
        return [Fill(f.symbol,f.timestamp_ms,f.fill_id,f.order_id,f.side,f.quantity,f.price,f.fee,f.fee_token,
                     source='LOCAL_PAPER_BBO_FILL')
                for f in self.execution.fills]

    def get_positions(self):
        return {s:self.get_position(s) for s in self.execution.portfolio.positions}

    def get_funding(self):
        return [dict(event) for event in self.execution.portfolio.events if event['kind']=='FUNDING']

    def get_equity(self):
        snapshot=self.execution.portfolio.snapshot(self.execution.quotes,self.execution.clock_ms())
        transfer_margin=max(snapshot.initial_margin,snapshot.gross_notional*Decimal('.1'))
        withdrawable=max(Decimal(0),snapshot.equity-transfer_margin-snapshot.order_reservations)
        return AccountEquity(snapshot.equity,snapshot.cash,snapshot.initial_margin,withdrawable,
                             'PAPER_USDPR_MARK_ACCOUNTING')

    def get_open_orders(self):
        return [dict(order_id=o.order_id,symbol=o.order.symbol,state=o.status,
                     remaining_quantity=o.remaining_quantity)
                for o in self.execution.orders.values() if o.status in {'OPEN','PARTIALLY_FILLED'}]
