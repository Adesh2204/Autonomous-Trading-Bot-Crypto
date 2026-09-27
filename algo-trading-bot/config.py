# ─────────────────────────────────────────────────────────────
# config.py  —  All tunable constants for the algo-trading-bot
# DO NOT hardcode these values anywhere else in the codebase.
# ─────────────────────────────────────────────────────────────

# ── UNIVERSE & CANDIDATE POOL ─────────────────────────────────
# Legacy default fallback (kept for offline tests & backward compatibility)
SYMBOL = "UNIONBANK-EQ"          # Union Bank of India (Legacy default)
EXCHANGE = "NSE"               # unchanged
TOKEN = "10753"                 # Angel One instrument token for UNIONBANK
SEGMENT = 1                   # unchanged (NSE equity)

# Configured pool of liquid candidate instruments evaluated by run_premarket_screener()
CANDIDATE_UNIVERSE = [
    {"symbol": "ONGC", "trading_symbol": "ONGC-EQ", "token": "2475", "exchange": "NSE"},
    {"symbol": "IFCI", "trading_symbol": "IFCI-EQ", "token": "1491", "exchange": "NSE"},
    {"symbol": "BANKBARODA", "trading_symbol": "BANKBARODA-EQ", "token": "4668", "exchange": "NSE"},
    {"symbol": "ADANIPOWER", "trading_symbol": "ADANIPOWER-EQ", "token": "17388", "exchange": "NSE"},
    {"symbol": "TATASTEEL", "trading_symbol": "TATASTEEL-EQ", "token": "3499", "exchange": "NSE"},
    {"symbol": "TATAMOTORS", "trading_symbol": "TATAMOTORS-EQ", "token": "3456", "exchange": "NSE"},
    {"symbol": "ITC", "trading_symbol": "ITC-EQ", "token": "1660", "exchange": "NSE"},
    {"symbol": "COALINDIA", "trading_symbol": "COALINDIA-EQ", "token": "20374", "exchange": "NSE"},
    {"symbol": "M&M", "trading_symbol": "M&M-EQ", "token": "2031", "exchange": "NSE"},
    {"symbol": "YESBANK", "trading_symbol": "YESBANK-EQ", "token": "11915", "exchange": "NSE"},
    {"symbol": "NTPC", "trading_symbol": "NTPC-EQ", "token": "2977", "exchange": "NSE"},
    {"symbol": "PNB", "trading_symbol": "PNB-EQ", "token": "10666", "exchange": "NSE"},
    {"symbol": "SJVN", "trading_symbol": "SJVN-EQ", "token": "18883", "exchange": "NSE"},
    {"symbol": "NHPC", "trading_symbol": "NHPC-EQ", "token": "11262", "exchange": "NSE"},
    {"symbol": "UNIONBANK", "trading_symbol": "UNIONBANK-EQ", "token": "10753", "exchange": "NSE"},
]

# ── PRE-MARKET SCREENER CONFIG ────────────────────────────────
SCREEN_MIN_LTP = 150.0            # Minimum Last Traded Price (₹)
SCREEN_MAX_LTP = 350.0            # Maximum Last Traded Price (₹)
SCREEN_MIN_ATR_PCT = 0.0040       # Minimum ATR% (0.40% of LTP)
SCREEN_MAX_SPREAD_PCT = 0.0015    # Maximum normalized spread (0.15%)
SCREEN_MIN_DAILY_VOLUME = 5000000 # Minimum previous session volume (shares)
SCREEN_ATR_PERIOD = 14            # ATR period for 1-minute historical candles
SCREEN_EMA_FAST_PERIOD = 9        # Fast EMA period for trend alignment
SCREEN_EMA_SLOW_PERIOD = 21       # Slow EMA period for trend alignment
SCREEN_API_REQUEST_INTERVAL = 0.5 # Sequential pacing delay (seconds)
SCREEN_API_MAX_RETRIES = 3        # Retries for rate limits / broker errors
SCREEN_API_BACKOFF_BASE = 1.0     # Base backoff multiplier (seconds)
SCREEN_MIN_CANDLE_COUNT = 300     # Minimum 1-minute bars required in completed session
SCREEN_TOP_N = 1                  # Single top qualifier for Phase 1-4
EXCLUSION_LIST = []               # Excluded symbols list

