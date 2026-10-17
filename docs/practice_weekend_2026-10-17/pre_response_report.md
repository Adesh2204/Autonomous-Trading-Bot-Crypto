# October 17–18 practice release — engineering and qualification report

Generated 2026-10-17T11:22:29.804000+05:30. **Engineering release passed; autonomous trading has not started. Native Stop Limit trigger/closing and subminimum-residual protection remain unqualified.** PAPER/false and the frozen strategy are unchanged. No actual-wallet signature, order or acceptance was created in this task.

## A. Dynamic pricing and tests

The previous approved cap 81,410 could not buy a fresh ask of 81,412. The new versioned corridor binds the initial ask, permitted movement and hard maximum BUY price before approval. One fresh correctly rounded IOC price is selected before reserving its durable intent. Final signing checks validate that same wire against fresh market/account data. Movement beyond either bound, deteriorated fees/funding/depth or stale evidence blocks it; no mandate mutation, uncertain retry or duplicate entry is permitted. Even a failed public preflight consumes this new invocation and requires a new human decision.

28 new corridor tests cover the previous small crossing, both corridor edges, inward rounding, independent bps/absolute caps, liquidity/fees/funding, stale account/quotes, leverage, exact approval, expiry, immutable durable wires, duplicate calls and consumed-preflight restart prevention. 23 new practice-contract tests cover dates, <=24h scope, expiry, revocation, unchanged risk caps, midnight carry and missing evidence. The earlier 151-test focus passed before adding the final consumption test; all 51 new tests are also in the full regression below. All signatures in these tests use isolated offline fixtures.

## B. Native Stop Limit and residual findings

