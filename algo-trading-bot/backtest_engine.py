"""
backtest_engine.py — Standalone Historical VWAP Pullback Backtester
=====================================================================
Vector-friendly, session-aware historical backtest harness that
simulates the *exact* rules used in the live trading pipeline.

How It Works
────────────
1. Accepts a DataFrame or CSV of 1-minute OHLCV candles.
2. For each session (09:15 → 15:29 IST), computes rolling VWAP
   (reset per session) and Wilder ATR-14 (rolling across candles).
3. Runs `signal_brain.generate_vwap_signal` for strict 3-condition
   dynamic-ATR pullback signals with Anti-Spam State Lock.
4. Simulates `PaperTrader` with:
     • Scale-in (Pyramiding) up to 3 tranches (33%, 33%, 34%)
     • Scale-in trigger on +0.50% gain + confirmed continuation
     • Zero-risk trailing stop locks (Breakeven / Profit Locks)
     • Priority: Stop Loss → Target → 15:20 IST EOD Auto-Square-Off
     • Capital partitions: 50% Working, 50% Backup, ₹100 risk limit, ₹200 daily loss limit
     • Statutory Friction Gate (Brokerage + STT + Stamp + GST + Txn)
5. On every simulated exit, a structured row is appended to the
   PaperTrader's internal `trades.csv` AND collected in-memory.
6. At end of simulation, prints an institutional-grade Performance
   Summary table:
       Total Trades / Win Rate % / Profit Factor / Max Drawdown
       Average Trade Duration / Net Expectancy per Trade

Usage
─────
>>> from backtest_engine import run_backtest
>>> result = run_backtest(csv_path="historical_ohlcv.csv",
...                        symbol="M&M",
...                        total_capital=10017.0)
>>> print(result.summary_table)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time as dtime
from typing import Optional, Union

from dotenv import load_dotenv
import numpy as np
import pandas as pd

load_dotenv()

# Internal project modules
from execution_engine import PaperTrader
from signal_brain import generate_vwap_signal


# ── Session Boundaries (IST Indian Cash Session) ─────────────────────
MARKET_OPEN_IST = dtime(9, 15)
EOD_SQUAREOFF_IST = dtime(15, 20)
MARKET_CLOSE_IST = dtime(15, 29)


@dataclass
class BacktestResult:
    """Structured output container from a backtest run."""

    symbol: str
    total_capital: float
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: list = field(default_factory=list)

    # Performance metrics
    total_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_inr: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_hold_duration_mins: float = 0.0
    net_expectancy_per_trade: float = 0.0
    net_pnl_total: float = 0.0
    net_roi_pct: float = 0.0

    @property
    def summary_table(self) -> str:
        """Render an institutional-grade performance summary table."""
        border = "═" * 68
        lines = [
            "",
            border,
            "║            BACKTEST PERFORMANCE SUMMARY                      ║",
            border,
            f"║  Symbol              :  {self.symbol:<46}║",
            f"║  Starting Capital    :  ₹{self.total_capital:>14,.2f}                            ║",
            f"║  Final  Capital      :  ₹{(self.total_capital + self.net_pnl_total):>14,.2f}                            ║",
            "╠" + "═" * 66 + "╣",
            f"║  Total Trades        :  {self.total_trades:<46}║",
            f"║  Win Rate            :  {self.win_rate_pct:.2f} % {'':<38}║",
            f"║  Profit Factor       :  {self.profit_factor:.2f}  {'':<41}║",
            f"║  Net Expectancy      :  ₹{self.net_expectancy_per_trade:>+10,.2f}  per trade {'':<21}║",
            f"║  Avg Hold Duration   :  {self.avg_hold_duration_mins:.1f} mins {'':<33}║",
            "╠" + "═" * 66 + "╣",
            f"║  Max Drawdown (₹)    :  ₹{self.max_drawdown_inr:>10,.2f}                            ║",
            f"║  Max Drawdown (%)    :  {self.max_drawdown_pct:>7.2f} %                                  ║",
            f"║  Net Realized P&L    :  ₹{self.net_pnl_total:>10,.2f}                            ║",
            f"║  Net ROI             :  {self.net_roi_pct:>7.2f} %                                  ║",
            border,
            "",
        ]
        return "\n".join(lines)


def _load_ohlcv(source: Union[str, pd.DataFrame]) -> pd.DataFrame:
    """Load OHLCV data from CSV path or in-memory DataFrame."""
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    elif isinstance(source, str):
        if not os.path.exists(source):
            raise FileNotFoundError(f"CSV not found: {source}")
        df = pd.read_csv(source)
    else:
        raise TypeError("source must be a pd.DataFrame or CSV file path (str)")

    # ── Normalize column names (case-insensitive) ──────────────────
    rename_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl in {"timestamp", "time", "datetime", "date"}:
            rename_map[c] = "Timestamp"
        elif cl == "open":
            rename_map[c] = "Open"
        elif cl == "high":
            rename_map[c] = "High"
        elif cl == "low":
            rename_map[c] = "Low"
        elif cl == "close":
            rename_map[c] = "Close"
        elif cl == "volume":
            rename_map[c] = "Volume"
    df = df.rename(columns=rename_map)

    required = {"Timestamp", "Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input missing required columns: {missing}")

    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    df = df.sort_values("Timestamp").reset_index(drop=True)
    return df


def _split_sessions(df: pd.DataFrame) -> list:
    """
    Split the historical frame into (session_date, session_df) tuples.
    A session is a single calendar date containing intraday 1-min rows.
    """
    if df.empty:
        return []

    session_dates = df["Timestamp"].dt.date.unique()
    sessions = []
    for sd in sorted(session_dates):
        mask = df["Timestamp"].dt.date == sd
        sdf = df.loc[mask].copy().reset_index(drop=True)
        if len(sdf) >= 14:
            sessions.append((sd, sdf))
    return sessions


def _intraday_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows strictly inside the 09:15–15:29 IST cash window."""
    t = df["Timestamp"].dt.time
    mask = (t >= MARKET_OPEN_IST) & (t <= MARKET_CLOSE_IST)
    return df.loc[mask].copy().reset_index(drop=True)


