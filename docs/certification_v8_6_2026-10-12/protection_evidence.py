"""Read-only public order evidence, never a permission or trading capability."""
from decimal import Decimal as D, InvalidOperation


def assess_open_stop(detail, row, before, after, *, symbol, lot):
    r=dict(one_lot_stop_acceptance=False, exact_position_coverage=False,
        position_attached_grouping_verified=False, residual_behavior_verified=False,
        capability_validated=False, reasons=[])
    try:
        if before != after: raise ValueError('POSITION_CHANGED_DURING_READBACK')
        positions=[v['position'] for v in after['assetPositions'] if D(v['position']['szi'])]
        held=[p for p in positions if p['coin']==symbol]
        if len(held)!=1: raise ValueError('NO_UNAMBIGUOUS_CURRENT_POSITION')
        if detail.get('status')!='order' or detail['order']['status']!='open':
            raise ValueError('ORIGINAL_STOP_NOT_OPEN')
        original=detail['order']['order']
        for key in ('coin','oid','side','sz','limitPx','isTrigger','reduceOnly','triggerPx','orderType'):
            if key not in original or original[key]!=row.get(key): raise ValueError('ORDER_READBACK_MISMATCH')
        if symbol!=row['coin'] or not symbol.startswith('par:'): raise ValueError('WRONG_VENUE')
        if row.get('isTrigger') is not True or row.get('reduceOnly') is not True:
            raise ValueError('NOT_A_REDUCE_ONLY_TRIGGER')
        if row['orderType'] not in {'Stop Limit','Stop Market'}: raise ValueError('NOT_A_STOP')
        q,price,trigger,lot,signed=[D(str(v)) for v in
            (row['sz'],row['limitPx'],row['triggerPx'],lot,held[0]['szi'])]
        if not all(v.is_finite() for v in (q,price,trigger,lot,signed)) or min(q,price,trigger,lot)<=0:
            raise ValueError('INVALID_STOP_OR_LOT')
        if D(original['origSz'])!=q or q!=lot or q*price>=10: raise ValueError('NOT_ORIGINAL_SUBMINIMUM_ONE_LOT')
        if abs(signed)!=q or row['side']!=('A' if signed>0 else 'B'):
            raise ValueError('STOP_DOES_NOT_EXACTLY_COVER_POSITION')
        r.update(one_lot_stop_acceptance=True,exact_position_coverage=True,
            position_attached_grouping_verified=row.get('isPositionTpsl') is True,
            oid=row['oid'],quantity=str(q),limit_notional=str(q*price),signed_position=str(signed))
        r['reasons'].append('TRIGGER_AND_RESIDUAL_BEHAVIOR_NOT_VERIFIED')
    except (ValueError,KeyError,TypeError,InvalidOperation,ArithmeticError) as exc:
        r['reasons'].append(str(exc) if isinstance(exc,ValueError) else 'INCOMPLETE_OR_INVALID_EVIDENCE')
    return r
