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
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from config import LIVE_MODE

# Load .env credentials at startup
load_dotenv(
    dotenv_path=os.path.join(
        os.path.dirname(__file__), ".env"
    )
)

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
from execution_engine import (
    PaperTrader,
    get_actual_fill_price,
    get_live_capital,
    reconcile_trade,
    reconcile_trade_intraday,
    reconcile_end_of_day,
    init_reconciliation_baselines,
    alert_human,
    calculate_true_friction,
    validate_trade_margin,
)
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
from signal_brain import detect_daily_bias, generate_vwap_signal


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


try:
    from config import (
        SYMBOL as DEFAULT_SYMBOL,
        TOTAL_CAPITAL,
        WORKING_CAPITAL,
        BACKUP_CAPITAL,
        RISK_PER_TRADE,
        DAILY_LOSS_LIMIT,
        TOKEN as CONFIG_TOKEN,
    )
except ImportError:
    DEFAULT_SYMBOL = "ONGC"
    TOTAL_CAPITAL = 10000.00
    WORKING_CAPITAL = 5000.00
    BACKUP_CAPITAL = 5000.00
    RISK_PER_TRADE = 100.00
    DAILY_LOSS_LIMIT = 200.00
    CONFIG_TOKEN = "2475"

# Liquid NSE cash equity instruments
INSTRUMENTS = {
    "ONGC": {
        "token": "2475",
        "symbol": "ONGC",
        "trading_symbol": "ONGC-EQ",
        "exchange_type": 1,
    },
    "IFCI": {
        "token": "1491",
        "symbol": "IFCI",
        "trading_symbol": "IFCI-EQ",
        "exchange_type": 1,
    },
    "BANKBARODA": {
        "token": "4668",
        "symbol": "BANKBARODA",
        "trading_symbol": "BANKBARODA-EQ",
        "exchange_type": 1,
    },
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
    "YESBANK": {
        "token": "11915",
        "symbol": "YESBANK",
        "trading_symbol": "YESBANK-EQ",
        "exchange_type": 1,
    },
}


