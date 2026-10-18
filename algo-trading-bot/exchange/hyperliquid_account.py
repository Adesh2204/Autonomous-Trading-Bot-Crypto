"""Public-address account reads; never accepts a private key or signs actions."""
import re
from dataclasses import replace
from .event_timing import timing

from .base_exchange import AccountEquity, ExchangeError, Fill, Position, VenueMismatch, decimal
from .hyperliquid_market_data import timestamp
from .account_events import AccountFunding


def event_id(value):
    if isinstance(value,bool) or not isinstance(value,(int,str)) or not re.fullmatch(r'[0-9]+',str(value)):
        raise ExchangeError('INVALID_ACCOUNT_EVENT_ID')
    result=int(value)
    if not 0<=result<2**64:
        raise ExchangeError('INVALID_ACCOUNT_EVENT_ID')
    return str(result)


class HyperliquidAccount:
    def __init__(self, client, team_address):
        if not isinstance(team_address, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', team_address):
            raise ExchangeError('PUBLIC_TEAM_ADDRESS_REQUIRED')
        if int(team_address[2:],16)==0:
            raise ExchangeError('ACCOUNT_NOT_CONFIGURED')
        self.client = client
        self.team_address = team_address

    def _query(self, query, **parameters):
        if not self.client.ready:
            raise VenueMismatch('PAR_STARTUP_CHECK_REQUIRED')
        return self.client.post_info(query, user=self.team_address, **parameters)

    def get_positions(self):
        state = self._query('clearinghouseState')
        if not isinstance(state, dict) or not isinstance(state.get('assetPositions'), list):
            raise ExchangeError('INVALID_ACCOUNT_POSITIONS')
        positions = {}
        try:
            for row in state['assetPositions']:
                position = row['position']
                symbol = position['coin']
                self.client.market(symbol)
                quantity = decimal(position['szi'])
                if symbol in positions:
                    raise ExchangeError('DUPLICATE_ACCOUNT_POSITION')
                if not quantity:
                    continue
                entry = position.get('entryPx')
                liquidation = position.get('liquidationPx')
                leverage=position.get('leverage')
                if leverage is not None and (not isinstance(leverage,dict) or leverage.get('type') not in {'cross','isolated'} or
                    type(leverage.get('value')) is not int or leverage['value']<1):
                    raise ExchangeError('INVALID_POSITION_LEVERAGE')
                positions[symbol] = Position(
                    symbol, quantity, decimal(entry, positive=True) if entry is not None else None,
                    decimal(position['unrealizedPnl']), decimal(position['marginUsed'], nonnegative=True),
                    decimal(liquidation, positive=True) if liquidation is not None else None,leverage)
        except (KeyError, TypeError) as exc:
            raise ExchangeError('INVALID_ACCOUNT_POSITIONS') from exc
        return positions

    def get_position(self, symbol):
        self.client.market(symbol)
        return self.get_positions().get(symbol)

    def get_open_orders(self):
        rows = self._query('openOrders')
        if not isinstance(rows, list):
            raise ExchangeError('INVALID_OPEN_ORDERS')
        try:
            seen=set()
            for row in rows:
                self.client.market(row['coin'])
                oid=event_id(row['oid'])
                if oid in seen:
                    raise ExchangeError('DUPLICATE_OPEN_ORDER_ID')
                seen.add(oid)
        except (TypeError, KeyError) as exc:
            raise ExchangeError('INVALID_OPEN_ORDERS') from exc
        return rows

    def get_fills(self, *, start_ms=None, end_ms=None):
        if start_ms is None:
            if end_ms is not None:
                raise ExchangeError('FILL_START_TIME_REQUIRED')
            rows = self._query('userFills')
        else:
            start_ms=timestamp(start_ms)
            end_ms=self.client.clock_ms() if end_ms is None else timestamp(end_ms)
            if end_ms<start_ms or end_ms>self.client.clock_ms():
                raise ExchangeError('INVALID_FILL_TIME_RANGE')
            rows=self._query('userFillsByTime',startTime=start_ms,endTime=end_ms,aggregateByTime=False)
        if not isinstance(rows, list):
            raise ExchangeError('INVALID_ACCOUNT_FILLS')
        if len(rows)>=2000:
            raise ExchangeError('FILL_HISTORY_PAGE_LIMIT_REQUIRES_PAGINATION')
        fills = {}
        try:
            for row in rows:
                symbol = row['coin']
                # userFills spans venues and has no dex argument. Filter explicitly.
                if not isinstance(symbol, str):
                    raise ExchangeError('INVALID_ACCOUNT_FILLS')
                if symbol != self.client.api_market:
                    continue
                self.client.market(symbol)
                if row['side'] not in {'B', 'A'} or row['feeToken'] != self.client.collateral_token_name:
                    raise ExchangeError('INVALID_ACCOUNT_FILLS')
                fill = Fill(symbol, timestamp(row['time']), event_id(row['tid']), event_id(row['oid']),
                            'BUY' if row['side'] == 'B' else 'SELL',
                            decimal(row['sz'], positive=True), decimal(row['px'], positive=True),
                            decimal(row['fee']), row['feeToken'],
                            decimal(row['closedPnl']) if 'closedPnl' in row else None,
                            decimal(row['startPosition']) if 'startPosition' in row else None,
                            'EXCHANGE_REPORTED_FILL')
                clocks=timing(self.client.clock_ms(),exchange_ms=fill.timestamp_ms,received_ms=self.client.last_received_ms,source='EXCHANGE_REPORTED_FILL')
                fill=replace(fill,**{k:clocks[k] for k in ('exchange_ts','received_ts','processed_ts')})
                if fill.timestamp_ms>self.client.clock_ms() or start_ms is not None and not start_ms<=fill.timestamp_ms<=end_ms:
                    raise ExchangeError('FILL_OUTSIDE_REQUESTED_WINDOW')
                prior = fills.get(fill.identity)
                if prior is not None and prior != fill:
                    raise ExchangeError('CONFLICTING_ACCOUNT_FILLS')
                fills[fill.identity] = fill
        except (KeyError, TypeError) as exc:
            raise ExchangeError('INVALID_ACCOUNT_FILLS') from exc
        return sorted(fills.values(), key=lambda fill: fill.identity)

    def get_frontend_open_orders(self):
        """Trigger-aware team/DEX snapshot; ordinary openOrders omits trigger fields."""
        rows=self._query('frontendOpenOrders')
        if not isinstance(rows,list):
            raise ExchangeError('INVALID_FRONTEND_OPEN_ORDERS')
        seen=set()
        for row in rows:
            try:
                self.client.market(row['coin'])
                oid=event_id(row['oid'])
                if oid in seen or row['side'] not in {'B','A'}:
                    raise ExchangeError('INVALID_FRONTEND_OPEN_ORDERS')
                seen.add(oid)
                decimal(row['sz'],positive=True)
                decimal(row['limitPx'],positive=True)
                if type(row['isTrigger']) is not bool or type(row['reduceOnly']) is not bool:
                    raise ExchangeError('INVALID_FRONTEND_OPEN_ORDERS')
                if row['isTrigger']:
                    decimal(row['triggerPx'],positive=True)
            except (KeyError,TypeError):
                raise ExchangeError('INVALID_FRONTEND_OPEN_ORDERS') from None
        return rows

    def get_funding(self, start_ms, end_ms=None):
        start_ms=timestamp(start_ms)
        end_ms=self.client.clock_ms() if end_ms is None else timestamp(end_ms)
        if end_ms<start_ms or end_ms>self.client.clock_ms():
            raise ExchangeError('INVALID_FUNDING_TIME_RANGE')
        rows=self._query('userFunding',startTime=start_ms,endTime=end_ms)
        if not isinstance(rows,list):
            raise ExchangeError('INVALID_ACCOUNT_FUNDING')
        if len(rows)>=500:
            raise ExchangeError('FUNDING_HISTORY_PAGE_LIMIT_REQUIRES_PAGINATION')
        events={}
        try:
            for row in rows:
                delta=row['delta']
                symbol=delta['coin']
                if not isinstance(symbol,str):
                    raise ExchangeError('INVALID_ACCOUNT_FUNDING')
                if symbol != self.client.api_market:
                    continue
                self.client.market(symbol)
                if delta['type']!='funding' or not start_ms<=timestamp(row['time'])<=end_ms:
                    raise ExchangeError('INVALID_ACCOUNT_FUNDING')
                # The protocol calls the collateral amount "usdc" even for
                # HIP-3 collateral. Use the reported signed amount verbatim.
                event=AccountFunding(symbol,row['time'],row['hash'],delta['usdc'],delta['szi'],delta['fundingRate'])
                clocks=timing(self.client.clock_ms(),exchange_ms=event.timestamp_ms,received_ms=self.client.last_received_ms,source='EXCHANGE_REPORTED_USER_FUNDING')
                event=replace(event,**{k:clocks[k] for k in ('exchange_ts','received_ts','processed_ts')})
                prior=events.get(event.identity)
                if prior is not None and prior!=event:
                    raise ExchangeError('CONFLICTING_ACCOUNT_FUNDING')
                events[event.identity]=event
        except (KeyError,TypeError) as exc:
            raise ExchangeError('INVALID_ACCOUNT_FUNDING') from exc
        return sorted(events.values(),key=lambda event:event.identity)

    def _complete_history(self,reader,start_ms,end_ms,limit_code,*,max_requests=64):
        """Split saturated time windows. An indivisible full millisecond is
        incomplete evidence, never a complete history page by assumption."""
        end_ms=self.client.clock_ms() if end_ms is None else end_ms
        windows=[(start_ms,end_ms)]
        events={};requests=0
        while windows:
            a,b=windows.pop()
            requests+=1
            if requests>max_requests:
                raise ExchangeError('ACCOUNT_HISTORY_BACKFILL_BUDGET_EXCEEDED')
            try:
                rows=reader(a,b)
            except ExchangeError as exc:
                if str(exc)!=limit_code:raise
                if a>=b:raise ExchangeError('ACCOUNT_HISTORY_SATURATED_TIMESTAMP_REQUIRES_REVIEW') from None
                midpoint=(a+b)//2
                windows.extend([(midpoint+1,b),(a,midpoint)])
                continue
            for event in rows:
                prior=events.get(event.identity)
                if prior is not None and prior!=event:raise ExchangeError('CONFLICTING_BACKFILLED_EVENT')
                events[event.identity]=event
        return sorted(events.values(),key=lambda e:e.identity)

    def get_complete_fills(self,start_ms,end_ms=None):
        return self._complete_history(lambda a,b:self.get_fills(start_ms=a,end_ms=b),start_ms,end_ms,
                                      'FILL_HISTORY_PAGE_LIMIT_REQUIRES_PAGINATION')

    def get_complete_funding(self,start_ms,end_ms=None):
        return self._complete_history(self.get_funding,start_ms,end_ms,
                                      'FUNDING_HISTORY_PAGE_LIMIT_REQUIRES_PAGINATION')

    def get_equity(self):
        if self._query('userAbstraction') != 'unifiedAccount':
            raise ExchangeError('UNIFIED_ACCOUNT_REQUIRED')
        state = self._query('clearinghouseState')
        spot = self._query('spotClearinghouseState')
        try:
            token = self.client.collateral_token_id
            if type(token) is not int or token < 0:
                raise ExchangeError('COLLATERAL_TOKEN_MAPPING_REQUIRED')
            balances = [row for row in spot['balances'] if row.get('coin') == self.client.collateral_token_name]
            if len(balances) > 1:
                raise ExchangeError('AMBIGUOUS_COLLATERAL_BALANCE')
            token_balances = [row for row in spot['balances'] if row.get('token') == token]
            if balances and (type(balances[0].get('token')) is not int or
                             balances[0]['token'] != token or len(token_balances) != 1):
                raise ExchangeError('COLLATERAL_TOKEN_MISMATCH')
            if not balances and token_balances:
                raise ExchangeError('COLLATERAL_TOKEN_MISMATCH')
            collateral = decimal(balances[0]['total'], nonnegative=True) if balances else decimal(0)
            # Unified collateral lives in spotClearinghouseState. Use the token
            # symbol resolved from live metadata; never assume USDPR/USDP.
            # Trading capacity still comes separately from activeAssetData.
            margin = decimal(0)
            seen = set()
            for row in state['assetPositions']:
                position = row['position']
                symbol = position['coin']
                self.client.market(symbol)
                if symbol in seen:
                    raise ExchangeError('DUPLICATE_ACCOUNT_POSITION')
                seen.add(symbol)
                if decimal(position['szi']):
                    margin += decimal(position['marginUsed'], nonnegative=True)
            return AccountEquity(collateral, collateral, margin, None,
                                 'spotClearinghouseState.' + str(self.client.collateral_token_name) + '.total')
        except (KeyError, TypeError) as exc:
            raise ExchangeError('ACCOUNT_EQUITY_UNAVAILABLE') from exc

    def get_balance(self):
        """Reported runtime-discovered PAS collateral; never inferred free margin."""
        return self.get_equity().collateral_balance

    def get_funding_history(self, start_ms, end_ms=None):
        return self.get_funding(start_ms,end_ms)
