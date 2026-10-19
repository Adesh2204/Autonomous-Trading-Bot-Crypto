# Anchorium PAS V3 final release and operator report

**Final status: BLOCKED_EXTERNAL_EVIDENCE. Trading: NO-GO. Public observation: READY_FOR_OBSERVATION.**

Report evidence captured at 2026-10-19T00:58:32.711000+05:30. This preparation made no actual-wallet signature, exchange order, cancellation, leverage change, transfer, mode change or actual human acceptance. PAPER/false, the frozen strategy and the shared uncertainty barriers remain enforced. The standalone public observer has no signer.

## Release and preserved evidence

Started from exact source `5ff45dbbafa905e4eda58d3cd50152df2fe739dd0b41b9853de74315f4a54a6d` and the preserved 2,927-test XML/receipt. Final source: **`6d37a929e23e295cd35a4aa137a077b6533b711bf085d292fff8c2103420ca42`**. Complete final regression: **2979 passed, zero failures/errors/skips**. XML SHA-256: `db85c3cdcf8557d8cb299e433a68590aa12411720b70a45f0b94e394644cdb0a`. Source before and after, pinned dependencies, strategy-freeze and production-policy checks match. See [release receipt](regression_release_final/test_receipt.json), [XML](regression_release_final/regression.xml), [change manifest](change_manifest.json) and [preservation receipt](preservation_receipt.json).

All 53 original journal logical dumps/integrity checks match the starting baseline. Original BUY/SELL proofs, consumed invocation/nonce records, both historical test releases, the frozen brain and preceding native repair modules remain unchanged. No strategy thresholds, VWAP/EMA/ATR/state rules, 300-bar warmup, 0.40% ATR screen, 15-bps spread, Top-3 weights or capital/risk/session limits were changed. Legacy occurrence inventory was regenerated.

Three interrupted runs are retained as **uncertified**, not passing releases: one exposed a test fixture inheriting the par environment and sandbox Git LFS filtering; later real serialized evidence exposed the embedded-plan hash mismatch, and targeted snapshot review prevented stale native-test quotes after broad discovery. The PAS fixture now selects its explicit environment, Git provenance runs with a read-only LFS filter override, and the actual embedded-plan structure has a regression. Only the final completed source-matched receipt certifies this source.

## Implemented software changes

1. **Canonical USDP funding watcher:** exact team wallet, runtime token mapping, Unified/Standard separation, ZERO/POSITIVE/UNAVAILABLE/STALE states, response hashes, explicit ages, durable funding events and terminal updates. Unified collateral is counted once. Credit triggers read-only reassessment and capacity refresh; it never signs or creates approval.
2. **Deterministic diagnostic readiness:** official calendar, funding, 1x, shared historical state, native/residual proof, warmup, executable setup, release and exact approval are separate logical gates. A public controller cannot manufacture session acceptance or AUTHORIZED_TRADING. Actual authority remains in the existing bounded worker.
3. **Durable authentic history:** SQLite WAL/FULL storage with canonical DEX/token/asset/precision binding; completed UTC candles only; numeric-format-safe deduplication; conflict/future/gap rejection; bounded incremental backfill and restart recovery. Reports include returned snapshot counts, unique completed bars, contiguous tail, missing intervals, timestamps, cache age and warmup. No missing bars are filled and no par/mainnet data is substituted.
4. **Fresh post-backfill signal observations:** slow candle recovery no longer ages the book/context before signal explanation. Capacity retains its own freshness checks. Existing production signal/ranking policy is unchanged.
5. **Exact PAS configuration-only workflow:** fresh ten-market plan review, genuine TTY plan-hash approval, source/release binding, finite signed expiry, existing shared nonce store and global leases, durable invocation/action consumption, exact 1x CROSS SDK wires and authoritative readbacks. Unsupported actions and uncertain retries remain blocked. Canonical validation now handles the discovery file embedding its own plan without weakening any other evidence hash.
6. **Dedicated native test preparation:** separate unsigned PAS experiment scope and staged telemetry, with no ordinary autonomous-native proof prerequisite merely to prepare it. Entry/stop/trigger/child/closing fill/flat milestones remain distinct; synthetic telemetry never qualifies a venue. Existing par native fixes and exact historical close scopes are untouched.
7. **Fee and terminal reporting:** documented PAS 2x base-fee scenario is distinct from the unchanged 6x stress/signing guard and actual fill charges. Target-scenario profit remains separate from expected/realized PnL. The dashboard exposes readiness, funding, ages, history, capacity, actual exposure/cashflows and the next required action.

The 52 added deterministic/adversarial cases cover funding arrival/disappearance, wrong wallet/token/mode, stale/future evidence, UTC boundaries, history restart/dedup/gaps/conflicts/numeric representations/deployment changes, configuration source/hash/expiry/host/scope, exact offline SDK wires and one-use actions, native milestone/partial-fill separation, and the serialized discovery-plan reproduction. The preserved complete suite also exercises partial/rejected/uncertain orders, triggered-unfilled gaps, dust, disconnect/recovery, duplicate workers, nonce/clock/rates, expiry/loss, shutdown and accounting. Ephemeral offline signatures are not real venue qualification.

