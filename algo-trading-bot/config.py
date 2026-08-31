# ─────────────────────────────────────────────────────────────
# config.py  —  All tunable constants for the algo-trading-bot
# DO NOT hardcode these values anywhere else in the codebase.
# ─────────────────────────────────────────────────────────────

# ── UNIVERSE ──────────────────────────────────────────────────
SYMBOL = "BANKBARODA"       # Change this to trade a different stock
EXCHANGE = "NSE"
TOKEN = "4668"             # Angel One instrument token for SYMBOL
SEGMENT = 1                # NSE equity

# ── CAPITAL (absolute ₹ — intentionally fixed, user config) ───
TOTAL_CAPITAL = 9999.46
WORKING_CAPITAL_PCT = 0.50       # 50% of total
DAILY_LOSS_LIMIT_PCT = 0.02      # 2% of total capital
RISK_PER_SETUP_PCT = 0.01        # 1% of working capital per setup

WORKING_CAPITAL = 4999.73        # 50% intraday deployment limit
BACKUP_CAPITAL = 4999.73         # 50% reserve buffer
RISK_PER_TRADE = 100.00          # Max initial risk per setup
DAILY_LOSS_LIMIT = 200.00        # Hard daily loss circuit breaker

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
MIN_NET_RR = 1.5                  # Minimum Net Risk-to-Reward ratio after all statutory friction
MIN_NET_PROFIT = 3.0              # Absolute floor in rupees for minimum net gain
MIN_NET_PROFIT_MULTIPLIER = 2.0   # Net Profit must be at least 2x the cost of doing business

# ── PYRAMIDING ────────────────────────────────────────────────
TRANCHE_1_PCT = 0.33              # 33% of working capital
TRANCHE_2_PCT = 0.33              # 33% of working capital
TRANCHE_3_PCT = 0.34              # 34% of working capital
TRANCHE_FRACTIONS = [TRANCHE_1_PCT, TRANCHE_2_PCT, TRANCHE_3_PCT]
MAX_TRANCHES = 3
PYRAMID_TRIGGER_ATR_MULT = 2.00   # 2.0x ATR above base/previous tranche

# ── TIMING ────────────────────────────────────────────────────
EOD_SQUAREOFF_TIME = "15:20"      # HH:MM IST — EOD auto square-off
MARKET_OPEN_TIME = "09:15"        # HH:MM IST