[Official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes default position-sized TP/SL, fixed explicit sizes, parent-child cancellation risks and the possibility of an unfilled triggered limit. [The API schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) exposes `positionTpsl`; it does not establish the required `par` subminimum exemption. The pinned SDK is 0.24.0. No unproved zero-size sentinel or native-minimum bypass was introduced.

The unsigned audit made 77 bounded /info requests with 0 recorded errors: ten permitted markets, six public accounts and three histories. Two histories reached the 2,000-row bound. No native candidates or actual native parent/child closing proof appeared. This is limited evidence, not proof that the venue prohibits position-associated small stops. See `native_stop_findings.json` for all eight requested questions and exact scope.

The historical exact one-lot IOC SELL is preserved; it proves only that scoped IOC recovery path. The supervised two-lot test can investigate an ordinary-minimum full-size native stop and safely attempt the authorized one-lot abort. Even successful full-size trigger proof alone cannot qualify unattended one-lot native protection. Existing partial-fill guards remain active.

## C. Current observed LONG capacity

Snapshot 2026-10-17T11:06:51.722000+05:30; ages grow after capture and this table is not an executable quote. Liquidity-only estimates enforce 10% both-side best-book/raw depth and 1x observed capacity, capped at 1,000; they exclude pending native/partial and full strategy gates. Values below 10 cannot satisfy an opening minimum.

| Market | One-lot mark value, TEST USDPR | Liquidity-only LONG notional | Qualified unattended notional |
| --- | ---: | ---: | ---: |
| par:BRENT | 1.0723 | 49.3396 | 0 |
| par:BTC | 8.14280 | 48.86640 | 0 |
| par:ETH | 0.24244 | 49.94264 | 0 |
| par:EWJ | 0.094874 | 50.005449 | 0 |
| par:EWY | 0.15065 | 49.8817 | 0 |
| par:GOLD | 0.41650 | 9.99720 | 0 |
| par:HYPE | 0.7964 | 9.56016 | 0 |
| par:SP500 | 7.6318 | 99.2329 | 0 |
| par:USDEUR | 0.11237 | 50.01355 | 0 |
| par:USDJPY | 1.5819 | 49.0482 | 0 |

Every runtime minimum lot is below 10 at the observed mark. A valid LONG SELL stop below mark with its limit below trigger is lower still. No permitted alternative market currently avoids that one-lot native minimum issue. Supported unattended capacity is therefore **0**. A 20,000 bankroll is a proposal, and larger desired notionals are research targets.

## D. Regression, source and preservation

**2726 passed; 0 failures, 0 errors, 0 skipped.** Full original 2,675 baseline plus 51 new tests. Source before/after: `88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f` / `88429ed4fabb3f1564b4c0bb281466e841cd6fa3e522bd3092172d78a3a7fc5f`. Regression XML SHA-256: `a8ae85f2d1130124eff7bd986c5287765d46e68d98431211a9feb3b4bf3cd173`. Receipt SHA-256: `64b790a3ee4ee42c4cf8b482a71e26f0ec52bfd1b81651e684a3ee1bfd7e575d`. Requirements SHA-256: `db76f769d0aae03197e922f579ce6db9aa6aced9587da93e11b4bba409774b4d`. Strategy freeze and Phase-0 passed before and after. SDK 0.24.0 and all dependency pins match local diagnostics.

Preservation receipt passed: original strategy/proofs/configs/locks unchanged; all three actual-account SQLite logical dumps unchanged, integrity OK; both recovery checkpoint checksums valid; raw historical intents and immutable UNKNOWN certificate preserved. Actual nonce remains 1792082604141. The public evidence audit ran concurrently with engineering, so its before/after source hashes differ; it is explicitly not stable-source execution certification. Final release and new proposal must match the stable hash above. The legacy dependency occurrence inventory was refreshed.

## E. New exact qualification and autonomous session scope

New **supervised qualification** mandate: `206517755e77aafd6c989f0129b5fd14bd784cafed50c95a48324d150f94e977`. Approval deadline: **2026-10-17T11:26:49.423000+05:30**. No acceptance exists.

- One TESTNET `par:BTC` LONG BUY IOC, exactly **0.0002 BTC**, maximum notional 25 TEST USDPR and **1x CROSS**.
- Initial bid/ask 81411.0 / 81459.0. Approved current-ask corridor **81378–81540**; maximum BUY limit **81580**. Each actual wire is rounded from its fresh ask with at most **5 bps** slippage; it is frozen before durable intent/SDK signing. The immutable proposal permits neither widening nor repricing an uncertain submission.
- Maximum adverse and favourable movements are separately the smaller of 10 bps and 100 USDPR/BTC, with runtime rounding inward. Fresh spread <=15 bps; exact quantity <=10% of both best bid and ask quantities; fresh source, fee, funding, margin, account, clock, rate and sole signer/nonce gates remain mandatory.
- Computed taker fee ceiling **0.09000%**, absolute current funding-rate ceiling **0.0002490164**. Worst approved one-boundary funding reserve **0.00406295158240** TEST USDPR is an estimate, not a cashflow.
- Full two-lot entry uses one independent, fixed-size reduce-only SELL Stop Limit: mark trigger **80597**, limit/floor **80195**. This does not claim `positionTpsl` or subminimum native support.
- Exactly 0.0001 BTC partial entry is immediately aborted with the separately approved exact-position reduce-only IOC path; no small native stop is placed. All cleanup prices must remain >=**80195**, with <=20 bps route slippage, <=2 resolved IOC cleanup attempts, <=1 owned cancellation round and <=6 signed actions total. Uncertain order/child/cancellation halts competing submissions.
- Estimated immediate cleanup net at the current selected BUY limit: **-0.0469238000 TEST USDPR**, before funding. At the maximum approved BUY limit: **-0.0631383800**. Planned loss at the floor, including fees: **0.306119500**, plus the conservative funding reserve, within the **10 TEST USDPR test budget**. This budget is not a guaranteed loss cap.
- Authority lasts at most **five minutes after genuine acceptance**; a natural trigger may be observed for at most 120 seconds, shortened to reserve cleanup time. No forced trigger. Accepted-but-untriggered native protection remains INCOMPLETE. A rejected/unfilled/partial/uncertain order, gap or outage may leave exposure.

The approval must explicitly allow this one supervised test while native protection is still unqualified. The request also says “Do not create new BUYs while actual native protection remains unqualified”; no BUY may proceed without that narrow, exact human exception. It grants no autonomous or future trading authority. Wallets: team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; API `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`; this Mac is the sole signer host. The consumed `aac5cd9405582382d7e79d355853211751bef350ffd45e653ae1f487e01437a0` is preserved and will not be rerun.

The new `EXACT_APPROVED_PRACTICE_WEEKEND_LONG_TESTNET_V1` contract is implemented separately from the expired October 16 contract. A future exact autonomous mandate may start/accept October 17, end October 18, last <=24h and never exceed October 18 23:57 IST. Entries stop 15 minutes before expiry; scheduled risk closure begins five minutes before expiry; signing and owned recovery end at hard expiry. It carries attempts, allocation, realized P&L, peak equity and drawdown through midnight. TESTNET `par`, LONG only, one global position, two total entry attempts, 1x, <=0.5% trade risk, <=1% session loss, <=12 signed actions and <=2 owned cancellation rounds remain fixed. Observation can continue without extending signer authority. No Oct19 rollover.

**No executable autonomous session ID, mandate ID, approval deadline, acceptance or authorized bankroll exists**, because native and partial-residual prerequisites fail. These fields remain null in the saved summary. No fake session ID was invented to fill this report.

## F. Local terminal commands

CLI grammar and local `doctor` were verified with the matching source. The standalone application has no LLM runtime dependency. The saved `operator_commands.md` gives diagnostics, qualification and future session commands. A complete verified autonomous execution command cannot yet name a real accepted session or validated native proof; the future command is explicitly a gated template and has not been executed. The user need not type or edit anything: ordinary commands will be performed after valid exact consent and prerequisites.

## G. Worker and exchange execution evidence

Actual trading worker **NOT STARTED**, PID null. Actual orders/signatures this task: **0 / 0**. No observer was substituted for trading. Process inspection identified only the offline regression worker, not an execution-enabled worker. Both old heartbeats are PAUSED. Fresh mandatory account/source/book/fee/funding/nonce checks remain necessary after any approval.

The account was authoritatively flat with zero open orders twice at 2026-10-17T11:07:49.670000+05:30 and 2026-10-17T11:07:52.640000+05:30. This is timestamped snapshot evidence, not a currentness guarantee. Actual account equity was 1,000,000.050512 TEST USDPR with margin used zero. There is no verified protective stop. Mac/process/power/internet interruption can stop local supervision; caffeinate does not guarantee availability or remote failover.

## H. Actual fills, fees, funding and P&L

This task: zero submitted orders, BUY/SELL fills and completed round trips. Realized P&L, trading fees and funding attributable to its nonexistent execution are **0 TEST USDPR**. No autonomous session drawdown or remaining authorized budget is asserted; those fields are null. Offline results are not real earnings.

The existing **October 15** trade remains separately verified: BUY 0.0002 BTC @81,512, order 62755970305, fill 800659111758533, fee 0.014672; SELL @81,909, order 62805581662, fill 260274449763192, fee 0.014743. Gross +0.0794, total fees 0.029415, reported funding +0.000527, **net +0.050512 TEST USDPR**. The new public audit recovered these same prior events; they are not October 17 earnings. Both original proof files are preserved. No organizer whitelist/reset evidence is claimed.

## I. Exact blocker and next action

The small fixed-price approval failure is repaired and offline verified. Genuine native Stop Limit trigger/child fills and subminimum-residual native support are still missing. The next admissible execution is only the exact supervised qualification above, after a genuine new approval explicitly permits that narrow BUY exception and loss-making cleanup. No uncertain retry, widened price, revived approval, silent stop bypass, automatic session renewal or guaranteed profit is permitted.

After any approved test: preserve actual parent/child/fill IDs, fees/funding and real net P&L; require two authoritative flat/zero-order reads. If the stop is accepted but never naturally triggers, record INCOMPLETE, perform only authorized settled-order cleanup and request a new human decision. Autonomous LONG activation remains blocked until all real native/partial prerequisites and a separate exact session approval exist.
