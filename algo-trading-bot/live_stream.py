"""
live_stream.py — Data Ingestion Layer
=====================================
Production-ready WebSocket client. Includes auto-reconnection,
keep-alive pings, and file-based logging.
"""

import websocket
import json
import os
import logging
import sys
import threading
import time as time_module
from datetime import datetime
from dotenv import load_dotenv

from candle_builder    import CandleBuilder
from signal_brain      import generate_vwap_signal
from execution_engine  import PaperTrader
from market_schedule   import (
    MarketPhase,
    can_enter_new_positions,
    get_market_state,
    holiday_name,
    is_trading_day,
    seconds_until_market_start,
    to_ist,
)

# ── Logging Setup ───────────────────────────────────────────────────────────
# This will print to the terminal AND save to a file named 'trading_bot.log'
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)

# ── Security ────────────────────────────────────────────────────────────────
load_dotenv()

BROKER_WSS_URL = os.getenv("BROKER_WSS_URL")
BROKER_API_KEY = os.getenv("BROKER_API_KEY")
INITIAL_RECONNECT_DELAY_SECONDS = 5
MAX_RECONNECT_DELAY_SECONDS = 300


# ── Paper Trader Instance ───────────────────────────────────────────────────
paper_trader = PaperTrader(
    total_capital=10_000,
    working_capital_pct=0.50,
    daily_loss_limit_pct=0.02,
    risk_per_trade_pct=0.01,
    stop_loss_pct=0.005,
    reward_to_risk=2.0,
)

_eod_square_off_done = False
_lifecycle_shutdown_requested = False


# ── Signal Callback ─────────────────────────────────────────────────────────
# Fired automatically every time a 1-minute candle closes.

def on_candle_close(df):
    """Run VWAP signal detection and execute paper trades on buy signals."""
    result = generate_vwap_signal(df.copy())
    latest = result.iloc[-1]
    signal_timestamp = to_ist()

    logging.info(
        f"Candle #{len(result)} closed | "
        f"O:{latest['Open']:.2f}  H:{latest['High']:.2f}  "
        f"L:{latest['Low']:.2f}  C:{latest['Close']:.2f}  "
        f"V:{latest['Volume']:.0f}  |  VWAP:{latest['VWAP']:.2f}"
    )

    if latest["Buy_Signal"]:
        if not can_enter_new_positions(signal_timestamp):
            logging.info(
                "Buy signal rejected - entries are disabled in "
                f"{get_market_state(signal_timestamp).value} after the "
                "15:15 IST cutoff."
            )
            return

        logging.info(
            "🚀 ════════════════════════════════════════════════════════"
        )
        logging.info(
            f"🚀  VWAP PULLBACK BUY SIGNAL  @  VWAP {latest['VWAP']:.2f}"
        )
        logging.info(
            "🚀 ════════════════════════════════════════════════════════"
        )

        # ── Execute the paper trade ─────────────────────────────────
        paper_trader.execute_trade({
            "VWAP":   latest["VWAP"],
            "Close":  latest["Close"],
            "symbol": "RELIANCE",
        }, timestamp=signal_timestamp)


# ── Candle Builder Instance ─────────────────────────────────────────────────
builder = CandleBuilder(interval_seconds=60, on_candle_close=on_candle_close)


# ── Lifecycle Controller ────────────────────────────────────────────────────

def parse_tick_timestamp(ts_raw) -> datetime:
    """Parse broker timestamps and normalize them to IST."""
    if not ts_raw:
        return to_ist()

    try:
        if isinstance(ts_raw, (int, float)):
            seconds = float(ts_raw)
            if seconds > 10_000_000_000:
                seconds /= 1000.0
            return to_ist(datetime.fromtimestamp(seconds, tz=to_ist().tzinfo))

        ts_text = str(ts_raw).replace("Z", "+00:00")
        if ts_text.isdigit():
            seconds = float(ts_text)
            if seconds > 10_000_000_000:
                seconds /= 1000.0
            return to_ist(datetime.fromtimestamp(seconds, tz=to_ist().tzinfo))

        return to_ist(datetime.fromisoformat(ts_text))
    except (OverflowError, OSError, ValueError, TypeError):
        return to_ist()


