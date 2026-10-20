"""Isolated 15 October profit-only observation lifecycle; existing SELL path retained."""
from dataclasses import dataclass,asdict,fields
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal as D
from .base_exchange import ExchangeError,decimal
from .exit_recovery import RecoveryMandate,profit_floor,QUANTITY,ENTRY_MS
from .execution_journal import fingerprint
from .qualification_watcher import sweep

START_MS=int(datetime(2026,10,15,tzinfo=ZoneInfo('Asia/Calcutta')).timestamp()*1000)
END_MS=int(datetime(2026,10,15,23,59,tzinfo=ZoneInfo('Asia/Calcutta')).timestamp()*1000)
LONG_MODE='PROFIT_ONLY_LONG_SESSION'

@dataclass(frozen=True)
class LongSessionMandate(RecoveryMandate):
    session_end_ms:int=END_MS
    reconciliation_reserve_ms:int=120000

    def require(self):
        if (self.mode!=LONG_MODE or self.minimum_net_profit!='0.001'
                or type(self.session_end_ms) is not int or self.session_end_ms!=END_MS
                or self.reconciliation_reserve_ms!=120000
                or not START_MS<=self.created_ms<END_MS-420000
                or self.window_ms!=END_MS-self.created_ms):
            raise ExchangeError('EXACT_OCTOBER_15_PROFIT_SESSION_REQUIRED')
        values={f.name:getattr(self,f.name) for f in fields(RecoveryMandate)}
        values.update(mode='PROFIT_ONLY_EXIT',window_ms=600000)
        RecoveryMandate(**values).require()
        return self

    def expires_at(self,accepted_ms):
        self.require()
        if accepted_ms+self.reconciliation_reserve_ms>=self.session_end_ms:
            raise ExchangeError('LONG_SESSION_MANAGEMENT_RESERVE_REQUIRED')
        return self.session_end_ms


def full_day_mandate(base):
    return LongSessionMandate(**dict(asdict(base),mode=LONG_MODE,
        window_ms=END_MS-base.created_ms)).require()


def fee_bound(base_rate,scale):
    base=decimal(base_rate,nonnegative=True)
    return base*(6 if scale is None else 1+scale if scale<1 else 2*scale)


def profit_observation(spec,book,entry,fee,funding,floor,*,now_ms,expires_ms,reserve_ms,market_context,
                       account_ms,fees_ms,funding_ms,reference_ms):
    q=QUANTITY
    be,computed=profit_floor(spec,q,entry.quantity*entry.price,entry.fee,fee,funding)
    floor=max(decimal(floor),computed)
    bid=book.bids[0].price if book and book.bids else None
    ask=book.asks[0].price if book and book.asks else None
    age=now_ms-book.timestamp_ms if book else None
    fresh=age is not None and 0<=age<=5000
    spread=(ask-bid)/((ask+bid)/2)*10000 if bid and ask and ask>bid else None
    limit=spec.normalize_price(max(floor,bid*D('.999')),'SELL') if bid else floor
    depth=sweep(book.bids,q,limit,'SELL') if book and bid else None
    net=q*limit*(1-fee)-entry.quantity*entry.price-entry.fee+funding
    at_bid=q*bid*(1-fee)-entry.quantity*entry.price-entry.fee+funding if bid else None
    ages=dict(account=now_ms-account_ms,fees=now_ms-fees_ms,funding=now_ms-funding_ms,reference=now_ms-reference_ms)
    supporting_fresh=all(0<=ages[k]<=bound for k,bound in dict(account=90000,fees=90000,funding=310000,reference=45000).items())
    candidate=bool(fresh and supporting_fresh and bid is not None and ask is not None and ask>bid
        and spread<=50 and fee<=D('.003') and now_ms+reserve_ms<expires_ms
        and limit<=bid and decimal(depth['available_quantity'])*D('.5')>=q and net>=D('.001'))
    return dict(at_ms=now_ms,bid=bid,ask=ask,book_exchange_ms=book.timestamp_ms if book else None,
        book_received_ms=book.received_timestamp_ms if book else None,book_age_ms=age,
        book_depth=dict(bids=[asdict(v) for v in book.bids],asks=[asdict(v) for v in book.asks]) if book else None,
        mark=market_context.get('markPx'),oracle=market_context.get('oraclePx'),spread_bps=spread,
        remaining_position=q,funding_cashflow=funding,conservative_exit_fee=fee,
        expected_exit_fee_at_limit=q*limit*fee,break_even=be,minimum_sell=floor,
        proposed_limit=limit,estimated_net_at_limit=net,estimated_net_at_bid=at_bid,
        depth=depth,fresh_book=fresh,evidence_ages_ms=ages,candidate=candidate,expires_ms=expires_ms,
        phase='FINAL_READ_ONLY_RESERVE' if now_ms+reserve_ms>=expires_ms else 'PROFIT_ONLY_OBSERVATION',
        evidence_scope='OBSERVATION_ONLY; FULL_FRESH_SIGNING_PREFLIGHT_REQUIRED')


