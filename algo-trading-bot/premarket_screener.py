"""
premarket_screener.py — Morning Market Screener & ATR% Filter Pipeline
========================================================================
Implements a reproducible, production-grade pre-market screener for NSE Cash Equities.
Evaluates configured candidate universe on the most recent completed market session's
1-minute historical data to dynamically select high-volatility, liquid stocks for intraday trading.

Architectural Guarantees:
1. Dynamic Screening: The winner is NEVER hardcoded.
2. Canonical ATR: Uses signal_brain.compute_atr() for 100% mathematical consistency.
3. Session Resolution: Resolves previous completed session via exchange calendar (skips weekends/holidays).
4. Rate-Limit & Error Protection: Sequential pacing, retry with exponential backoff & jitter.
5. Fail-Safe Zero Qualification: If qualified_candidates == [], trading_day_status = NO_TRADE (sits out).
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import (
    CANDIDATE_UNIVERSE,
    EXCLUSION_LIST,
    SCREEN_API_BACKOFF_BASE,
    SCREEN_API_MAX_RETRIES,
    SCREEN_API_REQUEST_INTERVAL,
    SCREEN_ATR_PERIOD,
    SCREEN_EMA_FAST_PERIOD,
    SCREEN_EMA_SLOW_PERIOD,
    SCREEN_MAX_LTP,
    SCREEN_MAX_SPREAD_PCT,
    SCREEN_MIN_ATR_PCT,
    SCREEN_MIN_CANDLE_COUNT,
    SCREEN_MIN_DAILY_VOLUME,
    SCREEN_MIN_LTP,
    SCREEN_TOP_N,
)
from market_schedule import BaseMarketSchedule, get_market_schedule
from signal_brain import compute_atr

logger = logging.getLogger(__name__)


# ── REJECTION REASONS ─────────────────────────────────────────
class RejectionReason:
    PRICE_BELOW_MIN = "PRICE_BELOW_MIN"
    PRICE_ABOVE_MAX = "PRICE_ABOVE_MAX"
    ATR_BELOW_MIN = "ATR_BELOW_MIN"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    DEPTH_INSUFFICIENT = "DEPTH_INSUFFICIENT"
    EMA_TREND_INVALID = "EMA_TREND_INVALID"
    VOLUME_INSUFFICIENT = "VOLUME_INSUFFICIENT"
    EXCLUDED_SYMBOL = "EXCLUDED_SYMBOL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE_DATA = "STALE_DATA"
    INVALID_QUOTE = "INVALID_QUOTE"
    ATR_CALCULATION_ERROR = "ATR_CALCULATION_ERROR"
    BROKER_DATA_ERROR = "BROKER_DATA_ERROR"


@dataclass
class CandidateDiagnostic:
    symbol: str
    trading_symbol: str
    token: str
    exchange: str
    ltp: float
    atr: float
    atr_pct: float
    spread_pct: float
    depth_status: str
    ema_fast: float
    ema_slow: float
    trend: str
    total_volume: int
    candle_count: int
    price_ok: bool
    atr_ok: bool
    spread_ok: bool
    depth_ok: bool
    ema_ok: bool
    volume_ok: bool
    exclusion_ok: bool
    data_ok: bool
    qualified: bool
    rejection_reasons: List[str] = field(default_factory=list)
    instrument: Any = None
    opportunity_score: float = 0.0
    opportunity_components: dict = field(default_factory=dict)
    volume_profiles: list = field(default_factory=list)


@dataclass
class PremarketScreenResult:
    session_date: date
    total_candidates: int
    qualified_candidates: List[CandidateDiagnostic]
    rejected_candidates: List[CandidateDiagnostic]
    selected_candidate: Optional[CandidateDiagnostic]
    trading_day_status: str  # "ACTIVE" or "NO_TRADE"
    diagnostics: List[CandidateDiagnostic]
    watchlist: List[CandidateDiagnostic] = field(default_factory=list)


def find_previous_completed_market_session(
    reference_date: Optional[date] = None,
    schedule: Optional[BaseMarketSchedule] = None,
) -> date:
    """
    Finds the most recent completed market trading session before reference_date.
    Uses exchange calendar logic (skips weekends and market holidays).
    """
    _sched = schedule or get_market_schedule("NSE")
    ref = reference_date or _sched.localize().date()

    check_day = ref - timedelta(days=1)
    while not _sched.is_trading_day(check_day):
        check_day -= timedelta(days=1)
    return check_day


def validate_candle_data(
    df: pd.DataFrame,
    min_candles: int = SCREEN_MIN_CANDLE_COUNT,
) -> Tuple[bool, Optional[str]]:
    """
    Validates OHLCV completeness, chronology, price integrity, and candle count.
    """
    if df is None or df.empty:
        return False, RejectionReason.INSUFFICIENT_DATA

    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    if not required_cols.issubset(df.columns):
        return False, RejectionReason.INSUFFICIENT_DATA

    if len(df) < min_candles:
        return False, RejectionReason.INSUFFICIENT_DATA

    # Price integrity
    highs = df["High"].astype(float)
    lows = df["Low"].astype(float)
    opens = df["Open"].astype(float)
    closes = df["Close"].astype(float)
    vols = df["Volume"].astype(float)

    if (highs <= 0).any() or (lows <= 0).any() or (opens <= 0).any() or (closes <= 0).any():
        return False, RejectionReason.INVALID_QUOTE

    if (highs < lows).any() or (highs < opens).any() or (highs < closes).any():
        return False, RejectionReason.INVALID_QUOTE

    if (lows > opens).any() or (lows > closes).any():
        return False, RejectionReason.INVALID_QUOTE

    if (vols < 0).any() or vols.sum() <= 0:
        return False, RejectionReason.INVALID_QUOTE

    # Timestamp monotonicity
    if "Timestamp" in df.columns:
        ts = pd.to_datetime(df["Timestamp"])
        if not ts.is_monotonic_increasing:
            return False, RejectionReason.STALE_DATA

    return True, None


def fetch_historical_session_candles(
    smart_api: Any,
    symbol: str,
    token: str,
    exchange: str,
    session_date: date,
    interval: str = "ONE_MINUTE",
    max_retries: int = SCREEN_API_MAX_RETRIES,
    backoff_base: float = SCREEN_API_BACKOFF_BASE,
) -> Optional[pd.DataFrame]:
    """
    Fetches 1-minute historical data for the completed session using SmartAPI.
    Implements rate-limiting backoff, jitter, and error isolation.
    """
    if smart_api is None:
        logger.warning(f"[SCREENER API] No active smart_api session to fetch candles for {symbol}.")
        return None

    from_str = f"{session_date.strftime('%Y-%m-%d')} 09:15"
    to_str = f"{session_date.strftime('%Y-%m-%d')} 15:30"

    param = {
        "exchange": exchange,
        "symboltoken": str(token),
        "interval": interval,
        "fromdate": from_str,
        "todate": to_str,
    }

    for attempt in range(max_retries):
        try:
            res = smart_api.getCandleData(param)
            if isinstance(res, dict) and res.get("status") and res.get("data"):
                candles = res["data"]
                df = pd.DataFrame(
                    candles,
                    columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"],
                )
                df["Timestamp"] = pd.to_datetime(df["Timestamp"])
                logger.info(
                    f"[SCREENER API ✅] Fetched {len(df)} candles for {symbol} ({session_date})."
                )
                return df
            else:
                msg = res.get("message", "Empty response") if isinstance(res, dict) else str(res)
                logger.warning(
                    f"[SCREENER API RETRY] {symbol} fetch attempt {attempt + 1}/{max_retries} failed: {msg}"
                )
        except Exception as exc:
            logger.warning(
                f"[SCREENER API RETRY] {symbol} fetch attempt {attempt + 1}/{max_retries} exception: {exc}"
            )

        if attempt < max_retries - 1:
            delay = backoff_base * (2**attempt) + random.uniform(0.1, 0.3)
            time.sleep(delay)

    logger.error(
        f"[SCREENER API FAILED] Exhausted retries fetching historical data for {symbol} (Token: {token})."
    )
    return None


def evaluate_candidate(
    candidate: Dict[str, Any],
    df: Optional[pd.DataFrame] = None,
    spread_pct: Optional[float] = None,
    depth_available: bool = True,
    min_ltp: float = SCREEN_MIN_LTP,
    max_ltp: float = SCREEN_MAX_LTP,
    min_atr_pct: float = SCREEN_MIN_ATR_PCT,
    max_spread_pct: float = SCREEN_MAX_SPREAD_PCT,
    min_daily_volume: int = SCREEN_MIN_DAILY_VOLUME,
    atr_period: int = SCREEN_ATR_PERIOD,
    ema_fast_period: int = SCREEN_EMA_FAST_PERIOD,
    ema_slow_period: int = SCREEN_EMA_SLOW_PERIOD,
    min_candle_count: int = SCREEN_MIN_CANDLE_COUNT,
    exclusion_list: Optional[List[str]] = None,
) -> CandidateDiagnostic:
    """
    Evaluates a single instrument against all pre-market qualification rules.
    Produces a structured CandidateDiagnostic result.
    """
    symbol = candidate.get("symbol", "")
    trading_symbol = candidate.get("trading_symbol", f"{symbol}-EQ")
    token = candidate.get("token", "")
    exchange = candidate.get("exchange", "NSE")
    exclusions = exclusion_list if exclusion_list is not None else EXCLUSION_LIST

    rejection_reasons: List[str] = []

    # 1. Exclusion check
    exclusion_ok = symbol not in exclusions and trading_symbol not in exclusions
    if not exclusion_ok:
        rejection_reasons.append(RejectionReason.EXCLUDED_SYMBOL)

    # 2. Data sufficiency check
    data_ok, data_err = validate_candle_data(df, min_candles=min_candle_count)
    if not data_ok:
        rejection_reasons.append(data_err or RejectionReason.INSUFFICIENT_DATA)
        return CandidateDiagnostic(
            symbol=symbol,
            trading_symbol=trading_symbol,
            token=token,
            exchange=exchange,
            ltp=0.0,
            atr=0.0,
            atr_pct=0.0,
            spread_pct=spread_pct if spread_pct is not None else 0.0,
            depth_status="UNAVAILABLE" if not depth_available else "AVAILABLE",
            ema_fast=0.0,
            ema_slow=0.0,
            trend="UNKNOWN",
            total_volume=0,
            candle_count=len(df) if df is not None else 0,
            price_ok=False,
            atr_ok=False,
            spread_ok=False,
            depth_ok=depth_available,
            ema_ok=False,
            volume_ok=False,
            exclusion_ok=exclusion_ok,
            data_ok=False,
            qualified=False,
            rejection_reasons=rejection_reasons,
        )

    # Calculate indicators
    try:
        atr_series = compute_atr(df, period=atr_period)
        latest_atr = float(atr_series.iloc[-1])
        latest_ltp = float(df["Close"].iloc[-1])
        total_volume = int(df["Volume"].astype(float).sum())
    except Exception as e:
        logger.error(f"[ATR ERROR] Calculation failed for {symbol}: {e}")
        rejection_reasons.append(RejectionReason.ATR_CALCULATION_ERROR)
        latest_atr = 0.0
        latest_ltp = float(df["Close"].iloc[-1]) if not df.empty else 0.0
        total_volume = 0

    # ATR% = (ATR / LTP) * 100
    atr_pct = (latest_atr / latest_ltp) * 100.0 if latest_ltp > 0 else 0.0

    # Calculate EMAs
    try:
        close_series = df["Close"].astype(float)
        ema_fast = float(close_series.ewm(span=ema_fast_period, adjust=False).mean().iloc[-1])
        ema_slow = float(close_series.ewm(span=ema_slow_period, adjust=False).mean().iloc[-1])
        trend = "BULLISH" if ema_fast >= ema_slow else "BEARISH"
    except Exception:
        ema_fast = float("nan")
        ema_slow = float("nan")
        trend = "UNKNOWN"

    # Evaluate filters
    price_ok = min_ltp <= latest_ltp <= max_ltp
    if not price_ok:
        if latest_ltp < min_ltp:
            rejection_reasons.append(RejectionReason.PRICE_BELOW_MIN)
        else:
            rejection_reasons.append(RejectionReason.PRICE_ABOVE_MAX)

    # ATR threshold: min_atr_pct configured as e.g. 0.0040 (0.40%)
    atr_threshold_pct = min_atr_pct * 100.0 if min_atr_pct < 0.1 else min_atr_pct
    atr_ok = atr_pct >= atr_threshold_pct
    if not atr_ok:
        rejection_reasons.append(RejectionReason.ATR_BELOW_MIN)

    # Spread filter: normalized percentage spread <= max_spread_pct (e.g. 0.15%)
    max_spread_val = max_spread_pct * 100.0 if max_spread_pct < 0.1 else max_spread_pct
    actual_spread_pct = spread_pct if spread_pct is not None else 0.05  # Default conservative 0.05% if depth tick unpopulated
    spread_ok = actual_spread_pct <= max_spread_val
    if not spread_ok:
        rejection_reasons.append(RejectionReason.SPREAD_TOO_WIDE)

    # Depth requirement
    depth_ok = bool(depth_available)
    if not depth_ok:
        rejection_reasons.append(RejectionReason.DEPTH_INSUFFICIENT)

    # Volume filter
    volume_ok = total_volume >= min_daily_volume
    if not volume_ok:
        rejection_reasons.append(RejectionReason.VOLUME_INSUFFICIENT)

    # Selection is direction-neutral; frozen strategy determines LONG/SHORT.
    ema_ok = not math.isnan(ema_fast) and not math.isnan(ema_slow)
    if not ema_ok:
        rejection_reasons.append(RejectionReason.EMA_TREND_INVALID)

    qualified = (
        price_ok
        and atr_ok
        and spread_ok
        and depth_ok
        and volume_ok
        and ema_ok
        and exclusion_ok
        and data_ok
    )

    return CandidateDiagnostic(
        symbol=symbol,
        trading_symbol=trading_symbol,
        token=token,
        exchange=exchange,
        ltp=latest_ltp,
        atr=latest_atr,
        atr_pct=atr_pct,
        spread_pct=actual_spread_pct,
        depth_status="AVAILABLE" if depth_ok else "UNAVAILABLE",
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        trend=trend,
        total_volume=total_volume,
        candle_count=len(df),
        price_ok=price_ok,
        atr_ok=atr_ok,
        spread_ok=spread_ok,
        depth_ok=depth_ok,
        ema_ok=ema_ok,
        volume_ok=volume_ok,
        exclusion_ok=exclusion_ok,
        data_ok=data_ok,
        qualified=qualified,
        rejection_reasons=rejection_reasons,
    )


def run_premarket_screener(
    smart_api: Optional[Any] = None,
    schedule: Optional[BaseMarketSchedule] = None,
    universe: Optional[List[Dict[str, Any]]] = None,
    session_date: Optional[date] = None,
    top_n: int = SCREEN_TOP_N,
    data_fetcher: Optional[Callable[[Dict[str, Any], date], Optional[pd.DataFrame]]] = None,
    pacing_interval: float = SCREEN_API_REQUEST_INTERVAL,
) -> PremarketScreenResult:
    """
    Executes the pre-market screening pipeline across the configured candidate universe.
    """
    _sched = schedule or get_market_schedule("NSE")
    _universe = universe if universe is not None else CANDIDATE_UNIVERSE
    target_session = session_date or find_previous_completed_market_session(schedule=_sched)

    logger.info("=" * 80)
    logger.info("  🚀 PREMARKET SCREEN STARTED")
    logger.info(f"  Target Completed Session : {target_session}")
    logger.info(f"  Candidate Universe Size  : {len(_universe)}")
    logger.info(f"  ATR Threshold Floor      : {SCREEN_MIN_ATR_PCT * 100:.2f}%")
    logger.info(f"  LTP Price Band           : ₹{SCREEN_MIN_LTP:.2f} – ₹{SCREEN_MAX_LTP:.2f}")
    logger.info(f"  Max Spread Allowed       : {SCREEN_MAX_SPREAD_PCT * 100:.2f}%")
    logger.info("=" * 80)

    diagnostics: List[CandidateDiagnostic] = []

    for idx, candidate in enumerate(_universe):
        sym = candidate.get("symbol", "")
        tok = candidate.get("token", "")
        exch = candidate.get("exchange", "NSE")

        logger.info(f"[SCREENING {idx + 1}/{len(_universe)}] Evaluating {sym} (Token: {tok})...")

        # 1. Fetch 1-minute historical data for the completed session
        df: Optional[pd.DataFrame] = None
        if data_fetcher is not None:
            df = data_fetcher(candidate, target_session)
        elif smart_api is not None:
            df = fetch_historical_session_candles(
                smart_api=smart_api,
                symbol=sym,
                token=tok,
                exchange=exch,
                session_date=target_session,
            )

        if df is None:
            diag = CandidateDiagnostic(
                symbol=sym,
                trading_symbol=candidate.get("trading_symbol", f"{sym}-EQ"),
                token=tok,
                exchange=exch,
                ltp=0.0,
                atr=0.0,
                atr_pct=0.0,
                spread_pct=0.0,
                depth_status="UNKNOWN",
                ema_fast=0.0,
                ema_slow=0.0,
                trend="UNKNOWN",
                total_volume=0,
                candle_count=0,
                price_ok=False,
                atr_ok=False,
                spread_ok=False,
                depth_ok=False,
                ema_ok=False,
                volume_ok=False,
                exclusion_ok=sym not in EXCLUSION_LIST,
                data_ok=False,
                qualified=False,
                rejection_reasons=[RejectionReason.BROKER_DATA_ERROR],
            )
        else:
            diag = evaluate_candidate(candidate=candidate, df=df)

        diag.instrument = candidate.get('instrument')
        from opportunity_engine import score_opportunity
        score = score_opportunity(diag.total_volume, diag.spread_pct, 0, diag.atr_pct, reliable=diag.data_ok)
        diag.opportunity_score = score.total
        diag.opportunity_components = score.__dict__
        diag.volume_profiles = list(candidate.get('volume_profiles', []))
        if df is not None and diag.data_ok:
            from opportunity_engine import build_volume_profile
            diag.volume_profiles.append(build_volume_profile(df,target_session))

        diagnostics.append(diag)

        status_icon = "✅ QUALIFIED" if diag.qualified else "❌ REJECTED"
        logger.info(
            f"  {status_icon} | {sym:<12} | LTP: ₹{diag.ltp:<8.2f} | ATR: ₹{diag.atr:<6.2f} | "
            f"ATR%: {diag.atr_pct:>5.2f}% | Vol: {diag.total_volume:>8} | Reasons: {diag.rejection_reasons}"
        )

        # Sequential pacing delay between requests (if making live API calls)
        if pacing_interval > 0 and idx < len(_universe) - 1:
            time.sleep(pacing_interval)

    qualified = [d for d in diagnostics if d.qualified]
    rejected = [d for d in diagnostics if not d.qualified]

    # Explicit deterministic ranking: sort by ATR% descending
    qualified.sort(key=lambda x: (-x.opportunity_score, -x.atr_pct, x.symbol))
    watchlist = qualified[:top_n]

    # Only selected symbols need the extra read-only history calls. Missing sessions
    # leave RVOL unknown; there is no replacement with a full-day volume estimate.
    if smart_api is not None:
        from opportunity_engine import build_volume_profile
        import config
        for selected_candidate in watchlist:
            historical_day=target_session
            for _ in range(config.OPPORTUNITY_RVOL_SESSIONS-1):
                historical_day=find_previous_completed_market_session(historical_day,_sched)
                history=fetch_historical_session_candles(smart_api,selected_candidate.symbol,
                    selected_candidate.token,selected_candidate.exchange,historical_day)
                if history is not None and validate_candle_data(history)[0]:
                    selected_candidate.volume_profiles.append(build_volume_profile(history,historical_day))
                if pacing_interval>0:time.sleep(pacing_interval)

    if watchlist:
        selected = watchlist[0]
        status = "ACTIVE"
        logger.info("=" * 80)
        logger.info(
            f"  🏆 PREMARKET SCREEN COMPLETE — TOP-{len(watchlist)} WATCHLIST SELECTED: "
            f"{[c.trading_symbol for c in watchlist]}"
        )
        for rank_idx, cand in enumerate(watchlist, 1):
            logger.info(
                f"  Rank {rank_idx}: {cand.trading_symbol:<12} (Token: {cand.token}) | "
                f"LTP: ₹{cand.ltp:.2f} | ATR: ₹{cand.atr:.2f} | ATR%: {cand.atr_pct:.3f}%"
            )
        logger.info(f"  Primary Winner (Rank 1) : {selected.trading_symbol}")
        logger.info(f"  Qualified: {len(qualified)}/{len(_universe)}")
        logger.info("=" * 80)
    else:
        watchlist = []
        selected = None
        status = "NO_TRADE"
        logger.warning("=" * 80)
        logger.warning("  ⚠️ PREMARKET SCREEN COMPLETE — NO QUALIFYING SYMBOLS")
        logger.warning(f"  Total Candidates Evaluated : {len(_universe)}")
        logger.warning(f"  Qualified Candidates       : 0")
        logger.warning(f"  Rejected Candidates        : {len(rejected)}")
        logger.warning("  ACTION: SIT OUT — ZERO TRADING FOR THIS SESSION")
        logger.warning("=" * 80)

    return PremarketScreenResult(
        session_date=target_session,
        total_candidates=len(_universe),
        qualified_candidates=qualified,
        rejected_candidates=rejected,
        selected_candidate=selected,
        trading_day_status=status,
        diagnostics=diagnostics,
        watchlist=watchlist,
    )
