# Team Anchorium — final engineering verification report

Audit date: 4 October 2026. This report follows the requested A–S structure.
It describes verified code, local tests, public observations and missing real-world evidence separately.

## A. Executive verdict

**ACCOUNT_SETUP_REQUIRED**

The repository has a functioning, tested migration architecture. Its strategy is
preserved, local paper/replay paths work, and the future signed path has substantial
execution, recovery and compliance controls. The funded Team wallet, API agent,
unified account, controlled real execution, sustained practice and competition
release have not been certified. Passing tests cannot replace those observations.

Current operating configuration remains:

```ini
TRADING_VENUE=HYPERLIQUID_TESTNET
HL_NETWORK=testnet
HL_DEX=par
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
```

No actual exchange order, cancel, leverage change, transfer, approval or account
administration was performed. Public REST/WebSocket reads and isolated offline
signing fixtures are the evidence sources for this engineering pass. A public
wallet address is safe to use for account queries; it grants no trading permission.

Repository: `/Users/adesh/Autonomous Trading Bot - Crypto `, including its trailing
space. Branch: `perpetual-alpha-migration`. Starting and ending Git commit:
`2add07bad934f2a843f75739b1dfe4c34ee87953`. The starting tree was clean. Audit fixes and
artifacts are now uncommitted; no Git release/tag, commit, push or deployment was made.
The protected `nse-working-baseline` tag is present. Python is 3.12.5 and the installed
official SDK is 0.24.0. The original NSE checkout was not used or modified.

## B. Current architecture

The working paths are:

```text
Testnet /info + public WebSocket
  -> mandatory par metadata + independent market clocks
  -> completed UTC candles / BBO / depth / mark / oracle / funding
  -> baseline scanner and Top-3 selection
  -> unchanged signal_brain + frozen management state
  -> bias / cooldown / economic / portfolio risk checks
  -> PAPER local execution, or separately authorized future signed execution
  -> fills / orders / position management
  -> accounting / recovery / diagnostics / results
```

`scripts/run_crypto_paper.py` assembles the public data, scanner, original brain,
paper portfolio and risk policy. `scripts/run_crypto_replay.py` reuses complete
recorded public responses and logical clocks. It never reconstructs fills from
candle highs or lows. `exchange/live_runtime.py:build_live_runtime` is a distinct,
locked future composition root. It connects the same strategy/risk owners to an
actual-account portfolio, durable journal, approved signer, account stream,
startup coordinator and protection manager.

Signed submissions pass the global position lock, compliance, exchange rules,
rate budget, nonce/clock and exact-action permit before the SDK transmits. Account
recovery consumes reported fills/fees/funding, not desired prices or response
summaries. Journal snapshots restore management only when actual exchange state
agrees. Unknown/manual exposure without management evidence pauses new entries.

Research lives in `research_intelligence/` and `research_lab/`; it has no production
execution authority. Retired Angel/NSE modules remain isolated legacy references
behind permanent execution lockouts. The new audit module is read-only and is not
used by any signing or activation gate. The machine-readable architecture index
lists existing source files, hashes and owner paths. Presence alone is marked
PARTIAL, not end-to-end VERIFIED.

## C. Phase gap matrix

Severity describes the remaining competition blocker, not whether unit tests failed.

