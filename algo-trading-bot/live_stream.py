"""Live market data stream for Angel One SmartAPI V2.

VERSION UPDATE (2026-08-25): Rebuilt the live ingestion layer around
SmartConnect + SmartWebSocketV2, removed the legacy websocket-client path,
and hardened the watchdog lifecycle so reconnects do not leak threads.
"""

from __future__ import annotations

import logging
import math
import os
import random
import socket
import sys
import threading
import time
import time as time_module
from datetime import datetime
from typing import Any, Optional

import pyotp
from dotenv import load_dotenv
from SmartApi.smartConnect import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

# Monkeypatch to absorb modern websocket-client 4-arg signature
_orig_on_close = getattr(SmartWebSocketV2, "_on_close", None)
def _patched_on_close(self, *args, **kwargs):
    try:
        if hasattr(self, "_user_on_close") and self._user_on_close:
            self._user_on_close(self, *args, **kwargs)
    except Exception:
        pass
SmartWebSocketV2._on_close = _patched_on_close

from candle_builder import CandleBuilder
from execution_engine import PaperTrader
from market_schedule import (
    BaseMarketSchedule,
    MarketPhase,
    can_enter_new_positions,
    get_market_schedule,
    get_market_state,
    holiday_name,
    is_trading_day,
    seconds_until_market_start,
    to_ist,
)
from signal_brain import generate_vwap_signal


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("trading_bot.log"), logging.StreamHandler()],
)

load_dotenv()


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def _normalize_bearer_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    token = token.strip()
    return token if token.startswith("Bearer ") else f"Bearer {token}"


def _parse_tick_timestamp(value: Any) -> datetime:
    """Parse SmartAPI timestamps to timezone-aware IST datetimes."""
    if value is None or value == "":
        return to_ist()

    try:
        if isinstance(value, (int, float)):
            seconds = float(value)
            if seconds > 10_000_000_000:
                seconds /= 1000.0
            return to_ist(datetime.fromtimestamp(seconds, tz=to_ist().tzinfo))

        text = str(value).replace("Z", "+00:00")
        if text.isdigit():
            seconds = float(text)
            if seconds > 10_000_000_000:
                seconds /= 1000.0
            return to_ist(datetime.fromtimestamp(seconds, tz=to_ist().tzinfo))

        return to_ist(datetime.fromisoformat(text))
    except (OverflowError, OSError, ValueError, TypeError):
        return to_ist()


import signal


TOTAL_CAPITAL = 10010.06
WORKING_CAPITAL = 5005.03  # 50% allocation
BACKUP_CAPITAL = 5005.03   # 50% allocation
RISK_PER_TRADE = 100.00
DAILY_LOSS_LIMIT = 200.00

# Liquid NSE cash equity instruments (<= ₹500 / share)
INSTRUMENTS = {
    "ADANIPOWER": {
        "token": "17388",
        "symbol": "ADANIPOWER",
        "trading_symbol": "ADANIPOWER-EQ",
        "exchange_type": 1,
    },
    "TATASTEEL": {
        "token": "3499",
        "symbol": "TATASTEEL",
        "trading_symbol": "TATASTEEL-EQ",
        "exchange_type": 1,
    },
    "TATAMOTORS": {
        "token": "3456",
        "symbol": "TATAMOTORS",
        "trading_symbol": "TATAMOTORS-EQ",
        "exchange_type": 1,
    },
    "ITC": {
        "token": "1660",
        "symbol": "ITC",
        "trading_symbol": "ITC-EQ",
        "exchange_type": 1,
    },
    "COALINDIA": {
        "token": "20374",
        "symbol": "COALINDIA",
        "trading_symbol": "COALINDIA-EQ",
        "exchange_type": 1,
    },
    "M&M": {
        "token": "2031",
        "symbol": "M&M",
        "trading_symbol": "M&M-EQ",
        "exchange_type": 1,
    },
}

DEFAULT_SYMBOL = "ADANIPOWER"


