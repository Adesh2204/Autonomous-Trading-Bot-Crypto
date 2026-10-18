"""Competition identity to runtime-verified Hyperliquid market mapping.

The competition key is not an API alias. Discover the DEX and coin from current
Testnet metadata on each startup; fail closed if identity is ambiguous.
"""
import re
from datetime import datetime, timezone

from .base_exchange import VenueMismatch

COMPETITION_MARKET = "pas"
COMPETITION_BASE_ASSET = "BTC"
COMPETITION_BTC_OI_CAP_USD = 10_000_000
COMPETITION_DEX_OI_CAP_USD = 50_000_000
SCORING_START_MS = int(datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
SCORING_END_MS = int(datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)


def is_scored_phase(timestamp_ms):
    return type(timestamp_ms) is int and SCORING_START_MS <= timestamp_ms < SCORING_END_MS


def _normalize(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def resolve_competition_dex(dexes):
    """Return (API DEX name, runtime index, verified metadata identity).

    A DEX can use a different API name if its metadata explicitly associates
    that name with the competition key. A hard-coded name is never a fallback.
    """
    if not isinstance(dexes, list) or not dexes:
        raise VenueMismatch("PAS_DEX_DISCOVERY_UNAVAILABLE")
    candidates = []
    explicit_fields = (
        "competitionMarket", "competition_market", "competitionId",
        "competition_id", "marketId", "market_id", "slug",
    )
    for index, row in enumerate(dexes):
        if index == 0 or not isinstance(row, dict):
            continue
        api_name = row.get("name")
        if not isinstance(api_name, str) or not api_name.strip():
            continue
        direct = _normalize(api_name) == COMPETITION_MARKET
        explicit = any(_normalize(row.get(field)) == COMPETITION_MARKET for field in explicit_fields)
        # Some API deployments expose the competition key in fullName while
        # keeping a distinct internal name. Only explicit PAS identity matches;
        # a generic "Perpetual Alpha" label does not override market identity.
        full_name = _normalize(row.get("fullName"))
        named = full_name in {COMPETITION_MARKET, "pasdex", "perpetualalpha26pas"}
        if direct or explicit or named:
            candidates.append((api_name, index, dict(row)))
    if len(candidates) != 1:
        raise VenueMismatch("PAS_DEX_MAPPING_UNVERIFIED")
    api_name, index, identity = candidates[0]
    if index < 1:
        raise VenueMismatch("PAS_DEX_INDEX_INVALID")
    return api_name, index, identity


def canonical_api_market(api_dex, raw_name):
    """Normalize a DEX metadata market to its fully-qualified API coin name."""
    if not isinstance(api_dex, str) or not api_dex.strip():
        raise VenueMismatch("PAS_DEX_MAPPING_UNVERIFIED")
    if not isinstance(raw_name, str) or not raw_name.strip() or raw_name.strip() != raw_name:
        raise VenueMismatch("INVALID_MARKET_METADATA_NAME")
    if ":" in raw_name:
        if raw_name.count(":") != 1:
            raise VenueMismatch("INVALID_MARKET_METADATA_NAME")
        prefix, base = raw_name.split(":", 1)
        if prefix != api_dex or not base:
            raise VenueMismatch("MARKET_METADATA_DEX_MISMATCH")
    else:
        base = raw_name
    if not re.fullmatch(r"[A-Za-z0-9._-]+", base):
        raise VenueMismatch("INVALID_MARKET_METADATA_NAME")
    return f"{api_dex}:{base}"


def resolve_collateral_token(token_id, spot_metadata):
    """Resolve the DEX collateral token's displayed symbol from current spotMeta."""
    if type(token_id) is not int or token_id < 0:
        raise VenueMismatch("PAS_COLLATERAL_MAPPING_UNVERIFIED")
    if not isinstance(spot_metadata, dict) or not isinstance(spot_metadata.get("tokens"), list):
        raise VenueMismatch("SPOT_TOKEN_METADATA_UNAVAILABLE")
    matches = []
    for row in spot_metadata["tokens"]:
        if not isinstance(row, dict):
            continue
        identifiers = (row.get("index"), row.get("token"), row.get("id"))
        if token_id in identifiers:
            symbol = row.get("name") or row.get("coin") or row.get("symbol")
            if isinstance(symbol, str) and symbol.strip():
                matches.append(symbol.strip())
    if len(matches) != 1:
        raise VenueMismatch("PAS_COLLATERAL_MAPPING_UNVERIFIED")
    return matches[0]
