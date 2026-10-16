"""Scoped entry controls. Changing a state never submits or flattens an order."""
from exchange.event_timing import timing
from enum import Enum
from decimal import Decimal


class RiskState(str,Enum):
    NORMAL='NORMAL'
    CAUTION='CAUTION'
    ENTRY_PAUSED='ENTRY_PAUSED'
    EMERGENCY='EMERGENCY'


class CircuitBreakers:
    def __init__(self,policy):
        self.policy=policy
        self.global_blocks={}
        self.symbol_blocks={}
        self.financial_reasons=()
        self.financial_state=RiskState.NORMAL
        self.consecutive_order_errors=0
        self.reconnect_failures=0
        self.transitions=[]
        self._signature=None
        self.operational_state=RiskState.NORMAL

    def update_reliability(self,execution):
        """Infrastructure gates are account-wide; existing market gates stay scoped."""
        for key in ('api_budget','clock','nonce','protection'):
            self.clear(key)
        self.operational_state=RiskState.NORMAL
        rates=execution.rate_limits
        if not rates.entries_allowed:
            self.pause('api_budget','API_BUDGET_'+rates.state.value)
        elif rates.state.value=='CAUTION':
            self.operational_state=RiskState.CAUTION
        if not execution.clock_health.healthy:
            self.pause('clock','CLOCK_'+execution.clock_health.state.value)
        if not execution.transport.nonces.healthy:
            self.pause('nonce','NONCE_SIGNING_DEGRADED')
        protection=execution.protection
        if protection is not None and not protection.entries_allowed:
            self.pause('protection','CATASTROPHIC_PROTECTION_NOT_READY')
            if any(r['status'] in {'ERROR','MISSING','PARTIAL'} for r in protection.states.values()):
                self.operational_state=RiskState.EMERGENCY
        if self.entry_reasons('__account__'):
            execution.entries_paused=True

    def pause(self,key,reason):
        self.global_blocks[key]=str(reason)

    def clear(self,key):
        self.global_blocks.pop(key,None)

    def update_symbols(self,health):
        self.symbol_blocks={s:tuple(h['reasons']) for s,h in health.items() if not h['healthy']}

    def order_result(self,success):
        self.consecutive_order_errors=0 if success else self.consecutive_order_errors+1
        if self.consecutive_order_errors>=self.policy.max_consecutive_order_errors:
            self.pause('order_errors','MAX_CONSECUTIVE_ORDER_ERRORS')
        # A successful protective fill may reset the counter, but a latched
        # order-error circuit is not silently cleared by an unrelated success.

    def update_reconnects(self,count):
        self.reconnect_failures=count
        if count>=self.policy.max_reconnect_failures:
            self.pause('reconnects','MAX_RECONNECT_FAILURES')

    def evaluate(self,snapshot,*,daily_loss,drawdown,daily_loss_limit=None):
        p=self.policy
        reasons=[]
        state=RiskState.NORMAL
        if snapshot.equity<=0 or snapshot.equity<=snapshot.maintenance_margin_estimate*p.maintenance_buffer_multiple:
            state=RiskState.EMERGENCY
            reasons.append('MAINTENANCE_OR_EQUITY_EMERGENCY')
        else:
            utilization=snapshot.initial_margin/snapshot.equity
            limit=snapshot.equity*p.max_daily_loss_fraction if daily_loss_limit is None else daily_loss_limit
            if daily_loss>=limit:
                reasons.append('MAX_DAILY_LOSS')
            if drawdown>=p.max_drawdown_fraction:
                reasons.append('MAX_DRAWDOWN')
            if utilization>p.max_margin_utilization:
                reasons.append('MAX_MARGIN_USAGE')
            if snapshot.gross_notional>snapshot.equity*p.max_gross_equity_multiple:
                reasons.append('MAX_TOTAL_EXPOSURE')
            if reasons:
                state=RiskState.ENTRY_PAUSED
            elif drawdown>=p.max_drawdown_fraction*Decimal('.8') or utilization>=p.max_margin_utilization*Decimal('.8'):
                state=RiskState.CAUTION
        self.financial_state=state
        self.financial_reasons=tuple(reasons)

    @property
    def state(self):
        if self.financial_state==RiskState.EMERGENCY or self.operational_state==RiskState.EMERGENCY:
            return RiskState.EMERGENCY
        if self.global_blocks or self.financial_state==RiskState.ENTRY_PAUSED:
            return RiskState.ENTRY_PAUSED
        if self.symbol_blocks or self.financial_state==RiskState.CAUTION or self.operational_state==RiskState.CAUTION:
            return RiskState.CAUTION
        return RiskState.NORMAL

    def entry_reasons(self,symbol):
        return tuple(self.global_blocks.values())+self.financial_reasons+self.symbol_blocks.get(symbol,())

    def report(self,now_ms):
        signature=(self.state,tuple(sorted(self.global_blocks.items())),repr(self.symbol_blocks),self.financial_reasons)
        if signature!=self._signature:
            self.transitions.append(dict(timestamp_ms=now_ms,state=self.state.value,**timing(now_ms),
                global_reasons=tuple(self.global_blocks.values())+self.financial_reasons,
                paused_symbols=dict(self.symbol_blocks)))
            self._signature=signature
        return dict(state=self.state.value,global_reasons=tuple(self.global_blocks.values())+self.financial_reasons,
            paused_symbols=self.symbol_blocks,consecutive_order_errors=self.consecutive_order_errors,
            reconnect_failures=self.reconnect_failures,transitions=self.transitions)
