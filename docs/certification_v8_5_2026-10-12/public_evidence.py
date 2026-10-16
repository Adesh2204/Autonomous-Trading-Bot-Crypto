"""Read-only evidence classification, never an execution permit or validator.

Historical fill arithmetic describes position immediately after that fill; it
is not an independent historical position snapshot or a present-day guarantee.
One lot means the CURRENT freshly queried runtime size increment.
"""
from decimal import Decimal, InvalidOperation


def classify(order_status, raw_fills, *, coin, lot):
    result = dict(exact_full_close=False, one_lot_full_close=False,
                  subminimum_stop_filled=False, stop_acceptance_observed=False,
                  current_lot=str(lot), post_fill_position=None,
                  protection_partial_fill_behavior_verified=False,
                  authority='PUBLIC_HISTORICAL_OBSERVATION_ONLY', reasons=[])
    try:
        lot = Decimal(str(lot))
        if not lot.is_finite() or lot <= 0:
            raise ValueError('INVALID_LOT')
        if order_status.get('status') != 'order':
            raise ValueError('ORIGINAL_ORDER_NOT_FOUND')
        historical = order_status['order']; order = historical['order']
        if order['coin'] != coin or not coin.startswith('par:'):
            raise ValueError('COIN_MISMATCH')
        if type(order['oid']) is not int or type(order.get('reduceOnly')) is not bool:
            raise ValueError('INVALID_ORIGINAL_ORDER')
        quantity, price = Decimal(order['origSz']), Decimal(order['limitPx'])
        if any(not v.is_finite() or v <= 0 for v in (quantity, price)):
            raise ValueError('INVALID_ORIGINAL_SIZE_OR_PRICE')
        result.update(oid=order['oid'], original_quantity=str(quantity),
                      original_limit_notional=str(quantity*price),
                      current_lot_count=str(quantity/lot), status=historical['status'])
        if order['reduceOnly'] is not True:
            raise ValueError('ORIGINAL_ORDER_NOT_REDUCE_ONLY')
        if order['side'] not in {'A', 'B'}:
            raise ValueError('INVALID_SIDE')
        if quantity*price >= 10:
            raise ValueError('ORIGINAL_ORDER_NOT_SUBMINIMUM')
        trigger = order.get('isTrigger') is True
        stop = trigger and order.get('orderType') in {'Stop Limit', 'Stop Market'}
        if trigger and not stop:
            raise ValueError('NOT_A_STOP_LOSS')
        if stop:
            trigger_px = Decimal(order['triggerPx'])
            if not trigger_px.is_finite() or trigger_px <= 0:
                raise ValueError('INVALID_STOP_TRIGGER')
            result['stop_acceptance_observed'] = historical['status'] in {
                'open', 'triggered', 'filled', 'canceled', 'cancelled'}
            result['stop_grouping_position_attached'] = order.get('isPositionTpsl') is True
        elif order.get('isTrigger') is not False or order.get('tif') != 'Ioc':
            raise ValueError('NOT_VERIFIED_MANUAL_IOC_CLOSE')
        if historical['status'] != 'filled':
            raise ValueError('NOT_FILLED')
        if Decimal(order['sz']) != 0:
            raise ValueError('ORDER_HAS_REMAINDER')
        fills = [f for f in raw_fills if f.get('coin') == coin and f.get('oid') == order['oid']]
        if not fills:
            raise ValueError('NO_MATCHED_FILLS')
        # Reject duplicate identities rather than silently double-count them.
        identities = [(f['coin'], f['tid']) for f in fills]
        if len(set(identities)) != len(identities):
            raise ValueError('DUPLICATE_FILL_IDENTITIES')
        fills.sort(key=lambda f: (f['time'], f['tid']))
        start = Decimal(fills[0]['startPosition'])
        if not start.is_finite() or abs(start) != quantity:
            raise ValueError('NOT_ENTIRE_START_POSITION')
        long = start > 0
        side, direction = ('A', 'Close Long') if long else ('B', 'Close Short')
        if order['side'] != side:
            raise ValueError('CLOSE_DIRECTION_MISMATCH')
        position, total = start, Decimal(0)
        for fill in fills:
            size, fill_price, fill_start = (Decimal(fill[k]) for k in ('sz', 'px', 'startPosition'))
            if any(not v.is_finite() for v in (size, fill_price, fill_start)) or size <= 0 or fill_price <= 0:
                raise ValueError('INVALID_FILL')
            if fill['side'] != side or fill['dir'] != direction or fill['feeToken'] != 'USDPR':
                raise ValueError('FILL_DIRECTION_OR_COLLATERAL_MISMATCH')
            if fill_start != position:
                raise ValueError('INCOMPLETE_OR_INTERLEAVED_FILL_CHAIN')
            if size > abs(position):
                raise ValueError('FILL_WOULD_FLIP_POSITION')
            position += -size if long else size
            total += size
        result.update(matched_fill_count=len(fills), filled_quantity=str(total),
                      post_fill_position=str(position),
                      final_quantity_evidence='DERIVED_FROM_REPORTED_START_POSITION_AND_MATCHED_FILLS')
        if total != quantity or position != 0:
            raise ValueError('INCOMPLETE_FULL_CLOSE')
        result['exact_full_close'] = True
        result['one_lot_full_close'] = not trigger and quantity == lot
        result['subminimum_stop_filled'] = stop
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError) as exc:
        result['reasons'].append(str(exc) if isinstance(exc, ValueError) else 'INVALID_OR_INCOMPLETE_EVIDENCE')
    return result
