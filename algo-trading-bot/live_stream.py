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
import pandas as pd
from dotenv import load_dotenv
from disabled_angel_client import DisabledAngelOneClient as SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
import config
from config import LIVE_MODE
from pathlib import Path
import json
from security_logging import install_broker_secret_filter
install_broker_secret_filter()
from execution_safety import InstrumentIdentity, MarketQuote, ExecutionQualityGate, SafetyError, solve_quantity
from instrument_registry import InstrumentRegistry
from execution_adapters import PaperExecutionAdapter, SmartAPIExecutionAdapter, BrokerCapabilities
from opportunity_engine import score_opportunity, same_time_rvol, arbitration_key

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
from premarket_pipeline import load_startup_universe, run_premarket_pipeline
from discovery_data import DiscoveryDataSource
from execution_engine import (
    PaperTrader,
    ReadOnlySmartConnectWrapper,
    log_execution_mode_banner,
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
    handlers=[logging.StreamHandler()],
)
install_broker_secret_filter()

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
        raise ValueError('MISSING_EXCHANGE_TIMESTAMP')

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
        raise ValueError('INVALID_EXCHANGE_TIMESTAMP')


import signal


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
from symbol_state import SymbolExecutionState, SymbolState, create_isolated_symbol_state


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
        reserves=None, run_context=None, history_service=None,
        registry: Optional[InstrumentRegistry] = None,
    ) -> None:
        self.schedule: BaseMarketSchedule = (
            schedule if schedule is not None else get_market_schedule(os.getenv("MARKET_SCHEDULE", "NSE"))
        )
        self.screener_diagnostic = screener_diagnostic
        self.run_context=run_context
        self.history_service=history_service
        from runtime_observation import OpportunityTelemetry
        self.telemetry=OpportunityTelemetry(run_context.run_id if run_context else 'TEST')
        self.shadow=None
        if run_context is not None and config.SHADOW_RESEARCH_ENABLED:
            from shadow_diagnostics import ShadowDiagnostics
            self.shadow=ShadowDiagnostics(run_context.directory)
        self._execution_lock = threading.RLock()

        self.registry = registry
        if self.registry is None:
            master_path = config.INSTRUMENT_MASTER_FILE or str(Path(__file__).parent/'data'/'instruments.json')
            self.registry = InstrumentRegistry.load(master_path,to_ist())
        self._cumulative_volumes = {}

        # Setup active symbols container (token -> SymbolState)
        self.active_symbols: Dict[str, SymbolState] = {}

        if watchlist and len(watchlist) > 0:
            self.watchlist = watchlist[:SCREEN_TOP_N]
            bounded_reserves=list(reserves or [])[:config.RESERVE_WATCHLIST_SIZE]
            for idx, cand in enumerate(self.watchlist+bounded_reserves):
                get = cand.get if isinstance(cand,dict) else lambda key,default=None:getattr(cand,key,default)
                c_sym = get('symbol')
                identity = get('instrument') or self.registry.resolve(c_sym,get('token'),to_ist())
                identity.validate(c_sym,get('token'),now=to_ist())
                c_tok, c_trd, c_exch = identity.token, identity.trading_symbol, identity.exchange
                if c_tok in self.active_symbols:
                    raise ValueError('DUPLICATE_WATCHLIST_TOKEN')
                c_ex_type = 1
                state = create_isolated_symbol_state(
                    symbol=c_sym,
                    token=c_tok,
                    trading_symbol=c_trd,
                    exchange=c_exch,
                    exchange_type=c_ex_type,
                    rank=idx + 1,
                    candle_close_callback=self._on_symbol_candle_close,
                    strict_session=True,
                )
                state.instrument = identity
                state.watchlist_role='PRIMARY' if idx<len(self.watchlist) else 'RESERVE'
                state.volume_profiles = get("volume_profiles",[])
                state.opportunity_score = get("opportunity_score",0.)
                state.execution_state = SymbolExecutionState.ACTIVE
                self.active_symbols[c_tok] = state
        else:
            self.watchlist = []
            resolved_sym = os.getenv("TRADING_SYMBOL") or target_symbol or DEFAULT_SYMBOL
            self.target_symbol = str(resolved_sym).upper()
            base_sym = self.target_symbol.replace("-EQ", "")

            identity = self.registry.resolve(base_sym,target_token,to_ist())
            self.instrument_info = {'token':identity.token,'symbol':identity.symbol,
                'trading_symbol':identity.trading_symbol,'exchange_type':1}

            single_state = create_isolated_symbol_state(
                symbol=self.instrument_info["symbol"],
                token=str(self.instrument_info["token"]),
                trading_symbol=self.instrument_info["trading_symbol"],
                exchange="NSE",
                exchange_type=self.instrument_info["exchange_type"],
                rank=1,
                candle_close_callback=self._on_symbol_candle_close,
                strict_session=True,
            )
            single_state.instrument = identity
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

        raw_session = angel_session
        is_live = getattr(config,'LIVE_MODE',False)
        if is_live:
            if not config.LIVE_VALIDATION_APPROVED or not config.BROKER_CAPABILITY_FILE:
                raise SafetyError('LIVE_EXECUTION_BLOCKED')
            if raw_session is None:raise SafetyError('BROKER_DATA_UNAVAILABLE')
            capability_data=json.loads(Path(config.BROKER_CAPABILITY_FILE).read_text())
            capability_data['verified_until']=datetime.fromisoformat(capability_data['verified_until'])
            adapter=SmartAPIExecutionAdapter(raw_session,BrokerCapabilities(**capability_data),to_ist)
        else:
            adapter=PaperExecutionAdapter()
            if raw_session is not None and not isinstance(raw_session,ReadOnlySmartConnectWrapper):
                raw_session=ReadOnlySmartConnectWrapper(raw_session)
        self.angel_session=raw_session
        self.paper_trader = PaperTrader(total_capital=TOTAL_CAPITAL,working_capital_pct=.50,
            daily_loss_limit=DAILY_LOSS_LIMIT,risk_per_trade=RISK_PER_TRADE,schedule=self.schedule,
            environment='LIVE' if is_live else config.EXECUTION_ENVIRONMENT,adapter=adapter)
        self.paper_trader.angel_session=raw_session
        self.paper_trader.run_id=run_context.run_id if run_context is not None else self.paper_trader.session_id

        # Restarted exposure must keep receiving quotes even if today's ranking
        # selects a different stock. Replace one unheld reserve within the cap.
        held=self.paper_trader.open_position if self.paper_trader.has_open_position else None
        if held and held['token'] not in self.active_symbols:
            limit=config.SCREEN_TOP_N+config.RESERVE_WATCHLIST_SIZE
            if len(self.active_symbols)>=limit:
                removable=sorted(self.active_symbols.values(),key=lambda s:(s.watchlist_role=='RESERVE',s.rank),reverse=True)[0]
                self.active_symbols.pop(removable.token)
            identity=held['instrument']
            protected=create_isolated_symbol_state(identity.symbol,identity.token,identity.trading_symbol,
                exchange=identity.exchange,rank=0,candle_close_callback=self._on_symbol_candle_close,strict_session=True)
            protected.instrument=identity
            protected.watchlist_role='PROTECTION_ONLY'
            self.active_symbols[identity.token]=protected
            logging.info('[RECOVERED POSITION] retaining quote subscription for %s',identity.symbol)

        self.builder = primary.builder

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
                f"Pre-market startup detected. Market opens at {open_str} "
                f"({wait_seconds:.0f}s)."
            )
            logging.info("Connecting before the open; entry time and warmup gates remain enforced.")
        elif state in {MarketPhase.SQUARE_OFF, MarketPhase.CLOSED}:
            logging.info("Market is already in shutdown window. Exiting.")
            sys.exit(0)
        elif state == MarketPhase.CLOSE_ONLY:
            cutoff_str = self.schedule.entry_cutoff_time.strftime("%H:%M:%S")
            logging.info(f"Started after {cutoff_str}. Entries are disabled; exits only.")

    def login(self) -> None:
        """Authenticate with SmartAPI and cache jwt/feed tokens for the stream.
        Includes retry with exponential backoff for rate-limit / transient errors."""
        session=getattr(self,'angel_session',None)
        if session is not None and isinstance(getattr(session,'access_token',None),str):
            auth=_normalize_bearer_token(session.access_token)
            feed=getattr(session,'feed_token',None) or session.getfeedToken()
            if auth and isinstance(feed,str) and feed:
                self.smart_api=session
                self.auth_token=auth
                self.feed_token=feed
                logging.info('Reusing authenticated market-data session for historical data and websocket.')
                return
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
        from history_service import HistoryService
        self.history_service=getattr(self,'history_service',None) or HistoryService(self.smart_api)
        # In the recovery/login path both consumers must use the fresh token.
        self.history_service.broker=self.smart_api
        context=getattr(self,'run_context',None)
        if context: context.start_stage('HISTORICAL_BASELINE_LOADING')
        bootstrap_errors=[]
        # Recovered exposure takes precedence: connect quotes immediately and
        # restore history on the worker while exits remain operational.
        restore_states=[] if self.paper_trader.has_open_position else self.active_symbols.values()
        if not restore_states:
            logging.info('[BOOTSTRAP] recovered exposure: history recovery runs alongside quote protection')
        for state in restore_states:
            try:
                self._restore_session_history(state,self.schedule.localize())
            except Exception as exc:
                bootstrap_errors.append(state.symbol+':'+str(exc))
                state.history_validation={'valid':False,'reason':str(exc)}
                logging.warning('[BOOTSTRAP BLOCKED] %s %s',state.symbol,type(exc).__name__)
        if context:
            if restore_states:
                context.end_stage('HISTORICAL_BASELINE_LOADING',not bootstrap_errors,'; '.join(bootstrap_errors) or None)
            context.start_stage('WATCHLIST_READY'); context.end_stage('WATCHLIST_READY')
        self._recovery_thread=threading.Thread(target=self._history_recovery_loop,daemon=True,name='HistoryRecovery')
        self._recovery_thread.start()

        # Capital Synchronization & Pre-flight RMS Validation
        is_live = getattr(config, "LIVE_MODE", False)
        session = self.angel_session if self.angel_session is not None else self.smart_api
        if is_live and session is not None:
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

        log_execution_mode_banner(
            live_mode=is_live,
            client_id=_first_env("ANGEL_CLIENT_ID", "CLIENT_ID") or "UNKNOWN",
            capital=TOTAL_CAPITAL,
            working_tranche=config.WORKING_CAPITAL,
        )

        mode_label = "LIVE TRADING" if is_live else "PAPER TRADING"
        logging.info("=" * 60)
        logging.info("  STARTING ALGO TRADING BOT — SMARTAPI V2 STREAM")
        logging.info(f"  Authenticated feed -> CandleBuilder -> Signal Brain -> {mode_label}")
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
                if context: context.start_stage('STREAM_CONNECTING')
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
        context=getattr(self,'run_context',None)
        if context is not None:
            try:
                context.write_session_summary(self)
                context.record_shutdown(reason)
            except Exception: logging.exception('[SESSION SUMMARY FAILED]')

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
        state.refresh_maturity()
        state.record_periodic_atr(atr=atr_val, ltp=close_p, timestamp=latest['Timestamp'], completed_count=len(df))

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

    def _evaluate_watchlist_orchestrator(self, triggered_by_symbol=None, evaluation_time=None):
        from runtime_observation import OpportunityTelemetry, observe_signal
        with self._execution_lock:
            now=to_ist(evaluation_time) if evaluation_time is not None else to_ist()
            trader=self.paper_trader
            if not hasattr(self,'telemetry'):
                self.telemetry=OpportunityTelemetry()
            self._promote_reserves(now)
            candidates=[]
            for state in sorted(self.active_symbols.values(),key=lambda x:(x.rank,x.symbol)):
                try:
                    observation=observe_signal(state,trader,self.schedule,now,generate_vwap_signal,detect_daily_bias)
                    existing=trader.open_position if trader.has_open_position else None
                    # Frozen direction-flip protection can EXIT despite a new-entry
                    # volatility/cutoff/economic failure. It still needs sound live data.
                    exit_gates=('session_data','warmup','feed','identity','signal_freshness','signal','bias','indicators')
                    if (existing and state.token==existing['token'] and observation.side!=existing['side']
                            and all(observation.gates.get(g)=='PASS' for g in exit_gates)):
                        if state.instrument!=existing['instrument']:
                            raise SafetyError('INSTRUMENT_IDENTITY_MISMATCH')
                        trader.set_quote(state.instrument,state.quote)
                        result=trader.close_position(observation.close,now,
                            f"Direction Flip ({existing['side']}→{observation.side})")
                        if result is None:
                            raise SafetyError('UNKNOWN_BROKER_STATE')
                        observation=observe_signal(state,trader,self.schedule,now,generate_vwap_signal,detect_daily_bias)
                    changed=self.telemetry.record(observation,trader)
                    if getattr(self,'shadow',None) is not None:
                        self.shadow.record(observation)
                    if changed and observation.signal_generated:
                        trader._event('SIGNAL',side=observation.side,symbol=state.symbol,
                                      signal_id=observation.signal_id,executable=observation.executable,
                                      blocking_reasons=observation.blocking_reasons)
                    if not observation.executable:
                        continue
                    if state.last_signal and state.last_signal.get('signal_id')==observation.signal_id:
                        continue
                    payload={'instrument':state.instrument,'quote':state.quote,'symbol':state.symbol,
                        'token':state.token,'exchange':state.exchange,'VWAP':observation.reference_entry,
                        'Close':observation.close,'ATR_14':observation.atr,'signal_type':observation.signal_type,
                        'signal_timestamp':observation.candle_timestamp,'signal_id':observation.signal_id}
                    depth=state.quote.ask_quantity if observation.side=='BUY' else state.quote.bid_quantity
                    candidates.append({'payload':payload,'side':observation.side,'bias':observation.bias,
                        'execution_quality':1-state.quote.spread_pct,'net_rr':observation.economics['net_rr'],
                        'depth':depth,'opportunity_score':observation.opportunity_score,
                        'timestamp':observation.candle_timestamp,'symbol':state.symbol,'state':state})
                except SafetyError as exc:
                    trader._event('REJECTED',reason=str(exc),symbol=state.symbol)
                except Exception as exc:
                    state.mark_error(type(exc).__name__)
                    trader._event('EXCEPTION',symbol=state.symbol,reason=type(exc).__name__)
                    logging.exception('[OBSERVATION FAILED] %s',state.symbol)
            for candidate in sorted(candidates,key=arbitration_key):
                state=candidate['state']
                state.last_signal={'signal_id':candidate['payload']['signal_id']}
                trader.update_daily_bias(candidate['bias'])
                if trader.execute_trade(candidate['payload'],timestamp=now,side=candidate['side'],angel_session=self.angel_session):
                    position=trader.open_position
                    if position and 'average_entry_price' in position and 'quantity' in position:
                        self.telemetry.peak_exposure=max(self.telemetry.peak_exposure,position['average_entry_price']*position['quantity'])
                    break
            self._write_readiness(now)

    def _promote_reserves(self,now):
        # Implementation below uses the same observations as entries; no separate order path.
        from reserve_watchlist import promote_reserves
        promote_reserves(self,now)

    def _write_readiness(self,now):
        context=getattr(self,'run_context',None)
        if context is not None:
            context.write_readiness(self,now)

    def _restore_session_history(self, state, now):
        from copy import copy
        from session_bootstrap import prepare_session_repair, commit_session_repair, missing_ranges
        from history_service import BOOTSTRAP, PROTECTION
        with self._execution_lock:
            state.builder.recovery_required=True
            state.refresh_maturity()
            snapshot=copy(state)
            snapshot.builder=copy(state.builder)
            snapshot.builder.df=state.builder.df.copy()
        existing=self.paper_trader.open_position if self.paper_trader.has_open_position else None
        priority=PROTECTION if existing and existing['token']==state.token else BOOTSTRAP
        repairs=prepare_session_repair(snapshot,now,
            lambda context:self.history_service.fetch(context,priority=priority,timeout=60.))
        with self._execution_lock:
            report=commit_session_repair(state,now,repairs)
            if missing_ranges(state.builder,self.schedule.localize()):
                state.builder.recovery_required=True
                state.builder.recovery_reason='HISTORY_ADVANCED_DURING_RECOVERY'
                state.refresh_maturity()
        logging.info('[SESSION DATA] %s status=%s restored=%s last=%s',state.symbol,state.data_status,
                     report.get('valid_count'),report.get('last_timestamp'))
        return report

    def _history_recovery_loop(self):
        last_attempt={}
        while not self._shutdown_requested:
            for state in sorted(self.active_symbols.values(),key=lambda s:(s.watchlist_role!='PROTECTION_ONLY',s.rank)):
                if self._shutdown_requested:
                    return
                if not state.builder.recovery_required:
                    continue
                now=self.schedule.localize()
                if self.schedule.get_market_state(now)==MarketPhase.PRE_MARKET:
                    continue
                if time_module.monotonic()-last_attempt.get(state.token,-1e9)<config.HISTORY_RECOVERY_RETRY_SECONDS:
                    continue
                last_attempt[state.token]=time_module.monotonic()
                try:
                    self._restore_session_history(state,now)
                except Exception as exc:
                    state.history_validation={'valid':False,'reason':str(exc)}
                    logging.warning('[SESSION DATA BLOCKED] %s %s; quote/exit processing continues',state.symbol,type(exc).__name__)
                self._write_readiness(self.schedule.localize())
            context=getattr(self,'run_context',None)
            if context and all(not s.builder.recovery_required for s in self.active_symbols.values()):
                context.end_stage('HISTORICAL_BASELINE_LOADING')
            time_module.sleep(1.)

    def _extract_tick_fields(self, data: dict) -> tuple[float, int, datetime, Optional[float], Optional[float], bool]:
        """Extract LTP, actual trade volume (without fake fallback), timestamp, best bid, best ask, and depth availability from SmartAPI data."""
        raw_price = data.get("last_traded_price")
        if raw_price is None:
            raw_price = data.get("ltp") or data.get("price")
        if raw_price is None:
            raise ValueError(f"Invalid SmartAPI tick payload: missing last_traded_price ({data!r})")

        raw_price = float(raw_price)
        price = raw_price / 100.0 if data.get('last_traded_price') is not None else raw_price
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
        depth_available = False

        best_5_buy = data.get("best_5_buy_data")
        if isinstance(best_5_buy, list) and len(best_5_buy) > 0 and isinstance(best_5_buy[0], dict):
            b_price = best_5_buy[0].get("price")
            if b_price is not None:
                raw_b = float(b_price)
                best_bid = raw_b / 100.0
        elif data.get("buy_price") is not None:
            raw_b = float(data["buy_price"])
            best_bid = raw_b / 100.0

        best_5_sell = data.get("best_5_sell_data")
        if isinstance(best_5_sell, list) and len(best_5_sell) > 0 and isinstance(best_5_sell[0], dict):
            s_price = best_5_sell[0].get("price")
            if s_price is not None:
                raw_s = float(s_price)
                best_ask = raw_s / 100.0
        elif data.get("sell_price") is not None:
            raw_s = float(data["sell_price"])
            best_ask = raw_s / 100.0

        depth_available = bool(best_bid and best_ask)
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
                logging.warning('Tick without instrument token rejected'); return

            sym_state = self.active_symbols.get(tok_str)
            if sym_state is None:
                logging.debug("Tick received for unknown token %s; safely dropped.", tok_str)
                return

            cumulative=data.get('volume_trade_for_the_day',data.get('volume_traded_today'))
            cumulative=float(cumulative) if cumulative is not None else 0.
            previous=self._cumulative_volumes.get(tok_str)
            if cumulative>0:
                volume=max(0,int(cumulative-previous)) if previous is not None and cumulative>=previous else 0
                self._cumulative_volumes[tok_str]=cumulative
            else:
                volume=0 # Unknown volume does not get invented for VWAP.
            buys=data.get('best_5_buy_data') or []
            sells=data.get('best_5_sell_data') or []
            bid_qty=int(buys[0].get('quantity',0)) if buys else 0
            ask_qty=int(sells[0].get('quantity',0)) if sells else 0

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
                bid_quantity=bid_qty,ask_quantity=ask_qty,cumulative_volume=cumulative,
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

                symbol_state.cumulative_volume=tick.cumulative_volume
                symbol_state.quote=MarketQuote(tick.best_bid or 0.,tick.best_ask or 0.,tick.bid_quantity,tick.ask_quantity,
                    tick.timestamp,tick.price,tick.cumulative_volume)
                if symbol_state.instrument is not None:
                    self.paper_trader.set_quote(symbol_state.instrument,symbol_state.quote)

                if state == FeedHealthState.HEALTHY and not getattr(symbol_state,'_healthy_reported',False):
                    symbol_state._healthy_reported=True
                    self._write_readiness(self.schedule.localize())

                # Backward compatibility for primary symbol attributes
                if symbol_state.token == self.token:
                    self._last_spread_pct = symbol_state.last_spread_pct
                    self._last_depth_available = symbol_state.last_depth_available

                # Feed genuine trade ticks into candle/VWAP builder (per-symbol isolation)
                if tick.volume > 0:
                    try:
                        with self._execution_lock:
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
        self.paper_trader.reconcile_broker('RECONNECT')
        for state in self.active_symbols.values():
            state.feed_monitor.on_connect()
            state._healthy_reported=False
            with self._execution_lock:
                state.builder.mark_connection_boundary()
                state.refresh_maturity()

        context=getattr(self,'run_context',None)
        if context:
            context.end_stage('STREAM_CONNECTING')
            context.start_stage('STREAM_HEALTHY')
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
            with self._execution_lock:
                state.builder.mark_connection_boundary()
                state.refresh_maturity()

    def _on_close(self, wsapp, *args, **kwargs) -> None:
        logging.warning("SmartAPI websocket closed.")
        for state in self.active_symbols.values():
            state.feed_monitor.on_disconnect(reason="SmartAPI websocket closed")
            with self._execution_lock:
                state.builder.mark_connection_boundary()
                state.refresh_maturity()
        if hasattr(self,'telemetry'): self.telemetry.feed_interruptions+=1
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

        flat = not self.paper_trader.has_open_position and self.paper_trader.reconcile_broker('EOD')
        self.paper_trader.session_report()
        if not flat:
            logging.critical('EOD exposure unresolved; entries blocked, operator action required')
            return
        self._eod_square_off_done = True
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
            if state in {MarketPhase.SQUARE_OFF, MarketPhase.CLOSED} and self._eod_square_off_done:
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
            f"Broker authentication rejected. "
            f"Check credentials in .env file."
        )

    logging.info(f"✅ Angel One authentication successful for client {client_id}.")
    is_live = getattr(config, "LIVE_MODE", False)
    if not is_live and not isinstance(angel, ReadOnlySmartConnectWrapper):
        angel = ReadOnlySmartConnectWrapper(angel)
    return angel