| Requirement | Status | Available evidence | What is missing | Severity |
|---|---|---|---|---|
| Identity / safety / strategy freeze | VERIFIED | Phase 0, frozen hashes, baseline tag | Version reviewed audit changes before release | Medium |
| 1. Real execution | PARTIAL | Official SDK offline signatures; per-operation response tests | Real funded LONG/SHORT, partial/cancel/modify/exit observations | Critical |
| 2. Account setup | MISSING | Public-address configuration check reports both absent | Funded Team account, separate approved API agent, unified USDPR mode, manual verification | Critical |
| 3. Venue rules | PARTIAL | Runtime metadata, precision, minimum, OI/margin/leverage tests | Fresh actual-account preflight and exchange acceptance | High |
| 4. Rate / nonce / clock | PARTIAL | Durable local tests; healthy public clock sample | Prolonged actual traffic, clock/NTP/host certification | High |
| 5. Crash / reconnect | PARTIAL | Synthetic timeout, process restart, checkpoint and reconciliation tests | Observed real disconnect/restart with actual exposure and funding | Critical |
| 6. Catastrophic protection | PARTIAL | Actual-quantity fixture lifecycle tests | Approved distance and verified real stop/restoration; policy remains disabled | Critical |
| 7. One global position | PARTIAL | Durable CAS/account lease/pending-order/fill tests | Controlled account demonstration; other-host/manual scope remains outside local ownership | High |
| 8. Competition compliance | PARTIAL | Provenance, self-cross, duplicate, price/depth and allowlist tests | Measured conduct evidence; committee review | High |
| 9. Long practice | MISSING | Short public probes and synthetic engineering tests | Multiple hours/conditions, funding boundaries and all real lifecycle scenarios | Critical |
| 10. Scanner calibration | PARTIAL | Rejection funnel, distributions/counterfactual tools | Representative fresh opportunities, costs and OOS results | High |
| 11. Session VWAP research | PARTIAL | Isolated anchor implementation and four-arm methodology | Adequate paired future portfolio/holdout evidence | Medium |
| 12. ML meta-controller | PARTIAL | Numerical isolated model pipeline and leakage tests | Genuine labels, trained/sealed validated models and adequate holdout | Medium |
| 13. Performance | PARTIAL | Local ledger and actual event accounting mechanisms | Real equity/trades/fees/funding; full attributed trade/regime/slippage statistics | High |
| 14. Reproducibility | PARTIAL | Hashes, manifests, test receipt, 54 installed dependency versions | Portable reviewed release and finalized environment/provenance package | High |
| 15. Jury evidence | PARTIAL | Architecture index, engineering report, four-section draft | Recorded real trade explanations and final 2–4 page PDF/code submission | High |
| Competition release | MISSING | Release requirements documented | Approved release identity, policy/model/config hashes and review | Critical |

The priority remains correctness, account/controlled certification, sustained
practice, evidence-supported research, then final release. Zero opportunities do
not authorize a change to thresholds or artificial volume generation.

## D. Files modified

Seven existing Python files changed; six are reporting/runtime infrastructure and
one is a test expectation. Their changes are narrowly scoped:

1. `algo-trading-bot/exchange/execution_journal.py`: adds session, event type,
   candidate and symbol fields to the common event envelope, preserves supplied
   exchange clocks, leaves global unknowns null, and permits public policy/source
   hashes to survive credential redaction.
2. `algo-trading-bot/exchange/single_position_guard.py`: gives the atomic position
   reconciliation event the same envelope. Its transaction and position decisions
   are unchanged.
3. `algo-trading-bot/exchange/live_runtime.py`: attaches the existing results writer
   in the future runtime; saves after cycles and before shutdown. An export failure
   pauses entries and stops the owner loop. This adds no activation mechanism.
4. `algo-trading-bot/live_session_results.py`: labels synthetic fixtures honestly,
   enriches provenance/CSV trace fields, rejects output-directory resume under a
   changed account/config/source identity, links child order IDs, distinguishes
   durable intents from accepted IDs, and leaves unknown real submission counts null.
5. `algo-trading-bot/live_execution_session.py`: corrects the recorded fill event's
   synthetic/actual mode and source; adds the market field. Fill/state behavior is
   unchanged.
6. `algo-trading-bot/opportunity_funnel.py`: distinguishes zero actions by the
   diagnostic observer from an unknown number of actual runtime submissions.
7. `algo-trading-bot/test_live_exchange_execution.py`: updates the expected source
   for an offline signing fixture to `SYNTHETIC_SIGNED_FIXTURE`.

