# Anchorium Perpetual Alpha migration

## Current directive: PAS-only, BTC and EWY (supersedes historical notes below)

The current/future engine is Hyperliquid Testnet PAS only, with exactly BTC and
EWY active. These are a narrowed subset of the already announced PAS universe;
other assets are deferred, not authorized for signals or orders. Discover the
canonical API DEX and both coins at startup. Reject ambiguous identity, PAR or
native production routing, missing active assets, and collateral other than
runtime-verified USDP. There is no fallback venue or collateral.

Keep exactly one global position across the two active assets at 1x, the frozen
strategy, existing risk ceilings, the $10m per-market ceiling for BOTH BTC and EWY
and DEX $50m ceiling. Use the lower authoritative/published caps, reserve pending
exposure, and require increasing entries strictly below 99% of each effective
market USD, market size and DEX USD cap. The 1% reserve is an INTERNAL engineering
choice, not an official competition percentage; it cannot be disabled by profile.
The scanner can inspect both assets but selects at most one candidate.

Preserve historical PAR practice/fill records and source evidence unchanged.
Legacy PAR literals in historical documents, data and explicit offline fixtures
are evidence, never a current production configuration. Legacy order/configuration
commands must fail closed rather than silently retargeting old approvals to PAS.

Default operation is read-only, PAPER and ALLOW_LIVE_ORDERS=false. Do not sign,
place orders, alter an account, deploy, or claim live certification in this work.
Future activation requires explicit current approval, funded unified-account and
API-wallet verification, protection and recovery checks, and controlled
certification covering BOTH BTC and EWY on the running commit.


- Work only in this cloned repository. Keep the original NSE repository untouched.
- This is an exchange/market infrastructure migration, never a strategy rewrite.
- Enforce `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` throughout migration.
  Angel One execution is permanently prohibited. No actual exchange submissions or
  team-wallet secrets are part of migration work. The latest directive permits
  isolated offline SDK signing with ephemeral API-wallet fixtures. An environment flag, wallet address,
  funding observation or successful connection test does not authorize activation.
  Any later activation requires the human user's explicit change after the Team
  Anchorium wallet is funded, configured and manually verified. Until then all
  exchange writes, including protective/exit orders, remain blocked.
- The strategy is frozen against `nse-working-baseline`. Never improve VWAP,
  long/short conditions, EMA, ATR, stops, targets, cooldowns or direction flips.
  Verify `docs/strategy_freeze.json` with `scripts/check_strategy_freeze.py`.
- Preserve `signal_brain.py` byte for byte. An unavoidable NSE-specific change
  requires a documented necessity, a minimal diff and explicit comparison;
  an input adapter is preferred when it preserves the formulas. Do not rewrite
  the freeze manifest to conceal a strategy change.
- Frozen strategy methods also live in `execution_engine.py`, `safe_trader.py`,
  `live_stream.py`, and `runtime_observation.py`; the manifest identifies them.
  Exchange plumbing outside those methods may change.
- Preserve strategy state behavior, not just indicator formulas. Do not silently
  tune ranking weights, thresholds, periods, VWAP anchors or stop/target concepts.
  Reference-document suggestions are proposals, not automatic authorization to
  change the validated strategy. Record unavoidable provider adaptations and
  verify baseline parity. The existing input convention is completed UTC bars.
- The user's subsequent pasted request explicitly authorizes the periodic all-par
  scanner, session adapter, perpetual risk/economics, paper portfolio and generic
  order lifecycle. Implement those infrastructure components. Keep baseline
  normalized strategy thresholds/periods; document stock-unit adaptations and
  expose paper infrastructure assumptions. Do not optimize alternate VWAP anchors.
- The next pasted request authorizes actual-fill/account-event reconciliation,
  reconnect/account barriers, independent per-market freshness clocks, depth and
  imbalance snapshots, exposure reporting and scoped risk states/circuit breakers.
  Keep exchange-account truth separate from the hypothetical paper ledger. Actual
  account P&L uses reported fills/fees/funding only; unresolved history pauses
  entries. A supplied public address permits reads, never signed actions.
- New exchange code belongs in `algo-trading-bot/exchange/`, depends on generic
  interfaces, and must not import Angel SDKs or legacy NSE execution modules.
- Every market-wide/position query selects `dex=par`; coin queries use prefixed
  names. Abort on missing/invalid venue metadata; never fall back to native markets.
- Read size decimals, leverage and asset mappings at runtime. Use Decimal for
  precision and round quantity down. Order normalization is not strategy tuning.
- New market/risk/account infrastructure must use perpetual-futures semantics:
  shared USDPR collateral, fees, funding, margin, leverage and distinct mark,
  oracle and executable bid/ask prices. Never import Indian transaction costs or
  stock-session/token assumptions into the new core. Do not claim these systems
  are fully integrated or report live P&L until their accounting is verified.
