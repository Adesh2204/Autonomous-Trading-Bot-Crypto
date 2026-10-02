"""Compare local ledger state with public account reads; never submits repairs."""
from .event_timing import timing
from dataclasses import dataclass,field,asdict
from decimal import Decimal

from .base_exchange import Fill, ExchangeError, decimal


@dataclass(frozen=True)
class ReconciliationReport:
    position_differences: dict
    unexpected_order_ids: tuple[str, ...]
    missing_order_ids: tuple[str, ...]
    unseen_fills: tuple[Fill, ...]

    @property
    def matched(self):
        return not (self.position_differences or self.unexpected_order_ids or self.missing_order_ids)


class HyperliquidReconciliation:
    def __init__(self, account):
        self.account = account

    def reconcile(self, local_positions, *, known_order_ids=(), processed_fill_ids=()):
        actual = {symbol: position.quantity for symbol, position in self.account.get_positions().items()}
        local = {symbol: decimal(quantity) for symbol, quantity in local_positions.items()}
        for symbol in local:
            self.account.client.market(symbol)
        differences = {symbol: {'local': local.get(symbol, Decimal(0)),
                                 'exchange': actual.get(symbol, Decimal(0))}
                       for symbol in sorted(actual.keys() | local.keys())
                       if local.get(symbol, Decimal(0)) != actual.get(symbol, Decimal(0))}
        orders = {str(row['oid']) for row in self.account.get_open_orders()}
        known = set(map(str, known_order_ids))
        processed = set(processed_fill_ids)
        unseen = tuple(fill for fill in self.account.get_fills() if fill.identity not in processed)
        return ReconciliationReport(differences, tuple(sorted(orders - known)),
                                    tuple(sorted(known - orders)), unseen)

    def recover(self,state,*,start_ms,end_ms=None):
        """Read a stable REST account view, adopt exchange truth, then verify.

        This observer never changes the hypothetical paper ledger or sends an
        exchange mutation. An unexplained quantity delta remains entry-paused.
        """
        state.entries_paused=True
        state.reasons=('REST_ACCOUNT_RECONCILIATION_REQUIRED',)
        try:
            before=self.account.get_positions()
            orders=self.account.get_open_orders()
            end_ms=self.account.client.clock_ms() if end_ms is None else end_ms
            fills=self.account.get_fills(start_ms=start_ms,end_ms=end_ms)
            funding=self.account.get_funding(start_ms,end_ms)
            equity=self.account.get_equity()
            after=self.account.get_positions()
            later_orders=self.account.get_open_orders()
            signature=lambda values:{s:(p.quantity,p.entry_price) for s,p in values.items()}
            order_signature=lambda values:{str(row['oid']):row for row in values}
            if signature(before)!=signature(after) or order_signature(orders)!=order_signature(later_orders):
                raise ExchangeError('ACCOUNT_CHANGED_DURING_RECONCILIATION')
            if state.last_window is not None and start_ms>state.last_window[1]:
                raise ExchangeError('ACCOUNT_HISTORY_WINDOW_GAP')
            if state.last_window is not None and end_ms<state.last_window[1]:
                raise ExchangeError('ACCOUNT_RECOVERY_TIME_REGRESSED')
            staged_fills=dict(state.fills)
            staged_funding=dict(state.funding)
            for events,store,source in ((fills,staged_fills,'EXCHANGE_REPORTED_FILL'),
                                       (funding,staged_funding,'EXCHANGE_REPORTED_USER_FUNDING')):
                for event in events:
                    if event.source!=source:
                        raise ExchangeError('EXCHANGE_EVENT_PROVENANCE_REQUIRED')
                    prior=store.get(event.identity)
                    if prior is not None and prior!=event:
                        raise ExchangeError('CONFLICTING_RECONCILED_EVENT')
                    store[event.identity]=event
            new_fills=[f for f in fills if f.identity not in state.fills]
            actual={s:p.quantity for s,p in after.items()}
            differences={s:dict(local=state.quantities.get(s,Decimal(0)),exchange=actual.get(s,Decimal(0)))
                         for s in sorted(actual.keys()|state.quantities.keys())
                         if state.quantities.get(s,Decimal(0))!=actual.get(s,Decimal(0))}
            reasons=[]
            if set(order_signature(orders))-state.tracked_order_ids:
                reasons.append('UNTRACKED_EXCHANGE_OPEN_ORDERS')
            if any(p.entry_price is None for p in after.values()):
                reasons.append('POSITION_ENTRY_PRICE_UNAVAILABLE')
            if state.initialized:
                replayed=dict(state.quantity_evidence if state.quantity_evidence is not None else state.quantities)
                for fill in new_fills:
                    replayed[fill.symbol]=replayed.get(fill.symbol,Decimal(0))+(
                        fill.quantity if fill.side=='BUY' else -fill.quantity)
                if any(replayed.get(s,Decimal(0))!=actual.get(s,Decimal(0)) for s in replayed.keys()|actual.keys()):
                    reasons.append('POSITION_DELTA_NOT_EXPLAINED_BY_OBSERVED_FILLS')
            else:
                replayed=dict(actual)
            if any(f.closed_pnl is None for f in staged_fills.values()):
                reasons.append('REPORTED_CLOSED_PNL_MISSING')
            # Adopt the actual quantity/order/entry view even if its history is
            # incomplete. Never invent a fill or edit the exchange to match local.
            state.positions=after
            state.quantities=actual
            state.quantity_evidence=replayed
            state.orders={str(row['oid']):dict(row) for row in orders}
            state.fills=staged_fills
            state.funding=staged_funding
            state.equity=equity
            state.last_window=(start_ms,end_ms)
            state.accounting_origin_ms=start_ms if state.accounting_origin_ms is None else min(state.accounting_origin_ms,start_ms)
            state.initialized=True
            state.reasons=tuple(reasons)
            state.entries_paused=bool(reasons)
            state.events.append(dict(kind='EXCHANGE_TRUTH_ADOPTED',timestamp_ms=self.account.client.clock_ms(),
                                     differences=differences,new_fill_count=len(new_fills),reasons=state.reasons,
                                     **timing(self.account.client.clock_ms())))
            return state.report()
        except Exception as exc:
            state.reasons=(str(exc),)
            state.entries_paused=True
            raise

    def recover_incremental(self,state,*,initial_start_ms):
        start=initial_start_ms
        if state.last_window is not None and not state.entries_paused:
            # Inclusive overlap reconciles duplicate/recent events while keeping
            # the recurring query small. An unresolved gap retries full evidence.
            start=max(initial_start_ms,state.last_window[1]-60000)
        return self.recover(state,start_ms=start)