`README.md` documents the verdict and reproducible audit command.
`docs/legacy_dependency_inventory.csv` and `.json` were regenerated with source
references and classifications. No scanner, risk, reliability or protection policy
file was modified. Historical reports were not relabeled as if produced by new code.

## E. Files created

Three new Python files provide the missing audit workflow:

- `algo-trading-bot/certification_audit.py`: source/test/evidence index, 29-row
  readiness matrix, account/practice gaps, source compatibility, session source
  validation and limited secret-pattern audit. It cannot grant trading permission.
- `scripts/run_hackathon_certification.py`: regenerates JSON/Markdown readiness
  and a jury evidence index without networking, account changes or signing.
- `algo-trading-bot/test_hackathon_certification.py`: 34 regressions for evidence
  ambiguity, mode/schema conflicts, source drift, event envelopes, runtime export
  failures and null missing measurements.

Created evidence includes the initial audit, baseline/final/new-test XML, final
test receipt, freeze/Phase 0/parity records, environment inventory, bounded public
readiness/stream/paper probes, recorded replays, consolidated validation, this
report and a four-section technical draft. `hackathon_certification_2026-10-04/`
contains `readiness.json`, `readiness.md` and `jury_evidence_index.json`.
The consolidated validation file records exact paths/hashes; these are audit
artifacts, not a competition release.

## F. Strategy integrity

`signal_brain.py` remains byte-identical to the frozen baseline:

```text
SHA-256: bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83
```

All eight protected management methods and 32 protected parameters pass. The
freeze manifest was not changed. Warmup, flat, uptrend, downtrend, volatile and UTC
day-boundary fixtures total 2,050 rows; all indicator/signal outputs match.

Of 148 pre-existing project Python files under `algo-trading-bot/` excluding its
inherited `venv`, 141 are byte-identical and seven have the changes listed above.
Two project Python files and one script were added. The broad working-source hash
also includes the inherited `algo-trading-bot/venv` Python files; its definition is
conservative and local. A portable competition release should use a nonignored
source-file manifest plus separately pinned dependency/environment evidence.

This confirms strategy preservation and engineering behavior, not the profitability
of that strategy in crypto. UTC VWAP, ATR ≥0.40%, spread ≤15 bps, 300 bars, Top-3,
one global position, leverage 1 and at most two new setups per UTC day remain intact.

## G. Execution certification

The official SDK serialization/signing path is implemented and tested offline.
Persistent nonces and a process/account ownership lease protect the signer.
Compliance issues an exact, short-lived permit bound to the selected action and
durable intent. Raw, unsupported or differently shaped signed actions are blocked.

The response parser inspects request status and each operation's status. It
distinguishes filled, resting, rejected, cancelled, partial/IOC remainder and
unknown transmission outcomes. HTTP success or a top-level `ok` is not treated as
a fill. Order summaries never create fee/P&L ledger entries. CLOIDs persist before
transmission; uncertain attempts reconcile rather than blindly resubmit.

Cancel, cancellation by CLOID, supported replacement and reduce-only close use
the same gates. Actual reported size controls partial entry/exit management.
Exposure-increasing replacement is deliberately blocked while the account is
occupied; current reduce-only protection replacement remains supported. No real
operation is certified in this pass. Technical implementation is UNIT_TESTED and
NOT_LIVE_VERIFIED, with signed actions still disabled.

## H. Account certification

The public readiness probe reports Team wallet and API wallet both unconfigured.
No funded account, approval expiry, unified mode, actual USDPR balance or live fee
tier was verified. The real query identity must be the Team wallet; the API wallet
is the signer and is not a replacement account address.

The existing readiness function queries `userAbstraction`, `extraAgents`,
`spotClearinghouseState`, fees, rate budget, positions and open orders. It rejects
missing/expired/retired agents and stale/unreconciled state. Future activation
additionally requires explicit human authorization and approved catastrophic
protection. A report, public address or environment override cannot satisfy those
human prerequisites.

