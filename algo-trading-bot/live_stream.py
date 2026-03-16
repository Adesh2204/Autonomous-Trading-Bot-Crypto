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
from dotenv import load_dotenv

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


# ── WebSocket Callbacks ─────────────────────────────────────────────────────

def on_message(ws, message):
    try:
        tick = json.loads(message)
        # Using DEBUG here so your log file doesn't get gigabytes large 
        # from logging every single millisecond tick. 
        logging.debug(f"Tick received: {tick}") 
    except json.JSONDecodeError:
        logging.warning(f"Failed to parse JSON: {message}")

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

    logging.info("=" * 50)
    logging.info("STARTING ALGO TRADING BOT (DATA INGESTION)")
    logging.info("=" * 50)

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