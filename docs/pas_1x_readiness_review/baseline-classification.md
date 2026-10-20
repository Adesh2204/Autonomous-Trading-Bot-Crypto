# Baseline test classification

**Source:** `/workspace/postmerge-audit/repo` at `d629e1bdecfeecfd70f4815dd82c3d1235ec1cd5`. **Input:** `main-broad-venv.xml`. Read-only classification; no production edits, signing, network, secrets, or gate changes.

## Totals: 1982 passed, 121 failed, 1278 errors (total 3381)

| Failed-test root cause | Count | Finding |
|---|---:|---|
| `legacy_fixture_or_policy_mismatch` | 85 | Tests are blocked by missing/mismatched static fixtures or stale policy expectations. In particular, the 60 PAS_DEX_MAPPING_UNVERIFIED failures are not proof of live mapping readiness; live metadata was not queried. |
| `intentional_lockout_or_signing_route_incompatibility` | 7 | Retired routes/old contract are rejected by explicit source guards. This does not prove replacement route readiness. |
| `possible_actual_pas_runtime_regression` | 3 | Three entry-fault variants report FLAT_VERIFIED instead of REJECTED/UNKNOWN/RECOVERY_REQUIRED. Potential PAS behavior defect; not proven harmless and not fixed. |
| `genuinely_unresolved_safety_lockout` | 25 | Do not waive these as obsolete tests. Startup lock readiness has not been demonstrated; UNKNOWN recovery remains locked because the proof fails certification. Keep both guards; investigate with valid evidence. |
| `confirmed_non_pas_paper_collateral_defect` | 1 | One concrete PAR paper-ledger collateral mismatch (USDPR expected, USDP emitted), outside PAS live runtime. |

### Error bucket

**1,278/1,278 errors:** `PAS_DEX_MAPPING_UNVERIFIED`. Static fixtures failed explicit PAS DEX discovery and the fail-closed resolver stopped setup. These results do **not** establish that live DEX identity is valid; no network/live checks were made.

### PAS findings and unresolveds

- **Possible actual PAS runtime regression (3 tests):** `test_pas_uncertain_entry_is_never_repeated` for `[reject]`, `[timeout_before]`, and `[entry_internet_after_fill]` ends with `FLAT_VERIFIED` rather than the accepted `REJECTED`/`UNKNOWN`/`RECOVERY_REQUIRED` states. Duplicate-signature prevention did not fail, but the state transition remains a possible defect; do not waive it.
- **Startup lock (12 tests):** `STARTUP_ENTRY_LOCK_REQUIRED` correctly blocks test entries unless coordinator readiness is established. This run does not prove whether the fixture omitted required evidence or runtime startup cannot become ready. Keep lock; resolve fixture/contract and test before claiming behavior.
- **Unknown-intent lock (13 tests):** `UNKNOWN_INTENT_REMAINS_LOCKED` is not waved away. Source requires certified append-only evidence. The embedded proof contains an obsolete absolute archive path; content/receipt checks pass but whole-descriptor comparison rejects it, so positive recovery semantics did not run. Keep UNKNOWN locked; repair/validate evidence portability separately.
- **No confirmed PAS runtime defect is proven by this run;** the three uncertain-entry cases are plausible and unresolved. One separate, concrete **non-PAS** defect is present: PAR paper execution/account emits `USDP` where its USDPR contract/test expects `USDPR`.

### Largest fixture/policy groups

- stale/incomplete fixture, environment, mutation, or policy assertion: **14**.
- non-active PAS market expected by test: **8**.
- missing_explicit_PAS_DEX_mapping (test blocked): **60**.
- missing_fresh_DEX_discovery_fixture: **3**.

Explicitly, `ACTIVE_PAS_BASE_ASSETS` is BTC/EWY, while several failures expect ten active markets; source documents ten as approved universe but two as current active engine set. Eight signer tests address non-active markets and stop earlier at `PAS_ACTIVE_MARKET_REQUIRED`. These are test-contract mismatches, not proof of a signer bypass.

### Other exclusions and limits

- Retired PAR/scored-session/authorized-terminal write paths and practice-contract reuse account for **7** failures; current source intentionally rejects those routes. This does not validate the replacement launcher.
- The initial system-Python collection had four missing-`pyotp` errors, remedied by the audit venv; they are outside the 121/1,278 counts.
- **No live-readiness claim.** All 1,278 mapping errors and 60 mapping-related failed tests remain a real readiness evidence gap until the current PAS identity is verified through an authorized, fresh source. The report classifies this test run only.

The JSON contains the exhaustive 121-case list with observed message and per-case classification.