Paper fees are explicit assumptions: 0.03% maker and 0.09% taker. The future live
builder verifies the venue fee scale and combines reported base account rates
with it; actual fill fees remain the accounting truth. Current account permissions,
funding and fee-tier certification are MISSING.

## I. Risk and venue certification

Startup verifies testnet, DEX `par` and all expected prefixed markets. Runtime
metadata supplies size decimals, market leverage/margin tiers and asset IDs.
Decimal normalization rounds quantity down and applies side-conservative price
precision without increasing strategy size. The validator enforces the $10
minimum, published reference-price band, post-only crossing rules, runtime OI
caps, account buying power, margin mode and leverage limits.

The bot's narrower mark/oracle, spread, participation, loss, drawdown and exposure
limits remain unchanged. Entry validation uses reported active-asset buying power
instead of treating the entire collateral balance as free margin. Reduce-only
actions must match actual direction and remaining quantity. Funding rates, cash
payments, margin, leverage, BBO, mark and oracle have separate meanings.

The tests cover those mechanics, but venue OI capacity and margin are shared and
can change between a read and transmission. Exchange acceptance and reconciliation
remain necessary. An untradable tiny remainder or failed protection placement must
remain an unresolved risk; it cannot be called successfully protected by a test.

## J. Reliability certification

Rate controls account for IP weights, response-size charges, account budget,
daily actions, WebSocket connections/messages/subscriptions, priorities and safety
reserves. Optional reads back off; signed unknown attempts are not retried as new
orders. Nonces persist monotonically and duplicate local ownership is rejected.
Clock health observes available exchange clocks and handles skew/age/jumps; the
public check obtained a healthy sample, not continuous NTP certification.

Startup/reconnect use the existing coordinator, actual-account reconciliation and
durable checkpoints. Missing management history, inconsistent quantities, unknown
orders/fills/funding and expired evidence pause entry. Local state does not override
exchange positions. Graceful and unclean shutdowns have different evidence.

Catastrophic protection is independent of normal strategy exits, reduce-only and
bound to actual remaining quantity. Its distance/slippage require explicit approval.
The current policy is disabled and has no selected distance. There is no observed
real exchange-side stop or real restart restoration. Unit/failure-injection coverage
cannot certify an actual machine restart, external activity or internet outage.

Runtime export now runs automatically. Full-disk/export failure stops further owner
loop cycles. Existing result directories with old CSV/manifest schemas or changed
configuration/source require review/new evidence directories rather than silent
mixing. Interrupted partial JSONL writes can fail resume and require repair/review;
that path remains safely blocked rather than hiding missing evidence.

## K. Compliance certification

The global lock treats actual exposure, partial fills and unresolved entry/exit
orders as occupancy. Startup begins UNKNOWN. Only reconciled flat account/order/
fill evidence clears it; a local close request or response summary does not.

Every admitted future order has a candidate, strategy, setup/direction, timestamp,
risk decision, execution decision, classification and compliance result. Own
opposite resting orders are checked to prevent self-crossing. Duplicate intent,
unsupported action, abnormal price and excessive displayed-depth participation
are blocked. Controlled certification orders require bounded explicit purpose and
authorization and are excluded from strategy-performance totals.

The transport excludes transfers/admin actions. It cannot monitor every manual
wallet action, another host, another OS user, cross-team coordination or future
committee interpretation. Local controls reduce those risks; they do not certify
committee compliance. Zero bot transfers is not proof of zero account transfers.
Genuine opportunities must drive activity; no volume farming was added.

## L. Practice results

