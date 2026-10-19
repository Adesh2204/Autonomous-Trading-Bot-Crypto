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

## Follow-up: both market caps and strict headroom

The authenticated follow-up confirmed two remaining validator defects: EWY did
not receive the $10m per-market clamp, and increasing entries could reach the
OI caps exactly without conservative headroom. This updates the existing draft
PR #2 and its branch, not a new PR or a merge.

Both BTC and EWY now use the lower of the authoritative exchange USD cap and
the announced $10m per-market ceiling. The DEX ceiling remains the lower of the
authoritative exchange limit and the announced $50m default. Missing or invalid
exchange limits still fail closed; published ceilings are never a fallback for
unverified runtime data.

The shared validator requires projected exposure-increasing entries to remain
**strictly below 99%** of each effective market USD cap, market size cap and DEX
USD cap. Equality at the buffered boundary or the published cap is rejected.
The **1% reserve is an internal engineering choice, not an official competition
percentage**. It is fixed in reviewed code, not a profile switch that can turn
it off. The production example and loader explicitly require both asset caps.

Projections retain authoritative pending-order reservations, deduplication and
the journal-only uncertainty block. Reduce-only exits retain their independent
position, permission, price, metadata and freshness safeguards; an exhausted
entry OI cap does not prevent an otherwise valid reduce-only exit. Historical
offline noncompetition protocol semantics remain unchanged. Existing historical
PAR trade/fill records, the frozen strategy and live approval gates are untouched.

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

The previous publication's focused command passed **85 tests** across
`test_pas_btc_competition.py`, `test_pas_active_markets.py`,
`test_pas_account_oi_regressions.py`, `test_pas_pending_journal_oi.py`,
`test_pas_two_asset_session.py`, `test_pas_launcher_regressions.py` and
`test_pas_retired_routes.py`. Static imports, source compilation,
frozen-strategy verification and whitespace checks passed too. Passing these checks is evidence of code behavior, not of
actual funded-wallet execution, exchange liquidity, committee certification or
operational readiness.

The OI follow-up's final combined offline suite passes **137 tests** using the
same seven files plus `test_pas_oi_headroom.py`. That new file contains **47**
regressions; five additional launcher cases reject omitted/relaxed/extra cap
declarations. The existing pending-order deduplication fixture was moved below
the new buffered limit without relaxing its deduplication/accumulation assertions.

For a behavior-only negative control, the original `f21100e` validator was
loaded only inside an isolated Python test process, without changing source
files. The eight high-exchange-cap cases produced **5 failed, 3 passed** on the
original validator and all eight pass with the fix. This demonstrates the old
EWY clamp and cap-equality defects rather than merely testing new audit fields.
All runs use `-p offline_no_sign`; no signing or network exchange transport is
allowed. Static imports, changed Python syntax, strategy freeze (one file, eight
methods, 32 parameters) and `git diff --check` also pass. Remote CI status is
reported separately; local results do not establish its completion.

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

## PR #2 conflict resolution against current main

The existing draft branch incorporates current main
`d5edb3668379d8b72e7f1551da04f4c3f47d6fd6` without merging the PR or rewriting
its prior head `c17548288bd453a9892928f3121d736bddee3193`.
The older 1x references above describe earlier review stages, not current policy:
BTC and EWY now both require exactly **20x CROSS**. This merge is code-side only;
no account configuration or exchange write is authorized.

The six textual conflicts are reconciled semantically: keep the shared candle
budget and thread-local cancellation isolation; combine unsigned 20x BTC/EWY
configuration proposals with main's organizer-registration blocker and audit
scope; retain verified market selection and main's trade/context observations;
retain the session's mapped primary market rather than restoring a PAR/BTC
fallback; and combine schema-3 PAS/API identity with main's entry/reconciliation
scope and venue-provenance fields. Configuration proposals remain unsigned and
cannot authorize the retired 1x configuration route.

Two automatically merged diagnostics still expected 1x. The PAS controller and
opening audit now expect 20x CROSS, with controller configuration readiness
requiring fresh readbacks for **both** active assets even for a narrower selected
scan. Main's same-market native/residual/history/opportunity intersection,
independent freshness checks, finite exact-acceptance validation and diagnostic
no-signing status remain intact. The retired authorized terminal route still
rejects before state creation; its regression now asserts that stronger lockout
instead of expecting the newly merged but inaccessible wait path to start.

The scoped no-network/no-sign CI includes the new conflict regressions and main's
activation/opening safety tests. Historical PAR records and all main-side data,
logs and evidence remain unchanged. The frozen strategy source and manifest are
not rewritten; liquidity selection, one global position, OI reserves and risk
limits retain their reviewed semantics. The full historical signed/legacy test
suite is not claimed green or executed as part of this no-sign review.

Live readiness remains blocked pending actual funded unified-account/API-wallet
verification, fresh 20x CROSS readbacks for BTC/EWY, authentic market history and
executable liquidity, resolved historical order uncertainty, genuine native and
residual protection/fill/exit/restart certification for both assets, a release
certificate matching the running commit and market mappings, and a new exact
human activation approval. Offline synthetic results do not satisfy these gates.

The review also found a pre-existing shared compliance check hardcoded to 1x.
Its verified competition path now requires the central PAS 20x target; explicit
noncompetition offline fixtures retain their historical 1x semantics. Provenance,
position permission, reduce-only handling and all later compliance checks are
unchanged. Old long-session 1x plumbing and subset mandates are not revived:
`build_long_runtime` rejects unconditionally at entry, and the authorized terminal
and scored-session routes remain retired. The canonical PAS launcher/session
continues to validate the two-asset mapping and scan BTC/EWY for one selection.

Final conflict-resolution validation: **549 passed** using the expanded
`PAS BTC-EWY offline safety` selection with `-p offline_no_sign` (network and
signatures prohibited), including **26 new conflict regressions**. Static imports
and changed Python syntax pass; strategy freeze passes for one file, eight
methods and 32 parameters. Review-source whitespace checks pass. Whitespace
already present in incoming historical logs/HTML/source evidence was preserved,
not reformatted. These results are scoped offline checks, not live certification
or a claim that every legacy signed fixture is compatible.
