# PAS migration implementation and qualification report

**BLOCKED_EXTERNAL_EVIDENCE**. Updated 2026-10-18T09:27:34.587000+05:30. This task continued across October 17–18; the evidence folder retains its original October 17 name. The reposted V2.0 directive has the same SHA-256 `bcc257f21a2ccf1ab67e87aab2381188f2033bbc24fcbda5c9bf42fd04a328e0`.

Actual source `d37a392acc0c080400d3bd466d10e3be10bb2c1605e7641a7fc1ef733b9ae8c7` on branch `codex/pas-migration-2026-10-17`, based on HEAD `6fdcca2569c3ca7360bc6ef7e53666b545be27c2`. No actual-wallet key, signature, exchange order, cancellation, leverage change, transfer, acceptance or autonomous activation was performed. PAPER/false remains enforced.

## A. Source modifications and root causes

The practice-only client, account currency filters, generic request namespace and terminal contracts could not represent the scored deployment. These are infrastructure changes; `signal_brain.py`, all eight frozen methods and all 32 strategy parameters remain unchanged. Dynamic PAS precision is order normalization, not strategy tuning.

| File | Change | Root cause and fix |
|---|---|---|
| `algo-trading-bot/venue_config.py` | MODIFIED | Explicit PAS PAPER profile; contradictory environment, live mode or foreign signal source still fails closed. |
| `algo-trading-bot/test_pas_migration.py` | NEW | 67 isolated synthetic PAS discovery, accounting, contract, CLI, residual, source/provenance and shared-state tests. |
| `algo-trading-bot/exchange/account_events.py` | MODIFIED | Funding now validates the exact namespace/collateral pair, preventing USDP/USDPR mixing. |
| `algo-trading-bot/exchange/bounded_daily_session.py` | MODIFIED | Explicit expected-DEX hook supports the separate finite scored contract; ordinary practice contracts remain par-only. |
| `algo-trading-bot/exchange/capital_allocation.py` | MODIFIED | Apply unchanged both-side BBO/depth/risk caps to either verified namespace. |
| `algo-trading-bot/exchange/terminal_observer.py` | MODIFIED | Actual PAS streams, selected account currency and unchanged frozen scanner in signer-free observation. |
| `algo-trading-bot/exchange/terminal_recovery.py` | MODIFIED | Final authoritative readback provenance names the actual DEX. |
| `algo-trading-bot/exchange/hyperliquid_account.py` | MODIFIED | Selected collateral and event filtering; canonical Standard versus Unified accounting without adding PnL twice. |
| `algo-trading-bot/exchange/venue_discovery.py` | NEW | Bounded unsigned all-ten-market/account audit with raw receipts, book-only versus account capacity and two terminal readbacks. |
| `algo-trading-bot/exchange/exchange_rules.py` | MODIFIED | Central validation requires the selected client namespace; all account, price, OI, leverage, permit and freshness gates remain. |
| `algo-trading-bot/exchange/hyperliquid_client.py` | MODIFIED | Canonical discovery, runtime PAS assets/precision, exact USDP token mapping, explicit query schemas and no par/pa/native fallback. |
| `algo-trading-bot/exchange/scored_session.py` | NEW | Finite PAS/USDP contract, extra exact acknowledgments, hash-bound original organizer records, source-bound discovery and shared par checks. |
| `algo-trading-bot/exchange/market_health.py` | MODIFIED | Validate completed UTC history in one namespace; retain all frozen warmup/freshness requirements. |
| `algo-trading-bot/exchange/terminal_app.py` | MODIFIED | Explicit --venue, isolated state binding, discover/prepare/approve/start identity checks and accurate PAS/USDP display, including failures. |
| `algo-trading-bot/exchange/pas_readiness.py` | NEW | Separate maintenance/special status checks from deposit metrics and organizer phase permission. |
| `algo-trading-bot/exchange/venue_profiles.py` | NEW | Immutable canonical par/USDPR practice and pas/USDP scored identities. |
| `algo-trading-bot/exchange/long_session.py` | MODIFIED | Bind scored approval/evidence to venue, shared account/nonce barrier, current metadata/status and a separate PAS journal; preserve legacy nonce and global account lease. |
| `algo-trading-bot/exchange/live_readiness.py` | MODIFIED | Expose selected venue/collateral and support verified PAS Standard mode without auto-changing account mode. |
| `algo-trading-bot/exchange/order_lifecycle.py` | MODIFIED | Generic durable requests recognize PAS; selected client/mandate still determine eligibility. |
| `algo-trading-bot/exchange/pas_residuals.py` | NEW | Pure entry/partial/full-close classification with exact fresh positions and no dust rounding; no unproven native/signing capability. |
| `algo-trading-bot/exchange/candle_availability.py` | MODIFIED | Accept one explicit par or pas universe; reject mixed namespaces without changing history requirements. |
| `algo-trading-bot/exchange/rate_limits.py` | MODIFIED | Discovery reads use the existing weighted budget, backoff and reserve machinery; no limits were relaxed. |
| `algo-trading-bot/exchange/sdk_transport.py` | MODIFIED | Official SDK selects the discovered DEX and verifies exact signed venue identity before signer use and again at dispatch. |
| `algo-trading-bot/exchange/scored_prepare.py` | NEW | Fresh discovery plus reviewed provenance and native/residual gates; save concrete blockers instead of fabricating a mandate. |
| `algo-trading-bot/exchange/public_quant_operator.py` | MODIFIED | Strict read-only receipts admit the new documented discovery queries, never exchange actions. |
| `algo-trading-bot/exchange/terminal_evidence.py` | MODIFIED | Read PAS journal without mutating it; reject capacity assembled from mismatched book/spec identities. |

