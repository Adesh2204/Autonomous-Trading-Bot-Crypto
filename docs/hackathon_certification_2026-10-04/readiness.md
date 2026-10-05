# Team Anchorium certification audit

Verdict: **ACCOUNT_SETUP_REQUIRED**

This report indexes engineering evidence. It grants no trading permission. Missing measurements remain null.

| Component | Status | Proof | Remaining requirement |
|---|---|---|---|
| REPOSITORY_INTEGRITY | VERIFIED | CURRENT_SOURCE_CHECK | Uncommitted audit changes must be reviewed/versioned before release. |
| STRATEGY_FREEZE | VERIFIED | CURRENT_HASH_CHECK | No strategy change is permitted. |
| MARKET_DATA | PARTIAL | RECORDED_PUBLIC | Continuous healthy candles/books/context and prolonged observation required. |
| PAPER | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| REPLAY | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| SIGNED_EXECUTION | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| WALLET | MISSING | NOT_CONFIGURED | Verify the funded Team wallet, separate approved API address, unified mode and permissions using read-only queries and human review. |
| USDPR | MISSING | NOT_CONFIGURED | Verify the funded Team wallet, separate approved API address, unified mode and permissions using read-only queries and human review. |
| API_AGENT | MISSING | NOT_CONFIGURED | Verify the funded Team wallet, separate approved API address, unified mode and permissions using read-only queries and human review. |
| UNIFIED_ACCOUNT | MISSING | NOT_CONFIGURED | Verify the funded Team wallet, separate approved API address, unified mode and permissions using read-only queries and human review. |
| VENUE_RULES | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| RATE_LIMIT | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| NONCE | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| CLOCK | PARTIAL | RECORDED_PUBLIC_SAMPLE | A past sample is not current runtime/NTP health. |
| RESTART_RECOVERY | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| RECONNECT_RECOVERY | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| PROTECTION | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| SINGLE_POSITION | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| COMPLIANCE | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| ACCOUNTING | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| PRACTICE | MISSING | NOT_OBSERVED | Requires real account/practice/release evidence. |
| PERFORMANCE_EVIDENCE | MISSING | NOT_OBSERVED | Requires real account/practice/release evidence. |
| VWAP_RESEARCH | PARTIAL | UNIT_TESTED | Engineering implementation only; actual account/practice/OOS evidence remains required. |
| ML_VALIDATION | MISSING | NOT_OBSERVED | Requires real account/practice/release evidence. |
| HOLDOUT | MISSING | NOT_OBSERVED | Requires real account/practice/release evidence. |
| JURY_EVIDENCE | PARTIAL | ENGINEERING_INDEX | Measured real trade explanations and final 2–4 page PDF/code submission are outstanding. |
| COMPETITION_RELEASE | MISSING | NOT_OBSERVED | Requires real account/practice/release evidence. |
| LIVE_READY | MISSING | FALSE | Funded account, controlled execution, prolonged practice and reviewed competition release remain unverified. |
| HACKATHON_READY | MISSING | FALSE | Funded account, controlled execution, prolonged practice and reviewed competition release remain unverified. |

Tests: 1155 recorded; current source bound: True.

Next action: Provide and manually verify the funded Team Anchorium PUBLIC wallet and approved API PUBLIC address with read-only account checks. Keep PAPER/false.
