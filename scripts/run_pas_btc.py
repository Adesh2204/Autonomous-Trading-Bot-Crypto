"""Fail-closed PAS BTC/EWY production launcher.

Default mode is read-only. Explicit Testnet order submission requires a current
20-gate certification report, an operator approval, account/API-wallet checks,
an enabled protection policy and the exact Testnet environment.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo-trading-bot"))

from exchange.base_exchange import ExchangeError, decimal
from exchange.competition_market import (
    COMPETITION_MARKET, SCORING_START_MS, is_scored_phase,
    COMPETITION_MARKET_OI_CAP_USD, COMPETITION_DEX_OI_CAP_USD,
)
from exchange.hyperliquid_client import HyperliquidClient
from exchange.hyperliquid_market_data import HyperliquidMarketData
from exchange.hyperliquid_account import HyperliquidAccount
from exchange.market_health import validate_history
from exchange.live_readiness import valid_address, require_pas_cross_1x
from exchange.execution_safety import HumanLiveApproval
from exchange.reliability_policy import load_reliability_policy
from market_regime_scanner import ScannerPolicy
from risk.models import RiskPolicy
from strategy_freeze import verify_strategy_freeze


CRITICAL_TESTS = (
    "static_import", "configuration", "pas_btc_ewy_discovery", "account_read_only",
    "api_wallet", "btc_ewy_market_data", "websocket", "rest_fallback",
    "btc_ewy_order_validation", "controlled_testnet_order_lifecycle",
    "actual_fill_verification", "protection_verification", "exit_verification",
    "partial_fill_handling", "restart_recovery", "account_reconciliation",
    "funding_accounting", "snapshot_utc_calculation", "supervisor_failure_recovery",
    "full_autonomous_btc_ewy_dry_run",
)


def write_report(path, report):
    encoded = json.dumps(report, indent=2, default=str, allow_nan=False) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, path)
    print(encoded)


def load_profile(path):
    """Load and bound the production risk profile; examples are not permissions."""
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExchangeError("PAS_BTC_PROFILE_UNAVAILABLE") from exc
    if (not isinstance(profile, dict) or profile.get("competition_market") != COMPETITION_MARKET or
            profile.get("base_assets") != ["BTC", "EWY"] or profile.get("network") != "testnet"):
        raise ExchangeError("PAS_BTC_PROFILE_IDENTITY_INVALID")
    if set(profile.get("risk", {})) != set(RiskPolicy.__dataclass_fields__):
        raise ExchangeError("PAS_BTC_RISK_POLICY_SCHEMA_INVALID")
    if set(profile.get("scanner", {})) != set(ScannerPolicy.__dataclass_fields__):
        raise ExchangeError("PAS_BTC_SCANNER_POLICY_SCHEMA_INVALID")
    risk = RiskPolicy(**profile["risk"])
    scanner = ScannerPolicy(**profile["scanner"])
    if risk.leverage != 1 or risk.max_positions != 1 or scanner.top_n != 1:
        raise ExchangeError("PAS_BTC_SINGLE_POSITION_1X_PROFILE_REQUIRED")

    # Enforce internal risk ceilings even if an operator edits the JSON profile.
    ceilings = {
        "risk_fraction": "0.0025",
        "max_daily_loss_fraction": "0.005",
        "max_gross_equity_multiple": "0.25",
        "max_margin_utilization": "0.25",
        "max_funding_cost_fraction": "0.001",
        "max_mark_oracle_bps": "50",
        "max_spread_bps": "15",
        "depth_participation": "0.05",
        "slippage_bps": "5",
        "max_drawdown_fraction": "0.03",
        "max_symbol_equity_multiple": "0.25",
        "max_net_equity_multiple": "0.25",
        "max_directional_equity_multiple": "0.25",
    }
    for name, ceiling in ceilings.items():
        if getattr(risk, name) > decimal(ceiling, nonnegative=True):
            raise ExchangeError("PAS_BTC_RISK_CEILING_EXCEEDED:" + name)
    if (risk.max_consecutive_order_errors > 3 or risk.max_reconnect_failures > 5 or
            risk.maintenance_buffer_multiple < decimal('2') or risk.holding_hours < decimal('1')):
        raise ExchangeError("PAS_BTC_RELIABILITY_OR_MARGIN_POLICY_WEAKENED")
    if risk.max_daily_setups > 2 or scanner.history_bars < 300:
        raise ExchangeError("PAS_BTC_ACTIVITY_OR_HISTORY_POLICY_INVALID")
    if (scanner.min_atr_fraction < decimal("0.004") or
            scanner.max_spread_bps > decimal("15") or
            scanner.min_bbo_notional < decimal("10")):
        raise ExchangeError("PAS_BTC_SCANNER_FLOOR_INVALID")
    if decimal(profile.get("target_starting_equity_usd"), positive=True) != decimal("100000"):
        raise ExchangeError("PAS_BTC_COMPETITION_EQUITY_REFERENCE_INVALID")
    oi_caps = profile.get("production_oi_caps_usd")
    if (not isinstance(oi_caps, dict) or
            set(oi_caps) != {"btc", "ewy", "dex_total"} or
            any(decimal(oi_caps[base], positive=True) != decimal(COMPETITION_MARKET_OI_CAP_USD)
                for base in ("btc", "ewy")) or
            decimal(oi_caps["dex_total"], positive=True) != decimal(COMPETITION_DEX_OI_CAP_USD)):
        raise ExchangeError("PAS_BTC_COMPETITION_OI_CAPS_INVALID")
    return profile, risk, scanner

def verify_certification(path, api_dex, api_markets, profile_path=None):
    if not path or not path.is_file():
        raise ExchangeError("CRITICAL_CERTIFICATION_REPORT_REQUIRED")
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        current = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                          cwd=ROOT, text=True).strip()
        dirty_runtime = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all", "--",
             "algo-trading-bot", "scripts", "configs", "deploy", "libquant_engine"],
            cwd=ROOT, text=True).strip()
        selected_profile = profile_path or ROOT / "configs/pas_btc_production.example.json"
        profile_sha256 = hashlib.sha256(selected_profile.read_bytes()).hexdigest()
    except Exception as exc:
        raise ExchangeError("CERTIFICATION_EVIDENCE_UNREADABLE") from exc
    if dirty_runtime:
        raise ExchangeError("CERTIFICATION_SOURCE_OR_CONFIG_DIRTY")
    if not isinstance(evidence, dict):
        raise ExchangeError("CRITICAL_CERTIFICATION_REPORT_INVALID")
    if evidence.get("profile_sha256") != profile_sha256:
        raise ExchangeError("CERTIFICATION_SELECTED_PROFILE_MISMATCH")
    checks = evidence.get("checks")
    if (evidence.get("status") != "READY_FOR_SCORED_PHASE" or
            evidence.get("competition_market") != COMPETITION_MARKET or
            evidence.get("api_dex") != api_dex or evidence.get("api_markets") != api_markets or
            evidence.get("active_base_assets") != ["BTC", "EWY"] or
            evidence.get("commit_sha") != current or not isinstance(checks, dict) or
            any(checks.get(name) is not True for name in CRITICAL_TESTS)):
        raise ExchangeError("CERTIFICATION_NOT_CURRENT_OR_NOT_COMPLETE")
    per_market = evidence.get("market_checks")
    required = ("market_data", "order_validation", "controlled_order_lifecycle",
                "actual_fill", "protection", "exit", "partial_fill", "restart_recovery")
    if (not isinstance(per_market, dict) or set(per_market) != set(api_markets.values()) or
            any(not isinstance(per_market[symbol], dict) or
                any(per_market[symbol].get(name) is not True for name in required)
                for symbol in api_markets.values())):
        raise ExchangeError("BOTH_ACTIVE_MARKETS_REQUIRE_CONTROLLED_CERTIFICATION")
    return evidence


def parse_oi_caps(response, client):
    """Normalize documented pair-list limits without silently accepting duplicates."""
    if not isinstance(response, dict):
        raise ExchangeError("PAS_OI_LIMITS_INVALID")
    rows = response.get("coinToOiCap")
    if isinstance(rows, dict):
        rows = list(rows.items())
    if not isinstance(rows, list):
        raise ExchangeError("PAS_OI_LIMITS_INVALID")
    caps = {}
    from exchange.competition_market import canonical_api_market
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ExchangeError("PAS_OI_LIMITS_INVALID")
        symbol = canonical_api_market(client.api_dex, row[0])
        if symbol in caps:
            raise ExchangeError("PAS_OI_LIMITS_DUPLICATE")
        caps[symbol] = decimal(row[1], positive=True)
    if not set(client.markets).issubset(caps):
        raise ExchangeError("PAS_ACTIVE_OI_LIMIT_MISSING")
    decimal(response.get("totalOiCap"), positive=True)
    return caps


def read_preflight_candles(market, symbol, bars, client):
    """Keep the existing warmup, with a bounded wait for the shared REST budget.

    Recalculate the completed window after waiting. Never pad missing bars or
    lower a requested policy; larger policies still fail closed if unavailable.
    """
    for attempt in range(2):
        now = client.clock_ms()
        end = now // 60_000 * 60_000 - 1
        start = end + 1 - bars * 60_000
        try:
            return market.get_candles(symbol, start, end, now_ms=now)
        except ExchangeError as exc:
            delay = getattr(exc, 'retry_after_ms', None)
            if (attempt == 0 and str(exc) == 'PAS_CANDLE_BUDGET_EXHAUSTED' and
                    type(delay) is int and 0 < delay <= 60_000):
                time.sleep((delay + 1) / 1000)
                continue
            raise


def read_only_preflight(profile_path, team_address=None, api_wallet_address=None, output_path=None):
    now_ms = time.time_ns() // 1_000_000
    report = {
        "status": "BLOCKED",
        "final_status": "BLOCKED",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "competition_market": COMPETITION_MARKET,
        "network": "testnet",
        "execution_mode": "READ_ONLY_PREFLIGHT",
        "exchange_orders_submitted": 0,
        "wallet_private_key_loaded": False,
        "checks": {},
        "reasons": [],
    }
    client = None
    try:
        profile, risk, scanner = load_profile(profile_path)
        report["checks"]["configuration"] = {
            "passed": True, "leverage": risk.leverage, "max_positions": risk.max_positions,
            "scanner_markets": scanner.top_n,
            "target_starting_equity_usd": profile["target_starting_equity_usd"],
            "note": "Target only. Live sizing uses account-reported equity.",
        }
        report["checks"]["strategy_freeze"] = verify_strategy_freeze()
        client = HyperliquidClient(venue='pas')
        client.startup()
        expected_markets = {base: f"{client.api_dex}:{base}" for base in ("BTC", "EWY")}
        if dict(client.api_markets) != expected_markets or set(client.markets) != set(expected_markets.values()):
            raise ExchangeError("PAS_BTC_EWY_MARKET_REGISTRY_REQUIRED")
        if client.collateral_token_name != "USDP":
            raise ExchangeError("PAS_USDP_COLLATERAL_REQUIRED")
        report.update(
            api_dex=client.api_dex, api_market=client.api_market,
            api_markets=dict(client.api_markets), active_base_assets=["BTC", "EWY"],
            dex_index=client.dex_index, collateral_token=client.collateral_token_name,
            metadata_timestamp_ms=client.metadata_timestamp_ms,
        )
        report["checks"]["pas_btc_ewy_discovery"] = {
            "passed": True, "competition_market": client.competition_market,
            "api_dex": client.api_dex, "api_markets": dict(client.api_markets),
            "markets_registered": list(client.markets),
        }
        market = HyperliquidMarketData(client)
        oi_caps = parse_oi_caps(client.post_info("perpDexLimits"), client)
        observations = {}
        for base, symbol in expected_markets.items():
            candles = read_preflight_candles(market, symbol, scanner.history_bars, client)
            validate_history(symbol, candles, client.clock_ms(), scanner.history_bars)
            # Budget waits must occur before executable quote observations.
            book = market.get_orderbook(symbol)
            quote = market.get_quote(symbol)
            now = client.clock_ms()  # after all reads, not before fresh quotes
            spread_bps = (quote.ask - quote.bid) / quote.mid * 10_000
            if (book.symbol != symbol or quote.symbol != symbol or not book.bids or not book.asks or
                    not 0 <= now - book.timestamp_ms <= risk.max_data_age_ms or
                    not 0 <= now - quote.timestamp_ms <= risk.max_data_age_ms or
                    quote.mark_timestamp_ms is None or
                    not 0 <= now - quote.mark_timestamp_ms <= risk.max_mark_age_ms or
                    len(candles) < scanner.history_bars or
                    not 0 <= now - (candles[-1].timestamp_ms + 60_000) <= scanner.max_candle_age_ms):
                raise ExchangeError("PAS_MARKET_DATA_STALE_OR_INCOMPLETE:" + base)
            if spread_bps > risk.max_spread_bps:
                raise ExchangeError("PAS_SPREAD_OUTSIDE_POLICY:" + base)
            observations[symbol] = {
                "completed_candles": len(candles), "bid": quote.bid, "ask": quote.ask,
                "mark": quote.mark, "oracle": quote.oracle, "spread_bps": spread_bps,
                "api_oi_cap": oi_caps[symbol],
            }
        market.get_asset_contexts()
        report["checks"]["btc_ewy_market_data"] = {
            "passed": True, "markets": observations,
            "dex_oi_notional": client.dex_total_oi_notional,
        }
        if client.dex_total_oi_notional is None:
            raise ExchangeError("DEX_OI_TOTAL_UNAVAILABLE")
        network_ok = client.base_url == "https://api.hyperliquid-testnet.xyz"
        report["checks"]["network_and_venue"] = {
            "passed": network_ok, "venue": "HYPERLIQUID_TESTNET", "network": "testnet",
        }
        if not network_ok:
            raise ExchangeError("HYPERLIQUID_TESTNET_ENDPOINT_REQUIRED")

        if not valid_address(team_address):
            report["checks"]["account_read_only"] = {"passed": False, "reason": "TEAM_WALLET_ADDRESS_REQUIRED"}
            report["reasons"].append("TEAM_WALLET_ADDRESS_REQUIRED")
        else:
            account = HyperliquidAccount(client, team_address)
            abstraction = account._query("userAbstraction")
            agents = account._query("extraAgents")
            fees = account._query("userFees")
            equity = account.get_equity()
            positions = account.get_positions()
            orders = account.get_frontend_open_orders()
            api_wallet_ok = False
            expiry_ms = None
            if valid_address(api_wallet_address) and isinstance(agents, list):
                matches = [row for row in agents if isinstance(row, dict) and
                           str(row.get("address", "")).lower() == api_wallet_address.lower()]
                if len(matches) == 1 and type(matches[0].get("validUntil")) is int:
                    expiry_ms = matches[0]["validUntil"]
                    api_wallet_ok = expiry_ms > client.clock_ms()
            report["checks"]["account_read_only"] = {
                "passed": abstraction == "unifiedAccount" and equity.reported_account_value > 0,
                "account_mode": abstraction, "reported_equity": equity.reported_account_value,
                "collateral": equity.collateral_balance, "margin_used": equity.margin_used,
                "position_count": len(positions), "open_order_count": len(orders),
            }
            report["checks"]["api_wallet"] = {
                "passed": api_wallet_ok, "configured": valid_address(api_wallet_address),
                "approved_and_unexpired": api_wallet_ok, "expiry_ms": expiry_ms,
                "reported_fee_schedule_available": isinstance(fees, dict),
            }
            try:
                leverage_settings = require_pas_cross_1x(account)
                report["checks"]["btc_ewy_account_leverage"] = {
                    "passed": True, "markets": leverage_settings,
                }
            except Exception:
                report["checks"]["btc_ewy_account_leverage"] = {
                    "passed": False, "reason": "PAS_ACTIVE_ASSET_CROSS_1X_REQUIRED",
                }
                report["reasons"].append("PAS_ACTIVE_ASSET_CROSS_1X_REQUIRED")
            if positions:
                report["reasons"].append("EXISTING_POSITION_REQUIRES_JOURNAL_AND_PROTECTION_RECONCILIATION")
            if orders:
                report["reasons"].append("OPEN_ORDERS_REQUIRE_JOURNAL_RECONCILIATION")
            if not api_wallet_ok:
                report["reasons"].append("API_WALLET_APPROVAL_NOT_VERIFIED")
        report["checks"]["restart_recovery"] = {
            "passed": False, "reason": "Requires the persistent production journal and actual session recovery",
        }
        report["checks"]["protection"] = {
            "passed": False, "reason": "Read-only market preflight cannot certify protective orders",
        }
        report["checks"]["websocket"] = {
            "passed": False, "reason": "Long-lived feed and reconnect recovery have not been certified by this preflight",
        }
        report["checks"]["critical_test_suite"] = {
            "passed": False, "required_tests": list(CRITICAL_TESTS),
            "reason": "Controlled lifecycle, fill, protection, restart, and supervisor tests are not claimed by a read-only preflight",
        }
        report["reasons"].append("READ_ONLY_PREFLIGHT_NEVER_AUTHORIZES_TRADING")
    except Exception as exc:
        report["status"] = "SAFE_HALT"
        report["final_status"] = "SAFE_HALT"
        report["reasons"].append("PREFLIGHT_FAILED:" + type(exc).__name__)
    finally:
        if client is not None:
            try:
                client.transport.close()
            except Exception:
                pass
    if report["status"] != "SAFE_HALT":
        report["final_status"] = "BLOCKED"
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, output_path)
    print(json.dumps(report, indent=2, default=str, allow_nan=False))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "configs/pas_btc_production.example.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--team-wallet", default=os.environ.get("TEAM_WALLET_ADDRESS"))
    parser.add_argument("--api-wallet-address", default=os.environ.get("API_WALLET_ADDRESS"))
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--confirm-live-testnet", action="store_true")
    parser.add_argument("--approval-id", default=os.environ.get("ANCHORIUM_LIVE_APPROVAL_ID"))
    parser.add_argument("--approval-expires-ms", type=int,
                        default=int(os.environ.get("ANCHORIUM_LIVE_APPROVAL_EXPIRES_MS", "0") or "0"))
    parser.add_argument("--fee-scale-verified")
    parser.add_argument("--certification-report", type=Path)
    parser.add_argument("--state-directory", type=Path, default=Path("/var/lib/anchorium/pas-btc"))
    parser.add_argument("--session-id", default="anchorium-pas-btc-ewy-scored-2026")
    parser.add_argument("--scan-interval-seconds", type=float, default=300)
    parser.add_argument("--management-interval-seconds", type=float, default=1)
    parser.add_argument("--export-interval-seconds", type=float, default=30)
    args = parser.parse_args(argv)
    if not args.run_live:
        report = read_only_preflight(args.profile, args.team_wallet, args.api_wallet_address, args.output)
        return 0 if report["final_status"] == "READY_FOR_SCORED_PHASE" else 2

    if not args.confirm_live_testnet:
        parser.error("--run-live requires --confirm-live-testnet")
    expected = {
        "TRADING_VENUE": "HYPERLIQUID_TESTNET",
        "HL_NETWORK": "testnet",
        "HL_COMPETITION_MARKET": "pas",
        "EXECUTION_MODE": "HYPERLIQUID_TESTNET_LIVE",
        "ALLOW_LIVE_ORDERS": "true",
    }
    for name, value in expected.items():
        if os.environ.get(name, "").strip().lower() != value.lower():
            raise SystemExit("BLOCKED: explicit environment setting required: " + name)
    if not valid_address(args.team_wallet) or not valid_address(args.api_wallet_address) or not args.approval_id:
        raise SystemExit("BLOCKED: valid team/API wallet and approval identifier are required")
    now_ms = time.time_ns() // 1_000_000
    if not is_scored_phase(now_ms):
        raise SystemExit("BLOCKED: outside the scored-phase UTC window")
    if args.approval_expires_ms <= now_ms or args.fee_scale_verified is None:
        raise SystemExit("BLOCKED: unexpired manual approval and fee-scale verification are required")
    profile, risk, scanner = load_profile(args.profile)
    preflight = read_only_preflight(args.profile, args.team_wallet, args.api_wallet_address)
    if preflight.get("api_dex") is None or not preflight.get("api_markets"):
        raise SystemExit("BLOCKED: PAS BTC/EWY market mapping is unverified")
    required_reads = ("configuration", "pas_btc_ewy_discovery", "btc_ewy_market_data", "network_and_venue",
                      "account_read_only", "api_wallet", "btc_ewy_account_leverage")
    if any(preflight.get("checks", {}).get(name, {}).get("passed") is not True for name in required_reads):
        raise SystemExit("BLOCKED: current read-only preflight checks failed")
    verify_certification(args.certification_report, preflight["api_dex"], preflight["api_markets"], args.profile)
    rate_policy, clock_policy, protection_policy = load_reliability_policy(
        ROOT / "configs/reliability_policy.json")
    if not protection_policy.enabled:
        raise SystemExit("BLOCKED: protection policy remains disabled pending controlled certification")
    approval = HumanLiveApproval(
        approval_id=args.approval_id,
        team_address=args.team_wallet,
        signer_address=args.api_wallet_address,
        expires_ms=args.approval_expires_ms,
        manually_verified=True,
        competition_market="pas", active_base_assets=("BTC", "EWY"), network="testnet",
    )
    from exchange.live_runtime import build_live_runtime
    from exchange.runtime_schedule import RuntimeSchedule
    runtime = build_live_runtime(
        team_address=args.team_wallet, approval=approval, session_id=args.session_id,
        initial_start_ms=SCORING_START_MS, risk_policy=risk, scanner_policy=scanner,
        state_directory=args.state_directory,
        fee_scale_verified=decimal(args.fee_scale_verified, nonnegative=True),
        rate_policy=rate_policy, protection_policy=protection_policy, clock_policy=clock_policy,
        schedule=RuntimeSchedule(args.scan_interval_seconds, args.management_interval_seconds,
                                 args.export_interval_seconds),
    )
    runtime.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