# ── INTRADAY ATR FIREWALL ─────────────────────────────────────
INTRADAY_ATR_MIN_PCT = 0.0040     # 0.40% minimum intraday ATR floor
ATR_RECHECK_INTERVAL_SECONDS = 1800 # 30-minute rolling recheck interval
ATR_LOW_CONFIRMATION_COUNT = 2    # Consecutive low readings required to enter STANDBY
ATR_RECOVERY_CONFIRMATION_COUNT = 2 # Consecutive healthy readings required to recover

# ── FEED INTEGRITY & WATCHDOG ─────────────────────────────────
STALE_TICK_TIMEOUT_SECONDS = 15.0 # Max seconds without genuine tick before STALE
FEED_RECONNECT_WARMUP_TICKS = 3   # Fresh ticks required after reconnect before HEALTHY
MAX_QUEUE_SIZE = 10000            # Thread-safe ingestion queue size


# ── CAPITAL (absolute ₹ — intentionally fixed, user config) ───
TOTAL_CAPITAL = 20000.00      # ₹20,000 real money
WORKING_CAPITAL_PCT = 0.50       # 50% of total
DAILY_LOSS_LIMIT_PCT = 0.02      # 2% of total capital
RISK_PER_SETUP_PCT = 0.01        # 1% of working capital per setup

WORKING_CAPITAL = 10000.00      # 50% of total
BACKUP_CAPITAL = 10000.00       # 50% reserve
RISK_PER_TRADE = 100.00        # 1% of working capital
DAILY_LOSS_LIMIT = 400.00        # 2% of ₹20,000

# ── BROKERAGE CONFIG ──────────────────────────────
# Always assume FULL standard brokerage. The ₹0 new-user offer is
# capped at ₹500 cumulative — a bot burning 18 orders/day exhausts
# it in days. Treat any remaining discount as a bonus, never a gate input.
# Rates verified against angelone.in/exchange-transaction-charges (2026-09-16).
BROKERAGE_PCT = 0.001        # 0.1% of order value
BROKERAGE_CAP = 20.0         # ₹20 max per order
BROKERAGE_MIN = 5.0          # ₹5 min per order

# ── SLIPPAGE ──────────────────────────────────────
# Assume entry fills slightly worse than signal price.
# Calibrate from historical fill data as more days are logged.
SLIPPAGE_HAIRCUT_PCT = 0.0005  # 0.05% — conservative default

# ── SIGNAL BRAIN: PRICE-RELATIVE PARAMS ───────────────────────
MIN_CANDLES_BEFORE_TRADE = 15     # Warmup period (unitless, keep)
MIN_ATR_PCT = 0.0006              # ATR floor as % of close price (0.06%)
ATR_BAND_MULT = 1.50              # Pullback band = VWAP ± mult × ATR
VWAP_SLOPE_LOOKBACK = 10          # Candles for VWAP slope (unitless)
EMA_FAST = 9                      # Fast EMA period (unitless)
EMA_SLOW = 21                     # Slow EMA period (unitless)
ATR_PERIOD = 14                   # ATR period (unitless)

# ── BREAKOUT SIGNAL PARAMS ────────────────────────────────────
BREAKOUT_CLOSE_MULT = 0.50        # Close must be > VWAP + mult × ATR
VOL_SURGE_MULT = 1.50             # Volume must be > mult × 10-bar avg
VOL_MA_PERIOD = 10                # Rolling window for volume average