Exact before/after SHA-256 values are in `source_change_manifest.json`. `baseline.json`, `source_before.tar.gz` and read-only database snapshots preserve the starting point. The legacy dependency inventory was regenerated; it classifies retained references and does not import legacy execution into the new core.

## B. Independently verified blockers

| Area | Actual result | Remaining acceptance requirement |
|---|---|---|
| Scored venue | Canonical `pas`, DEX index 271, separate from `par` and `pa`; all ten runtime assets discovered | Repeat current metadata/status/liquidity checks before any action |
| Liquidity | New PAS both-side displayed books observed; table below | Current account, spread, risk, economics and native/residual feasibility must also pass |
| Residual close | Offline exact entry/partial/full-close semantics tested; one/multiple lots and stale/oversize cases covered | Original organizer clarification and genuine exact PAS route proof; full-close IOC does not qualify a native trigger |
| Account equity | Actual Unified account; USDP token 3307 total is zero, independently of per-DEX zero summaries | Organizer/operator funding evidence; no automatic transfer |
| Leverage | Actual PAS markets are 20x CROSS, HYPE 10x; trading policy remains 1x CROSS | Separate scoped configuration authority and fresh readback; no setting was changed |
| Original UNKNOWN | Preserved `par:BTC` CLOID/nonce; current `unknownOid` and empty snapshots are not a terminal outcome | Admissible original outcome or explicitly approved safe isolation under immutable policy |
| Native stop | No genuine PAS natural trigger → linked closing SELL fill → two flat/zero-order readbacks | Separate exact approved qualification; acceptance alone is insufficient |
| Session permission | V2.0 contract added; no actual scored mandate or acceptance created | Original applicable organizer record, funded/qualified account, phase open and fresh exact human approval |

Latest discovery completed **2026-10-18T09:18:18.261000+05:30**, 556326 ms before this report; it is a timestamped snapshot, not continuous account truth. Evidence: `pas_discovery_oct18/discovery.json` and 54 raw `/info` receipts. Canonical collateral token ID is `0xa7ab296859c43140a4e71f1464c137dc`; maximum venue leverage and OI caps remain in the raw metadata/deployment. `perpDexStatus.totalNetDeposit` is a deposit metric, not a market-open flag. No special exchange status was reported in this snapshot. A book cannot identify Keyrock, so quoting identity is unverified.

### Actual displayed PAS book capacity

The quantities below use the minimum of 10% of **each** BBO quantity and each side's available depth within 5 bps, rounded down to the actual lot. They precede spread, funding, leverage, account, capital/risk, signal and protection gates. They are not approved executable trade sizes or guaranteed fills. The old approximately 50 USDPR practice observations were not reused.