def place_live_order(angel,symbol,token,side,qty,**kwargs):
    from execution_engine import place_live_order as protected_order
    return protected_order(angel,symbol,token,side,qty,**kwargs)


def record_screening_report(result=None,reason=None,output_dir=None,now=None):
    """Record a zero-trade session too, without constructing an execution engine."""
    from safety_journal import SafetyJournal
    current=now or to_ist()
    environment='LIVE' if config.LIVE_MODE else config.EXECUTION_ENVIRONMENT
    base=Path(output_dir) if output_dir else Path(__file__).parent/'data'/environment.lower()
    base.mkdir(parents=True,exist_ok=True)
    journal=SafetyJournal(base/'trades.sqlite3',environment)
    journal.start_day(current.date())
    try:
        if reason:journal.event(f'{current.date()}:startup:{reason}','REJECTED',{'reason':reason})
        if result:
            for candidate in result.diagnostics:
                prefix=f'{current.date()}:{candidate.symbol}'
                journal.event(prefix+':screen','SCREENED',{'symbol':candidate.symbol,'qualified':candidate.qualified,
                    'opportunity_score':candidate.opportunity_score,'rejections':candidate.rejection_reasons})
                if candidate.qualified:journal.event(prefix+':tradeable','TRADEABLE',{'symbol':candidate.symbol})
                for rejection in candidate.rejection_reasons:
                    journal.event(prefix+':'+str(rejection),'REJECTED',{'symbol':candidate.symbol,'reason':str(rejection),'stage':'SCREENING'})
            for rank,candidate in enumerate(result.watchlist,1):
                journal.event(f'{current.date()}:{candidate.symbol}:watchlist','WATCHLIST',{'symbol':candidate.symbol,
                    'rank':rank,'components':candidate.opportunity_components,'rvol_history_sessions':len(candidate.volume_profiles)})
        report=journal.report()
        (base/'trades.report.json').write_text(json.dumps(report,indent=2,default=str))
        return report
    finally:journal.close()


