# Anchorium Perpetual Alpha migration

- Work only in this cloned repository. Keep the original NSE repository untouched.
- This is an exchange/market infrastructure migration, never a strategy rewrite.
- Enforce `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false` throughout migration.
  Angel One execution is permanently prohibited. No signed exchange actions or
  wallet secrets are part of migration work. An environment flag, wallet address,
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