def log_daily_summary(prefix: str = "Daily Summary") -> None:
    virtual_equity = paper_trader.backup_capital + paper_trader.working_capital
    logging.info(
        f"{prefix} | Daily P&L: ₹{paper_trader.daily_pnl:,.2f} | "
        f"Working Capital: ₹{paper_trader.working_capital:,.2f} | "
        f"Virtual Equity: ₹{virtual_equity:,.2f}"
    )


def trigger_eod_square_off(ws, current_dt: datetime, reason: str) -> None:
    """Run the mandatory EOD cleanup exactly once."""
    global _eod_square_off_done, _lifecycle_shutdown_requested

    if _eod_square_off_done:
        return

    _eod_square_off_done = True
    logging.info(f"{reason} triggered at {to_ist(current_dt).strftime('%H:%M:%S')} IST.")
    paper_trader.cancel_pending_orders(reason)
    paper_trader.square_off_all_positions(reason, timestamp=current_dt)
    log_daily_summary("Final Daily P&L")

    _lifecycle_shutdown_requested = True
    if ws is not None:
        ws.close()


def enforce_lifecycle(ws=None, current_dt: datetime | None = None) -> MarketPhase:
    """
    Apply session lifecycle actions for the supplied clock time.

    Live mode passes system time. The simulator passes synthetic tick time.
    """
    global _lifecycle_shutdown_requested

    clock = to_ist(current_dt)
    state = get_market_state(clock)

    if state == MarketPhase.SQUARE_OFF:
        trigger_eod_square_off(ws, clock, "EOD Auto-Square-Off")
    elif state == MarketPhase.CLOSED:
        if paper_trader.has_open_position:
            trigger_eod_square_off(ws, clock, "Market Close Safety Square-Off")
        else:
            logging.info("Market closed. Disconnecting and exiting cleanly.")
            log_daily_summary("Final Daily P&L")
            _lifecycle_shutdown_requested = True
            if ws is not None:
                ws.close()

    return state


def validate_market_startup() -> None:
    """Validate trading day and hold before opening WebSocket subscriptions."""
    now = to_ist()
    today = now.date()

    if not is_trading_day(today):
        reason = holiday_name(today) or "Weekend/Holiday"
        logging.info(f"Market is closed today ({reason}). Exiting.")
        sys.exit(0)

    state = get_market_state(now)
    if state == MarketPhase.PRE_MARKET:
        wait_seconds = seconds_until_market_start(now)
        logging.info(
            "Pre-market startup detected. Waiting until 09:15:00 IST "
            f"({wait_seconds:.0f}s)."
        )
        time_module.sleep(wait_seconds)
    elif state in {MarketPhase.SQUARE_OFF, MarketPhase.CLOSED}:
        logging.info("Market is already in shutdown window. Exiting.")
        sys.exit(0)
    elif state == MarketPhase.CLOSE_ONLY:
        logging.info("Started after 15:15 IST. Entries are disabled; exits only.")


def lifecycle_watchdog(ws) -> None:
    """Timer-based lifecycle enforcement independent of incoming ticks."""
    while not _lifecycle_shutdown_requested:
        state = enforce_lifecycle(ws=ws, current_dt=to_ist())
        if state in {MarketPhase.SQUARE_OFF, MarketPhase.CLOSED}:
            return
        time_module.sleep(5)


# ── WebSocket Callbacks ─────────────────────────────────────────────────────

def extract_tick_metrics(tick):
    """Return a validated (price: float, volume: int) pair from broker payloads."""
    if not isinstance(tick, dict):
        raise ValueError("Tick payload must be a JSON object")

    # Broker payloads are inconsistent across endpoints and versions. Try the
    # most common LTP aliases in order and reject any missing or malformed value.
    price = None
    for key in ("ltp", "last_traded_price", "last_price", "price"):
        if key not in tick or tick[key] is None:
            continue
        try:
            price = float(tick[key])
            if price > 0 and __import__("math").isfinite(price):
                break
        except (TypeError, ValueError):
            continue

    if price is None or price <= 0:
        raise ValueError(
            f"Invalid tick payload: LTP missing or non-positive (received {tick!r})"
        )

    # Volume is often encoded as volume / v / qty / last_qty. We only drop it to 0
    # for missing values after the price has already passed validation.
    volume = 0
    for key in ("volume", "v", "qty", "last_qty", "traded_volume"):
        if key not in tick or tick[key] is None:
            continue
        try:
            volume = int(float(tick[key]))
            break
        except (TypeError, ValueError):
            continue

    return float(price), max(volume, 0)