| Market | Asset ID | Size decimals | Venue max leverage | Bid / ask | Spread bps | Book-only quantity | Book-only USDP | Authorized USDP | Rejection reasons |
|---|---:|---:|---:|---|---:|---:|---:|---:|---|
| pas:BRENT | 2810006 | 2 | 20x | 106.65 / 106.81 | 14.991 | 9.36 | 999.741600 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |
| pas:BTC | 2810000 | 5 | 40x | 81995.0 / 82069.0 | 9.021 | 0.01218 | 999.600420 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |
| pas:ETH | 2810001 | 4 | 25x | 2427.3 / 2429.5 | 9.059 | 0.4116 | 999.982200 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |
| pas:EWJ | 2810005 | 3 | 20x | 94.798 / 94.94 | 14.968 | 10.532 | 999.908080 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |
| pas:EWY | 2810004 | 3 | 20x | 153.99 / 154.02 | 1.948 | 0.007 | 1.078140 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified; Below ordinary $10 minimum |
| pas:GOLD | 2810007 | 4 | 25x | 4160.2 / 4163.9 | 8.890 | 0.2401 | 999.752390 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |
| pas:HYPE | 2810002 | 2 | 10x | 79.24 / 79.359 | 15.006 | 12.60 | 999.923400 | 0 | No funded USDP; Configured 10x, approved policy 1x; Native/residual unqualified; Spread exceeds 15 bps |
| pas:SP500 | 2810003 | 3 | 50x | 7617.7 / 7624.5 | 8.923 | 0.131 | 998.809500 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |
| pas:USDEUR | 2810008 | 1 | 50x | 1.1237 / 1.1247 | 8.895 | 889.1 | 999.970770 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |
| pas:USDJPY | 2810009 | 2 | 50x | 157.79 / 157.93 | 8.869 | 6.33 | 999.696900 | 0 | No funded USDP; Configured 20x, approved policy 1x; Native/residual unqualified |

Current conservative fee bound is 6 × reported user base rate: taker `0.00270` per leg, reported base `0.00045`. The multiplier was retained conservatively, not represented as an actual charged PAS fee. Actual future fills determine fees. Funding is the actual per-market context; EWY has materially different observed funding and remains independently excluded. No synthetic fill, fill probability, slippage realization or expected profit was invented. Passive/post-only validation and maker-versus-taker cost comparison remain available infrastructure; the autonomous contract retains bounded IOC entry, without assuming passive fills or changing strategy rules.

## C. Read-only terminal verification

Canonical `--venue pas` selects USDP, runtime metadata and a separate terminal state directory. It has no signer. Actual market WebSocket subscription acknowledgments, books and contexts were observed; the full ten-market loop was exercised. A duplicate start was rejected by the owner lock. A graceful stop produced two independent authoritative flat/zero-order snapshots and stopped all collector threads. A subsequent read-only restart recorded `restored_authority=false`. The old October 15/16 workers were absent when their original PIDs were inspected; no old trading heartbeat was resumed.

The first full scan also exposed legitimate limitations: insufficient completed-bar warmup in several markets, an EWY executable-book rejection, four local `INFO_PUBLIC_READ_BUDGET_DEADLINE` results, and an account stream that was connected but not reconciled/healthy at that sampled instant. It was not labeled fully healthy. The market stream had 30/30 confirmed subscriptions and zero missing acknowledgments at that sample. These observations do not qualify signing. No HTTP429 was recorded for those local budget refusals. The subsequent final-source October 18 run completed all ten diagnostics with no recorded HTTP/transport errors, retained actual warmup/book rejections, then stopped flat with no signatures. Some legacy error-code names retain PAR in generic validation; recorded requests, symbols and asset IDs identify PAS explicitly. The initial sandbox discovery failure was recorded as `INFO_DNS_FAILED`, then a permitted public-network run succeeded. Supporting cached ages remain explicit; five-second signing freshness was not relaxed.

