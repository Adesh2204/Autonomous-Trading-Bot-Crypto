"""Auditable 12:00 UTC competition snapshots; never submits orders."""
from datetime import datetime, timezone
from decimal import Decimal
import math

from .base_exchange import ExchangeError, decimal
from .competition_market import (
    COMPETITION_MARKET, SCORING_END_MS, SCORING_START_MS, is_scored_phase,
)


class CompetitionSnapshotRecorder:
    def __init__(self, session):
        self.session = session
        self.journal = session.journal

    @staticmethod
    def _day_key(day):
        return "competition_daily_snapshot:" + day

    def _skip(self, day, now_ms, reason):
        key = self._day_key(day)
        record = {
            "status": "SKIPPED",
            "reason": reason,
            "competition_market": COMPETITION_MARKET,
            "observed_at_utc": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
        }
        self.session.execution.entries_paused = True
        self.journal.control(key, record)
        self.journal.event("COMPETITION_SNAPSHOT_SKIPPED", now_ms, **record)
        return record

    def observe(self, now_ms=None):
        """Run from the owner loop. Missing/stale account truth blocks new entries."""
        now_ms = self.session.clock_ms() if now_ms is None else now_ms
        now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
        day = now.date().isoformat()
        if now_ms < SCORING_START_MS:
            return None
        key = self._day_key(day)
        prior = self.journal.control(key)
        if prior is not None:
            # A missed/failed snapshot remains a durable entry pause after restart.
            if prior.get("status") != "RECORDED":
                self.session.execution.entries_paused = True
            return prior

        end_day = datetime.fromtimestamp(SCORING_END_MS / 1000, timezone.utc).date()
        in_snapshot_minute = now.hour == 12 and now.minute == 0
        if now_ms > SCORING_END_MS and not (now.date() == end_day and in_snapshot_minute):
            if now.date() == end_day:
                return self._skip(day, now_ms, "SCORING_END_SNAPSHOT_WINDOW_MISSED")
            return None
        if not in_snapshot_minute:
            if now.hour < 12:
                return None
            return self._skip(day, now_ms, "SNAPSHOT_WINDOW_MISSED")

        try:
            client = self.session.market.client
            api_market = client.api_market
            api_markets=getattr(client,'api_markets',None)
            if (client.api_dex is None or api_market is None or
                    not isinstance(api_markets,dict) or set(api_markets)!={'BTC','EWY'} or
                    api_markets.get('BTC')!=api_market or
                    set(client.markets)!=set(api_markets.values()) or
                    any(not symbol.endswith(':'+base) for base,symbol in api_markets.items())):
                raise ExchangeError("PAS_BTC_MAPPING_UNVERIFIED")

            # Snapshot data comes from a fresh authoritative recovery pass, not
            # from a local simulated ledger or an order-submission response.
            report = self.session.recovery.recover()
            if not report.ready:
                raise ExchangeError("ACCOUNT_RECONCILIATION_NOT_READY")
            state = self.session.recovery.state
            if state.equity is None:
                raise ExchangeError("ACCOUNT_EQUITY_UNAVAILABLE")
            positions = dict(state.positions)
            if any(symbol not in api_markets.values() for symbol in positions):
                raise ExchangeError("UNEXPECTED_INACTIVE_POSITION")
            if len(positions) > 1:
                raise ExchangeError("SINGLE_GLOBAL_POSITION_REQUIRED")
            quotes = {symbol: self.session.market.get_quote(symbol)
                      for symbol in api_markets.values()}
            # Anchor freshness AFTER the reads, never before a fresh response.
            quote_reference_ms = self.session.clock_ms()
            completed = datetime.fromtimestamp(quote_reference_ms / 1000, timezone.utc)
            if completed.date() != now.date() or completed.hour != 12 or completed.minute != 0:
                raise ExchangeError("SNAPSHOT_WINDOW_EXPIRED_DURING_READS")
            for symbol, observed in quotes.items():
                if (observed.symbol != symbol or
                        not 0 <= quote_reference_ms - observed.timestamp_ms <= 5000 or
                        observed.mark_timestamp_ms is None or
                        not 0 <= quote_reference_ms - observed.mark_timestamp_ms <= 60000):
                    raise ExchangeError("SNAPSHOT_MARKET_DATA_STALE")
            quote = quotes[api_market]  # historical BTC fields remain compatible
            position = positions.get(api_market)
            equity = decimal(state.equity.reported_account_value, nonnegative=True)
            unrealized = sum((p.unrealized_pnl for p in positions.values()), Decimal(0))
            exposure = sum((abs(p.quantity) * decimal(quotes[symbol].mark, positive=True)
                            for symbol, p in positions.items()), Decimal(0))
            fills = list(state.fills.values())
            funding_events = list(state.funding.values())
            closed_pnl = [f.closed_pnl for f in fills]
            realized = (sum(closed_pnl, Decimal(0))
                        if all(value is not None for value in closed_pnl) else None)
            fees = sum((f.fee for f in fills), Decimal(0))
            funding = sum((event.cashflow for event in funding_events), Decimal(0))

            history = self.journal.control("competition_daily_snapshot_history") or []
            prior_good = next((item for item in reversed(history) if item.get("status") == "RECORDED"), None)
            previous_equity = decimal(prior_good["equity"], positive=True) if prior_good else None
            daily_return = ((equity - previous_equity) / previous_equity
                            if previous_equity is not None else None)
            returns = [float(item["daily_equity_return"]) for item in history
                       if item.get("status") == "RECORDED" and item.get("daily_equity_return") is not None]
            if daily_return is not None:
                returns.append(float(daily_return))
            daily_volatility = None
            if len(returns) >= 2:
                mean = sum(returns) / len(returns)
                daily_volatility = math.sqrt(sum((value - mean) ** 2 for value in returns) / len(returns))

            peak = self.session.peak_equity
            drawdown = (max(Decimal(0), (peak - equity) / peak)
                        if peak is not None and peak > 0 else Decimal(0))
            snapshot = {
                "status": "RECORDED",
                "scheduled_snapshot_utc": now.replace(minute=0, second=0, microsecond=0).isoformat(),
                "observed_at_utc": datetime.fromtimestamp(quote_reference_ms / 1000, timezone.utc).isoformat(),
                "competition_market": COMPETITION_MARKET,
                "api_dex": client.api_dex,
                "api_market": api_market,
                "api_markets": dict(api_markets),
                "active_positions": {symbol: {"quantity": p.quantity, "unrealized_pnl": p.unrealized_pnl}
                                     for symbol, p in positions.items()},
                "mark_prices": {symbol: q.mark for symbol, q in quotes.items()},
                "collateral_token": client.collateral_token_name,
                "equity": equity,
                "btc_position": ({
                    "quantity": position.quantity,
                    "side": "LONG" if position.quantity > 0 else "SHORT",
                    "entry_price": position.entry_price,
                    "unrealized_pnl": position.unrealized_pnl,
                    "margin_used": position.margin_used,
                    "liquidation_price": position.liquidation_price,
                } if position else {"quantity": Decimal(0), "side": "FLAT"}),
                "btc_mark_price": quote.mark,
                "btc_oracle_price": quote.oracle,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "fees_paid": fees,
                "funding_cashflow": funding,
                "exposure_notional": exposure,
                "daily_equity_return": daily_return,
                "drawdown": drawdown,
                "daily_equity_volatility": daily_volatility,
                "reconciliation_state": "RECONCILED",
                "fills_observed": len(fills),
                "funding_events_observed": len(funding_events),
            }
            self.journal.control(key, snapshot)
            history.append(snapshot)
            self.journal.control("competition_daily_snapshot_history", history[-60:])
            self.journal.event("COMPETITION_DAILY_SNAPSHOT", quote_reference_ms, **snapshot)
            return snapshot
        except Exception as exc:
            return self._skip(day, now_ms, "SNAPSHOT_BLOCKED:" + type(exc).__name__)