class AngelOneLiveStream:
    """Manage authenticated live streaming, candle generation, and pyramiding lifecycle."""

    def __init__(
        self,
        target_symbol: str = DEFAULT_SYMBOL,
        schedule: Optional[BaseMarketSchedule] = None,
        angel_session: Optional[SmartConnect] = None,
    ) -> None:
        self.schedule: BaseMarketSchedule = (
            schedule if schedule is not None else get_market_schedule(os.getenv("MARKET_SCHEDULE", "NSE"))
        )
        self.target_symbol = os.getenv("TRADING_SYMBOL", target_symbol).upper()
        base_sym = self.target_symbol.replace("-EQ", "")
        if self.target_symbol in INSTRUMENTS:
            self.instrument_info = INSTRUMENTS[self.target_symbol]
        elif base_sym in INSTRUMENTS:
            self.instrument_info = INSTRUMENTS[base_sym]
        else:
            self.instrument_info = {
                "token": CONFIG_TOKEN,
                "symbol": base_sym,
                "trading_symbol": f"{base_sym}-EQ",
                "exchange_type": 1,
            }
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
        self.angel_session: Optional[SmartConnect] = (
            angel_session if angel_session is not None else (angel_login() if LIVE_MODE else None)
        )
        self.paper_trader.angel_session = self.angel_session

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
        """Authenticate with SmartAPI and cache jwt/feed tokens for the stream.
        Includes retry with exponential backoff for rate-limit / transient errors."""
        max_retries = 5
        base_delay = 30  # seconds — Angel One rate-limit window

        for attempt in range(1, max_retries + 1):
            try:
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
                return  # ← success, exit retry loop

            except Exception as e:
                err_msg = str(e).lower()
                is_rate_limit = "access rate" in err_msg or "rate" in err_msg or "too many" in err_msg
                is_transient = "json" in err_msg or "parse" in err_msg or "connection" in err_msg

                if (is_rate_limit or is_transient) and attempt < max_retries:
                    wait = base_delay * attempt  # 30s, 60s, 90s, 120s
                    logging.warning(
                        f"[LOGIN RETRY {attempt}/{max_retries}] {e} — "
                        f"waiting {wait}s before retry..."
                    )
                    time_module.sleep(wait)
                else:
                    raise  # non-recoverable or max retries exhausted

    # ──────────────────────────────────────────────────────────────
    #  Trading Lifecycle
    # ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Login, connect, and keep the live stream running until shutdown with Exponential Backoff + Jitter."""
        self.validate_market_startup()
        self.login()

        # Fix #2: Sync capital with the real account at startup
        session = self.angel_session if self.angel_session is not None else self.smart_api
        if LIVE_MODE and session is not None:
            try:
                live_cap = get_live_capital(session)
                self.paper_trader.working_capital = live_cap
                self._day_opening_capital = live_cap
                logging.info(f"[CAPITAL SYNC ✅] Synchronized Working Capital with Angel One: ₹{live_cap:,.2f}")
                # Fix #6: Snapshot broker position baselines for restart safety
                self.paper_trader.init_reconciliation_baselines(session)
            except Exception as exc:
                logging.error(f"[CAPITAL SYNC ERROR] Failed to fetch live capital at startup: {exc}")
                self._day_opening_capital = self.paper_trader.working_capital
        else:
            self._day_opening_capital = self.paper_trader.working_capital

        logging.info("=" * 60)
        logging.info("  STARTING ALGO TRADING BOT — SMARTAPI V2 STREAM")
        logging.info("  Authenticated live feed -> CandleBuilder -> Signal Brain -> PaperTrader")
        logging.info(f"  Target Asset      : {self.symbol} ({self.trading_symbol}, Token: {self.token})")
        logging.info(f"  Total Capital     : ₹{TOTAL_CAPITAL:,.2f}")
        logging.info(f"  Working Capital   : ₹{WORKING_CAPITAL:,.2f}")
        logging.info(f"  Backup Capital    : ₹{BACKUP_CAPITAL:,.2f}")
        logging.info(f"  Daily Loss Limit  : ₹{DAILY_LOSS_LIMIT:,.2f}")
        logging.info(f"  Risk Per Setup    : ≤ ₹{RISK_PER_TRADE:,.2f}")
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

        # Update and apply daily directional bias
        daily_bias = detect_daily_bias(result)
        self.paper_trader.update_daily_bias(daily_bias)

        is_pullback = bool(latest.get("Buy_Signal"))
        is_breakout = bool(latest.get("Breakout_Signal"))
        is_short_pullback = bool(latest.get("Sell_Signal"))
        is_short_breakdown = bool(latest.get("Breakdown_Sell_Signal"))

        # Bias-based signal filtering:
        # LONG_BIAS: accept only longs
        # SHORT_BIAS: accept only shorts
        # NEUTRAL: accept all signals
        if daily_bias == "LONG_BIAS":
            is_short_pullback = False
            is_short_breakdown = False
        elif daily_bias == "SHORT_BIAS":
            is_pullback = False
            is_breakout = False

        has_long = is_pullback or is_breakout
        has_short = is_short_pullback or is_short_breakdown

        if has_long and not can_enter_new_positions(signal_timestamp):
            logging.info(
                "Signal rejected - entries are disabled in %s after the 15:15 IST cutoff.",
                get_market_state(signal_timestamp).value,
            )
            has_long = False

        if has_short and not can_enter_new_positions(signal_timestamp):
            logging.info(
                "Signal rejected - entries are disabled in %s after the 15:15 IST cutoff.",
                get_market_state(signal_timestamp).value,
            )
            has_short = False

        if has_long:
            sig_type = "BREAKOUT" if (is_breakout and not is_pullback) else "PULLBACK"
            sig_banner = (
                "🚀  VWAP BREAKOUT BUY SIGNAL [BREAKOUT_LONG]"
                if sig_type == "BREAKOUT"
                else "🚀  VWAP PULLBACK BUY SIGNAL [PULLBACK_LONG]"
            )

            logging.info("🚀 ════════════════════════════════════════════════════════")
            logging.info(f"{sig_banner}  @  VWAP {latest['VWAP']:.2f} (ATR: {atr_val:.2f}) | Bias: {daily_bias}")
            logging.info("🚀 ════════════════════════════════════════════════════════")

            self.paper_trader.execute_trade(
                {
                    "VWAP": float(latest["VWAP"]),
                    "Close": float(latest["Close"]),
                    "symbol": self.symbol,
                    "ATR_14": atr_val,
                    "atr": atr_val,
                    "signal_type": f"[{sig_type}_LONG]",
                },
                timestamp=signal_timestamp,
                atr_14=atr_val,
                side="BUY",
                angel_session=self.angel_session,
            )
        elif has_short:
            sig_type = "BREAKDOWN" if (is_short_breakdown and not is_short_pullback) else "PULLBACK"
            sig_banner = (
                "🔻  VWAP BREAKDOWN SELL SIGNAL [BREAKDOWN_SHORT]"
                if sig_type == "BREAKDOWN"
                else "🔻  VWAP PULLBACK SELL SIGNAL [PULLBACK_SHORT]"
            )

            logging.info("🔻 ════════════════════════════════════════════════════════")
            logging.info(f"{sig_banner}  @  VWAP {latest['VWAP']:.2f} (ATR: {atr_val:.2f}) | Bias: {daily_bias}")
            logging.info("🔻 ════════════════════════════════════════════════════════")

            self.paper_trader.execute_trade(
                {
                    "VWAP": float(latest["VWAP"]),
                    "Close": float(latest["Close"]),
                    "symbol": self.symbol,
                    "ATR_14": atr_val,
                    "atr": atr_val,
                    "signal_type": f"[{sig_type}_SHORT]",
                },
                timestamp=signal_timestamp,
                atr_14=atr_val,
                side="SELL",
                angel_session=self.angel_session,
            )

        # Position management on candle close
        self.paper_trader.manage_open_position(
            candle=latest.to_dict() if hasattr(latest, "to_dict") else dict(latest),
            timestamp=signal_timestamp,
            latest_price=float(latest["Close"]),
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

        # Fix #6: Layer B — End-of-Day authoritative reconciliation pass
        session = self.angel_session if self.angel_session is not None else self.smart_api
        if LIVE_MODE and session is not None and hasattr(self, "_day_opening_capital"):
            try:
                reconcile_end_of_day(
                    smart_api=session,
                    opening_capital=self._day_opening_capital,
                    logged_daily_net_pnl=self.paper_trader.daily_pnl,
                )
            except Exception as exc:
                logging.error(f"[EOD RECONCILIATION ERROR] Failed to compute EOD reconciliation: {exc}")

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


def angel_login() -> SmartConnect:
    """
    Authenticates with Angel One SmartAPI using
    credentials from .env file.

    Reads:
      BROKER_API_KEY      → Angel One API key
      BROKER_CLIENT_ID    → Angel One client/login ID
      BROKER_PIN          → 4-digit trading PIN
      BROKER_TOTP_SECRET  → TOTP secret for 2FA

    Returns: authenticated SmartConnect session object
    Raises:  Exception on login failure (bot will stop)
    """
    api_key      = os.getenv("BROKER_API_KEY")
    client_id    = os.getenv("BROKER_CLIENT_ID")
    pin          = os.getenv("BROKER_PIN")
    totp_secret  = os.getenv("BROKER_TOTP_SECRET")

    # Validate all credentials are present
    missing = [
        name for name, val in {
            "BROKER_API_KEY":     api_key,
            "BROKER_CLIENT_ID":   client_id,
            "BROKER_PIN":         pin,
            "BROKER_TOTP_SECRET": totp_secret,
        }.items() if not val
    ]
    if missing:
        raise ValueError(
            f"[LIVE] Missing .env keys: {missing}. "
            f"Check algo-trading-bot/.env file."
        )

    # Generate TOTP (time-based 2FA code)
    totp_code = pyotp.TOTP(totp_secret).now()

    # Authenticate with Angel One
    angel = SmartConnect(api_key=api_key)
    session = angel.generateSession(
        clientCode=client_id,
        password=pin,
        totp=totp_code
    )

    if not session.get("status", False):
        raise Exception(
            f"[LIVE] Angel One login FAILED. "
            f"Response: {session}. "
            f"Check credentials in .env file."
        )

    logging.warning(
        "══════════════════════════════════════════"
    )
    logging.warning(
        "  ✅ ANGEL ONE LOGIN SUCCESS"
    )
    logging.warning(
        f"  Client : {client_id}"
    )
    logging.warning(
        f"  Mode   : LIVE — REAL MONEY ACTIVE ⚠️"
    )
    logging.warning(
        f"  Capital: ₹20,000"
    )
    logging.warning(
        "══════════════════════════════════════════"
    )
    return angel


def place_live_order(
    angel: SmartConnect,
    symbol: str,
    token: str,
    side: str,
    qty: int,
) -> str | None:
    """
    Places a real MIS (intraday) MARKET order on NSE
    via Angel One SmartAPI.

    Parameters:
      angel  : authenticated SmartConnect session
      symbol : NSE trading symbol (e.g. "ONGC-EQ")
      token  : Angel One instrument token (e.g. "1594")
      side   : "BUY" or "SELL"
      qty    : number of shares

    Returns:
      order_id (str) on success
      None on failure (position NOT opened)

    Notes:
      - producttype "INTRADAY" = MIS (auto square-off)
      - ordertype "MARKET" = best available price
      - price "0" required for MARKET orders
      - EOD auto square-off by bot at 15:20 IST
      - Angel One also squares off at 15:20 as backup
    """
    order_params = {
        "variety":          "NORMAL",
        "tradingsymbol":    symbol,
        "symboltoken":      token,
        "transactiontype":  side,           # "BUY" / "SELL"
        "exchange":         "NSE",
        "ordertype":        "MARKET",
        "producttype":      "INTRADAY",     # MIS
        "duration":         "DAY",
        "price":            "0",            # MARKET = 0
        "squareoff":        "0",
        "stoploss":         "0",
        "quantity":         str(qty),
    }

    # ---------------------------------------------------------
    # DEFENSIVE SMARTAPI RESPONSE PARSER (DO NOT ALTER LOGIC)
    # ---------------------------------------------------------
    try:
        response = angel.placeOrder(order_params)
        order_id = None

        # Case 1: Standard SDK returns order ID as a raw string
        if isinstance(response, str) and response.strip():
            order_id = response.strip()
            logging.info(f"[LIVE ORDER PLACED] Successfully routed. Order ID: {order_id}")
            logging.warning(
                f"[LIVE ORDER ✅] {side} {qty} {symbol} "
                f"| OrderID: {order_id}"
            )
            return order_id

        # Case 2: Wrapper/SDK returns a response dictionary
        elif isinstance(response, dict):
            if response.get("status") is True or response.get("success") is True:
                data_payload = response.get("data") or {}
                order_id = data_payload.get("orderid") if isinstance(data_payload, dict) else str(data_payload)
                logging.info(f"[LIVE ORDER PLACED] Successfully routed. Order ID: {order_id}")
                logging.warning(
                    f"[LIVE ORDER ✅] {side} {qty} {symbol} "
                    f"| OrderID: {order_id}"
                )
                return order_id
            else:
                err_msg = response.get("message", "Unknown broker error")
                logging.error(f"[LIVE ORDER REJECTED] Broker returned failure: {err_msg}")
                return None
        else:
            logging.error(f"[LIVE ORDER ERROR] Unexpected response payload type: {type(response)} -> {response}")
            return None

    except Exception as e:
        logging.error(f"[LIVE ORDER EXCEPTION] Failed during placeOrder execution: {str(e)}")
        return None


def main() -> None:
    # ── LIVE MODE STARTUP ──────────────────────────────
    angel_session = None   # default: paper mode

    if LIVE_MODE:
        # Real money mode — login to Angel One
        angel_session = angel_login()
        # angel_session passed to execution engine below
    else:
        logging.info(
            "══════════════════════════════════════════"
        )
        logging.info(
            "  📄 PAPER TRADING MODE ACTIVE"
        )
        logging.info(
            "  No real orders will be placed."
        )
        logging.info(
            "  Set LIVE_MODE=True in config.py to go live."
        )
        logging.info(
            "══════════════════════════════════════════"
        )

    stream = AngelOneLiveStream(angel_session=angel_session)
    stream.run()


if __name__ == "__main__":
    main()
