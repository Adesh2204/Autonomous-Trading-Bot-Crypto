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
from datetime import datetime
from dotenv import load_dotenv

from candle_builder    import CandleBuilder
from signal_brain      import generate_vwap_signal
from execution_engine  import PaperTrader

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


# ── Paper Trader Instance ───────────────────────────────────────────────────
paper_trader = PaperTrader(
    total_capital=10_000,
    working_capital_pct=0.50,
    daily_loss_limit_pct=0.02,
    risk_per_trade_pct=0.01,
    stop_loss_pct=0.005,
    reward_to_risk=2.0,
)


# ── Signal Callback ─────────────────────────────────────────────────────────
# Fired automatically every time a 1-minute candle closes.

def on_candle_close(df):
    """Run VWAP signal detection and execute paper trades on buy signals."""
    result = generate_vwap_signal(df.copy())
    latest = result.iloc[-1]

    logging.info(
        f"Candle #{len(result)} closed | "
        f"O:{latest['Open']:.2f}  H:{latest['High']:.2f}  "
        f"L:{latest['Low']:.2f}  C:{latest['Close']:.2f}  "
        f"V:{latest['Volume']:.0f}  |  VWAP:{latest['VWAP']:.2f}"
    )

    if latest["Buy_Signal"]:
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
        })


# ── Candle Builder Instance ─────────────────────────────────────────────────
builder = CandleBuilder(interval_seconds=60, on_candle_close=on_candle_close)


# ── WebSocket Callbacks ─────────────────────────────────────────────────────

def on_message(ws, message):
    try:
        tick = json.loads(message)
        logging.debug(f"Tick received: {tick}")

        # ── Feed the tick into the candle aggregation pipeline ──────
        # Adjust the key names below to match your broker's payload.
        # Common variants:  ltp / last_price / price
        #                   volume / qty / last_qty
        price     = float(tick.get("ltp", tick.get("last_price", tick.get("price", 0))))
        volume    = float(tick.get("volume", tick.get("qty", tick.get("last_qty", 0))))
        ts_raw    = tick.get("timestamp", tick.get("exchange_timestamp"))

        # Parse timestamp if the broker provides one; otherwise use local clock.
        if ts_raw:
            try:
                timestamp = datetime.fromisoformat(str(ts_raw))
            except (ValueError, TypeError):
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        builder.on_tick(price=price, volume=volume, timestamp=timestamp)

    except json.JSONDecodeError:
        logging.warning(f"Failed to parse JSON: {message}")
    except Exception as e:
        logging.error(f"Error processing tick: {e}")

def on_error(ws, error):
    logging.error(f"WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    logging.warning(f"Disconnected — Code: {close_status_code} | Reason: {close_msg}")
    logging.info("Attempting to reconnect...")

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


# ── Main Execution ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BROKER_WSS_URL or not BROKER_API_KEY:
        logging.critical("Missing WSS_URL or API_KEY in .env file. Exiting.")
        exit(1)

    logging.info("=" * 60)
    logging.info("  STARTING ALGO TRADING BOT — FULL PIPELINE")
    logging.info("  Ingestion → Candles → VWAP Signal → Paper Trader")
    logging.info("=" * 60)

    # Enable trace for deep debugging of the websocket if needed (keep False normally)
    websocket.enableTrace(False) 

    ws = websocket.WebSocketApp(
        BROKER_WSS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )

    # Bulletproof run_forever settings
    ws.run_forever(
        ping_interval=30,   # Send a ping every 30 seconds
        ping_timeout=10,    # Disconnect if no pong received in 10s
        reconnect=5         # Wait 5 seconds before auto-reconnecting on a drop
    )