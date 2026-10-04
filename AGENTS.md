# Anchorium Perpetual Alpha migration

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
