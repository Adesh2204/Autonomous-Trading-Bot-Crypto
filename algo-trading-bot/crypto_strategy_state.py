"""Provider callbacks around verified baseline target/close-stop/bias behavior."""
from datetime import datetime, timezone
from decimal import Decimal
import threading

from exchange.base_exchange import ExchangeError
from exchange.market_health import bar_step
from session_manager import SessionManager
from strategy_contract import ManagementState, baseline_parameters, frozen_management_class


class CryptoStrategyState(frozen_management_class()):
    def __init__(self, symbol, close_callback, *, clock_ms, session=None):
        self.symbol=symbol
        self.close_callback=close_callback
        self.clock_ms=clock_ms
        self.schedule=session or SessionManager()
        self.lock=threading.RLock()
        self.max_tranches=1  # The validated SafeTrader already enforces one tranche.
        self._open_position=None
        self._state=ManagementState.CLOSED
        self.daily_bias='NEUTRAL'
        self.candles_since_last_sl=10000
        self.candles_held=0
        self.entry_atr=None
        self._day=None
        self.last_candle_ms=None
        self.parameters=baseline_parameters()

    @property
    def has_open_position(self):
        return self._open_position is not None

    def _resolve_timestamp(self, value):
        return self.schedule.localize(value or datetime.fromtimestamp(self.clock_ms()/1000,timezone.utc))

    def _check_day_reset(self, value):
        day=self.schedule.localize(value).date()
        if self._day!=day:
            self._day=day
            self.daily_bias='NEUTRAL'
            # Overnight liquidation/halt is a stock-session assumption. A par
            # position and its candle counters survive the UTC date boundary.

    def _set_latest_price(self, price, timestamp):
        self.latest_price=price

    def close_position(self, exit_price, timestamp=None, reason='Signal Exit'):
        return self.close_callback(self.symbol,reason)

    def square_off_all_positions(self, **kwargs):
        raise ExchangeError('STOCK_EOD_PATH_MUST_NOT_RUN')

    def confirm_entry(self, fill, decision):
        if self.has_open_position:
            raise ExchangeError('STRATEGY_POSITION_ALREADY_OPEN')
        self.entry_atr=float(abs(decision.target-decision.stop)/
            Decimal(str(self.parameters['SL_ATR_MULT']+self.parameters['TP_ATR_MULT'])))
        self._open_position=dict(side=fill.side,quantity=fill.quantity,
            average_entry_price=float(fill.price),target_price=float(decision.target),
            stop_loss_price=float(decision.stop),current_tranches=1,
            tranches=[{'entry_price':float(fill.price)}],breakeven_armed=False,atr_14=self.entry_atr)
        self._state=ManagementState.HOLDING_TRANCHE_1
        self.candles_held=0

    def confirm_exit(self, fill, reason):
        p=self._open_position
        if p is None or fill.quantity>p['quantity']:
            raise ExchangeError('STRATEGY_EXIT_QUANTITY_MISMATCH')
        p['quantity']-=fill.quantity
        if not p['quantity']:
            self._open_position=None
            self._state=ManagementState.CLOSED
            self.candles_held=0
            self.entry_atr=None
            if 'Stop Loss' in reason:
                self.candles_since_last_sl=0

    def completed_candle(self, candle):
        if candle.symbol!=self.symbol:
            raise ExchangeError('STRATEGY_CANDLE_IDENTITY_MISMATCH')
        if self.last_candle_ms is not None and candle.timestamp_ms<=self.last_candle_ms:
            return None
        step=bar_step([candle])
        if self.last_candle_ms is not None and candle.timestamp_ms-self.last_candle_ms!=step:
            raise ExchangeError('STRATEGY_STATE_CANDLE_GAP')
        if candle.timestamp_ms+step>self.clock_ms():
            raise ExchangeError('OPEN_CANDLE_NOT_ELIGIBLE')
        self.last_candle_ms=candle.timestamp_ms
        ts=datetime.fromtimestamp((candle.timestamp_ms+step)/1000,timezone.utc)
        self._check_day_reset(ts)
        return self.notify_candle_close({'Timestamp':ts,'Close':float(candle.close)})

    def permits(self, side):
        if self.candles_since_last_sl<self.parameters['REENTRY_COOLDOWN_CANDLES']:
            return False
        return not (side=='BUY' and self.daily_bias=='SHORT_BIAS' or
                    side=='SELL' and self.daily_bias=='LONG_BIAS')

    def recover_idle_cursor(self,candle):
        if self.has_open_position:
            raise ExchangeError('OPEN_POSITION_STATE_REPLAY_REQUIRED')
        # No exposure was held during the missing minutes. Keep cooldown state
        # and count only the newly observed bar; never invent missed increments.
        self.last_candle_ms=None
        return self.completed_candle(candle)