def run_backtest(
    source: Union[str, pd.DataFrame],
    symbol: str = "UNKNOWN",
    total_capital: float = 10017.0,
    working_capital_pct: float = 0.50,
    daily_loss_limit_pct: float = 0.02,
    risk_per_trade_pct: float = 0.01,
    stop_loss_pct: float = 0.005,
    reward_to_risk: float = 2.0,
    max_tranches: int = 3,
    breakeven_trigger_pct: float = 0.0050,
    csv_log_path: Optional[str] = None,
) -> BacktestResult:
    """
    Run a full vector-friendly backtest over historical 1-min OHLCV.

    Parameters
    ----------
    source : DataFrame or str
        Either a DataFrame (with timestamp/open/high/low/close/volume),
        or a path to a CSV file with equivalent columns.
    symbol : str
        Instrument name used for logging / reporting.
    total_capital, working_capital_pct, daily_loss_limit_pct,
    risk_per_trade_pct, stop_loss_pct, reward_to_risk, max_tranches
        Passed directly to PaperTrader (same parameters as the live bot).
    breakeven_trigger_pct
        Passed directly to PaperTrader active-trade management.
    csv_log_path : str, optional
        Override persistent `trades.csv` output path.

    Returns
    -------
    BacktestResult
        DataClass with trades list, equity curve DataFrame, and
        formatted institutional summary table (.summary_table).
    """
    raw_df = _load_ohlcv(source)
    sessions = _split_sessions(raw_df)

    if not sessions:
        logging.warning("No valid sessions with ≥ 14 candles to backtest.")
        return BacktestResult(symbol=symbol, total_capital=total_capital)

    if csv_log_path is None:
        base = os.path.dirname(os.path.abspath(__file__))
        csv_log_path = os.path.join(base, "trades.csv")

    if os.path.exists(csv_log_path):
        os.remove(csv_log_path)

    trader = PaperTrader(
        total_capital=total_capital,
        working_capital_pct=working_capital_pct,
        daily_loss_limit_pct=daily_loss_limit_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        stop_loss_pct=stop_loss_pct,
        reward_to_risk=reward_to_risk,
        max_tranches=max_tranches,
        csv_log_path=csv_log_path,
        breakeven_trigger_pct=breakeven_trigger_pct,
    )

    equity_points = []
    all_trade_rows = []

    # ── Session Loop ──────────────────────────────────────────────────
    for sidx, (session_date, sdf) in enumerate(sessions, start=1):
        sdf = _intraday_filter(sdf)
        if sdf.empty:
            continue

        logging.info(
            f"[SESSION {sidx}/{len(sessions)}]  Date: {session_date}  |  "
            f"Candles: {len(sdf)}  |  Processing..."
        )

        sig_df = generate_vwap_signal(sdf)

        # ── Intra-session candle-by-candle simulation ──────────────
        for _, row in sig_df.iterrows():
            row_ts = row["Timestamp"]
            ts = row_ts.to_pydatetime() if hasattr(row_ts, "to_pydatetime") else pd.Timestamp(row_ts).to_pydatetime()

            c_open  = float(row["Open"])
            c_high  = float(row["High"])
            c_low   = float(row["Low"])
            c_close = float(row["Close"])
            vwap    = float(row["VWAP"]) if not pd.isna(row["VWAP"]) else None
            atr14   = float(row["ATR_14"]) if not pd.isna(row["ATR_14"]) else None
            signal  = bool(row["Buy_Signal"])

            trader.check_day_reset(ts)

            # ── A. EOD square-off @ 15:20 IST ────────────────────
            if ts.time() >= EOD_SQUAREOFF_IST and trader.has_open_position:
                closed = trader.square_off_all_positions(
                    reason="15:20 IST EOD Square-Off",
                    latest_price=c_close,
                    timestamp=ts,
                )
                if closed is not None:
                    all_trade_rows.append(closed)
                continue

            # ── B. Price-path simulation (Open → Low/High → Close) ─
            price_path = [("OPEN", c_open), ("LOW", c_low), ("HIGH", c_high)]
            for _, px in price_path:
                closed = trader.check_exit(live_price=px, timestamp=ts)
                if closed is not None:
                    all_trade_rows.append(closed)
                    break

            trader.check_exit(live_price=c_close, timestamp=ts)

            t_closed = trader.notify_candle_close(timestamp=ts)
            if t_closed is not None:
                all_trade_rows.append(t_closed)

            # ── D. Signal → entry ─────────────────────────────────
            if signal and vwap is not None and atr14 is not None and not trader.is_halted:
                payload = {
                    "VWAP": vwap,
                    "Close": c_close,
                    "symbol": symbol,
                }
                trader.execute_trade(signal_data=payload, timestamp=ts)

        # ── Session end — force close any remaining (edge case past 15:20) ──
        last_ts_raw = sdf["Timestamp"].iloc[-1]
        last_ts_dt = (
            last_ts_raw.to_pydatetime()
            if hasattr(last_ts_raw, "to_pydatetime")
            else pd.Timestamp(last_ts_raw).to_pydatetime()
        )
        if trader.has_open_position:
            final_px = float(sdf["Close"].iloc[-1])
            closed = trader.square_off_all_positions(
                reason=f"Session Close {session_date}",
                latest_price=final_px,
                timestamp=last_ts_dt,
            )
            if closed is not None:
                all_trade_rows.append(closed)

        equity_points.append({
            "Timestamp": last_ts_dt,
            "Session_Date": session_date,
            "Working_Capital": trader.working_capital,
            "Backup_Capital": trader.backup_capital,
            "Total_Capital": trader.working_capital + trader.backup_capital,
            "Session_Daily_PnL": trader.daily_pnl,
        })

    # ── Build Equity Curve DataFrame ───────────────────────────────────
    eq = pd.DataFrame(equity_points)
    if not eq.empty:
        eq.set_index("Timestamp", inplace=True)
        eq["Net_PnL"] = eq["Total_Capital"] - total_capital

    # ── Compute Performance Metrics ────────────────────────────────────
    n_trades = len(all_trade_rows)
    wins = [t for t in all_trade_rows if float(t.get("net_pnl", 0.0)) > 0.0]
    losses = [t for t in all_trade_rows if float(t.get("net_pnl", 0.0)) <= 0.0]
    n_wins = len(wins)
    win_rate = (n_wins / n_trades * 100.0) if n_trades else 0.0

    gross_win = sum(float(t.get("net_pnl", 0.0)) for t in wins)
    gross_loss_abs = abs(sum(float(t.get("net_pnl", 0.0)) for t in losses))
    profit_factor = (
        gross_win / gross_loss_abs if gross_loss_abs > 0
        else (float("inf") if gross_win > 0 else 0.0)
    )

    net_pnl_total = sum(float(t.get("net_pnl", 0.0)) for t in all_trade_rows)
    net_roi_pct = (net_pnl_total / total_capital) * 100.0 if total_capital else 0.0
    net_expectancy = (net_pnl_total / n_trades) if n_trades else 0.0
    avg_hold_mins = (
        float(np.mean([t.get("hold_duration_mins", 0.0) for t in all_trade_rows]))
        if n_trades else 0.0
    )

    max_dd_inr = 0.0
    max_dd_pct = 0.0
    if not eq.empty and "Total_Capital" in eq.columns:
        running_peak = eq["Total_Capital"].cummax()
        dd_inr = running_peak - eq["Total_Capital"]
        dd_pct = (dd_inr / running_peak) * 100.0
        max_dd_inr = float(dd_inr.max())
        max_dd_pct = float(dd_pct.max())

    result = BacktestResult(
        symbol=symbol,
        total_capital=total_capital,
        equity_curve=eq,
        trades=all_trade_rows,
        total_trades=n_trades,
        win_rate_pct=win_rate,
        profit_factor=profit_factor,
        max_drawdown_inr=max_dd_inr,
        max_drawdown_pct=max_dd_pct,
        avg_hold_duration_mins=avg_hold_mins,
        net_expectancy_per_trade=net_expectancy,
        net_pnl_total=net_pnl_total,
        net_roi_pct=net_roi_pct,
    )

    logging.info(result.summary_table)

    return result