Final-source terminal output: `/Users/adesh/Autonomous Trading Bot - Crypto /runtime/pas-migration-oct18/sessions/8975fad88edb437fad82672ee154af36/terminal_result.json`. Current terminal result: `STOPPED`; threads stopped `True`; two-readback terminal flat `True`. The runbook includes the tested public command, dashboard, status and stop commands. It runs locally without Codex/LLM API calls; the Mac/Python process, power and internet remain necessary.

## D. Exact initial human approval

`ScoredLimits`/`ScoredLongMandate` preserve finite scope: canonical pas/USDP, named team/API/sole host, LONG-only, exactly one global position, at most two entry attempts and 12 signed actions, bounded owned cancellation/recovery, 1x CROSS, fixed capital/risk/economics/liquidity limits, source/release hashes and hard expiry. Routine in-scope BUY/SELL decisions do not prompt again. No restart, midnight or date rollover restores/renews approval. Default proposal length is 60 minutes; CLI proposal maximum is 12 hours; the typed scored contract cannot exceed 24 hours or the conservative scored end boundary.

The new contract starts no earlier than **October 19, 12:00 UTC / 17:30 IST**, subject to original organizer confirmation. Until a precise final-day cutoff is supplied, it conservatively excludes time at/after November 6 00:00 UTC; that is a local restriction, not a claimed official cutoff. Original organizer provenance, its raw file hash, scope, source-bound discovery and extra PAS risk acknowledgments are mandatory. Symlink escape, missing provenance, stale/mismatched source, wrong collateral and practice approval are rejected. No real mandate/acceptance was manufactured during this task. The actual PAS prepare command was also exercised: it wrote an unsigned proposal listing the unresolved prerequisites and created neither mandate.json nor acceptance.json.

## E. Autonomous launch and protection limits

The scored builder is wired to the official SDK, central validator, global account lease, durable nonce manager, risk allocator, frozen scanner, account reconciliation, independent protection manager and finite lifecycle. PAS uses its own execution journal but retains the existing nonce domain. At startup UNKNOWN stops construction before key access. Each PAS preflight also rechecks shared par exposure/orders, venue status and current PAS metadata. Owned known PAS protection can be managed; UNKNOWN remains a hard barrier. Exact venue identity is checked before signer construction and again at dispatch.

The operator launch command is documented and its CLI/failure gates are tested. **An actual PAS signed launch and unattended BUY/protect/SELL cycle were not executed or qualified.** Missing venue-controlled proof prevents that positive test. Native Stop Limit below-minimum residual handling remains excluded; the full-position IOC clarification is not a native-stop exemption. The pure PAS residual planner grants no transport permit. Existing genuine par exact-size close scopes remain par-only and cannot certify PAS. A supported narrow native/residual transport extension must be reviewed against actual PAS route evidence before using it for a subminimum position; it is not automatically enabled by adding a green JSON flag.

The existing native state machine distinguishes submission, acknowledgement, armed coverage, trigger/child-order state, actual fills and final reconciliation. Rejections, partials, gaps, orphan orders, stale data and disconnection remain independent failure states; a Stop Limit can remain unfilled through a gap. There is no new verified protective stop in this task.

## F. Shutdown and recovery

Graceful stop and duplicate-worker rejection were verified against real public runs. Manual stop disables new entries; only an already-valid exact mandate could permit owned bounded risk actions before hard expiry. After expiry the process cannot sign even to close. It reports remaining/uncertain positions and requires human review. Public reconciliation continues independently of expired signing authority. No blind retry of UNKNOWN, nonce reset, hidden signer, automatic extension or loss-cap guarantee exists. `stop` is a request: verify final `threads_stopped` and two authoritative readbacks with `status`/`report`; a process kill or lost Mac/network is not proof of flatness.

## G. Verified accounting

PAS has **no reported fills**, no reported funding events, no positions and no open orders in the completed history/snapshots. Actual observed PAS gross, fees, funding and net are **0 USDP**. USDP collateral/equity is zero; return percentage and empirical performance statistics are **undefined/unavailable**, not profitable or competition-ranked. Unified accounting takes the selected USDP balance once and reports position fields separately, without adding per-DEX equity or unrealized PnL again. Canonical Standard mode (`disabled`) is separately tested using selected-DEX margin fields. The account mode was not changed.

