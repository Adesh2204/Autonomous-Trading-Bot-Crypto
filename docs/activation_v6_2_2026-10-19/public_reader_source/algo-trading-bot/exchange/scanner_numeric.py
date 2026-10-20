"""Validate frozen output at the scanner boundary without changing its math."""
from .base_exchange import ExchangeError,decimal


def scanner_number(value, field, evidence, *, nonnegative=False):
    record=dict(field=field,operand_type=type(value).__name__,operand=str(value))
    try:
        result=decimal(value,nonnegative=nonnegative,positive=not nonnegative)
    except ExchangeError as exc:
        try:
            candidate=decimal(value)
            reason='NEGATIVE' if candidate<0 else 'NONPOSITIVE'
        except ExchangeError:reason='NONFINITE_OR_NOT_DECIMAL'
        record.update(valid=False,reason=reason,exception_type=type(exc).__name__)
        evidence.setdefault('numeric_fields',{})[field]=record
        raise ExchangeError('SCANNER_NUMERIC_INVALID:'+field+':'+reason) from exc
    record['valid']=True
    evidence.setdefault('numeric_fields',{})[field]=record
    return result
