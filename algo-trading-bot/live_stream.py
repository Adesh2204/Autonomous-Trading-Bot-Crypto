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

from atr_firewall import ATRFirewall, FirewallStatus
from candle_builder import CandleBuilder
from feed_integrity import FeedHealthMonitor, FeedHealthState, ThreadSafeTickIngestionQueue
from premarket_screener import PremarketScreenResult, run_premarket_screener
from execution_engine import (
    PaperTrader,
    get_actual_fill_price,
    get_live_capital,
    validate_broker_capital,
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
        CANDIDATE_UNIVERSE,
        MAX_OPEN_POSITIONS,
        SCREEN_TOP_N,
        STANDBY_ATR_THRESHOLD,
        STANDBY_CONFIRMATION_COUNT,
        STANDBY_RECOVERY_CONFIRMATION_COUNT,
        STANDBY_RECOVERY_THRESHOLD,
        WATCHLIST_EVALUATION_INTERVAL,
        WATCHLIST_MODE,
        WATCHLIST_SIZE,
        RUN_PREMARKET_SCREENER,
    )
except ImportError:
    CANDIDATE_UNIVERSE = []
    DEFAULT_SYMBOL = "ONGC"
    TOTAL_CAPITAL = 10000.00
    WORKING_CAPITAL = 5000.00
    BACKUP_CAPITAL = 5000.00
    RISK_PER_TRADE = 100.00
    DAILY_LOSS_LIMIT = 200.00
    CONFIG_TOKEN = "2475"
    MAX_OPEN_POSITIONS = 1
    SCREEN_TOP_N = 3
    STANDBY_ATR_THRESHOLD = 0.0035
    STANDBY_CONFIRMATION_COUNT = 2
    STANDBY_RECOVERY_CONFIRMATION_COUNT = 2
    STANDBY_RECOVERY_THRESHOLD = 0.0040
    WATCHLIST_EVALUATION_INTERVAL = 1.0
    WATCHLIST_MODE = True
    WATCHLIST_SIZE = 3
    RUN_PREMARKET_SCREENER = False