The original October 15 practice round trip remains separately preserved: BUY 0.0002 par:BTC at 81,512, OID 62755970305, fill 800659111758533, fee 0.014672 USDPR; SELL 0.0002 at 81,909, OID 62805581662, fill 260274449763192, fee 0.014743 USDPR. Gross +0.0794, fees 0.029415, actual funding +0.000527, net **+0.050512 TEST USDPR**. This is not today's PAS PnL, USDP funding or an official score. Original proof hashes match the baseline.

## H. Qualification, forensics and release evidence

Current full-regression receipt: `regression_release_v2/test_receipt.json`, passed `True`, totals `{'tests': 2850, 'failures': 0, 'errors': 0, 'skipped': 0}`; source before/after `d37a392acc0c080400d3bd466d10e3be10bb2c1605e7641a7fc1ef733b9ae8c7` / `d37a392acc0c080400d3bd466d10e3be10bb2c1605e7641a7fc1ef733b9ae8c7`; XML SHA-256 `6078c7a576ecac28d3900128de52efaa9f41abf316de49a16e671227f7a3c117`. Separate nine 4,900/5,000/5,100 ms signing-boundary tests: `signing_boundaries_v2.xml`, SHA-256 `1d6e0067c2f53a929da25a58303eca525607dca33207bed93643810154c69066`. Tests include offline ephemeral SDK signatures only. They do not qualify an actual wallet or native order. Strategy freeze and phase-zero checks pass before/after when the release receipt is complete.

The first full run remains preserved: 2,846 passed, two new PAS fixture failures because older suites install practice environment defaults during import. The correction explicitly selects PAS inside synthetic PAS fixtures and adds contradictory-environment rejection tests; no production guard was weakened. Earlier focused failures and command-selection mistakes are retained in their logs. The old 2,783-test receipt/XML remains historical and unchanged.

Preservation audit: `True`. Original qualification, nonce and configuration SQLite logical dumps match the pre-change baseline; integrity checks are `ok`, recovery snapshot checksums validate, the original UNKNOWN and nonce 1792217834069 remain intact. Full original signing-source/timeline and admissibility records remain in `docs/practice_recovery_2026-10-17/`. New exact-CLOID readbacks completed 2026-10-18T09:18:12.328000+05:30, returning `unknownOid` twice with stable empty par position/order snapshots. There is no matching positive original terminal record or original explicit guard failure. Reconstructed 5,526 ms timing alone cannot substitute for one. No certificate was broadened. `unknown_scope_verdict.json` records the shared-account/signer/nonce analysis: approved safe isolation is not established.

Protocol references: [official perpetual info schemas](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals), [account abstraction accounting](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes), [rate and user limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits), and [native TP/SL behavior](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl). These protocol descriptions do not grant team competition permission or establish PAS qualification.

Formal order provenance retains CREATED request → durable PERSISTED identity → pre-HTTP DISPATCHED audit → ACKNOWLEDGED response → verified TERMINAL result → account RECONCILED state. An acknowledgement is not a fill; HTTP uncertainty is preserved as UNKNOWN. Durable CLOIDs, consumed authority and nonce records prevent duplicate retransmission. Original source evidence is not retroactively reconstructed into a successful non-transmission certificate.

`PAS_ORGANIZER_ADDENDUM_DRAFT.txt` is prepared but **not sent**. The earlier exact authorized par request was already sent and was not duplicated. No original applicable PAS organizer confirmation has been placed in this evidence set. No organizer whitelist/reset or maker identity is claimed. No PAS qualification or EXIT_RECOVERY_PROOF was created without real closing records.

## I. Release decision

**BLOCKED_EXTERNAL_EVIDENCE**. The software migration and unsigned diagnostic paths are implemented and tested to the limits above. This is not an autonomous trading qualification. The account must receive verified USDP collateral, authorized/read-back 1x CROSS settings, admissible historical-order resolution (or approved isolation), original organizer scope, genuine PAS native/residual route qualification, usable current data/economics and one fresh exact session approval before any actual signing. Frozen strategy edge and competition performance remain unproven; target-scenario arithmetic is not an empirical expected return. No profit, fill, ranking, loss cap or zero-error guarantee is made.