def on_message(ws, message):
    try:
        tick = json.loads(message)
        logging.debug(f"Tick received: {tick}")

        # Guardrail: never trust a broker payload that omits or zeroes the price.
        # A 0.0 LTP can poison the VWAP engine and create false pullback entries.
        try:
            price, volume = extract_tick_metrics(tick)
        except ValueError as exc:
            logging.warning("[WARNING] Received invalid tick payload (Price/Volume rejected): %s | raw=%s", exc, tick)
            return

        ts_raw = tick.get("timestamp", tick.get("exchange_timestamp"))

        # Parse timestamp if the broker provides one; otherwise use local IST.
        timestamp = parse_tick_timestamp(ts_raw)

        builder.on_tick(price=price, volume=volume, timestamp=timestamp)

        # ── Check SL / Target on every tick (O(1) — two comparisons) ──
        paper_trader.check_exit(live_price=price, timestamp=timestamp)

        # ── Enforce close-only, square-off, and market-close lifecycle ─
        enforce_lifecycle(ws=ws, current_dt=timestamp)

    except json.JSONDecodeError:
        logging.warning(f"Failed to parse JSON: {message}")
    except Exception as e:
        logging.error(f"Error processing tick: {e}")

def on_error(ws, error):
    logging.error(f"WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    logging.warning(f"Disconnected — Code: {close_status_code} | Reason: {close_msg}")
    if not _lifecycle_shutdown_requested:
        logging.info("Connection dropped. Reconnect supervisor will retry.")

def on_open(ws):
    logging.info("WebSocket connection established successfully.")
    
    subscription_payload = json.dumps({
        "action": "subscribe",
        "params": {
            "symbol": "RELIANCE",
            "api_key": BROKER_API_KEY,
        },
    })

    ws.send(subscription_payload)
    logging.info("Subscription request sent for: RELIANCE")


def build_websocket_app() -> websocket.WebSocketApp:
    """Create a fresh WebSocketApp for each reconnect attempt."""
    return websocket.WebSocketApp(
        BROKER_WSS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )


def run_websocket_forever() -> None:
    """Run the WebSocket with exponential backoff after abnormal exits."""
    delay = INITIAL_RECONNECT_DELAY_SECONDS

    while not _lifecycle_shutdown_requested:
        ws = build_websocket_app()
        threading.Thread(target=lifecycle_watchdog, args=(ws,), daemon=True).start()

        try:
            ws.run_forever(
                ping_interval=30,
                ping_timeout=10,
            )
        except Exception as exc:
            logging.exception(f"WebSocket run_forever crashed: {exc}")

        if _lifecycle_shutdown_requested:
            return

        logging.warning(
            f"WebSocket disconnected unexpectedly. Reconnecting in {delay}s."
        )
        time_module.sleep(delay)
        delay = min(delay * 2, MAX_RECONNECT_DELAY_SECONDS)


# ── Main Execution ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BROKER_WSS_URL or not BROKER_API_KEY:
        logging.critical("Missing WSS_URL or API_KEY in .env file. Exiting.")
        exit(1)

    validate_market_startup()

    logging.info("=" * 60)
    logging.info("  STARTING ALGO TRADING BOT — FULL PIPELINE")
    logging.info("  Ingestion → Candles → VWAP Signal → Paper Trader")
    logging.info("=" * 60)

    # Enable trace for deep debugging of the websocket if needed (keep False normally)
    websocket.enableTrace(False) 

    run_websocket_forever()

    if _lifecycle_shutdown_requested:
        sys.exit(0)