# ── EXECUTION ENGINE: ATR-RELATIVE TRADE MANAGEMENT ──────────
SL_ATR_MULT = 2.00                # Stop-loss distance in ATR units (Wick-Immune buffer)
TP_ATR_MULT = 4.00                # Profit target distance in ATR units (1:2 Risk-Reward)
BE_ATR_MULT = 1.00                # Breakeven trigger (profit ≥ mult × ATR)
TRAIL_ATR_MULT = 2.00             # Trailing stop gap in ATR units
REENTRY_ATR_MULT = 1.50           # Anti-spam: price must be > VWAP + mult×ATR
REENTRY_COOLDOWN_CANDLES = 10     # Post-SL cooldown in candles (unitless)

# ── ADAPTIVE FRICTION GATE ────────────────────────────────────
MIN_NET_RR = 1.2                  # Legacy alias (used by fallback imports)
MIN_NET_RR_NORMAL = 1.2           # R:R floor in normal volatility (was 1.5)
MIN_NET_RR_LOW_VOL = 0.8          # R:R floor when ATR < LOW_VOL_ATR_PCT
LOW_VOL_ATR_PCT = 0.0010          # Below this = "low vol regime"
MIN_NET_PROFIT = 5.0              # Absolute floor in rupees for minimum net gain
MIN_NET_PROFIT_RS = 5.0           # Alias for MIN_NET_PROFIT (explicit name)
# MIN_NET_PROFIT_MULTIPLIER = 2.0
# DEPRECATED — removed from all logic paths 2026-09-07.
# Replaced by MIN_NET_PROFIT_RS inside friction_gate_check().
# Do not uncomment or reference in any logic.

# ── PYRAMIDING ────────────────────────────────────────────────
TRANCHE_1_PCT = 0.33              # 33% of working capital
TRANCHE_2_PCT = 0.33              # 33% of working capital
TRANCHE_3_PCT = 0.34              # 34% of working capital
TRANCHE_FRACTIONS = [TRANCHE_1_PCT, TRANCHE_2_PCT, TRANCHE_3_PCT]
MAX_TRANCHES = 3
PYRAMID_TRIGGER_ATR_MULT = 2.00   # 2.0x ATR above base/previous tranche

# ── SHORT SIGNAL PARAMS ──────────────────────────────────────
SHORT_BAND_MULT = 1.50            # Same as ATR_BAND_MULT (symmetric)
SHORT_CLOSE_MULT = 0.50           # Breakdown: close < VWAP - mult × ATR
KNIFE_UP_MULT = 1.00              # Knife-up filter for short signals

# ── DAILY BIAS DETECTOR ──────────────────────────────────────
BIAS_VWAP_GAP_PCT = 0.0005        # Threshold for VWAP position check
BIAS_VOTES_NEEDED = 2             # Min confluence votes to declare bias

# ── TIMING ────────────────────────────────────────────────────
EOD_SQUAREOFF_TIME = "15:20"      # HH:MM IST — EOD auto square-off
MARKET_OPEN_TIME = "09:15"        # HH:MM IST

# ── TRADING MODE ─────────────────────────────────────────────
# LIVE_MODE = False → Paper trading (default, safe)
# LIVE_MODE = True  → Real Angel One API orders (real money)
# ⚠️  Set True ONLY on Sep 15 morning, AFTER login test passes
LIVE_MODE = False   # ← CHANGE TO True ON SEP 15 MORNING ONLY

# ── RECONCILIATION ───────────────────────────────────────────
RECONCILIATION_TOLERANCE_INTRADAY = 0.50   # ₹0.50 tolerance for per-trade gross P&L vs broker realised delta
RECONCILIATION_TOLERANCE_EOD = 1.00        # ₹1.00 tolerance for EOD account net P&L vs capital movement
RECONCILIATION_MAX_RETRIES = 3             # Max retries for delayed broker position state
RECONCILIATION_RETRY_INTERVAL = 0.5        # Seconds between position refresh retries