def _main(run_context) -> None:
    # ── LIVE MODE STARTUP ──────────────────────────────
    is_live = getattr(config, "LIVE_MODE", False)
    angel_session = None
    run_context.start_stage("AUTHENTICATING")

    if is_live:
        # Real money mode — login to Angel One
        angel_session = angel_login()
    else:
        try:
            angel_session = angel_login()
        except Exception as e:
            logging.warning(f"Paper mode broker session creation skipped / failed: {e}")

    run_context.end_stage('AUTHENTICATING', angel_session is not None,
                          None if angel_session is not None else 'BROKER_AUTHENTICATION_FAILED')
    from history_service import HistoryService
    history_service=HistoryService(angel_session) if angel_session is not None else None
    log_execution_mode_banner(
        live_mode=is_live,
        client_id=_first_env("ANGEL_CLIENT_ID", "CLIENT_ID") or "UNKNOWN",
        capital=TOTAL_CAPITAL,
        working_tranche=config.WORKING_CAPITAL,
    )

    startup_time = to_ist()
    override_sym = os.getenv("TRADING_SYMBOL")
    if override_sym or not RUN_PREMARKET_SCREENER:
        try:
            registry = load_startup_universe(angel_session, DiscoveryDataSource(), startup_time).registry
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logging.error('NO_TRADE: instrument/eligibility source unavailable (%s)', type(exc).__name__)
            record_screening_report(reason='INSTRUMENT_SOURCE_UNAVAILABLE', now=startup_time)
            return
    if override_sym:
        logging.warning("=" * 70)
        logging.warning(f"⚠️  [MANUAL OVERRIDE] Manual TRADING_SYMBOL override specified: {override_sym}")
        logging.warning(f"🔒  Execution Mode remains strictly: {'LIVE' if is_live else 'SIMULATION / PAPER'}")
        logging.warning("=" * 70)
        stream = AngelOneLiveStream(target_symbol=override_sym, angel_session=angel_session,registry=registry,
            run_context=run_context,history_service=history_service)
        run_context.stream=stream
        stream.run()
        return

    if RUN_PREMARKET_SCREENER:
        # Discovery supplies only the input universe; the existing screener chooses Top 3.
        output_base = Path(__file__).parent / 'data' / config.EXECUTION_ENVIRONMENT.lower()
        pipeline = run_premarket_pipeline(smart_api=angel_session,
            report_path=run_context.directory/'discovery.json',history_service=history_service,run_context=run_context)
        registry = pipeline.registry
        screen_result = pipeline.screen
        run_context.pipeline_report=pipeline.report()
        failure_reason = pipeline.screen_failure_reason or pipeline.discovery.failure_reason
        record_screening_report(screen_result, reason=failure_reason, now=startup_time)

        if pipeline.readiness == 'BLOCKED':
            logging.error('[PREMARKET BLOCKED] Required premarket data unavailable: %s. '
                          'No configured stock list will be substituted. See discovery report.',
                          failure_reason)
            sys.exit(2)

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
            f"🎯 Primary premarket candidate: {winner.symbol} (Token: {winner.token}) "
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
            watchlist=watchlist,registry=registry,reserves=screen_result.reserves,
            run_context=run_context,history_service=history_service,
        )
        run_context.stream=stream
        stream.run()
    else:
        logging.warning("=" * 70)
        logging.warning("⚠️  [MANUAL OVERRIDE] RUN_PREMARKET_SCREENER is set to False!")
        logging.warning(f"Configured symbol requires verified registry resolution: {DEFAULT_SYMBOL}")
        logging.warning(f"🔒  Execution Mode remains strictly: {'LIVE' if is_live else 'SIMULATION / PAPER'}")
        logging.warning("=" * 70)
        stream = AngelOneLiveStream(
            target_symbol=DEFAULT_SYMBOL,
            target_token=registry.resolve(DEFAULT_SYMBOL).token,
            registry=registry,
            angel_session=angel_session,run_context=run_context,history_service=history_service,
        )
        run_context.stream=stream
        stream.run()


def main() -> None:
    from run_context import RunContext
    with RunContext('REGULAR') as context:
        return _main(context)


if __name__ == "__main__":
    main()
