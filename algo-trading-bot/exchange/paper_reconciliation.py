"""Recover local paper state from recorded fills/funding, never exchange truth."""
from decimal import Decimal

from .base_exchange import ExchangeError
from .paper_account import PaperAccount
from .paper_portfolio import PaperPortfolio,FundingSettlement


class PaperReconciliation:
    source='LOCAL_PAPER_FILL_REPLAY'

    def __init__(self,execution):
        self.execution=execution
        self.account=PaperAccount(execution)
        self.last_report=None

    def recover(self,managers):
        execution=self.execution
        ledger=execution.portfolio
        replay=PaperPortfolio(execution.specs,ledger.starting_collateral)
        fills={fill.fill_id:fill for fill in execution.fills}
        if len(fills)!=len(execution.fills):
            raise ExchangeError('CONFLICTING_PAPER_FILL_IDS')
        for event in ledger.events:
            if event['kind']=='FILL_ACCOUNTED':
                if event['fill_id'] not in fills:
                    raise ExchangeError('PAPER_FILL_EVIDENCE_MISSING')
                replay.apply_fill(fills[event['fill_id']],event.get('leverage',execution.leverage))
            elif event['kind']=='FUNDING':
                replay.settle_funding(FundingSettlement(event['symbol'],event['timestamp_ms'],
                    event['oracle_price'],event['hourly_rate'],event['source']),execution.clock_ms())
        if set(replay._fills)!=set(fills):
            raise ExchangeError('PAPER_FILL_ACCOUNTING_EVENT_MISSING')
        reasons=[]
        quantities={s:p.quantity for s,p in replay.positions.items()}
        differences={s:dict(local=execution.positions.get(s,Decimal(0)),paper_fill_truth=quantities.get(s,Decimal(0)))
                     for s in sorted(execution.positions.keys()|quantities.keys())
                     if execution.positions.get(s,Decimal(0))!=quantities.get(s,Decimal(0))}
        for symbol,manager in managers.items():
            held=replay.positions.get(symbol)
            if manager.has_open_position:
                if held is None or (held.quantity>0)!=(manager._open_position['side']=='BUY'):
                    reasons.append('STRATEGY_FILL_REPLAY_REQUIRED:'+symbol)
                else:
                    manager._open_position['quantity']=abs(held.quantity)
                    manager._open_position['average_entry_price']=float(held.entry_price)
        for symbol in replay.positions:
            if symbol not in managers or not managers[symbol].has_open_position:
                reasons.append('STRATEGY_POSITION_EVIDENCE_MISSING:'+symbol)
        # Recorded simulated fills and explicitly labelled funding are the local
        # authority. Corrections never manufacture an exchange fill or virtual SL.
        for name in ('cash','positions','realized_pnl','fees_paid','funding_cashflow','_fills','_funding','last_event_ms'):
            setattr(ledger,name,getattr(replay,name))
        execution.positions={**{s:Decimal(0) for s in execution.positions},**quantities}
        ledger.reservations={o.order_id:o.remaining_quantity*o.order.price/execution.leverage+
                             execution.fees.fee(o.remaining_quantity,o.order.price)
                             for o in execution.orders.values() if o.status in {'OPEN','PARTIALLY_FILLED'} and not o.order.reduce_only}
        positions=self.account.get_positions()
        orders=self.account.get_open_orders()
        account_fills=self.account.get_fills()
        funding=self.account.get_funding()
        equity=self.account.get_equity()
        self.last_report=dict(source=self.source,exchange_account_verified=False,
            entries_paused=bool(reasons),reasons=tuple(reasons),position_corrections=differences,
            position_count=len(positions),open_order_count=len(orders),fill_count=len(account_fills),
            funding_event_count=len(funding),reported_equity=equity.reported_account_value,
            exchange_orders_submitted=0,recovered_at_ms=execution.clock_ms())
        return self.last_report