@dataclass
class ExchangeTruthState:
    """Read-only account mirror; profits are reported exchange-event amounts."""
    quantities: dict=field(default_factory=dict)
    positions: dict=field(default_factory=dict)
    orders: dict=field(default_factory=dict)
    fills: dict=field(default_factory=dict)
    funding: dict=field(default_factory=dict)
    equity: object=None
    initialized: bool=False
    entries_paused: bool=True
    reasons: tuple=('REST_ACCOUNT_RECONCILIATION_REQUIRED',)
    events: list=field(default_factory=list)
    last_window: tuple | None=None
    quantity_evidence: dict | None=None
    tracked_order_ids: set=field(default_factory=set)
    accounting_origin_ms: int | None=None

    def report(self):
        fills=list(self.fills.values())
        known=self.initialized and all(f.closed_pnl is not None for f in fills)
        gross=sum((f.closed_pnl for f in fills),Decimal(0)) if known else None
        fees=sum((f.fee for f in fills),Decimal(0))
        funding=sum((e.cashflow for e in self.funding.values()),Decimal(0))
        return dict(source='EXCHANGE_REPORTED_ACCOUNT_OBSERVER',exchange_orders_submitted=0,
            entries_paused=self.entries_paused,reasons=self.reasons,
            positions=[asdict(p) for p in self.positions.values()],open_orders=list(self.orders.values()),
            fills=[asdict(f) for f in fills],funding_events=[asdict(e) for e in self.funding.values()],
            reported_account_equity=asdict(self.equity) if self.equity else None,
            accounting_window_ms=(self.accounting_origin_ms,self.last_window[1]) if self.last_window else None,
            latest_query_window_ms=self.last_window,
            realized=dict(gross_closed_pnl=gross,actual_fill_fees=fees,actual_funding_cashflow=funding,
                net_after_fees_and_funding=gross-fees+funding if gross is not None else None,
                scope='ONLY_OBSERVED_ACCOUNT_EVENTS; excludes deposits/transfers and unknown historical events'),
            corrections=self.events)
