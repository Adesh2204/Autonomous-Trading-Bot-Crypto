# PAS BTC/EWY review fixes

## What this changes

This is a separate fix branch based on PR #1's reviewed head
`76bee2c44631625c2b15e78bf0ac6ee426433070`, targeting the same `main` branch.
PR #1 stays open and unchanged. During publication, `main` advanced from
`7353ed9f9a5b8e8b208cda1aa8dd418fd0a2b908` to
`e1f8a53a1af7ed066b31b14f5da7ec51b7f65952`. This working branch incorporates
that updated base, preserves its durable-history/readiness additions, resolves
three source conflicts without relaxing PAS-only gates, and re-passes the same
85-test no-sign suite. Neither PR is merged. This PR includes that unmerged foundation plus
its review fixes; compare against the reviewed head to isolate the fixes.

The current/future engine is **PAS-only on Hyperliquid Testnet**, with exactly
**BTC and EWY** active. This narrows the previously announced PAS universe; it
does not expand authorization to any other asset. The scanner may inspect both,
but the risk policy still permits just one global position and one selected
candidate at 1x. The frozen strategy and its manifest are not rewritten.

PAR is retired from production, not erased from history. Existing PAR practice,
fill, journal, audit and source evidence remains intact. Historical fixtures and
parsers do not authorize real PAR clients or signing. Legacy PAR-specific write
commands must stop rather than retargeting their old approval to PAS.

## Review defects addressed

- Runtime construction explicitly selects PAS rather than inheriting PAR.
- The official transport's missing venue guard is restored and checks the
  Testnet endpoint, verified PAS identity, active mappings and approval boundary.
- The launcher imports its reliability-policy loader and human-approval type;
  regression coverage exercises its composition with a mocked runtime, no signer.
- OI limits accept the API's pair-list shape and reject missing, malformed or
  duplicate active-market limits instead of calling `.get()` on a list.
- Fee scale is read from each active asset's `meta.universe` row, not the
  `perpDexs` identity object. Missing/different/unverified scales block startup.
  The shared fee schedule requires the two active scales to agree; it never
  quietly underprices a differently priced market.
- Runtime collateral must resolve unambiguously to **USDP**. USDPR/USDC or a
  mismatched token identifier cannot stand in for scored collateral.
- Snapshot freshness is evaluated after the quote reads, retaining stale/future
  data rejection and the durable missed-snapshot entry pause.
- Unified-account NAV uses the mapped USDP spot balance once, not per-DEX
  accountValue plus unrealized PnL. This follows the exchange's
  [account-abstraction source-of-truth guidance](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes).
  Account NAV and pending-order OI handling have dedicated regression coverage;
  account equity is never replaced with the $100,000 reference target.

Both assets flow through market data, the scanner, central order validation,
account history (including EWY fills and funding), position-state reconciliation and restart handling. Unsupported
PAS positions/orders block readiness rather than being silently ignored.

## What the tests mean

The review CI uses the `offline_no_sign` pytest plugin: network connections,
HTTP requests and signing functions are prohibited. Tests use synthetic metadata,
account responses and mocked transport/runtime boundaries. Historical tests that
intentionally create signatures are not part of this review's execution.

The final focused command passed **85 tests** across
`test_pas_btc_competition.py`, `test_pas_active_markets.py`,
`test_pas_account_oi_regressions.py`, `test_pas_pending_journal_oi.py`,
`test_pas_two_asset_session.py`, `test_pas_launcher_regressions.py` and
`test_pas_retired_routes.py`. Static imports, source compilation,
frozen-strategy verification and whitespace checks passed too. Passing these checks is evidence of code behavior, not of
actual funded-wallet execution, exchange liquidity, committee certification or
operational readiness.

## Still blocked: live activation

This PR is **draft / not live-ready**. No orders, signatures, account changes,
service installation, deployment or merge is authorized or performed by this work.
PAPER/false development defaults and the disabled protection policy remain intact.

Before any future live activation, an operator must separately validate the
funded unified account and actual NAV, approved API-wallet identity and expiry,
current per-market fee scale, available BTC/EWY market data and liquidity, and
controlled order/fill/partial-fill/exit/protection behavior for **both** assets.
Restart, WebSocket recovery, journal/account reconciliation and supervisor soak
remain required. A certificate must match the running commit, PAS API DEX and
both active coin mappings, plus per-market controlled checks. A prior BTC-only
certificate cannot authorize this two-asset scope. Human approvals also explicitly
name PAS, Testnet and exactly BTC/EWY; historical unscoped approvals are rejected.

A broader legacy compatibility selection is **not green**: old suites still
instantiate PAR fixtures through the now-PAS default, expect the superseded
all-market PAS registry, or expect retired write launchers to run. Their fixture
and expectation migration is outstanding. The scoped CI is deliberately named
PAS BTC/EWY offline safety; it is not a claim that the complete historical test
suite passes. This limitation is disclosed rather than weakening PAS-only gates
or executing signed fixture tests to produce a misleading green result.

The source fixes do not establish whether the current external PAS deployment or
funded account satisfies these prerequisites. No live certification is claimed.