- Keep retired dependencies as classified legacy references. Maintain the
  occurrence inventory with `scripts/inventory_legacy_dependencies.py`.
- Run production-policy lockout tests, strategy-freeze verification and applicable
  exchange tests. Offline legacy protocol fixtures cannot authorize real clients.

- The latest pasted request authorizes timing/results/session provenance, offline
  replay, explicit wallet readiness and blocked LIVE interface structure. REPLAY
  is a local run context using complete recorded public market responses; retain
  PAPER/false safety configuration and every signed-action lock. Never infer
  quotes/fills from candle OHLC or change strategy parameters for replay.
- Keep unavailable exchange clocks null, paper/account truth distinct and dirty
  source hashes alongside Git commits. Observed daily/oracle estimates are not
  official competition scores. Blank/zero wallets are NOT_CONFIGURED; even a
  supplied valid address remains unverified until the human verifies it.

- The subsequent production-execution directive authorizes the official SDK
  0.24.0 signed transport, central exchange validation, durable order recovery,
  account readiness, nonce/rate/clock controls and offline signed fixtures.
  It does not authorize any actual exchange order or account administration.
  Preserve PAPER/false defaults and the frozen strategy. Future testnet writes
  additionally require explicit human approval and verified funded account,
  agent approval, unified mode, metadata, account reconciliation and health.
  An offline signed fixture must have no HTTP exchange transport and must never
  grant permission to the production transport.

- The production reliability directive authorizes centralized priority/reserve
  budgets, adaptive read backoff, nonce/clock health, WebSocket budgets and a full
  independent reduce-only catastrophic protection lifecycle. It supersedes the
  earlier planner-only limitation. Keep actual exchange actions unauthorized,
  PAPER/false and catastrophic protection disabled by default. Production stop
  distance requires explicit documented approval; no strategy geometry changes.

- The restart/diagnostics directive authorizes one crash-safe startup coordinator,
  transactional recovery checkpoints, clean/unclean shutdown evidence, exposed
  downtime review and complete opportunity traces/reports. Reuse account truth
  reconciliation and the journal. Keep scanner ATR 0.40%, spread 15 bps, 300-bar
  history and Top-3 unchanged. Counterfactual variants are isolated observation
  research, cannot execute, and never promote themselves to production policy.

- The VWAP/ML directive authorizes isolated anchor research and a numerical,
  explainable candidate-quality meta-controller. Keep production UTC VWAP,
  strategy/state/risk/execution byte-identical. Research may replace only the
  VWAP and its slope assignments in a separately compiled, hash-verified brain;
  EMA, ATR, volume, warmup and management remain baseline controls. Record this
  narrow experimental adaptation. No production imports of research, no exchange
  transport, no invented fills/labels, chronological purged splits, training-only
  transforms, immutable artifacts and no automatic promotion.

- The single-position/compliance directive requires exactly one global par
  position, including partially filled exposure and unresolved entry/exit orders.
  Keep the durable account lock, fresh exchange-state checks, central provenance,
  self-cross/duplicate/price/liquidity guard and exact-action SDK permits on every
  signed submission path. Restart/disconnect begins UNKNOWN; only authoritative
  flat reconciliation clears the lock. Account administration/transfers and
  multi-position activation remain prohibited. Synthetic tests never certify a
  funded account, committee compliance or LIVE readiness. Complete controlled
  account certification and explicit user activation remain future work.

- The 7 October practice-setup request authorizes local derivation of the actual
  API key's public address, without printing the key, creating an actual-wallet
  signature or submitting an order. It also authorizes deliberate alignment of
  all ten runtime `par:` markets to exactly 1x CROSS, through the separate
  configuration helper. This is the only narrow exception to the earlier
  account-administration prohibition: preserve PAPER/false and require human
  verification of both wallet identities, fresh funded/unified/agent/flat-account
  checks, local account/signer ownership, healthy nonce/clock/rates, fixed-action
  permits, durable uncertainty handling and exchange readback. No order,
  cancellation, transfer, account-mode change or general administration is
  authorized. The human manually verified both wallet identities in the 7 October reply
  to `call_8vxKplKS9TzNbgFTbEfuoq2P`. This completes identity verification
  for the separately requested 1x CROSS configuration only; it does not
  authorize any order or protection activation.
- The same request approves configuration of independent protection at one entry
  ATR beyond the normal strategy stop, with a 0.5% execution allowance and
  reduce-only semantics. The approval reference is
  `docs/practice_setup_2026-10-07/protection_configuration_approval.md`. Keep
  protection disabled until separately authorized controlled certification.
  This configuration approval is not live-order activation. Preserve the
  original historical ZIP/source proof if supplied; absent provenance evidence
  does not block genuine public market-data PAPER collection.