# ────────────────────────────────────────────────────────────────────────
#  HISTORICAL DATA HARNESS (Angel One API -> yfinance -> Synthetic)
# ────────────────────────────────────────────────────────────────────────

SYMBOL_TOKEN_MAP = {
    "M&M": "2031",
    "TATASTEEL": "3499",
    "TATAMOTORS": "3456",
    "ITC": "1660",
    "COALINDIA": "20374",
    "RELIANCE": "2885",
    "SBIN": "3045",
}

BASE_PRICES = {
    "M&M": 2500.0,
    "TATASTEEL": 150.0,
    "TATAMOTORS": 980.0,
    "ITC": 490.0,
    "COALINDIA": 480.0,
}


def _generate_synthetic_historical_data(symbol: str = "M&M", days: int = 5) -> pd.DataFrame:
    """Generate high-fidelity synthetic 1-minute OHLCV sessions for offline backtesting."""
    base_price = BASE_PRICES.get(symbol.upper(), 500.0)
    records = []

    start_date = date.today() - timedelta(days=days * 2)
    session_count = 0
    curr_date = start_date

    while session_count < days:
        if curr_date.weekday() < 5:  # Monday to Friday
            # Generate 09:15 to 15:29 (375 bars)
            session_start = datetime.combine(curr_date, MARKET_OPEN_IST)
            px = base_price * (1.0 + (session_count * 0.005))

            for m in range(375):
                ts = session_start + timedelta(minutes=m)
                # Introduce realistic intraday volatility and VWAP pullback setups
                noise = np.sin(m / 15.0) * (base_price * 0.002) + np.random.normal(0, base_price * 0.001)
                trend = (m / 375.0) * (base_price * 0.008)
                bar_close = round(px + trend + noise, 2)
                bar_open = round(bar_close - np.random.normal(0, base_price * 0.0005), 2)
                bar_high = round(max(bar_open, bar_close) + abs(np.random.normal(0, base_price * 0.0008)), 2)
                bar_low = round(min(bar_open, bar_close) - abs(np.random.normal(0, base_price * 0.0008)), 2)
                bar_volume = int(np.random.uniform(500, 3000))

                records.append({
                    "Timestamp": ts,
                    "Open": bar_open,
                    "High": bar_high,
                    "Low": bar_low,
                    "Close": bar_close,
                    "Volume": bar_volume,
                })
            session_count += 1
        curr_date += timedelta(days=1)

    df = pd.DataFrame(records)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df


