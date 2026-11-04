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
- 26 October 22:35 IST: the user made HYPE the priority carry leg ("best performing market"): HYPE $35,000, SP500
  $20,000, BTC $18,000, ETH $17,000, USDJPY $5,000 (the others by 24 h funding; USDJPY funding had fallen to
  0.06%/day); the total stays $95k at 1x (CarryMandate.leg_notionals, each <= $35k, sum <= equity). The user also
  chose larger IOC children: up to 25% of the depth within 5 bps of the touch (taker_depth_bps=5; the compliance
  guard sizes IOC children by depth inside their own limit, post-only children by the touch). Recent-price momentum
  allocation and leverage above 1x were offered and NOT chosen. A leg already partly built resumes with IOC children
  after a restart instead of a new 2 h maker window. No profit or rank is guaranteed.
- 27 October 01:05 IST: the user asked for more risk ("now or never", "invest heavily on HYPE") after the model numbers for
  1x / 1.5x / 2x (1.5x: P(profit) 44%, P(#1) 34%, -5% halt hit in ~46% of paths). Implemented the best of those: the five
  carry markets at a 2x CROSS leverage SETTING (human-typed configuration route, scope CARRY_2X, configuration only) and
  exposure capped at 1.5x equity by the carry mandate: HYPE $60k, SP500 $30k, BTC $25k, ETH $22.5k, USDJPY $5k ($142.5k);
  each leg at most $60k. ComplianceGuard.entry_leverage (default 1) and the validator/provider policy leverage follow the
  carry mandate only; every other runtime still requires 1x. The 8% leg stops and the -5% account halt are kept.
- 27 October 01:35 IST: the 2x leverage change could not run: the human configuration route (isolation review,
  plan, apply) requires a flat, order-free account and the basket was open. Of the options offered (more HYPE within
  1x / flatten and rebuild at 1.5x / rework the approval route / keep), the user chose more HYPE within 1x: HYPE
  $50,000, SP500 $15,000, BTC $13,000, ETH $12,000, USDJPY $5,000 ($95k at 1x; 1x tilted leg cap raised to $50k).
  Legs above a lowered target are trimmed first with reduce-only IOC children (same 25%-of-depth-within-5-bps rule);
  entries wait until every trim is done. The 2x code stays in place but unused (mandate leverage 1, markets at 1x).
- 27 October 02:45 IST: relaunched from 9f5e31f (codex/equity-fix). Carry equity is the unified USDP balance, which
  already includes unrealized P&L; adding uPnL again double-counted it. No limit, leg, stop or strategy change.
- 27 October 09:05 IST (user: "don't sell or trim HYPE, leverage at 2x, give more funds to the other markets"; answered
  questions): the user approved changing the flat-account rule for one narrow purpose and chose 1.5x exposure. New
  raise-only route `exchange/carry_leverage_raise.py` (human-run `docs/carry_2026-10-25/raise_carry_leverage_2x.py`):
  only 1x -> 2x CROSS on the five carry markets, with only the carry basket (basket sides) and its full-size,
  journaled reduce-only stops open, no UNKNOWN except the historical qualification row while unknownOid, no par
  exposure; the same exact-action transport, typed plan-hash approval, durable journal and readback. It never lowers
  leverage, switches margin mode, places/cancels orders or transfers. The general configuration route keeps its
  flat-account rule. HYPE is a hold leg (CarryMandate.hold_legs: target = the size held, never bought, trimmed or
  topped up; flat -> CLOSED). Budgets (`run_carry.py rebind`): HYPE at its marked value, USDJPY $5k, SP500/BTC/ETH share
  the rest of 1.5x the starting equity equally (~$31.5k each, ~$150k total). 8% leg stops and the -5% account halt
  (vs the original $99,998 start) are unchanged; at 1.5x the halt is about a 2.8% basket fall from the 27 Oct level.
- 27 October 15:33 IST: relaunched from 2d36040 (codex/stop-check-budget; release 3,542 tests, source f1c8751d...;
  old state/mandate/release archived _cdab9cb). Each stop's 5 s position-freshness window now runs from that symbol's
  own confirmation read: with five legs every later symbol failed PROTECTION_POSITION_CHANGED_OR_STALE on read latency,
  and the keep-valid re-checks (a position and an open-orders read per leg each minute) used the read budget the entry
  slices wait for. No limit, leg, stop or strategy change. Rotating HYPE into SP500 was raised by the user and NOT done
  (HYPE held at a loss; the 09:05 hold-leg choice stands until the user approves a change with the numbers).
- 29 October 13:45 IST (user, strict instruction: "start buying with the remaining balance... 1st most into HYPE, then
  SP500, then BTC, then Ethereum and then others"): the carry exposure cap is 1.85x the starting equity
  (CARRY_MAX_EXPOSURE_2X; each leg at most $65k, CARRY_MAX_LEG_2X). At the 2x setting 1.85x keeps the free margin above
  the loss that trips the -5% halt, so no build child runs out of margin before the halt; full 2x would not.
  HYPE is no longer a hold leg (hold_legs empty). `run_carry.py rebind` uses ranked_notionals: each leg keeps its marked
  value plus a 5:4:3:2:1 share (HYPE, SP500, BTC, ETH, USDJPY) of the room up to 1.85x, rounded down to $100, and refuses
  any target at or below the held value or out of that order (no sale, no trim). Mandate fd52066b...: HYPE $62.4k,
  SP500 $40.7k, BTC $38.4k, ETH $36.1k, USDJPY $7.2k ($184.8k). The 8% leg stops and the -5% account halt (vs $99,998)
  are unchanged; at 1.85x the halt is about a 3.2% basket fall. Relaunched 13:58 IST (release 3,547 tests, source
  dfd33834...; old state/mandate/release archived _b3d18d1).
- 31 October 22:40 IST (user: "square off USDJPY and S&P500 ... put all the balance into HYPE ... reduce the leverage
  strictly from 2x to 1.5x"; answered question "1.5x, HYPE gets part"): SP500 and USDJPY are close legs
  (CarryMandate.close_legs), sold to flat with reduce-only touch IOC children (25% of the depth within 5 bps, no maker
  window, never a sweep) and never bought; their stops go with them. BTC and ETH are hold legs (kept exactly as held).
  HYPE gets the room up to 1.5x the CURRENT equity (`run_carry.py rebind`, close_notionals; about $85k) and is bought
  only after both close legs are flat. The exchange setting stays 2x (whole numbers only); 1.5x is the exposure, and
  the ~$31k of freed margin not given to HYPE stays unused. With close legs one leg may reach $90k
  (CARRY_MAX_LEG_2X_CLOSE); the 1.85x mandate cap, 8% leg stops and the -5% account halt (vs $99,998) are unchanged.
  Model numbers given first: #1 is unreachable by the 1 Nov 12:00 UTC sample (the score caps near 0.339 for any gain);
  P(#2) ~15% vs ~12% unchanged. The runner had been halted (API_DISCONNECT_OVER_LIMIT, no flatten) since 29 Oct 20:40 UTC.
- 1 November 12:05 IST (user: "invest the remaining total balance of 26k dollars strictly all into HYPE making sure the
  leverage still stays 1.5x"): the basket was already at 1.5x the current equity (the $26k was free margin at the 2x
  setting), so adding HYPE alone would have raised exposure. Answered question: keep 1.5x and move $26,000 of BTC and
  ETH, in proportion to their marked values, into HYPE (`run_carry.py rebind`, move_notionals). BTC and ETH are no
  longer hold legs: they are trimmed first with reduce-only IOC children (25% of the depth within 5 bps, never a
  sweep), then HYPE is bought with exactly what was trimmed, capped at 1.5x the current equity. With close legs one
  leg may reach $120k (CARRY_MAX_LEG_2X_CLOSE). SP500/USDJPY stay closed; the 1.85x mandate cap, 2x setting, 8% leg
  stops and -5% account halt (vs $99,998) are unchanged. HYPE is the most volatile leg, so daily-return volatility rises.
- 1 November 22:30 IST (user: "trim some more of the btc and eth ... atleast 10k dollars ... put it into hype ... levareg
  should be til 1.5x only ... voltailty does not increase much"): a further $10,000 of BTC and ETH, in proportion to their
  marked values, is moved into HYPE (`run_carry.py rebind`, move_notionals, MOVE_AMOUNT 10,000). The kept BTC/ETH budgets
  now round down to $100, so at least $10,000 is trimmed (at most $10,200); the smallest qualifying move keeps the
  volatility increase small. Trims first (reduce-only IOC, 25% of the depth within 5 bps, never a sweep), then HYPE is
  bought with what was trimmed, capped at 1.5x the current equity. HYPE may reach $130k (CARRY_MAX_LEG_2X_CLOSE). The
  1.85x mandate cap, 2x setting, 8% leg stops and -5% account halt (vs $99,998) are unchanged; SP500/USDJPY stay closed.
- 1 November 23:10 IST (user: "Ok increase the leverage for 1.85x and make sure that The team anchorium grows more";
  answered question "$185k: bot's 1.85x cap", after the score analysis: a down day costs the score ~4x what an up day
  adds): exposure rises to 1.85x the STARTING equity ($99,998 x 1.85, about 1.75x the current equity), the existing
  CARRY_MAX_EXPOSURE_2X cap, so the free margin at the 2x setting stays above the loss that trips the -5% halt. BTC and
  ETH are hold legs (kept exactly as held); HYPE alone gets the room (`run_carry.py rebind`, raise_notionals), bought
  with touch-limited IOC children (25% of the depth within 5 bps, never a sweep) and never sold. HYPE may reach $155k
  (CARRY_MAX_LEG_2X_CLOSE). The 2x setting, 8% leg stops and -5% account halt (vs $99,998) are unchanged; SP500/USDJPY
  stay closed. No rank or profit is guaranteed for the 2 Nov 12:00 UTC sample.
- 2 November 11:40 IST (user, strict: "make the leverage 2x strictly from 1.85x to 2x, these are my strict instructions
  for all three positions"): exposure rises to 2x the STARTING equity ($99,998 x 2, the base of the 1.85x; about 1.9x
  the current equity). BTC, ETH and HYPE are no longer hold legs: each is scaled up by the same factor and keeps its share
  of the basket (`run_carry.py rebind`, scale_notionals), bought with touch-limited IOC children (25% of the depth
  within 5 bps, never a sweep); nothing is sold. With close legs the mandate cap is 2x (CARRY_MAX_EXPOSURE_2X_CLOSE) and
  one leg may reach $170k; without close legs 1.85x still applies. 2x the current equity was not used: it would need
  every dollar of free margin. An entry child above the free margin is refused before signing (INSUFFICIENT_MARGIN, a
  skip). The 2x setting, 8% leg stops and -5% account halt (vs $99,998, about a 5% basket fall at 2x) are unchanged;
  SP500/USDJPY stay closed. The runner had been halted (API_DISCONNECT_OVER_LIMIT, no flatten) since 02:59 IST.
- 2 November 20:50 IST (user, strict: "trim about 40-50k from HYPE now and put that money into the markets ... which is
  going to be profitable by tommorow ... keep the levarge same"): $50,000 of HYPE (never more; the kept budget rounds UP
  to $100) is trimmed with reduce-only touch-limited IOC children (25% of the depth within 5 bps, never a sweep) and
  SP500 is bought LONG with what was trimmed (`run_carry.py rebind`, shift_notionals), capped at 2x the starting equity
  and refused below $40,000. SP500 alone of the ten pas markets paid longs funding over both 24 h and 7 d, is ~6x less
  volatile than HYPE and was already at the 2x setting; EWJ/GOLD/BRENT/USDEUR are at 20x and EWY at 1x, so they would
  need a configuration change (no account administration was done). BTC and ETH are hold legs, USDJPY stays closed.
  The 2x setting, 8% leg stops and -5% account halt (vs $99,998) are unchanged. Score math given to the user: #1 is
  unreachable at the 3 Nov 12:00 UTC sample (any one-day gain caps the score near 0.324 vs 0.375); #2 needs about a
  +15.5% account day; a -1.5% day drops the rank to ~27. No profit or rank is guaranteed.
- 2 November 22:05 IST (user: "our voltality is actually very high and we have to make sure it get's low ... diversifying
  the funds, not just SP500 ... without changing the levaergae at all"; answered questions "$50k more" and "SP500 + USDJPY
  + EWJ"): HYPE was 92% of the basket's daily risk (6.2%/day), and splitting the first $50k alone would have lowered it
  only to 6.19%. $50,000 more of HYPE (never more) is trimmed with reduce-only touch-limited IOC children
  (`run_carry.py rebind`, diversify_notionals); SP500 grows by $10,000 and USDJPY is re-opened SHORT at $15,000 (no
  close legs). EWJ's $25,000 is reserved: the user approved changing EWJ's account setting from 20x to 2x CROSS through
  the typed configuration route (configuration only; the overall 2x leverage is unchanged), after which EWJ joins the
  basket LONG. Until then the exposure is about 1.73x. BTC/ETH are hold legs; the 8% leg stops and -5% account halt (vs
  $99,998) are unchanged. Simulated with EWJ: daily volatility about 3.7%, -5% halt by 6 Nov about 30% (was 46%).
  Second step (same directive): EWJ joins the carry basket LONG (CARRY_BASKET_EWJ, CARRY_ENTRY_MARKETS, six positions,
  CarryPositionGuard up to six). The raise-only route (`exchange/carry_leverage_raise.py`, human-run
  `raise_carry_leverage_2x.py`, typed plan-hash approval) gains one exception: pas:EWJ alone may be set from a higher
  CROSS setting down to 2x CROSS while it holds no position; every other market is still only raised from 1x and no
  margin mode is switched. With no close leg left, the 2x exposure cap applies without close legs too
  (CARRY_MAX_EXPOSURE_2X = 2; legs still at most $65k). `run_carry.py rebind --prior <mandate> --prior-state
  <that run's carry_state.json>` (ewj_notionals): legs the prior run verified complete (HOLD) become hold legs, the
  others keep their budgets, EWJ gets the reserved $25,000 (capped at 2x the starting equity, refused below $15,000,
  and only after HYPE's trim was verified).
- 2 November 23:20 IST (user: "We are out of top 10 pnl now, this is unacceptable ... increase the leverage such that the
  balance target of HYPE reaches to 150k dollars without changing the balance of these stocks at all"; answered question
  "Yes, HYPE $150k (2.9x)" after the model numbers: -5% halt (which flattens everything) by the 3 Nov sample ~32% vs ~7%,
  by 6 Nov ~66% vs ~40%; top 5 tomorrow ~12% vs ~5%): HYPE's budget becomes $150,000 (`run_carry.py rebind`,
  hype_up_notionals), bought with touch-limited IOC children; SP500, EWJ, USDJPY, BTC and ETH keep their budgets (a leg
  the prior run verified complete is held as it is). Exposure about $290k, about 2.9x the starting equity: the six
  markets move from 2x to 4x CROSS through the typed route (`raise_carry_leverage_4x.py`, carry_leverage_raise target 4,
  scope CARRY_4X: only 2x -> 4x CROSS, nothing else), and the mandate allows leverage 4 with the exposure capped at 2.95x
  the starting equity and one leg at $155k (CARRY_MAX_EXPOSURE_4X, CARRY_MAX_LEG_4X). The 8% leg stops and the -5%
  account halt (vs $99,998; it flattens) are unchanged: with HYPE at $150k a ~3% HYPE fall alone trips it.
- 3 November 00:10 IST (user: "move the stoploss from 3% drop to 6% drop then it would sell everything, rest everything
  should be strictly unchanged"): the carry account halt (which flattens the basket) moves from -5% to -9.5% of the
  $99,998 starting equity (about $90,500; with HYPE at $150k on ~$99.5k equity that is a ~6% HYPE fall instead of ~3%).
  CARRY_ACCOUNT_LOSS_HALTS allows only 0.05 or 0.095 for the carry profile; every other runtime keeps at most 5%.
  `run_carry.py rebind` (keep_notionals) keeps every budget, holds the legs the prior run verified complete, and keeps
  the 4x setting, 2.95x cap and 8% leg stops unchanged.
- 3 November 01:08-01:30 IST (incident, no limit change): a testnet API outage made fresh reads time out; one order error
  (INFO_RETRY_BUDGET_EXHAUSTED) and then an EWJ IOC entry child (21.528 @ 92.994, ~$2k) that was SIGNED and DISPATCHED but
  got no reply (RemoteDisconnected -> TRANSMISSION_UNCERTAIN, journal UNKNOWN; signed without an expiry). At 2 consecutive
  order errors the runner was stopped (stop.flag) so a third could not halt AND flatten the basket. The UNKNOWN row blocks
  every cancel (ACCOUNT_NOT_READY) and restart (RESTART_CHILD_UNSETTLED); the shutdown's "10 min" cancel loop is counted in
  rounds (~90 s each when cancels are refused) so it was killed after 17 min (no signed action in flight; journal durable).
  The exchange reported the cloid unknownOid with no EWJ fill since dispatch. New human-run tool
  `docs/carry_2026-10-25/resolve_dispatched_ioc.py` ("Resolve stuck IOC order.command"): marks exactly one UNKNOWN carry IOC
  entry as REJECTED (DISPATCHED_IOC_NOT_EXECUTED) only if it failed with a connection error after DISPATCHED, is >= 10 min
  old, is unknownOid on two reads, has no fill on its market since dispatch, and its worst case fits the leg's remaining
  budget, and only after the human types THIS IOC ORDER DID NOT EXECUTE. resolve_not_sent.py still covers pre-dispatch refusals.
- 3 November 09:18-09:25 IST (user: "complete the work such that bot is finally trading without any errors ... no losses";
  answered question "Keep building to HYPE $150k" after the model numbers: P(account ends in profit) ~36-44% building vs
  ~42-47% holding, -9.5% halt ~39-46% vs ~15-17%; no position's profit can be guaranteed). The user typed the confirmation
  and the EWJ row became REJECTED (DISPATCHED_IOC_NOT_EXECUTED). The overnight USDJPY maker child (0.79 @ 157.74) had filled
  while the runner was stopped. The halted state (API_DISCONNECT_OVER_LIMIT) was archived and `rebind` reproduced the SAME
  mandate identity (no budget or source change), so the fresh state restarted each leg's child counter and every new child
  key collided with the prior run's journal rows (CLOID_INTENT_CONFLICT; nothing signed). The third conflict came one second
  before stop.flag: HALT CONSECUTIVE_ORDER_ERRORS with flatten started an EMERGENCY unwind, and the stop ended the run 15 s
  later before any exit child; every position and stop was intact, no fill. Fix f2bc63e (branch codex/child-key-resume):
  a new child skips any key already in the journal. Every limit, budget and stop is unchanged.
- 3 November 13:20-13:35 IST: one entry child was refused before reservation (nothing journaled or signed) because a slow
  read let the carry guard's 5 s observation window lapse; it raised POSITION_LIMIT, which counted toward the 3-error
  halt-and-flatten. Fix 4de43ca (codex/stale-reserve-skip): a stale observation raises the skip code
  ACCOUNT_PREFLIGHT_INVALIDATED; every real limit check is unchanged. Release 3,638 tests (source cf84eae3); paused
  cleanly, archived _cd7d5d7, rebind mandate 85af1f58 (USDJPY and EWJ verified complete, now hold legs), relaunched 13:35 IST.
  The user asked for +20% by the evening "at any cost", any leverage and new markets; not done: the build is limited to
  ~$25k/hour by thin books (no sweeps), a +20% day needed a ~7% basket rise in 4 h (<0.1%), and a 15-day backtest of a
  long-when-rising / short-when-falling rule lost on every market after fees. Limits and strategy are unchanged.
- 3 November 15:20 IST (user, strict: "put btc into shorting without exiting or squaring off"; told that the exchange nets
  one position per market, so a long cannot become a short without reaching zero; answered question "Flip BTC to a $20k
  short", which was not the recommendation): branch codex/btc-short 1ece4cb. Step 1: `rebind` (flip_notionals) makes BTC a
  close leg while its long is held (reduce-only touch-limited IOC children to flat; close legs are now allowed at the 4x
  setting). Step 2: once BTC is flat, `rebind` again with CARRY_BASKET_EWJ_BTC_SHORT and BTC at $20,000 SHORT (sliced
  children, 8% stop above). Every other leg keeps its budget (verified-complete legs held), and the 4x setting, 2.95x cap,
  8% leg stops and -9.5% halt are unchanged. The user was told a short profits only if BTC falls and that closing locks
  in the BTC long's loss (about -$790); no profit is guaranteed.
- 3 November 16:37-16:51 IST: testnet flickered exchangeStatus.specialStatuses twice in 15 min; each pre-order refusal
  (EXCHANGE_SPECIAL_STATUS_REQUIRES_REVIEW) counted as an order error. My watcher's safety net (stop.flag at 2 consecutive
  order errors) paused the runner cleanly; nothing halted or sold. Fix 8ea8729 (codex/special-status-skip): that code is a
  carry SKIP_CODE (refuse, retry next cycle). Release 3,641+1 tests (source 22dc2aef); archived _8a473f9; rebind mandate
  8760f1fa (BTC SHORT $20k building, HYPE $150k building, others held); relaunched 16:51 IST. BTC long closed 15:36 IST:
  0.26485 sold for $20,372.61 (avg 76,921.3).
- 3 November 23:50 IST (user: "utilize the unused 30k funds as well now in Hype ... rest everything should be unchanged";
  answered question "Buy $30k more HYPE", not the ~$120k that all ~$30.5k of free margin would buy at 4x): branch
  codex/hype-add-30k 8a90677. `rebind` (hype_add_notionals, once: only on top of the d57bd2eb HYPE budget $153,400) sets
  HYPE to its marked value plus $30,000 (about $184.5k), bought with touch-limited IOC children; every other leg is held.
  The 4x caps become 3.3x the starting equity and $190,000 per leg; about $23k of margin stays free. The 4x setting,
  8% leg stops and -9.5% halt are unchanged; the halt is then about a 4% basket fall (about 7.5% in HYPE alone). Earlier
  tonight (22:30 IST) the user asked to lock +4% and was told an exact floor is impossible (fees alone exceeded the
  cushion); the user chose to change nothing then. 19:35 IST: API_DISCONNECT_OVER_LIMIT halt (laptop off network, no
  flatten); rebind d57bd2eb held all six legs, relaunched 20:58 IST.
- 4 November 07:28 IST (user, strict, with the account at -6.2% and ~$3.3k above the floor: "don't sell everything at
  -9.5% ... I am hoping everything would bounce back ... strictly don't sell everything at -9.5% halt"): the runner was
  paused at once (the halt only runs inside it; nothing sold), then branch codex/no-account-halt 935880f: carry
  account_loss_halt may be 1 (fires only at zero equity) and run_carry.py uses it. The 8% per-leg exchange stops,
  budgets, sides and 4x setting are unchanged. Other runtimes keep at most 5%. Without the halt the only protection is
  each leg's own stop (HYPE ~77.2); the account can fall well past -9.5% before those trigger.