class AngelOneLiveStream:
    """Manage authenticated live streaming, candle generation, and pyramiding lifecycle."""

    def __init__(
        self,
        target_symbol: str = DEFAULT_SYMBOL,
        schedule: Optional[BaseMarketSchedule] = None,
    ) -> None:
        self.schedule: BaseMarketSchedule = (
            schedule if schedule is not None else get_market_schedule(os.getenv("MARKET_SCHEDULE", "NSE"))
        )
        self.target_symbol = os.getenv("TRADING_SYMBOL", target_symbol).upper()
        if self.target_symbol not in INSTRUMENTS:
            logging.warning(
                "Symbol %s not in pre-configured INSTRUMENTS dictionary. Using %s.",
                self.target_symbol,
                DEFAULT_SYMBOL,
            )
            self.target_symbol = DEFAULT_SYMBOL

        self.instrument_info = INSTRUMENTS[self.target_symbol]
        self.token = self.instrument_info["token"]
        self.symbol = self.instrument_info["symbol"]
        self.trading_symbol = self.instrument_info["trading_symbol"]
        self.exchange_type = self.instrument_info["exchange_type"]
        self.correlation_id = f"{self.symbol.lower()}-snapquote"
        self.subscription_mode = getattr(SmartWebSocketV2, "SNAPQUOTE_MODE", 3)

        self.api_key = _first_env("BROKER_API_KEY")
        self.client_code = _first_env("BROKER_CLIENT_ID", "BROKER_CLIENT_CODE")
        self.client_pin = _first_env("BROKER_PIN", "BROKER_PASSWORD")
        self.totp_secret = _first_env("BROKER_TOTP_SECRET")

        missing = [
            name
            for name, value in (
                ("BROKER_API_KEY", self.api_key),
                ("BROKER_CLIENT_ID/BROKER_CLIENT_CODE", self.client_code),
                ("BROKER_PIN/BROKER_PASSWORD", self.client_pin),
                ("BROKER_TOTP_SECRET", self.totp_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

        self.smart_api: Optional[SmartConnect] = None
        self.websocket: Optional[SmartWebSocketV2] = None
        self.auth_token: Optional[str] = None
        self.feed_token: Optional[str] = None

        self.paper_trader = PaperTrader(
            total_capital=TOTAL_CAPITAL,
            working_capital_pct=0.50,
            daily_loss_limit=DAILY_LOSS_LIMIT,
            risk_per_trade=RISK_PER_TRADE,
            stop_loss_pct=0.005,
            reward_to_risk=2.0,
            schedule=self.schedule,
        )

        self.builder = CandleBuilder(interval_seconds=60, on_candle_close=self.on_candle_close)

        self._shutdown_requested = False
        self._eod_square_off_done = False
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop_event: Optional[threading.Event] = None
        self._reconnect_delay = 1.0
        self._retry_attempt = 0

        self._install_signal_handlers()

    def _install_signal_handlers(self) -> None:
        """Register graceful shutdown handlers for SIGINT and SIGTERM."""
        def _handle_signal(signum, frame):
            sig_name = "SIGINT (Ctrl+C)" if signum == signal.SIGINT else "SIGTERM"
            logging.info(f"\nCaught {sig_name}. Initiating graceful shutdown...")
            self.request_shutdown(sig_name)

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            pass  # May fail on non-main thread in test harnesses

    # ──────────────────────────────────────────────────────────────
    #  Startup / Login
    # ──────────────────────────────────────────────────────────────

    def validate_market_startup(self) -> None:
        """Validate that today is a trading day and wait for the open if needed."""
        now = self.schedule.localize()
        today = now.date()

        if not self.schedule.is_trading_day(today):
            reason = self.schedule.holiday_name(today) or "Weekend/Holiday"
            logging.info(f"Market is closed today ({reason}). Exiting.")
            sys.exit(0)

        state = self.schedule.get_market_state(now)
        if state == MarketPhase.PRE_MARKET:
            wait_seconds = self.schedule.seconds_until_market_start(now)
            open_str = self.schedule.market_open_time.strftime("%H:%M:%S")
            logging.info(
                f"Pre-market startup detected. Waiting until {open_str} "
                f"({wait_seconds:.0f}s)."
            )
            time_module.sleep(wait_seconds)
        elif state in {MarketPhase.SQUARE_OFF, MarketPhase.CLOSED}:
            logging.info("Market is already in shutdown window. Exiting.")
            sys.exit(0)
        elif state == MarketPhase.CLOSE_ONLY:
            cutoff_str = self.schedule.entry_cutoff_time.strftime("%H:%M:%S")
            logging.info(f"Started after {cutoff_str}. Entries are disabled; exits only.")

    def login(self) -> None:
        """Authenticate with SmartAPI and cache jwt/feed tokens for the stream."""
        self.smart_api = SmartConnect(api_key=self.api_key)
        totp = pyotp.TOTP(self.totp_secret).now()
        login_data = self.smart_api.generateSession(self.client_code, self.client_pin, totp)

        if not isinstance(login_data, dict) or not login_data.get("status"):
            raise RuntimeError(f"SmartAPI login failed: {login_data}")

        data = login_data.get("data", {}) or {}
        self.auth_token = _normalize_bearer_token(data.get("jwtToken"))
        self.feed_token = data.get("feedToken") or self.smart_api.getfeedToken()
        self.client_code = data.get("clientcode") or self.client_code

        if not self.auth_token or not self.feed_token or not self.client_code:
            raise RuntimeError("SmartAPI login did not return required auth/feed tokens.")

        logging.info("Angel One SmartAPI authenticated successfully.")

    # ──────────────────────────────────────────────────────────────
    #  Trading Lifecycle
    # ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Login, connect, and keep the live stream running until shutdown with Exponential Backoff + Jitter."""
        self.validate_market_startup()
        self.login()

        logging.info("=" * 60)
        logging.info("  STARTING ALGO TRADING BOT — SMARTAPI V2 STREAM")
        logging.info("  Authenticated live feed -> CandleBuilder -> Signal Brain -> PaperTrader")
        logging.info("=" * 60)

        retry_attempt = 0

        while not self._shutdown_requested:
            if self._shutdown_requested:
                return
            try:
                if self._shutdown_requested:
                    return
                self.websocket = self._build_websocket()
                self._start_watchdog_thread()
                self.websocket.connect()
                if self._shutdown_requested:
                    break
                # Reset retry attempt on clean disconnect/completion
                retry_attempt = 0
                self._retry_attempt = 0
            except KeyboardInterrupt:
                logging.info("Keyboard interrupt received. Shutting down live stream.")
                self.request_shutdown("KeyboardInterrupt")
                break
            except (socket.gaierror, ConnectionError, ConnectionRefusedError, Exception) as exc:
                if self._shutdown_requested:
                    break

                # Exponential Backoff with Jitter:
                # Base Delay = 1.0s, Delay = min(30.0, 1.0 * (2 ** retry_attempt))
                # FinalDelay = Delay + random.uniform(0.0, Delay * 0.3)
                base_delay = 1.0
                delay = min(30.0, base_delay * (2.0 ** retry_attempt))
                jitter = random.uniform(0.0, delay * 0.30)
                final_delay = round(delay + jitter, 2)

                logging.warning(
                    "Connection failed: %s. Retrying in %.2f seconds... (Attempt %d)",
                    exc,
                    final_delay,
                    retry_attempt + 1,
                )
                time_module.sleep(final_delay)
                retry_attempt += 1
                self._retry_attempt = retry_attempt
                if self._shutdown_requested:
                    break
            finally:
                self._stop_watchdog_thread()
                self.websocket = None

        if self._shutdown_requested:
            sys.exit(0)

    def request_shutdown(self, reason: str) -> None:
        """Mark the stream for shutdown, disable SDK auto-reconnect, and close active websocket."""
        logging.info("Shutdown requested: %s", reason)
        self._shutdown_requested = True

        sws = getattr(self, "websocket", None)
        if sws is not None:
            if hasattr(sws, "auto_reconnect"):
                sws.auto_reconnect = False
            if hasattr(sws, "wsapp") and sws.wsapp:
                sws.wsapp.keep_running = False
            try:
                sws.close_connection()
            except Exception:
                pass

        if hasattr(self, "paper_trader") and self.paper_trader is not None:
            try:
                if hasattr(self.paper_trader, "flush_logs"):
                    self.paper_trader.flush_logs()
            except Exception:
                pass

        # Flush all logging handlers
        for handler in logging.root.handlers[:]:
            try:
                handler.flush()
            except Exception:
                pass

        # Ensure process exits cleanly within 1.0s if blocked by external threads
        def _force_exit():
            time_module.sleep(1.0)
            os._exit(0)

        t = threading.Thread(target=_force_exit, daemon=True)
        t.start()

    def _build_websocket(self) -> SmartWebSocketV2:
        if self._shutdown_requested:
            raise RuntimeError("Shutdown already requested; cannot build new WebSocket.")
        if not self.auth_token or not self.feed_token or not self.client_code:
            raise RuntimeError("Cannot build SmartWebSocketV2 without auth/feed tokens.")

        websocket = SmartWebSocketV2(
            auth_token=self.auth_token,
            api_key=self.api_key,
            client_code=self.client_code,
            feed_token=self.feed_token,
            max_retry_attempt=3,
            retry_strategy=1,
            retry_delay=5,
            retry_multiplier=2,
            retry_duration=60,
        )
        websocket.on_open = self._on_open
        websocket.on_data = self._on_data
        websocket.on_message = self._on_message
        websocket.on_error = self._on_error
        websocket.on_close = self._on_close
        websocket.on_control_message = self._on_control_message
        return websocket

    # ──────────────────────────────────────────────────────────────
    #  Candle / Signal / Trade Pipeline
    # ──────────────────────────────────────────────────────────────

    def on_candle_close(self, df) -> None:
        """Run VWAP signal detection and execute/scale-in paper trades on buy signals."""
        result = generate_vwap_signal(df.copy())
        latest = result.iloc[-1]
        signal_timestamp = to_ist()
        atr_val = float(latest.get("ATR_14", float("nan")))

        logging.info(
            f"Candle #{len(result)} closed | "
            f"O:{latest['Open']:.2f}  H:{latest['High']:.2f}  "
            f"L:{latest['Low']:.2f}  C:{latest['Close']:.2f}  "
            f"V:{latest['Volume']:.0f}  |  VWAP:{latest['VWAP']:.2f}  |  "
            f"ATR_14:{atr_val:.2f}"
        )

        # Explicitly notify execution engine that 1-minute candle completed
        self.paper_trader.notify_candle_close(
            candle=latest.to_dict() if hasattr(latest, "to_dict") else dict(latest),
            timestamp=signal_timestamp,
            latest_price=float(latest["Close"]),
        )

        if not bool(latest.get("Buy_Signal")):
            return

        if not can_enter_new_positions(signal_timestamp):
            logging.info(
                "Buy signal rejected - entries are disabled in %s after the 15:15 IST cutoff.",
                get_market_state(signal_timestamp).value,
            )
            return

        logging.info("🚀 ════════════════════════════════════════════════════════")
        logging.info(f"🚀  VWAP PULLBACK BUY SIGNAL  @  VWAP {latest['VWAP']:.2f} (ATR: {atr_val:.2f})")
        logging.info("🚀 ════════════════════════════════════════════════════════")

        self.paper_trader.execute_trade(
            {
                "VWAP": float(latest["VWAP"]),
                "Close": float(latest["Close"]),
                "symbol": self.symbol,
                "ATR_14": atr_val,
                "atr": atr_val,
            },
            timestamp=signal_timestamp,
            atr_14=atr_val,
        )

    def _extract_tick_fields(self, data: dict) -> tuple[float, int, datetime]:
        """Extract LTP, actual trade volume (without fake fallback), and timestamp from SmartAPI data."""
        raw_price = data.get("last_traded_price")
        if raw_price is None:
            raw_price = data.get("ltp") or data.get("price")
        if raw_price is None:
            raise ValueError(f"Invalid SmartAPI tick payload: missing last_traded_price ({data!r})")

        raw_price = float(raw_price)
        price = raw_price / 100.0 if raw_price > 1000 else raw_price
        if price <= 0 or not math.isfinite(price):
            raise ValueError(f"Invalid SmartAPI tick payload: non-positive LTP ({raw_price!r})")

        # Map actual trade volume (SnapQuote mode 3 / Quote mode 2 packet structure)
        raw_volume = (
            data.get("last_traded_quantity")
            or data.get("last_traded_qty")
            or data.get("trade_volume")
            or data.get("volume_trade_for_the_day")
            or data.get("volume_traded_today")
            or data.get("volume")
        )
        volume = 0
        if raw_volume is not None:
            try:
                volume = int(float(raw_volume))
            except (TypeError, ValueError):
                volume = 0

        timestamp = _parse_tick_timestamp(data.get("exchange_timestamp", data.get("last_traded_timestamp")))
        return price, volume, timestamp

    def _on_data(self, wsapp, data: dict) -> None:
        try:
            if not isinstance(data, dict):
                logging.warning("Received non-dict SmartAPI payload: %r", data)
                return

            price, volume, timestamp = self._extract_tick_fields(data)

            if price <= 0 or not math.isfinite(price):
                logging.warning("Rejected invalid LTP payload: %r", data)
                return

            # Failsafe: Only feed ticks with genuine trade volume into the Candle/VWAP builder.
            # If a tick genuinely arrives with 0 volume or missing volume keys from the exchange,
            # skip passing that specific tick to the VWAP engine entirely rather than defaulting to 1.
            if volume > 0:
                self.builder.on_tick(price=price, volume=volume, timestamp=timestamp)
            else:
                logging.debug("Skipped tick with zero volume for VWAP builder: price=%.2f", price)

            self.paper_trader.check_exit(live_price=price, timestamp=timestamp)
            self.enforce_lifecycle(ws=self.websocket, current_dt=timestamp)
        except Exception as exc:
            logging.error("Error processing SmartAPI data frame: %s | payload=%r", exc, data)

    def _on_message(self, wsapp, message: str) -> None:
        if message == "pong":
            logging.debug("SmartAPI heartbeat pong received.")

    def _on_control_message(self, wsapp, message: dict) -> None:
        logging.debug("SmartAPI control message: %s", message)

    def _on_open(self, wsapp) -> None:
        logging.info("WebSocket connection established successfully.")
        self._retry_attempt = 0

        token_list = [
            {
                "exchangeType": self.exchange_type,
                "tokens": [self.token],
            }
        ]

        if self.websocket is None:
            raise RuntimeError("SmartWebSocketV2 is not initialized.")

        self.websocket.subscribe(
            self.correlation_id,
            self.subscription_mode,
            token_list,
        )
        logging.info(
            "Subscribed to %s token %s in SnapQuote mode (mode=%s, exchangeType=%s).",
            self.symbol,
            self.token,
            self.subscription_mode,
            self.exchange_type,
        )

    def _on_error(self, wsapp, error, *args, **kwargs) -> None:
        logging.error("WebSocket Error: %s", error)

    def _on_close(self, wsapp, *args, **kwargs) -> None:
        logging.warning("SmartAPI websocket closed.")
        if not self._shutdown_requested:
            logging.info("Connection dropped. Reconnect supervisor will retry.")

    # ──────────────────────────────────────────────────────────────
    #  EOD / Square-off / Watchdog
    # ──────────────────────────────────────────────────────────────

    def log_daily_summary(self, prefix: str = "Daily Summary") -> None:
        virtual_equity = self.paper_trader.backup_capital + self.paper_trader.working_capital
        logging.info(
            f"{prefix} | Daily P&L: ₹{self.paper_trader.daily_pnl:,.2f} | "
            f"Working Capital: ₹{self.paper_trader.working_capital:,.2f} | "
            f"Virtual Equity: ₹{virtual_equity:,.2f}"
        )

    def trigger_eod_square_off(self, ws, current_dt: datetime, reason: str) -> None:
        """Run the mandatory EOD cleanup exactly once."""
        if self._eod_square_off_done:
            return

        self._eod_square_off_done = True
        loc_dt = self.schedule.localize(current_dt)
        logging.info(f"{reason} triggered at {loc_dt.strftime('%H:%M:%S')}.")
        self.paper_trader.cancel_pending_orders(reason)
        self.paper_trader.square_off_all_positions(reason, timestamp=current_dt)
        self.log_daily_summary("Final Daily P&L")
        self.request_shutdown(reason)

        if ws is not None:
            try:
                ws.close_connection()
            except Exception:
                logging.exception("Failed to close SmartAPI websocket during EOD square-off.")

    def enforce_lifecycle(self, ws=None, current_dt: Optional[datetime] = None) -> MarketPhase:
        """Apply session lifecycle actions for the supplied clock time."""
        clock = self.schedule.localize(current_dt)
        state = self.schedule.get_market_state(clock)

        if state == MarketPhase.SQUARE_OFF or self.schedule.is_eod_square_off(clock):
            self.trigger_eod_square_off(ws, clock, "EOD Auto-Square-Off")
        elif state == MarketPhase.CLOSED:
            if self.paper_trader.has_open_position:
                self.trigger_eod_square_off(ws, clock, "Market Close Safety Square-Off")
            else:
                logging.info("Market closed. Disconnecting and exiting cleanly.")
                self.log_daily_summary("Final Daily P&L")
                self.request_shutdown("Market closed")

        return state

    def lifecycle_watchdog(self, ws, stop_event: threading.Event) -> None:
        """Timer-based lifecycle enforcement independent of incoming ticks."""
        while not self._shutdown_requested and not stop_event.is_set():
            if self._shutdown_requested:
                return
            state = self.enforce_lifecycle(ws=ws, current_dt=self.schedule.localize())
            if state in {MarketPhase.SQUARE_OFF, MarketPhase.CLOSED}:
                return
            time_module.sleep(5)

    def _start_watchdog_thread(self) -> None:
        """Start at most one watchdog thread for the active websocket session."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return

        self._watchdog_stop_event = threading.Event()
        self._watchdog_thread = threading.Thread(
            target=self.lifecycle_watchdog,
            args=(self.websocket, self._watchdog_stop_event),
            daemon=True,
        )
        self._watchdog_thread.start()

    def _stop_watchdog_thread(self) -> None:
        """Stop and join the active watchdog thread, if any."""
        if self._watchdog_stop_event is not None:
            self._watchdog_stop_event.set()

        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=2.0)

        self._watchdog_thread = None
        self._watchdog_stop_event = None


def main() -> None:
    stream = AngelOneLiveStream()
    stream.run()


if __name__ == "__main__":
    main()