class LongSessionObserver:
    """WS prices; bounded light polls; full history every five minutes or before a SELL."""
    def __init__(self,env,mandate,approval,context,entry):
        self.env,self.m,self.a=env,mandate,approval
        self.m.require();self.context,self.entry=context,entry
        self.floor=decimal(mandate.minimum_sell)
        self.last_candidate=0;self.rows=0;self.full_refreshes=0;self.light_refreshes=0
        self.no_book_since=None;self.claimed=False
        self.adopt(context,entry)

    @property
    def now(self):return self.env.client.clock_ms()

    def adopt(self,context,entry):
        self.context,self.entry=context,entry
        now=self.now;self.account_ms=self.fees_ms=self.reference_ms=now
        self.funding_ms=self.env.recovery.state.last_window[1]
        self.funding=sum((f.cashflow for f in self.env.recovery.state.funding.values()
            if f.symbol=='par:BTC' and f.timestamp_ms>=ENTRY_MS),D(0))
        self.fee=fee_bound(context.readiness.fees['userCrossRate'],self.env.provider.current_fee_scale)
        self.market_context=context.contexts['par:BTC'];self.last_full=now
        self.full_refreshes+=1

    def refresh_if_due(self):
        now=self.now
        # Reported funding arrives hourly. Refresh at the boundary as well as
        # on the five-minute history schedule; signing always reacquires it.
        crossed_hour=self.funding_ms//3600000<now//3600000 and now%3600000>=1500
        if now-self.last_full>=300000 or crossed_hour:
            self.adopt(*self.env.context())
        else:
            if now-self.account_ms>=60000:
                positions=self.env.account.get_positions();orders=self.env.account.get_frontend_open_orders()
                held=positions.get('par:BTC')
                if (len(positions)!=1 or held is None or held.quantity!=QUANTITY
                        or held.entry_price!=self.entry.price or held.leverage!={'type':'cross','value':1} or orders):
                    raise ExchangeError('LONG_SESSION_POSITION_OR_ORDERS_CHANGED')
                self.account_ms=self.now;self.light_refreshes+=1
            if self.now-self.fees_ms>=60000:
                fees=self.env.account._query('userFees');self.env.provider.fee_scale()
                self.fee=fee_bound(fees['userCrossRate'],self.env.provider.current_fee_scale);self.fees_ms=self.now
            if self.now-self.reference_ms>=30000:
                metadata,values=self.env.client.post_info('metaAndAssetCtxs')
                self.env.client.validate_metadata(metadata)
                if fingerprint(metadata)!=self.env.provider.metadata_hash:
                    raise ExchangeError('RECOVERY_METADATA_CHANGED')
                matches=[v for m,v in zip(metadata['universe'],values) if m['name']=='par:BTC']
                if len(matches)!=1:raise ExchangeError('LONG_SESSION_REFERENCE_REQUIRED')
                self.market_context=matches[0];self.reference_ms=self.env.client.last_received_ms
        if self.fee>D('.003'):raise ExchangeError('RECOVERY_FEE_ABOVE_APPROVED_BOUND')
        return self.context,self.entry

    def observation(self,book,origin,connection,*,preflight=False):
        r=profit_observation(self.context.spec,book,self.entry,self.fee,self.funding,self.floor,
            now_ms=self.now,expires_ms=self.a.expires_ms,reserve_ms=self.m.reconciliation_reserve_ms,
            market_context=self.market_context,account_ms=self.account_ms,fees_ms=self.fees_ms,
            funding_ms=self.funding_ms,reference_ms=self.reference_ms)
        self.floor=r['minimum_sell'];self.env.journal.control('exit_long_profit_floor:'+self.m.identity,str(self.floor))
        if not r['fresh_book']:
            if self.no_book_since is None:self.no_book_since=self.now
            if self.now-self.no_book_since>=120000:raise ExchangeError('LONG_SESSION_NO_FRESH_BOOK_TWO_MINUTES')
        else:self.no_book_since=None
        if not preflight and self.now-self.last_candidate<60000:r['candidate']=False
        self.rows+=1
        return dict(r,transport=origin,connection=connection,full_history_refreshes=self.full_refreshes,
            light_account_refreshes=self.light_refreshes)

    def refresh_candidate(self):
        self.last_candidate=self.now
        self.adopt(*self.env.context())
        return self.context,self.entry

    def claim_closing_path(self,auth):
        auth.require(self.m.team_wallet,self.m.api_wallet)
        if self.claimed or self.now+self.m.reconciliation_reserve_ms>=self.a.expires_ms:
            raise ExchangeError('LONG_SESSION_CLOSING_PATH_CONSUMED_OR_EXPIRED')
        key='exit_long_closing_path:'+self.m.identity
        with self.env.journal.transaction():
            if self.env.journal.control(key):raise ExchangeError('LONG_SESSION_CLOSING_PATH_CONSUMED_OR_EXPIRED')
            self.env.journal.db.execute('INSERT INTO controls VALUES (?,?)',(key,str(self.now)))
        self.claimed=True

    def summary(self):
        return dict(observations=self.rows,full_history_refreshes=self.full_refreshes,
            light_account_refreshes=self.light_refreshes,last_profit_floor=str(self.floor),
            closing_path_entered=self.claimed,auto_resume=False,auto_renewal=False)