| Measurement | Real LIVE_TESTNET practice | Final-code bounded public PAPER observation |
|---|---|---|
| Runtime | Unavailable | One scan, not prolonged practice |
| Markets discovered/scanned | Account practice unavailable | 10 |
| Starting / ending equity | Unavailable | 20,000 / 20,000 hypothetical USDPR |
| Orders / fills / closed trades | Unavailable | 0 / 0 / 0 |
| Realized / unrealized P&L | Unavailable | 0 / 0 local simulation |
| Net P&L / fees / funding | Unavailable | 0 / 0 / 0 local simulation |
| Sampled maximum drawdown | Unavailable | 0 with no exposure |
| Daily volatility / win rate / expectancy | Unavailable | Unavailable; insufficient observations/trades |
| Actual errors / reconnects | Unavailable | Separate short public probes; not account statistics |

The eight-second public BTC WebSocket probe received 10 messages, had zero
reconnections/no reported error, and observed zero completed candles. Its `passed`
field means transport/probe completion, not a healthy tradable candle stream. No
reconnect was exercised. The last public-paper scan found all ten completed histories
stale. A prior scan found nine stale histories and `INVALID_DECIMAL` on EWY; offline
inspection of that recorded EWY terminal ATR showed 0.0. No strategy/data threshold
was relaxed to bypass either condition.

No actual LONG/SHORT, partial fill, funding boundary, cancel, normal stop/target,
protection/recovery or sustained-practice measurement is supplied. The machine
report leaves all 28 practice requirements NOT_OBSERVED and measurements null.
An observed paper zero and an absent actual measurement are different facts.

## M. Opportunity funnel

The last public-paper scan contains 10 unique market-cycle observations, one date and
zero opportunities. Its recorded no-trade outcome reproduces in REPLAY.

| Stage | Observed passes | Observed failures | Meaning |
|---|---:|---:|---|
| Markets seen / valid identity | 10 / 10 | 0 / 0 | Correct universe |
| Market data healthy | 0 | 10 | All failed stale-candle check |
| Enough history | 10 | 0 | At least 300 bars existed; they were not fresh enough |
| Liquidity / spread / ATR | 0 | 0 | NOT_OBSERVED for all 10; not successful checks |
| Scanner qualified | 0 | 10 | Rejected upstream |
| Top-3 / strategy / signal | 0 | 0 | NOT_REACHED |
| Bias / anti-spam / friction / risk | 0 | 0 | NOT_REACHED |
| Execution permission | 0 | 10 | Upstream stale-data blocker |
| Order attempted / filled / completed | 0 | 0 | NOT_REACHED; zero actual/local attempts |

Enough history has 10 independent passes but zero cumulative healthy survivors.
The funnel preserves that distinction. Spread and liquidity are not inferred from
missing downstream checks. One date cannot establish per-hour/regime bottlenecks
or justify changing scanner policy. Earlier short research observations had eight
stale markets and two low-ATR/wide-spread markets; those are separate historical
windows, not a contradictory replacement for the latest measurements.

## N. Research results

Four independent arms already exist: UTC/no ML, session/no ML, UTC/ML and session/ML.
The historical receipted capture lasted about 75 seconds and produced 64 observation
frames. Its admitted candidate count, completed labels and fills were zero. The
two no-ML portfolios stayed flat. ML arms were unavailable because validated model
artifacts did not exist. Those results establish no advantage for any arm.

```ini
SESSION_ANCHOR_VALIDATED=false
ML_DATA_READY=false
ML_MODEL_VALIDATED=false
HOLDOUT_COMPLETE=false
PROMOTION_RECOMMENDED=false
```

No training, validation or sealed future holdout result can be claimed. Existing
tools require decision-time features, genuine labels, train-only transforms,
chronological purged splits, prospective sealed model artifacts and portfolio
comparisons including costs. The historical report is indexed as historical;
changed working-source hashes do not become a new model seal automatically.

The current 500-executed-label floor cannot be met quickly by a reference portfolio
allowing two setups/day: even the optimistic upper limit requires 250 days.
Replaying or duplicating arms cannot inflate that sample. Organizers' historical
price data may support research, but prices alone cannot invent executable fill
outcomes. Alternate scanner, ranking, anchor or confidence sizing remains research
only. Insufficient data means MORE_DATA_REQUIRED and retention of the baseline.

