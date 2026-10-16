# Existing BTC trade closed — authoritative TESTNET result

**CLOSED_EXCHANGE_VERIFIED. Net realized profit: +0.050512 TEST USDPR.** Exactly one approved reduce-only SELL IOC closed the existing 0.0002 BTC LONG at **15 October 2026 22:13:25 IST**. There were no new BUYs and no repeated SELL submissions.

| Actual exchange evidence | Value |
|---|---:|
| Original BUY quantity / price | 0.0002 BTC / 81512 USDPR |
| Original BUY order / fill | 62755970305 / 800659111758533 |
| SELL quantity / actual average price | 0.0002 BTC / 81909 USDPR |
| SELL submitted limit | 81828 USDPR, above approved 81809 floor |
| SELL order / fill | **62805581662 / 260274449763192** |
| SELL cloid | 0xbb16ea7808930ef2742c1b8f91f7f27c |
| Remaining positions / open orders | **0 / 0** |

Two independent authoritative reconciliations at **15 October 2026 22:13:33 IST** and **15 October 2026 22:14:20 IST** each reported zero positions, zero open orders, reconciliation ready and the actual closing SELL fill. An additional final read at 15 October 2026 22:14:23 IST agreed. Both worker PID 16284 and its process-bound caffeinate PID 16285 exited. The mandate is consumed/finished/revoked; no restart or next order is authorized. The pre-signing health file is historical; the terminal result contains completion evidence. The existing heartbeat remains **PAUSED**.

## Actual realized P&L

| Component | TEST USDPR |
|---|---:|
| Actual SELL proceeds | 16.38180 |
| Original BUY cost | -16.30240 |
| Actual entry fee | -0.014672 |
| Actual exit fee | -0.014743 |
| Actual net funding (12 reported events) | +0.000527 |
| **Net realized profit** | **+0.050512** |

Gross closed price P&L is 0.07940; total actual fill fees are 0.029415. These calculations use exchange-reported fills, fees and funding, not a candle, mark estimate or account-balance inference. The final signing checks used a conservative fee upper bound of 0.27% and estimated minimum net +0.004867880 at the 81828 limit; the actual exchange fill and lower reported fee determine the realized result above.

## Authorization, source and persistence

Genuine approval of exact mandate **5395c75090f1aa96a07c31c40e999420c58c5a82d2735536dc7ef22be3d63f05** was accepted at 15 October 2026 22:11:57 IST, within its deadline, and expired at 15 October 2026 22:21:57 IST. One signing attempt, one generated nonce, one HTTP POST and one HTTP 200 response are durably recorded. The exact reduce-only quantity, IOC, original order identity, profitable floor, nonce/account/source/clock/rate and signer guards remained enforced. The repaired historical barrier recognized only certificate `a6ea851efdd3c0e90b26b55587bdb60e3ba8449b782d1e39a94a01743acdd058`; the original UNKNOWN row and certificate were preserved.

Tested source **abc36e4a6eb6b61994b3bdc22ce05700e965afe44be697f6a0345e8c5f98f8c0** is unchanged. Matching full regression: **2385 passed, zero failures/errors/skips**; XML SHA-256 **39e5dc3c8042575d5a401ca4b68655c04908cdbdddd8e2a6ffa76d883ac110c9**. Phase-0 and strategy freeze passed before/after the regression. Production remains **PAPER / ALLOW_LIVE_ORDERS=false**, and `signal_brain.py` is unchanged. This isolated approved TESTNET close does not activate general trading. No source changes were made for this execution.

Journal and nonce SQLite integrity are `ok`; both retained checkpoint checksums verify. Both original BUY proof files retain their pre-recovery hashes. The existing runtime did not write a certified clean-shutdown flag; explicit terminal result, authority revocation, final reconciliation and process exit are established. No verified protective stop existed during the exposure. The account is now flat. Organizer whitelisting remains unconfirmed.

[Closing exchange proof](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/EXIT_RECOVERY_PROOF.json>) · [Final JSON summary](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/final_summary.json>) · [Original worker result](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/authorized_session/result.json>) · [Local journal evidence](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/final_local_journal_evidence.json>) · [Human approval provenance](</Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_exit_refresh_2026-10-15_2209/fresh_proposal/human_approval_provenance.json>)