def fetch_historical_candles(
    symbol: str = "M&M",
    days: int = 5,
    interval: str = "ONE_MINUTE",
    exchange: str = "NSE",
) -> pd.DataFrame:
    """
    Fetch 1-minute historical OHLCV data using Angel One SmartAPI,
    falling back to yfinance, and falling back to high-fidelity synthetic data.
    """
    symbol_clean = symbol.upper().replace(".NS", "")
    token = SYMBOL_TOKEN_MAP.get(symbol_clean)

    # ── Attempt 1: Angel One SmartAPI Historical Data ──────────────
    api_key = os.getenv("BROKER_API_KEY")
    client_code = os.getenv("BROKER_CLIENT_ID") or os.getenv("BROKER_CLIENT_CODE")
    client_pin = os.getenv("BROKER_PIN") or os.getenv("BROKER_PASSWORD")
    totp_secret = os.getenv("BROKER_TOTP_SECRET")

    if api_key and client_code and client_pin and totp_secret and token:
        try:
            import pyotp
            from SmartApi.smartConnect import SmartConnect

            logging.info(f"Authenticating with Angel One SmartAPI to fetch historical {symbol_clean} ({interval})...")
            smart_api = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_secret).now()
            login_data = smart_api.generateSession(client_code, client_pin, totp)
            if isinstance(login_data, dict) and login_data.get("status"):
                now = datetime.now()
                from_dt = now - timedelta(days=days)
                from_str = from_dt.strftime("%Y-%m-%d 09:15")
                to_str = now.strftime("%Y-%m-%d 15:30")

                param = {
                    "exchange": exchange,
                    "symboltoken": token,
                    "interval": interval,
                    "fromdate": from_str,
                    "todate": to_str,
                }
                res = smart_api.getCandleData(param)
                if isinstance(res, dict) and res.get("status") and res.get("data"):
                    candles = res["data"]
                    df = pd.DataFrame(candles, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
                    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
                    logging.info(f"Successfully fetched {len(df)} historical candles from Angel One SmartAPI for {symbol_clean}.")
                    return df
        except Exception as exc:
            logging.warning(f"Angel One Historical API fetch failed: {exc}. Trying fallback...")

    # ── Attempt 2: yfinance fallback ──────────────────────────────
    try:
        import yfinance as yf
        ticker = f"{symbol_clean}.NS"
        logging.info(f"Attempting to download 1-minute historical data for {ticker} via yfinance...")
        data = yf.download(ticker, period=f"{min(days, 7)}d", interval="1m", progress=False)
        if not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]
            data = data.reset_index()
            rename_map = {}
            for col in data.columns:
                cl = col.lower()
                if "time" in cl or "date" in cl:
                    rename_map[col] = "Timestamp"
                elif cl == "open":
                    rename_map[col] = "Open"
                elif cl == "high":
                    rename_map[col] = "High"
                elif cl == "low":
                    rename_map[col] = "Low"
                elif cl == "close":
                    rename_map[col] = "Close"
                elif cl == "volume":
                    rename_map[col] = "Volume"
            data = data.rename(columns=rename_map)
            data["Timestamp"] = pd.to_datetime(data["Timestamp"])
            logging.info(f"Successfully fetched {len(data)} candles via yfinance for {ticker}.")
            return data[["Timestamp", "Open", "High", "Low", "Close", "Volume"]]
    except Exception as exc:
        logging.debug(f"yfinance download not available: {exc}.")

    # ── Attempt 3: High-fidelity synthetic session generator ──────
    logging.info(f"Generating high-fidelity historical benchmark candles for {symbol_clean} ({days} sessions)...")
    return _generate_synthetic_historical_data(symbol=symbol_clean, days=days)


def run_historical_backtest(
    symbol: str = "M&M",
    days: int = 5,
    total_capital: float = 10017.0,
    source: Optional[Union[str, pd.DataFrame]] = None,
) -> BacktestResult:
    """
    Fetch historical data (or load source) and execute a full historical backtest.
    """
    if source is not None:
        df_or_path = source
    else:
        df_or_path = fetch_historical_candles(symbol=symbol, days=days)

    return run_backtest(source=df_or_path, symbol=symbol, total_capital=total_capital)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    arg1 = sys.argv[1] if len(sys.argv) >= 2 else "M&M"
    arg2 = float(sys.argv[2]) if len(sys.argv) >= 3 else 10017.0
    arg3 = int(sys.argv[3]) if len(sys.argv) >= 4 else 5

    if arg1.endswith(".csv") and os.path.exists(arg1):
        logging.info(f"Running historical backtest from CSV file: {arg1}")
        run_backtest(source=arg1, symbol="CSV_FEED", total_capital=arg2)
    else:
        symbol_target = arg1.upper()
        logging.info(f"Running historical backtest harness for {symbol_target} (Capital: ₹{arg2:,.2f}, Days: {arg3})")
        run_historical_backtest(symbol=symbol_target, days=arg3, total_capital=arg2)
