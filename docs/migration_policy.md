# Non-negotiable Anchorium migration policy

This project migrates exchange and market infrastructure. Preserve the baseline
VWAP strategy, LONG/SHORT decisions, ATR and EMA calculations, stop/target
concepts and strategy state behavior. No strategy changes have been made.

The development configuration is:

```ini
TRADING_VENUE=HYPERLIQUID_TESTNET
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

`venue_config.require_paper_migration()` rejects a different venue, a non-paper
mode or a live-order permission setting. It checks both imported configuration
and runtime environment overrides. The public migration probe validates it
before requesting data. The crypto paper executor validates it at construction,
order creation and simulated fill; a runtime change cannot mutate its positions
or fills. Local cancellation remains available for cleanup. `order_guard`
continues to block every real exchange mutation in all modes.

No private key, funded wallet or exchange login is required for the current
public-data and local-paper work. No automatic activation path exists. Any later
activation requires an explicit instruction from the human user **after** the
Team Anchorium wallet is funded, configured and manually verified. A connection
check, public address, balance observation or flag change alone cannot authorize
live trading. Angel One execution remains permanently disabled in this clone.

The strategy remains checked against `nse-working-baseline` by
`scripts/check_strategy_freeze.py`. Necessary provider adaptations belong outside
the brain, must be narrow and documented, and must preserve comparison with the
baseline. Changing a freeze hash to conceal a strategy change is prohibited.

The earlier pasted reference was design context. The subsequent request explicitly
authorizes implementing its infrastructure: the all-par periodic scanner, session
adapter, perpetual risk/economics, paper accounting and order lifecycle. This does
not authorize tuning the brain or optimizing alternate VWAP anchors. Existing code
already has a price-relative ATR filter and
ATR-relative stop/target multipliers. Those values and calculations remain
unchanged. The current adapter supplies completed UTC bars without rewriting
the brain; the established UTC date convention must not silently change.

Infrastructure replacements use `par` metadata and prefixed symbols, public
Hyperliquid REST/WebSocket data, generic execution/account interfaces, and
perpetual accounting. Indian brokerage, stock tokens and market-session rules
remain isolated legacy references. Shared USDPR collateral, maker/taker fees,
funding, margin, leverage, liquidation risk and separate mark/oracle/BBO data
belong to the infrastructure and risk layers, not signal formulas.

Current status: public market data, runtime specifications, frozen signal/state
integration, shared USDPR paper accounting, margin/funding/exposure gates, local
order lifecycle and labelled performance reports are implemented. Actual team
account reads remain fixture-tested. Funding booked from hourly public snapshots
is explicitly a paper estimate; missed boundaries require replay and pause new
entries. No private key or signed transport exists. Necessary stock-unit/session
adaptations are recorded separately in `infrastructure_adaptations.json`, without
changing the baseline manifest. See the step-by-step guide in
`crypto_paper_migration_2026-10-02.md`.

Earlier policy checkpoint on 2026-10-02: the full suite passed **527 tests**, including 28
additional policy checks. Strategy freeze and Phase 0 checks passed. Tests verify
invalid modes/permissions are rejected before public requests or paper-ledger
changes and that every signed execution method remains blocked in every mode.
Evidence is saved in `migration_policy_tests_2026-10-02.xml` and
`migration_policy_validation_2026-10-02.json` in this directory.

The subsequent paper migration checkpoint passed **595 tests**, including 68
focused infrastructure checks, with strategy freeze and Phase 0 still passing.
Evidence is in `crypto_paper_tests_2026-10-02.xml` and
`crypto_paper_validation_2026-10-02.json`. The saved public-data paper probe scanned
all ten current markets and returned `NO_TRADE`, zero local fills and zero exchange
orders. Its 20,000 USDPR balance is hypothetical; it is not the Team Anchorium
wallet and does not demonstrate trading returns.

A subsequent short continuous public run also completed two ten-market scans,
with two equity snapshots, `NO_TRADE`, no failure/halt artifact and zero orders.
Its exact report is `crypto_public_continuous_probe_2026-10-02.json`. This does not
validate long-duration operation with exposure or actual wallet funding.

Subsequent recovery checkpoint: **645 tests**, including 50 new safety checks,
with the freeze and Phase 0 locks still passing. Actual account observation uses
reported fill prices/fees and `userFunding` cashflows only, in a separate read-only
mirror. Reconnects require account recovery; per-market clocks isolate stale data,
and risk states never activate exchange execution. See
`crypto_recovery_migration_2026-10-02.md` and its validation/report artifacts.


## Audit/replay checkpoint, 2026-10-02

The explicitly requested session timing, ten results files, full candidate trace,
source/configuration manifests, offline replay and wallet readiness checks are
implemented. The source/strategy freeze and PAPER/false policy remain enforced.
REPLAY is a recorded-data local run context, never an environment override that
grants exchange access. The LIVE interface remains an unconditionally blocked
skeleton, including cancel/modify/close/leverage methods. No account approval,
unified-mode mutation or signed test was attempted. See
[the run guide](crypto_audit_replay_2026-10-02.md) and
[678-test validation](crypto_audit_validation_2026-10-02.json).