## Actual account and market evidence

Final unsigned PAS discovery completed at `2026-10-18T19:14:36.929000+00:00` on the final source. It resolved canonical PAS and USDP from runtime metadata and obtained two authoritative flat/zero-order readbacks. Mode: **unifiedAccount**. USDP balance: **0**. Exact organizer credit origin/reset amount: **UNKNOWN**. Actual 1x CROSS: **0/10**. No configuration action was performed. [Discovery and raw receipts](native_qualification_release/fresh_discovery/discovery.json), [funding](native_qualification_release/fresh_discovery/funding_evidence.json), [exact unsigned plan](native_qualification_release/fresh_discovery/account_configuration_plan.json).

Book-only notional below is a dated, lot-rounded bound from both 10% best levels and five-bps depth. It excludes funding, approved allocation, margin, risk, protection and authorization. It is not a recommended trade size. History columns come from actual continuous collection; their independent timestamps/ages are in the JSON. Authorized capacity remains zero everywhere.

| Market | Runtime asset | Current leverage | Book-only USDP | Unique completed / contiguous tail | History ready | Frozen decision | Authorized USDP |
| --- | ---: | --- | ---: | --- | --- | --- | ---: |
| pas:BRENT | 2810006 | 20x cross | 49.2338 | 0 / 0 | False | NO_TRADE | 0 |
| pas:BTC | 2810000 | 20x cross | 49.448430 | 6 / 6 | False | NO_TRADE | 0 |
| pas:ETH | 2810001 | 20x cross | 49.89728 | 60 / 60 | False | NO_TRADE | 0 |
| pas:EWJ | 2810005 | 20x cross | 49.999140 | 2 / 2 | False | NO_TRADE | 0 |
| pas:EWY | 2810004 | 20x cross | 49.93274 | 951 / 951 | False | NO_TRADE | 0 |
| pas:GOLD | 2810007 | 20x cross | 49.91520 | 0 / 0 | False | NO_TRADE | 0 |
| pas:HYPE | 2810002 | 10x cross | 49.4336 | 6 / 6 | False | NO_TRADE | 0 |
| pas:SP500 | 2810003 | 20x cross | 228.3720 | 1 / 1 | False | NO_TRADE | 0 |
| pas:USDEUR | 2810008 | 20x cross | 49.96905 | 0 / 0 | False | NO_TRADE | 0 |
| pas:USDJPY | 2810009 | 20x cross | 49.0451 | 6 / 6 | False | NO_TRADE | 0 |

[Market-by-market evidence, gaps and reasons](market_readiness.json). Sparse or old exchange candles remain unavailable/stale; local caching cannot repair unavailable upstream history. No fresh executable positive-edge LONG is inferred from an incomplete strategy window. The 2x published fee scenario does not silently lower the existing stress guard.

The actual serialized old plan and new plan were separately verified; [original plan hashes](original_plan_verification.json) and [final actual workflow validation](actual_workflow_validation.json) retain the evidence. The final targeted proposal used a 730 ms book, 553 ms context and 382 ms account observation; no stale-quote blocker remained.

## Historical UNKNOWN and consumed attempt

Question A, original outcome: **BLOCKED**. Question B, independently safe PAS isolation: **BLOCKED**. Exact original CLOID `0xac0eea156fcec80986dd67c9057b6ded`, nonce `1792217834069`, source `88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f` and mandate `59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea` remain preserved. Fresh original-CLOID reads returned no admissible new causal/terminal resolution. Current flatness, expiry or unknownOid do not prove nontransmission. The older certificate concerns a different CLOID and was not reused. The consumed native attempt remains do_not_restart. No row, nonce or marker was cleared, and no isolation certificate was fabricated. [Forensic disposition](historical_disposition.json).

## Native qualification: precise remaining limitation

**Actual PAS native and residual protection remains UNQUALIFIED.** The new preparation command creates a dedicated unsigned proposal, not an executable exception or an acceptance. It is separate from an ordinary scored mandate. Its fresh recorded proposal hash is `470bba7a8333a41d3202a27b2b42a234a8c1ac1cf5a0f3492dfd3a6fddc6a23e`; its current price/quantity values are stale once their recorded freshness window expires and must be refreshed, never reused as authority.

The proposal describes one explicit LONG entry, an independent fixed-size mark-triggered reduce-only Stop Limit, grouping na, bounded cleanup/action/time limits and the risks. A possible one-lot PAS partial can fall below the documented ordinary minimum. The retained par IOC exception cannot establish PAS cleanup or a native residual stop. This release does **not** contain an executable PAS subminimum qualification exception. An admissible residual cleanup policy, independent consumed-attempt review, genuine funded/1x/clean account evidence, applicable permission and exact new test approval are required before any narrow execution integration can be qualified. Ordinary session approval cannot bypass this missing scope. A triggered order without closing fills is not a closed position; actual raw linked fills, USDP fees/funding and two flat/zero-order readbacks are required.