from symbol_state import SymbolExecutionState, SymbolState, create_isolated_symbol_state

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
        target_symbol: Optional[str] = None,
        target_token: Optional[str] = None,
        schedule: Optional[BaseMarketSchedule] = None,
        angel_session: Optional[SmartConnect] = None,
        screener_diagnostic: Optional[Any] = None,
        watchlist: Optional[List[Any]] = None,
    ) -> None:
        self.schedule: BaseMarketSchedule = (
            schedule if schedule is not None else get_market_schedule(os.getenv("MARKET_SCHEDULE", "NSE"))
        )
        self.screener_diagnostic = screener_diagnostic
        self._execution_lock = threading.Lock()

        # Build candidate lookup dictionary from CANDIDATE_UNIVERSE
        universe_map = {}
        for c in CANDIDATE_UNIVERSE:
            if isinstance(c, dict):
                sym_k = c.get("symbol", "").upper()
                trd_k = c.get("trading_symbol", "").upper()
                if sym_k:
                    universe_map[sym_k] = c
                if trd_k:
                    universe_map[trd_k] = c

        # Setup active symbols container (token -> SymbolState)
        self.active_symbols: Dict[str, SymbolState] = {}

        if watchlist and len(watchlist) > 0:
            self.watchlist = watchlist[:SCREEN_TOP_N]
            for idx, cand in enumerate(self.watchlist):
                c_sym = getattr(cand, "symbol", None) or cand.get("symbol", "")
                c_tok = str(getattr(cand, "token", None) or cand.get("token", ""))
                c_trd = getattr(cand, "trading_symbol", None) or cand.get("trading_symbol", f"{c_sym}-EQ")
                c_exch = getattr(cand, "exchange", None) or cand.get("exchange", "NSE")
                c_ex_type = 1
                state = create_isolated_symbol_state(
                    symbol=c_sym,
                    token=c_tok,
                    trading_symbol=c_trd,
                    exchange=c_exch,
                    exchange_type=c_ex_type,
                    rank=idx + 1,
                    candle_close_callback=self._on_symbol_candle_close,
                )
                state.execution_state = SymbolExecutionState.ACTIVE
                self.active_symbols[c_tok] = state
        else:
            self.watchlist = []
            resolved_sym = os.getenv("TRADING_SYMBOL") or target_symbol or DEFAULT_SYMBOL
            self.target_symbol = str(resolved_sym).upper()
            base_sym = self.target_symbol.replace("-EQ", "")

            if target_token:
                self.instrument_info = {
                    "token": str(target_token),
                    "symbol": base_sym,
                    "trading_symbol": f"{base_sym}-EQ",
                    "exchange_type": 1,
                }
            elif self.target_symbol in INSTRUMENTS:
                self.instrument_info = INSTRUMENTS[self.target_symbol]
            elif base_sym in INSTRUMENTS:
                self.instrument_info = INSTRUMENTS[base_sym]
            elif self.target_symbol in universe_map:
                u_info = universe_map[self.target_symbol]
                self.instrument_info = {
                    "token": str(u_info.get("token", CONFIG_TOKEN)),
                    "symbol": base_sym,
                    "trading_symbol": u_info.get("trading_symbol", f"{base_sym}-EQ"),
                    "exchange_type": 1,
                }
            elif base_sym in universe_map:
                u_info = universe_map[base_sym]
                self.instrument_info = {
                    "token": str(u_info.get("token", CONFIG_TOKEN)),
                    "symbol": base_sym,
                    "trading_symbol": u_info.get("trading_symbol", f"{base_sym}-EQ"),
                    "exchange_type": 1,
                }
            else:
                self.instrument_info = {
                    "token": CONFIG_TOKEN,
                    "symbol": base_sym,
                    "trading_symbol": f"{base_sym}-EQ",
                    "exchange_type": 1,
                }

            single_state = create_isolated_symbol_state(
                symbol=self.instrument_info["symbol"],
                token=str(self.instrument_info["token"]),
                trading_symbol=self.instrument_info["trading_symbol"],
                exchange="NSE",
                exchange_type=self.instrument_info["exchange_type"],
                rank=1,
                candle_close_callback=self._on_symbol_candle_close,
            )
            single_state.execution_state = SymbolExecutionState.ACTIVE
            self.active_symbols[single_state.token] = single_state

        # Validate token uniqueness across active symbols
        tokens = [s.token for s in self.active_symbols.values()]
        if len(tokens) != len(set(tokens)):
            raise ValueError(f"Duplicate tokens detected in watchlist: {tokens}")

        # Primary symbol properties (backward compatibility pointing to Rank 1)
        primary = sorted(self.active_symbols.values(), key=lambda s: s.rank)[0]
        self.target_symbol = primary.symbol
        self.token = str(primary.token)
        self.symbol = primary.symbol
        self.trading_symbol = primary.trading_symbol
        self.exchange_type = primary.exchange_type
        self.instrument_info = {
            "token": primary.token,
            "symbol": primary.symbol,
            "trading_symbol": primary.trading_symbol,
            "exchange_type": primary.exchange_type,
        }
        self.correlation_id = f"{self.symbol.lower()}-snapquote"
        self.subscription_mode = getattr(SmartWebSocketV2, "SNAPQUOTE_MODE", 3)

        # Primary isolated components for backward compatibility
        self.feed_monitor = primary.feed_monitor
        self.atr_firewall = primary.atr_firewall
        self.builder = primary.builder

        # Feed Integrity, Concurrency Queue, and ATR Firewall
        self.ingestion_queue = ThreadSafeTickIngestionQueue()
        self._consumer_thread: Optional[threading.Thread] = None
        self._last_spread_pct: Optional[float] = None
        self._last_depth_available: bool = True

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

        # Capital Synchronization & Pre-flight RMS Validation
        session = self.angel_session if self.angel_session is not None else self.smart_api
        if LIVE_MODE and session is not None:
            try:
                is_sufficient, broker_cash = validate_broker_capital(
                    smart_api=session,
                    required_capital=WORKING_CAPITAL,
                    engine=self.paper_trader,
                )
                if not is_sufficient:
                    logging.critical("[STARTUP HALT] Broker available cash insufficient or unverified. Halting trading.")
                    self.paper_trader._halted = True
                if broker_cash is not None:
                    self._day_opening_capital = broker_cash
                else:
                    self._day_opening_capital = self.paper_trader.working_capital
                # Fix #6: Snapshot broker position baselines for restart safety
                self.paper_trader.init_reconciliation_baselines(session)
            except Exception as exc:
                logging.error(f"[CAPITAL SYNC ERROR] Failed to validate live capital at startup: {exc}")
                self.paper_trader._halted = True
                alert_human(f"[CRITICAL STARTUP ERROR] Live capital validation exception: {exc}. Trading halted.")
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

        # Launch single consumer thread for thread-safe tick processing
        if self._consumer_thread is None or not self._consumer_thread.is_alive():
            self._consumer_thread = threading.Thread(
                target=self._tick_consumer_loop,
                daemon=True,
                name="TickConsumerThread",
            )
            self._consumer_thread.start()
            logging.info("Tick ingestion consumer thread started.")

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
    #  Candle / Signal / Trade Pipeline & Watchlist Orchestrator
    # ──────────────────────────────────────────────────────────────

    def _on_symbol_candle_close(self, symbol: str, token: str, df: pd.DataFrame) -> None:
        """Isolated candle-close callback preserving symbol identity."""
        state = self.active_symbols.get(token)
        if state is None:
            return

        state.current_candle_df = df.copy()
        latest = df.iloc[-1]
        candle_timestamp = to_ist()
        atr_val = float(latest.get("ATR_14", float("nan")))
        close_p = float(latest.get("Close", 0.0))

        # Record ATR in symbol's isolated firewall and evaluate STANDBY transitions
        state.record_periodic_atr(atr=atr_val, ltp=close_p, timestamp=candle_timestamp)

        logging.info(
            f"Candle #{len(df)} closed for {symbol} (Rank {state.rank}) | "
            f"O:{latest['Open']:.2f}  H:{latest['High']:.2f}  "
            f"L:{latest['Low']:.2f}  C:{latest['Close']:.2f}  "
            f"V:{latest['Volume']:.0f}  |  ATR_14:{atr_val:.2f}  |  "
            f"State: {state.execution_state.value}"
        )

        # Position management on candle close (strictly for the open position's matching symbol)
        if self.paper_trader.has_open_position:
            pos = self.paper_trader._open_position
            if pos is not None:
                pos_sym = pos.get("symbol")
                pos_tok = pos.get("token")
                if symbol == pos_sym or (pos_tok and token == str(pos_tok)):
                    self.paper_trader.manage_open_position(
                        candle=latest.to_dict() if hasattr(latest, "to_dict") else dict(latest),
                        timestamp=candle_timestamp,
                        latest_price=close_p,
                    )

        # Trigger Watchlist Execution Orchestration
        self._evaluate_watchlist_orchestrator(triggered_by_symbol=symbol, evaluation_time=candle_timestamp)

    def on_candle_close(self, df: pd.DataFrame) -> None:
        """Legacy entry point routing candle close to primary symbol."""
        self._on_symbol_candle_close(self.symbol, self.token, df)

    def _evaluate_watchlist_orchestrator(
        self,
        triggered_by_symbol: Optional[str] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> None:
        """
        Phase 5 Watchlist Execution Orchestrator:
        1. Observes all symbols.
        2. Filters unsafe symbols (STANDBY, degraded feed, ERROR, BLOCKED).
        3. Evaluates symbols in strict premarket ranking order (Rank 1 -> Rank 2 -> Rank 3).
        4. Finds actionable signal via unmodified signal_brain.
        5. Applies global position limit (MAX_OPEN_POSITIONS = 1) under lock.
        6. Applies symbol's isolated ATR firewall.
        7. Executes trade via existing execution engine.
        8. Halts candidate search upon first valid execution (One-cycle rule).
        """
        with self._execution_lock:
            # 1. Global Position Gate
            if self.paper_trader.has_open_position:
                logging.debug(
                    "[ORCHESTRATOR] Global position limit occupied (has_open_position=True). "
                    "Skipping entry search."
                )
                return

            current_time = to_ist(evaluation_time) if evaluation_time is not None else to_ist()
            if not can_enter_new_positions(current_time):
                logging.info(
                    "Signal rejected - entries are disabled in %s after the 15:15 IST cutoff.",
                    get_market_state(current_time).value,
                )
                return


            # 2. Evaluate in strict premarket ranking order
            sorted_states = sorted(self.active_symbols.values(), key=lambda s: s.rank)

            for state in sorted_states:
                # 3. Candidate Filters
                if state.execution_state == SymbolExecutionState.STANDBY:
                    logging.info(
                        f"[ORCHESTRATOR] Skipping {state.symbol} (Rank {state.rank}): "
                        "Symbol in STANDBY (low volatility)."
                    )
                    continue

                if state.feed_monitor.state != FeedHealthState.HEALTHY:
                    logging.warning(
                        f"[ORCHESTRATOR] Skipping {state.symbol} (Rank {state.rank}): "
                        f"Feed not healthy ({state.feed_monitor.state.value})."
                    )
                    continue

                if state.execution_state in (SymbolExecutionState.BLOCKED, SymbolExecutionState.ERROR):
                    logging.info(
                        f"[ORCHESTRATOR] Skipping {state.symbol} (Rank {state.rank}): "
                        f"Symbol in state {state.execution_state.value}."
                    )
                    continue

                if state.current_candle_df is None or len(state.current_candle_df) < 15:
                    logging.debug(
                        f"[ORCHESTRATOR] Skipping {state.symbol} (Rank {state.rank}): "
                        "Insufficient candles for signal evaluation."
                    )
                    continue

                try:
                    df = state.current_candle_df.copy()
                    result = generate_vwap_signal(df)
                    latest = result.iloc[-1]
                    atr_val = float(latest.get("ATR_14", float("nan")))

                    # Directional bias detection
                    daily_bias = detect_daily_bias(result)

                    is_pullback = bool(latest.get("Buy_Signal"))
                    is_breakout = bool(latest.get("Breakout_Signal"))
                    is_short_pullback = bool(latest.get("Sell_Signal"))
                    is_short_breakdown = bool(latest.get("Breakdown_Sell_Signal"))

                    if daily_bias == "LONG_BIAS":
                        is_short_pullback = False
                        is_short_breakdown = False
                    elif daily_bias == "SHORT_BIAS":
                        is_pullback = False
                        is_breakout = False

                    has_long = is_pullback or is_breakout
                    has_short = is_short_pullback or is_short_breakdown

                    if not (has_long or has_short):
                        continue

                    # 4. ATR Firewall Pre-Entry Gating (isolated per symbol)
                    pre_eval = state.atr_firewall.validate_pre_entry(
                        atr=atr_val,
                        ltp=float(latest["Close"]),
                        feed_health=state.feed_monitor.state.value,
                        spread_pct=state.last_spread_pct,
                        depth_available=state.last_depth_available,
                        is_new_entry=True,
                    )
                    if not pre_eval.execution_allowed:
                        logging.warning(
                            f"🛑 [FIREWALL GATE BLOCKED] {state.symbol} (Rank {state.rank}) "
                            f"{'LONG' if has_long else 'SHORT'} rejected: {pre_eval.rejection_reason} "
                            f"| ATR%: {pre_eval.atr_pct:.3f}% | Feed: {pre_eval.feed_health}"
                        )
                        continue

                    # 5. Global Position Re-Check before execution
                    if self.paper_trader.has_open_position:
                        logging.warning(
                            f"🛑 [GLOBAL POSITION BLOCK] {state.symbol} (Rank {state.rank}) blocked: "
                            "Position already open."
                        )
                        break

                    # 6. Execute Trade via Existing Engine
                    self.paper_trader.update_daily_bias(daily_bias)
                    if has_long:
                        sig_type = "BREAKOUT" if (is_breakout and not is_pullback) else "PULLBACK"
                        sig_banner = (
                            "🚀  VWAP BREAKOUT BUY SIGNAL [BREAKOUT_LONG]"
                            if sig_type == "BREAKOUT"
                            else "🚀  VWAP PULLBACK BUY SIGNAL [PULLBACK_LONG]"
                        )
                        logging.info("🚀 ════════════════════════════════════════════════════════")
                        logging.info(
                            f"🚀  WATCHLIST ORCHESTRATOR EXECUTION: {state.symbol} (Rank {state.rank}) "
                            f"{sig_banner} @ VWAP {latest['VWAP']:.2f} (ATR: {atr_val:.2f}) | Bias: {daily_bias}"
                        )
                        logging.info("🚀 ════════════════════════════════════════════════════════")
                        self.paper_trader.execute_trade(
                            {
                                "VWAP": float(latest["VWAP"]),
                                "Close": float(latest["Close"]),
                                "symbol": state.symbol,
                                "ATR_14": atr_val,
                                "atr": atr_val,
                                "signal_type": f"[{sig_type}_LONG]",
                            },
                            timestamp=current_time,
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
                        logging.info(
                            f"🔻  WATCHLIST ORCHESTRATOR EXECUTION: {state.symbol} (Rank {state.rank}) "
                            f"{sig_banner} @ VWAP {latest['VWAP']:.2f} (ATR: {atr_val:.2f}) | Bias: {daily_bias}"
                        )
                        logging.info("🔻 ════════════════════════════════════════════════════════")
                        self.paper_trader.execute_trade(
                            {
                                "VWAP": float(latest["VWAP"]),
                                "Close": float(latest["Close"]),
                                "symbol": state.symbol,
                                "ATR_14": atr_val,
                                "atr": atr_val,
                                "signal_type": f"[{sig_type}_SHORT]",
                            },
                            timestamp=current_time,
                            atr_14=atr_val,
                            side="SELL",
                            angel_session=self.angel_session,
                        )

                    # 7. One-Cycle Execution Rule: Stop searching!
                    logging.info(
                        f"[ORCHESTRATOR] Order placed for {state.symbol} (Rank {state.rank}). "
                        "One-cycle execution complete. Halting candidate search."
                    )
                    break

                except Exception as exc:
                    state.mark_error(str(exc))
                    logging.error(
                        f"[ORCHESTRATOR ERROR] Error evaluating {state.symbol} (Rank {state.rank}): {exc}",
                        exc_info=True,
                    )
                    continue

    def _extract_tick_fields(self, data: dict) -> tuple[float, int, datetime, Optional[float], Optional[float], bool]:
        """Extract LTP, actual trade volume (without fake fallback), timestamp, best bid, best ask, and depth availability from SmartAPI data."""
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

        # Extract best bid and ask if present
        best_bid: Optional[float] = None
        best_ask: Optional[float] = None
        depth_available = True

        best_5_buy = data.get("best_5_buy_data")
        if isinstance(best_5_buy, list) and len(best_5_buy) > 0 and isinstance(best_5_buy[0], dict):
            b_price = best_5_buy[0].get("price")
            if b_price is not None:
                raw_b = float(b_price)
                best_bid = raw_b / 100.0 if raw_b > 1000 else raw_b
        elif data.get("buy_price") is not None:
            raw_b = float(data["buy_price"])
            best_bid = raw_b / 100.0 if raw_b > 1000 else raw_b

        best_5_sell = data.get("best_5_sell_data")
        if isinstance(best_5_sell, list) and len(best_5_sell) > 0 and isinstance(best_5_sell[0], dict):
            s_price = best_5_sell[0].get("price")
            if s_price is not None:
                raw_s = float(s_price)
                best_ask = raw_s / 100.0 if raw_s > 1000 else raw_s
        elif data.get("sell_price") is not None:
            raw_s = float(data["sell_price"])
            best_ask = raw_s / 100.0 if raw_s > 1000 else raw_s

        return price, volume, timestamp, best_bid, best_ask, depth_available

    def _on_data(self, wsapp, data: dict) -> None:
        """Fast non-blocking WebSocket callback pushing raw ticks to the thread-safe ingestion queue."""
        try:
            if not isinstance(data, dict):
                logging.warning("Received non-dict SmartAPI payload: %r", data)
                return

            price, volume, timestamp, best_bid, best_ask, depth_available = self._extract_tick_fields(data)

            if price <= 0 or not math.isfinite(price):
                logging.warning("Rejected invalid LTP payload: %r", data)
                return

            raw_tok = data.get("token")
            tok_str = str(raw_tok).strip() if raw_tok is not None else ""
            if not tok_str:
                if len(self.active_symbols) == 1:
                    tok_str = list(self.active_symbols.keys())[0]
                else:
                    logging.debug("Tick missing token while multiple symbols active; dropped: %r", data)
                    return

            sym_state = self.active_symbols.get(tok_str)
            if sym_state is None:
                logging.debug("Tick received for unknown token %s; safely dropped.", tok_str)
                return

            self.ingestion_queue.enqueue(
                symbol=sym_state.symbol,
                token=sym_state.token,
                exchange_type=sym_state.exchange_type,
                price=price,
                volume=volume,
                timestamp=timestamp,
                best_bid=best_bid,
                best_ask=best_ask,
                depth_available=depth_available,
            )
        except Exception as exc:
            logging.error("Error processing SmartAPI data frame: %s | payload=%r", exc, data)

    def _tick_consumer_loop(self) -> None:
        """Single consumer thread that drains the tick ingestion queue,
        evaluates feed integrity, updates candle builder, checks exits, and enforces lifecycle.
        This preserves single-threaded state ownership for candle building and execution."""
        while not self._shutdown_requested:
            try:
                tick = self.ingestion_queue.get(timeout=0.5)
                if tick is None:
                    self.enforce_lifecycle(ws=self.websocket, current_dt=to_ist())
                    continue

                symbol_state = self.active_symbols.get(tick.token)
                if symbol_state is None:
                    logging.debug("Consumer received tick for unknown token %s; dropped.", tick.token)
                    continue

                # Per-symbol feed health evaluation & duplicate/frozen tick filtration
                is_genuine, state, reason = symbol_state.feed_monitor.evaluate_tick(tick)
                if not is_genuine:
                    logging.debug(
                        "Tick dropped by FeedHealthMonitor for %s: %s | LTP: %.2f",
                        symbol_state.symbol,
                        reason,
                        tick.price,
                    )
                    continue

                # Update symbol-local spread, depth, and price telemetry
                symbol_state.last_tick_price = tick.price
                symbol_state.last_tick_volume = tick.volume
                symbol_state.last_tick_time = tick.timestamp

                if tick.best_bid and tick.best_ask and tick.best_bid > 0:
                    spread = tick.best_ask - tick.best_bid
                    symbol_state.last_spread_pct = (spread / tick.best_bid) * 100.0
                    symbol_state.last_depth_available = tick.depth_available
                else:
                    symbol_state.last_spread_pct = None
                    symbol_state.last_depth_available = tick.depth_available

                # Backward compatibility for primary symbol attributes
                if symbol_state.token == self.token:
                    self._last_spread_pct = symbol_state.last_spread_pct
                    self._last_depth_available = symbol_state.last_depth_available

                # Feed genuine trade ticks into candle/VWAP builder (per-symbol isolation)
                if tick.volume > 0:
                    try:
                        symbol_state.builder.on_tick(price=tick.price, volume=tick.volume, timestamp=tick.timestamp)
                    except Exception as b_exc:
                        symbol_state.mark_error(str(b_exc))
                        logging.error(f"[BUILDER ERROR] Error in {symbol_state.symbol} builder: {b_exc}", exc_info=True)
                else:
                    logging.debug("Skipped tick with zero volume for %s builder: price=%.2f", symbol_state.symbol, tick.price)

                # Exit checks (only if open position symbol matches this tick's symbol)
                if self.paper_trader.has_open_position:
                    pos = self.paper_trader._open_position
                    if pos is not None:
                        pos_sym = pos.get("symbol")
                        pos_tok = pos.get("token")
                        if symbol_state.symbol == pos_sym or (pos_tok and symbol_state.token == str(pos_tok)):
                            self.paper_trader.check_exit(live_price=tick.price, timestamp=tick.timestamp)

                # Lifecycle enforcement
                self.enforce_lifecycle(ws=self.websocket, current_dt=tick.timestamp)
            except Exception as exc:
                logging.error("Error in tick consumer loop: %s", exc, exc_info=True)

    def _on_message(self, wsapp, message: str) -> None:
        if message == "pong":
            logging.debug("SmartAPI heartbeat pong received.")

    def _on_control_message(self, wsapp, message: dict) -> None:
        logging.debug("SmartAPI control message: %s", message)

    def _on_open(self, wsapp) -> None:
        logging.info("WebSocket connection established successfully.")
        self._retry_attempt = 0
        for state in self.active_symbols.values():
            state.feed_monitor.on_connect()

        by_exchange: Dict[int, List[str]] = {}
        for state in self.active_symbols.values():
            by_exchange.setdefault(state.exchange_type, []).append(state.token)

        token_list = [
            {"exchangeType": ex_type, "tokens": toks}
            for ex_type, toks in by_exchange.items()
        ]

        if self.websocket is None:
            raise RuntimeError("SmartWebSocketV2 is not initialized.")

        self.websocket.subscribe(
            self.correlation_id,
            self.subscription_mode,
            token_list,
        )
        subscribed_str = ", ".join([f"{s.symbol} ({s.token})" for s in self.active_symbols.values()])
        logging.info(
            f"Subscribed to {len(self.active_symbols)} watchlist token(s): {subscribed_str} "
            f"in SnapQuote mode (mode={self.subscription_mode})."
        )

    def _on_error(self, wsapp, error, *args, **kwargs) -> None:
        logging.error("WebSocket Error: %s", error)
        for state in self.active_symbols.values():
            state.feed_monitor.on_disconnect(reason=f"WebSocket error: {error}")

    def _on_close(self, wsapp, *args, **kwargs) -> None:
        logging.warning("SmartAPI websocket closed.")
        for state in self.active_symbols.values():
            state.feed_monitor.on_disconnect(reason="SmartAPI websocket closed")
        if not self._shutdown_requested:
            logging.info("Connection dropped. Reconnect supervisor will retry.")


    # ──────────────────────────────────────────────────────────────
    #  EOD / Square-off / Watchdog
    # ──────────────────────────────────────────────────────────────

    def log_daily_summary(self, prefix: str = "Daily Summary") -> None:
        session = self.angel_session if self.angel_session is not None else self.smart_api
        broker_cash = None
        if LIVE_MODE and session is not None:
            try:
                broker_cash = get_live_capital(session)
            except Exception:
                broker_cash = None

        if broker_cash is not None:
            logging.info(
                f"{prefix} | Daily P&L: ₹{self.paper_trader.daily_pnl:,.2f} | "
                f"Working Capital: ₹{self.paper_trader.working_capital:,.2f} | "
                f"Broker Available Cash: ₹{broker_cash:,.2f}"
            )
        else:
            logging.info(
                f"{prefix} | Daily P&L: ₹{self.paper_trader.daily_pnl:,.2f} | "
                f"Working Capital: ₹{self.paper_trader.working_capital:,.2f}"
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

            # Feed integrity check: detect silent websocket freeze / stale ticks across all symbols
            for sym_state in self.active_symbols.values():
                sym_state.feed_monitor.check_heartbeat()

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
        try:
            angel_session = angel_login()
        except Exception as e:
            logging.warning(f"Paper mode broker session creation skipped / failed: {e}")

    override_sym = os.getenv("TRADING_SYMBOL")
    if override_sym:
        logging.info(f"Manual TRADING_SYMBOL override specified: {override_sym}")
        stream = AngelOneLiveStream(target_symbol=override_sym, angel_session=angel_session)
        stream.run()
        return

    if RUN_PREMARKET_SCREENER:
        # Run the Pre-Market Screener
        logging.info("Executing Pre-Market Screener across candidate universe...")
        screen_result = run_premarket_screener(smart_api=angel_session)

        if screen_result.trading_day_status == "NO_TRADE" or screen_result.selected_candidate is None:
            logging.warning("=" * 70)
            logging.warning("  🛑 [PREMARKET SCREENER: NO TRADE TODAY]")
            logging.warning("  No candidate satisfied the ATR%, volume, or price thresholds.")
            logging.warning("  Zero trade rule active: Bot will sit out this session.")
            logging.warning("=" * 70)
            sys.exit(0)

        winner = screen_result.selected_candidate
        watchlist = screen_result.watchlist if WATCHLIST_MODE else ([winner] if winner else [])
        logging.info(
            f"🎯 Premarket screening winner: {winner.symbol} (Token: {winner.token}) "
            f"| ATR%: {winner.atr_pct:.2f}% | Spread: {winner.spread_pct:.2f}%"
        )
        if WATCHLIST_MODE and len(watchlist) > 1:
            logging.info(
                f"🎯 Phase 5 Watchlist: {[c.trading_symbol for c in watchlist]} ({len(watchlist)} symbols)"
            )

        stream = AngelOneLiveStream(
            target_symbol=winner.symbol,
            target_token=winner.token,
            angel_session=angel_session,
            screener_diagnostic=winner,
            watchlist=watchlist,
        )
        stream.run()
    else:
        logging.info(
            f"⏩ Pre-market screener bypassed (RUN_PREMARKET_SCREENER=False). "
            f"Using configured default instrument: {DEFAULT_SYMBOL} (Token: {CONFIG_TOKEN})"
        )
        stream = AngelOneLiveStream(
            target_symbol=DEFAULT_SYMBOL,
            target_token=CONFIG_TOKEN,
            angel_session=angel_session,
        )
        stream.run()


if __name__ == "__main__":
    main()
