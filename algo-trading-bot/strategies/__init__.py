"""Strategy selection switch. Each entry is pure decision logic with no exchange access."""
from .funding_carry import CarryParams, FundingCarry

STRATEGIES = {'funding_carry': FundingCarry}


def select(name):
    try:
        return STRATEGIES[name]
    except KeyError:
        raise ValueError('UNKNOWN_STRATEGY:'+str(name)) from None
