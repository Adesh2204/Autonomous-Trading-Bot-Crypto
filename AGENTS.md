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

- The 24 October overnight directive authorizes, for 2026-10-24 00:30-09:00 IST only,
  an unattended momentum scalper on testnet PAS inside the committed limits: BTC/EWY,
  LONG-only (SHORT setups are detected and logged but never traded), one position,
  <= $1,000 per entry, <= 2 entries per hour, 1x cross, default 10% top-of-book
  compliance rule, 0.4% risk sizing, exchange-side reduce-only stop and take-profit,
  flat by 08:45 IST, verified exit at 08:50 IST with no restart. Live orders go only
  through `scripts/run_overnight.py`, bound to `docs/overnight_2026-10-24/mandate.json`
  and its matching release receipt. The shared-account barrier stays in force with one
  exact exemption: the historical qualification intent (configuration_isolation CLOID
  and INTENT) while the exchange reports that cloid as unknownOid. The user's 23-Oct
  work is preserved in `stash@{0}` (backup-23oct-directive) and
  `~/backup-23oct-20261024-0025.patch`.

- The 24 October day-session directive (13:00-18:00 IST) permits SHORT for the momentum
  scalper. That is the only limit change: BTC/EWY, one position, <= $1,000 per entry,
  <= 2 entries per hour, 1x cross, 10% top-of-book compliance rule and the 180 s signal
  window stay as committed. Live orders go only through `scripts/run_day.py`, bound to
  `docs/day_2026-10-24/mandate.json` and its release receipt. Every live entry is
  verified on the exchange (position side/size, exchange stop, take-profit); any
  mismatch flattens, cancels and halts without retry. Rank protection uses the
  published fractional score; LOCK flattens and pauses, -0.30% halts for the day.