## O. Recommended production candidate

The candidate for later review is the deterministic frozen VWAP baseline, UTC
anchor, no production ML, ATR ≥0.40%, spread ≤15 bps, 300 completed bars and Top-3.
Use the existing risk configuration: 0.5% risk per setup, 1% daily loss cap,
5% drawdown cap, leverage 1, one global position and at most two new setups/day.
Do not raise these because other teams are more active.

Actual operating mode remains PAPER/false. Catastrophic protection remains disabled
until its separate distance approval and real certification. No model/anchor/scanner
promotion or production strategy change was made. Production **infrastructure** did
change as listed in D; the historical research flag `PRODUCTION_CHANGED=false` must
not be misread as saying this audit made no code changes.

## P. Test results

| Run | Passed | Failed / error / skipped | Scope |
|---|---:|---:|---|
| Pre-edit full baseline | 1,121 | 0 / 0 / 0 | 231.94 seconds |
| New regression cases | 34 | 0 / 0 / 0 | Evidence/source/trace/export integrity |
| Focused execution + audit | 113 | 0 / 0 / 0 | Earlier focused run; final full run supersedes it |
| Final full repository | 1,155 | 0 / 0 / 0 | 222.29 seconds; final source hash bound |

An initial new-test run exposed seven test-helper wiring failures; those were fixed and all cases rerun. A later integration check exposed the PAPER/REPLAY manifest-mode schema mismatch; that reader was corrected, three regressions were added and the full suite was repeated. These resolved development failures are not missing real-account evidence.

Freeze and Phase 0 passed both before and after edits. The parity check matched all
six fixtures/2,050 rows. The latest full-suite receipt records Git identity, command,
XML checksum, source hash before and after, duration and exit code. The hashes
match; local source did not change during that final run. A receipt documents local
reproducibility and is not an external execution attestation.

The suite includes signed response states, uncertain transmission/CLOID recovery,
minimum/precision/band/OI/margin/leverage, funded/expired agent fixtures, rate budgets,
nonce ownership, skew/staleness, partial-fill crashes, reconnect/restart snapshots,
LONG/SHORT protection, self-cross/duplicate/provenance, single position, accounting
deduplication and research leakage. New cases exercise source/mode corruption and
the reporting gaps discovered in this audit. Actual wallet/machine/network tests
remain missing even when their synthetic counterparts pass.

## Q. Remaining risks

1. No funded/configured Team and approved API wallet evidence; no explicit activation.
2. Stale completed candles and zero current scanner opportunities. Eight seconds of
   WebSocket traffic did not provide fresh completed bars. Practice opens on the
   published next-day schedule; future feed behavior needs observation.
3. No prolonged actual LONG/SHORT, partial/exits/cancel/fees/funding/restart proof.
4. Catastrophic protection distance is unapproved and its policy is disabled.
5. Actual full trade/regime/slippage/performance attribution is incomplete; funding
   must not be allocated by guesswork across manual/controlled/strategy exposure.
6. Local ownership locks do not prevent external/manual/other-host activity; committee
   compliance is not locally certifiable.
7. Hash-bound output schema changes require a reviewed new evidence directory.
   Source hashes include an inherited environment; a portable release needs a
   separate nonignored source/dependency manifest.
8. No adequate model data/holdout or demonstrated after-cost crypto edge. No automatic
   optimization or profit/rank guarantee is supported.
9. The published eligibility includes at least 10 distinct trading days and a minimum
   cumulative notional volume. Zero trades risks ineligibility. The exact volume
   threshold/score weights are not assumed; confirm organizer updates. Never create
   artificial trades to satisfy them.
10. Audit work is uncommitted; no COMPETITION_RELEASE or completed jury PDF exists.
    The security scan found no matching secret literals in its stated current-tree
    scope; ignored secrets, Git history and arbitrary credential formats were not
    comprehensively audited.