## Blocker truth table

| Blocker | Final status | Remaining independently verifiable requirement |
| --- | --- | --- |
| Release consistency | VERIFIED_RESOLVED | None for offline release |
| Funding detection | SOFTWARE_READY_EXTERNAL_PROOF_MISSING | Actual USDP credit and original organizer origin record |
| PAS 1x CROSS | AUTHORIZATION_REQUIRED | Fresh funded clean account, separate approval and authoritative final readbacks |
| Historical UNKNOWN outcome A | BLOCKED | Admissible original terminal/causal record |
| Independent PAS isolation B | BLOCKED | Independently justified and explicitly authorized policy; preserve original row and nonce |
| Consumed native attempt | BLOCKED | Independent review; no authority inherited by a new test |
| PAS native/residual qualification | BLOCKED | Admissible PAS residual cleanup scope, funded/1x/clean account, permission and new exact test approval; future narrow integration review |
| History and frozen signal readiness | SOFTWARE_READY_EXTERNAL_PROOF_MISSING | Sufficient fresh authentic 300-bar history and a valid frozen LONG signal |
| Executable economics | SOFTWARE_READY_EXTERNAL_PROOF_MISSING | Qualified protection, funding/margin, fresh signal and exact approved risk bounds |
| Scored calendar | SOFTWARE_READY_EXTERNAL_PROOF_MISSING | Official opening plus independent account eligibility requirements |
| October 17–18 special practice permission on PAS | NOT_APPLICABLE_WITH_PROOF | Not applicable to open PAS scored phase; team provenance remains separate |
| Finite autonomous signing | AUTHORIZATION_REQUIRED | Fresh genuine exact session approval after every prerequisite |
| Standalone observation | VERIFIED_RESOLVED | Mac/Python/power/internet/exchange must remain available |

[Full truth table](blocker_truth_table.json) includes each initial cause, code repair, offline verification and actual exchange evidence. No external condition is marked resolved by a synthetic PASS.

## Standalone operation and actual PnL

The public worker is a separate local process; its latest launch, matched command/source/session/output and owner evidence are in [verification](public_observer_verification.json) and [launch receipt](public_observer_release_launch.json). Report-time session: `6665be4ba11a4c6baf3be6cab8638777`, PID `21050`. Running status is a dated observation, not a permanent claim. The earlier validation worker was deliberately stopped with threads stopped, clean history checkpoint/integrity and two real flat readbacks; see [completed validation](completed_public_validation.json). It restored no authority when public collection resumed. A duplicate public owner was actually rejected.

One actual account WebSocket disconnection was recorded and recovered through reconnect generation 2 and fresh REST reconciliation. One INFO_READ_CANCELLED record has no HTTP status and is not evidence of HTTP429. Final matched process health was healthy; the original error/recovery records remain in [observed recovery](observed_recovery.json). No worker or signer was blindly restarted by that recovery.

No PAS trade was submitted during preparation. Actual observed PAS fill fees, funding and reported realized PnL are retained in [release summary](release_summary.json) and raw account receipts; unknown/incomplete accounting stays unknown. With zero initial USDP equity, a percentage return is undefined. The verified October 15 practice net `+0.050512 TEST USDPR` remains separate and is not today’s PAS PnL or an official score. No organizer whitelist/reset or guaranteed profit is claimed.

Continuous public collection depends on this Mac, Python process, power, internet and exchange. It runs independently of Codex/app. Process-bound caffeinate does not guarantee operation through lid closure, power failure, network loss or process interruption. Source drift or a critical collector failure stops it; it never restarts a signer or renews a session. A running account snapshot is not terminal flatness proof.

## Exact commands and opening playbook

The [operator runbook](OPERATOR_RUNBOOK.md) contains verified CLI interfaces for public observation, funding verification, PAS configuration review/approval/application, native qualification preparation, exact human trading acceptance, conditional authorized launch, dashboard/status, graceful stop, emergency review and PnL reconciliation. Missing evidence variables represent actual future artifacts; no example/fake approval or proof is supplied.

At opening: verify the official window → genuine USDP credit/provenance and account/signer eligibility → separately approved actual 1x configuration → admissible UNKNOWN disposition/independent isolation → genuine separately authorized native/residual qualification → authentic market history and account exposure → current complete release → fresh exact finite session mandate → genuine initial human acceptance → authorized worker → verify first entry/protection and actual accounting. Any failed condition keeps trading disabled. Inside one valid mandate the existing lifecycle has no per-trade prompts; two-entry/twelve-action/global-position/risk/loss/expiry constraints remain. No automatic midnight reset, renewal or next session is granted.

Official sources reviewed: [schedule](https://perpetual-alpha26.github.io/schedule), [participant guide](https://perpetual-alpha26.github.io/docs/), [exchange action documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint). The published scored window is October 19 12:00 UTC to November 6 12:00 UTC. The October 17–18 practice exception is not imposed on the open PAS phase; independent team/account evidence remains required.