- The 24 October continuous directive (approved 16:24 IST, mission step 4) runs the same
  momentum scalper from the end of the day session to 2026-11-06 11:30 UTC (flatten before the
  final 12:00 UTC sample) with the committed limits unchanged: BTC/EWY, LONG and SHORT, one
  position, <= $1,000 per entry, <= 2 entries per hour, 1x cross, 10% top-of-book, 0.4% risk.
  No compliance limit was changed; options a/b/c (other markets, order slicing, 25% of the
  book) were NOT approved. Live orders go only through `scripts/run_continuous.py`, bound to
  `docs/continuous_2026-10-24/mandate.json` and its release receipt. Each period runs from one
  12:00 UTC sample to the next: LOCK (the official-score #5 threshold plus buffer) and a -0.30%
  period loss cap flatten and pause until after the next sample; 3 consecutive order errors,
  a failed entry verification or a long stream disconnect halt permanently. A fresh exchange
  read precedes every order. Heartbeat every 15 min, report at 17:45 IST.

- 25 October 00:30 IST: an overnight PnL-push profile ($20k, 25% of top-of-book, slicing,
  2 positions, 6 entries/h, 2x) was authorized but NOT adopted; the user chose to keep the
  continuous limits above unchanged. The organizer pages set none of those limits (only
  leverage <= market maxLeverage, $10 minimum order, $10M open interest per market, and
  thin-book manipulation monitoring). The continuous run was relaunched under a new mandate
  and release after a fix: the account receiver keeps reconnecting instead of dying after
  five connect failures; the 3-minute disconnect halt is unchanged.
- 25 October 01:05 IST: the user approved adding pas:HYPE as a third entry market
  (`PAS_ENTRY_MARKETS`, run_continuous MARKETS); every other limit is unchanged. HYPE was set
  10x -> 1x CROSS through the human-typed configuration route (plan ef19e60b..., 1 action,
  0 orders). The completed 19 Oct BTC/EWY configuration journal was archived as
  `runtime/testnet/anchorium-bot-1/pas-configuration_btc_ewy_2026-10-19.sqlite` because the
  journal is bound to one plan session. Relaunched 01:56 IST from commit bfd83ec.
- 25 October 02:53 IST: relaunched from aa458ed (branch codex/entry-deadline). An entry now waits for
  read headroom until its signal is 130 s old (compliance still 60-180 s; 880 headroom unchanged), after a
  02:40 BTC signal was skipped 0.7 s short of the fixed 25 s wait.
- 25 October 04:08 IST: relaunched from a01d33e (codex/budget-refresh). The entry gate re-reads
  userRateLimit before re-deriving paused entries; a stale (>60 s) budget snapshot reads UNKNOWN and had
  kept entries paused after every closed trade until a random stream reconnect.
- 25 October 09:07 IST: relaunched from 059521f (codex/entry-paused-skip). An entry the executor refuses
  with ENTRY_PAUSED before signing (stream reconnect) is logged ENTRY_SKIPPED, not an order error; all
  other entry failures still count toward the 3-consecutive-error halt.
- 25 October 12:30 IST (user directive, answered questions): the scalper no longer has the 60-minute
  time exit or the 45-minute forced trade (`ScalpParams.time_stop_ms`/`guarantee_ms` = None), and the
  take-profit is floored at 2 x 0.09% taker fees + 0.05% net. The user kept the 1-ATR exchange stop
  after a backtest showed "never exit at a loss" lost more (-12.6% vs -48% summed, but trades stuck
  3-9% down for days). Approved: up to 3 concurrent positions (one per market, `MultiPositionGuard`;
  the one-position `SinglePositionGuard` is unchanged and still used when max_positions = 1) and 25% of
  top-of-book on the same quote snapshot the price checks use. Every other limit is unchanged ($1,000 per
  entry, 2 entries/hour, 1x, 0.4% risk, LOCK, -0.30% period loss cap). No profit is guaranteed: the
  backtest still loses on average per trade after fees.
- 25 October 22:30 IST (user mission "stop the fee bleed"): the bot stays FLAT (stop.flag kept; last run finished
  11:19 UTC, 0 positions / 0 orders verified on the exchange) unless a strategy passes the pre-registered Phase 3
  out-of-sample gate AND the user approves. The fee-aware 1h trend-pullback (maker-only) FAILED that gate
  (docs/fee_bleed_2026-10-25/research_results.md): NO-GO. Funding carry is NOT approved (needs an explicit
  "yes, carry"). Runtime fixes, no limit or strategy change: exchange fills are the source of truth for trade
  records (exchange/fill_ledger.py; 30 s and boot reconcile, adoption of untracked positions; bug #11); a stop-update
  error keeps a valid existing full-size stop and flattens only after 2 fresh-read retries, and a stop next to our
  resting take-profit is not a DUPLICATE_ORDER (bug #12); per-entry-cycle read weight is logged; stop-fill slippage
  is recorded per trade. Tests: test_fill_truth_and_stop_update.py. VPS kit (prepared, not enabled): deploy/vps/.
- 25 October 23:35 IST (user mission "Final release, then carry"): the user chose "YES, CARRY" ("We wanna move with
  Carry Strategy"). Half-size funding-carry basket: LONG BTC, ETH, HYPE, SP500 and SHORT USDJPY, <= $9,500 per leg,
  1x, 5 positions, held to the 6 Nov flatten; NO basket stop (the -1.5% stop was rejected), the existing 8% per-leg
  exchange stop, and the -5% account catastrophe halt kept (answered question). The user and co-founder accept a
  ~43% chance of finishing negative. Organizer rule (no moving a thin book): each leg is built/unwound with one child
  at a time, post-only at the touch for 2 h (10-min re-price), then IOC children limited to the touch and <= 25% of
  it (answered question); never a sweep. 3 consecutive order errors halt AND flatten (touch-limited); a failed leg
  verification flattens that leg and halts. These limits live only in the carry profile (CarryMandate.profile,
  exchange/carry_basket.py, entry scope 'CARRY', CarryPositionGuard); every other runtime keeps its committed limits.
  Live orders only through `scripts/run_carry.py`, bound to `docs/carry_2026-10-25/mandate.json` and its release.
  ETH/SP500/USDJPY were 20x cross on 25 Oct and need the human-typed 1x CROSS route
  (`docs/carry_2026-10-25/Set carry markets 1x.command`, configuration only, no orders). The momentum scalper and the
  1h pullback stay off. Tests: test_carry_profile.py.
- 26 October 11:55 IST: the user chose FULL SIZE for the carry basket ("trade with big money"; answered question with
  the model numbers: median +0.91%, P(loss) ~43%, 5th percentile about -4.2%): $19,000 per leg, $95k at 1x on ~$100k.
  CARRY_MAX_LEG_NOTIONAL is 19,000; every other carry limit is unchanged. The unwind starts 2026-11-05 20:00 UTC so the
  ~760 touch-limited slices finish before the 11:30 UTC flatten. The user also claimed the bot trades in the wrong
  direction; the 25 Oct shorts were the momentum scalper (both directions by design, now off) and its 16 round trips
  had gross P&L +$0.05 against $1.71 fees, i.e. no edge rather than an inverted one. No direction change was made.
