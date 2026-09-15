# ─────────────────────────────────────────────────────────────
# config.py  —  All tunable constants for the algo-trading-bot
# DO NOT hardcode these values anywhere else in the codebase.
# ─────────────────────────────────────────────────────────────

# ── UNIVERSE ──────────────────────────────────────────────────
SYMBOL = "SJVN-EQ"               # SJVN Ltd
EXCHANGE = "NSE"               # unchanged
TOKEN = "18883"                 # Angel One instrument token for SJVN
SEGMENT = 1                   # unchanged (NSE equity)

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
# Angel One 30-day free trial: Aug 25 → Sep 25 2026
# Zero flat fee during this period.
# After Sep 25: revert to 20.0 per trade.
BROKERAGE_PER_TRADE = 0.0    # ₹0 until Sep 25 2026

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
MIN_NET_PROFIT = 2.0              # Absolute floor in rupees for minimum net gain (was 3.0)
MIN_NET_PROFIT_RS = 2.0           # Alias for MIN_NET_PROFIT (explicit name)
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
LIVE_MODE = True   # ← CHANGE TO True ON SEP 15 MORNING ONLY

