"""Reuse verified baseline management functions without importing NSE plumbing."""
import __future__
import ast
from datetime import datetime
from enum import Enum
import logging
from pathlib import Path
import json

from strategy_freeze import verify_strategy_freeze

ROOT=Path(__file__).resolve().parents[1]


def baseline_parameters():
    verify_strategy_freeze()
    return json.loads((ROOT/'docs/strategy_freeze.json').read_text())['parameters']['algo-trading-bot/config.py']


class ManagementState(str,Enum):
    HOLDING_TRANCHE_1='HOLDING_TRANCHE_1'
    CLOSED='CLOSED'


class VenueLogging:
    def __getattr__(self,name):
        def write(message,*args,**kwargs):
            return getattr(logging,name)(str(message).replace('₹','USDPR '),*args,**kwargs)
        return write


def frozen_management_class():
    verify_strategy_freeze()
    source=ast.parse((ROOT/'algo-trading-bot/execution_engine.py').read_text())
    legacy=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='LegacyPaperTrader')
    names={'update_daily_bias','check_exit','notify_candle_close'}
    functions=[n for n in legacy.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in functions}!=names:
        raise RuntimeError('FROZEN_MANAGEMENT_METHOD_MISSING')
    # Compile only hash-verified functions from the local trusted source. Module
    # imports, constructors, broker transport and legacy fee functions never run.
    node=ast.ClassDef(name='FrozenManagement',bases=[],keywords=[],body=functions,decorator_list=[])
    module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    namespace={'logging':VenueLogging(),'datetime':datetime,'PyramidingState':ManagementState}
    exec(compile(module,'<verified-baseline-management>','exec',
                 flags=__future__.annotations.compiler_flag),namespace)
    return namespace['FrozenManagement']
