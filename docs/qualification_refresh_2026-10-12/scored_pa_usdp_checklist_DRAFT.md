# Scored pa / USDP — staged read-only migration checklist

Status: **DRAFT FOR REVIEW AFTER THE QUALIFICATION ATTEMPT**. The current attempt has not been authorized or submitted. This document makes no exchange call, switches no venue and grants no trading or account-administration permission.

The user reports an organizer announcement naming scored DEX `pa` and collateral `USDP`. The public [participant guide](https://perpetual-alpha26.github.io/docs/) inspected on 12 October still names practice `par` and `USDPR`. Preserve the dated organizer announcement as the authoritative scored specification before implementing a change. Do not infer the network or API URL from the DEX name.

| Check | Read-only evidence needed | Current status |
|---|---|---|
| Finish practice accounting | Actual qualification order/fill IDs, fees, funding, terminal order states and fresh position/open-order reconciliation | Pending exact trade approval; no qualification attempt yet |
| Establish scored specification | Organizer's dated `pa`/`USDP` announcement, network, URLs, allowed markets, starting/reset rules and scoring dates | User-reported target; announcement details not independently verified |
| Discover the venue | Public `perpDexs`, followed by `meta` and `metaAndAssetCtxs` with `dex=pa` on the explicitly confirmed network | Not queried; practice client remains par-only |
| Verify collateral identity | DEX collateral-token index mapped through public token metadata to the exact `USDP` token, and actual team balance | Not verified; 1,000,000 USDPR does not prove any USDP balance |
| Read market specifications | Actual `pa:` names, DEX index, asset IDs, size decimals, price rules, leverage limits and open-interest limits | Not verified; never copy par asset IDs or lots |
| Read account readiness | Team address, agent approval/expiry, unified mode, `clearinghouseState(dex=pa)`, orders and `activeAssetData` for each selected `pa:` coin | Not verified; par 1x approval/settings do not configure pa |
| Check liquidity and data | Two-sided books, depth, spread, mark/oracle, funding and genuine completed UTC candles | Not verified; retain production 300-bar/ATR/spread/Top-3 checks |
| Establish protection and closure | Authoritative pa-specific minimum-order, exact full-close, trigger admission, position coverage and partial-fill behavior | Not verified; par closing evidence cannot exempt pa orders |
| Preserve account identity and nonce ownership | Correct account_address, approved API signer, one signing host and the existing durable nonce history on the confirmed network | Future fresh verification required; do not clone/reset the nonce database |
| Keep journals and reports separate | New scored account/data provenance; actual fills, fees and funding labeled by pa/USDP; archive practice evidence | No scored runtime/state created |
| Verify migration offline first | Tests for correct venue/token, wrong-venue aborts, accounting, precision, recovery, global exposure and all write lockouts | Future separately authorized implementation, then PAPER validation |

The relevant current code intentionally rejects another venue/token. Review these exact areas in a later migration; do not replace strings globally:

- [hyperliquid_client.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/hyperliquid_client.py>): par metadata, prefixed symbols and runtime asset mapping.
- [hyperliquid_account.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/hyperliquid_account.py>): par fill/funding filters, USDPR fee validation and collateral valuation.
- [sdk_transport.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/sdk_transport.py>): testnet signing domain, par-only SDK mapping and team account_address.
- [full_position_close.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/full_position_close.py>): historical exceptions bound to specific par asset IDs, sizes and directions.
- [testnet_certification.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/testnet_certification.py>) and [testnet_qualification.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/exchange/testnet_qualification.py>): practice-only proposals, approval scope and USDPR accounting; neither approval carries over to scored execution.

After an attempt, first append its truthful outcome to this checklist. If there is residual exposure or uncertain order status, read and reconcile it before considering a migration. Preserve the single global account exposure guard while checking both venues as applicable; do not let separate DEX journals hide an existing position. Confirm whether collateral and account constraints span both venues from actual venue/account evidence.

Keep `EXECUTION_MODE=PAPER`, `ALLOW_LIVE_ORDERS=false`, the frozen brain and the practice configuration unchanged. This checklist does not authorize transfers, converting USDPR into USDP, approving an agent, changing account mode/leverage, submitting pa orders or activating scored/autonomous trading. Any future configuration or activation must be separately authorized after the scored account and venue are verified.