## R. Final readiness matrix

| Requirement | Status | Proof |
|---|---|---|
| REPOSITORY_INTEGRITY | VERIFIED | CURRENT_SOURCE_CHECK |
| STRATEGY_FREEZE | VERIFIED | CURRENT_HASH_CHECK |
| MARKET_DATA | PARTIAL | RECORDED_PUBLIC |
| PAPER | PARTIAL | UNIT_TESTED |
| REPLAY | PARTIAL | UNIT_TESTED |
| SIGNED_EXECUTION | PARTIAL | UNIT_TESTED |
| WALLET | MISSING | NOT_CONFIGURED |
| USDPR | MISSING | NOT_CONFIGURED |
| API_AGENT | MISSING | NOT_CONFIGURED |
| UNIFIED_ACCOUNT | MISSING | NOT_CONFIGURED |
| VENUE_RULES | PARTIAL | UNIT_TESTED |
| RATE_LIMIT | PARTIAL | UNIT_TESTED |
| NONCE | PARTIAL | UNIT_TESTED |
| CLOCK | PARTIAL | RECORDED_PUBLIC_SAMPLE |
| RESTART_RECOVERY | PARTIAL | UNIT_TESTED |
| RECONNECT_RECOVERY | PARTIAL | UNIT_TESTED |
| PROTECTION | PARTIAL | UNIT_TESTED |
| SINGLE_POSITION | PARTIAL | UNIT_TESTED |
| COMPLIANCE | PARTIAL | UNIT_TESTED |
| ACCOUNTING | PARTIAL | UNIT_TESTED |
| PRACTICE | MISSING | NOT_OBSERVED |
| PERFORMANCE_EVIDENCE | MISSING | NOT_OBSERVED |
| VWAP_RESEARCH | PARTIAL | UNIT_TESTED |
| ML_VALIDATION | MISSING | NOT_OBSERVED |
| HOLDOUT | MISSING | NOT_OBSERVED |
| JURY_EVIDENCE | PARTIAL | ENGINEERING_INDEX |
| COMPETITION_RELEASE | MISSING | NOT_OBSERVED |
| LIVE_READY | MISSING | FALSE |
| HACKATHON_READY | MISSING | FALSE |

The generated dashboard is a conservative observer. Imported `LIVE_TESTNET` labels,
all-green JSON, successful unit tests and caller-supplied receipts cannot authorize
trading or certify the real account/practice phase. Old source evidence remains
historical; its compatibility field must be reviewed rather than silently ignored.

The published [schedule](https://perpetual-alpha26.github.io/schedule) places
practice on October 5–18, scored trading on October 19–November 6 and report/code
submission on November 9. The [evaluation page](https://perpetual-alpha26.github.io/about)
uses return, daily equity volatility and jury assessment; it also states the
distinct-day/volume eligibility requirement. [API/conduct documentation](https://perpetual-alpha26.github.io/docs/)
supports the testnet/par/account separation and venue checks.
The [FAQ](https://perpetual-alpha26.github.io/faq/) describes PDF/code submission
and says detailed reproducibility requirements are still being finalized.

## S. Next highest-priority action

**Provide and manually verify the funded Team Anchorium PUBLIC wallet address and
the approved API wallet PUBLIC address through read-only account checks. Keep
PAPER/false.** Funding, unified mode, agent approval/expiry and fee/budget observations
are the immediate dependency for later controlled certification. Private keys and
seed phrases belong in credential management, never this report or chat. No subsequent
practice activation is inferred from completing these reads.


Artifact: [consolidated validation](hackathon_certification_validation_2026-10-04.json).

Source compatibility: the public PAPER capture predates the final audit-reader/test changes and is explicitly historical. The current-source REPLAY reproduces its decisions and portfolio. No new PAPER performance claim is inferred.

Current broad working-source hash: `75e33621870a1681b718a24ede1ab0d59a7a648f22c6b4670dcd09a5ec98989d`.
