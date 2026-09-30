"""Explicit research replay using the frozen strategy and separate simulated accounting.

Requires authoritative instrument metadata and dataset provenance. Candle execution
assumptions are recorded; results do not establish live profitability.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, time as dtime
from typing import Optional, Union
from pathlib import Path

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


def run_backtest(source,symbol='UNKNOWN',total_capital=20000.,working_capital_pct=.5,
    daily_loss_limit_pct=.01,risk_per_trade_pct=.01,stop_loss_pct=.005,reward_to_risk=2.,max_tranches=1,
    breakeven_trigger_pct=.005,csv_log_path=None,*,instrument=None,provenance=None,variant=None):
    """Research replay with explicit data provenance and immutable instrument metadata."""
    from replay_engine import replay
    from execution_safety import SafetyError
    if instrument is None or not provenance:raise SafetyError('REPLAY_INSTRUMENT_AND_PROVENANCE_REQUIRED')
    if (working_capital_pct,daily_loss_limit_pct,risk_per_trade_pct,stop_loss_pct,reward_to_risk,max_tranches,breakeven_trigger_pct)!=(.5,.01,.01,.005,2.,1,.005):
        raise SafetyError('LEGACY_PARAMETER_OVERRIDES_FORBIDDEN')
    output=Path(csv_log_path).parent if csv_log_path else Path(__file__).parent/'data'/'backtest'
    trades,equity,metadata=replay(_load_ohlcv(source),instrument,provenance,output,total_capital,variant)
    result=BacktestResult(symbol=symbol,total_capital=total_capital)
    result.trades=trades
    from replay_engine import research_metrics
    metrics=research_metrics(trades)
    result.total_trades=len(trades)
    result.win_rate_pct=(metrics['win_rate'] or 0)*100
    result.profit_factor=metrics['profit_factor'] if metrics['profit_factor'] is not None else float('inf') if any(t['net_pnl']>0 for t in trades) else 0.
    result.max_drawdown_inr=metrics['maximum_drawdown']
    result.max_drawdown_pct=result.max_drawdown_inr/total_capital*100
    result.avg_hold_duration_mins=sum(t['hold_duration_minutes'] for t in trades)/len(trades) if trades else 0.
    result.net_expectancy_per_trade=metrics['net_expectancy'] or 0.
    result.net_pnl_total=sum(t['net_pnl'] for t in trades)
    result.net_roi_pct=result.net_pnl_total/total_capital*100
    if not equity.empty:result.equity_curve=equity.set_index('Timestamp')
    result.research_metadata=metadata
    return result




def fetch_historical_candles(
    symbol: str = "M&M",
    days: int = 5,
    interval: str = "ONE_MINUTE",
    exchange: str = "NSE",
    *, instrument=None,
) -> pd.DataFrame:
    """
    Fetch 1-minute historical OHLCV data using Angel One SmartAPI,
    with an explicit authoritative mapping and provider provenance. No synthetic fallback.
    """
    symbol_clean = symbol.upper().replace(".NS", "")
    from execution_safety import InstrumentIdentity, SafetyError
    from security_logging import install_broker_secret_filter
    install_broker_secret_filter()
    if not isinstance(instrument,InstrumentIdentity):raise SafetyError('HISTORICAL_INSTRUMENT_REQUIRED')
    instrument.validate(symbol_clean,exchange=exchange)
    token = instrument.token

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
                    df.attrs['provenance']='ANGEL_ONE_SMARTAPI_ONE_MINUTE_OHLCV'
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
            result=data[["Timestamp", "Open", "High", "Low", "Close", "Volume"]]
            result.attrs['provenance']='YFINANCE_ONE_MINUTE_OHLCV'
            return result
    except Exception as exc:
        logging.debug(f"yfinance download not available: {exc}.")

    raise RuntimeError('REAL_HISTORICAL_DATA_UNAVAILABLE: synthetic data is never substituted')


def run_historical_backtest(
    symbol: str = "M&M",
    days: int = 5,
    total_capital: float = 20000.0,
    source: Optional[Union[str, pd.DataFrame]] = None,
    *, instrument=None, provenance=None,
) -> BacktestResult:
    """
    Fetch historical data (or load source) and execute a full historical backtest.
    """
    from execution_safety import SafetyError
    if instrument is None or (source is not None and not provenance):
        raise SafetyError('REPLAY_INSTRUMENT_AND_PROVENANCE_REQUIRED')
    if source is not None:
        df_or_path = source
    else:
        df_or_path = fetch_historical_candles(symbol=symbol, days=days,instrument=instrument)
        provenance=df_or_path.attrs['provenance']

    return run_backtest(source=df_or_path,symbol=symbol,total_capital=total_capital,instrument=instrument,provenance=provenance)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import argparse
    from instrument_registry import InstrumentRegistry
    from market_schedule import to_ist
    from replay_engine import ResearchVariant
    parser=argparse.ArgumentParser(description='Offline research replay; no live activation or synthetic fallback.')
    parser.add_argument('--source',required=True,help='One-minute OHLCV CSV')
    parser.add_argument('--symbol',required=True)
    parser.add_argument('--master',required=True,help='Archived broker master/eligibility envelope')
    parser.add_argument('--provenance',required=True,help='Actual dataset provider; fixtures must use SYNTHETIC_TEST_FIXTURE')
    parser.add_argument('--output',default='data/replay')
    parser.add_argument('--research-timeframe',type=int,default=1)
    args=parser.parse_args()
    import json
    envelope=json.loads(Path(args.master).read_text())
    mapping=InstrumentRegistry(envelope['records'],datetime.fromisoformat(envelope['source_timestamp']),
        envelope['intraday_symbols'],envelope.get('restricted_symbols',[])).resolve(args.symbol)
    result=run_backtest(args.source,args.symbol,instrument=mapping,provenance=args.provenance,
        csv_log_path=str(Path(args.output)/'trades.csv'),variant=ResearchVariant('research',args.research_timeframe))
    print('RESEARCH ONLY — see recorded execution assumptions and provenance.')
    print(result.summary_table)
    print(result.research_metadata['output_dir'])
