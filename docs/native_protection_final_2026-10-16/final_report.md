# Approved native qualification — terminal result

Mandate `aac5cd9405582382d7e79d355853211751bef350ffd45e653ae1f487e01437a0`. Genuine approval recorded at 2026-10-17T08:53:08.160000+05:30; it arrived before the proposal deadline. The worker exited with code 1 during final preflight. It was not restarted.

**Outcome: no signer setup, signature, BUY, stop, SELL, fee or new fill. Account independently verified flat with zero open orders twice after the worker stopped. Native trigger qualification remains incomplete and unattended trading stays disabled.**

## Exact failed final check

Approved BUY IOC limit: **81,410**. Fresh final best ask: **81,412**; best bid **81,362**. Both best-side quantities were 0.0061 BTC, so the unchanged 10% participation guard could support 0.0002 BTC. Fee, size and margin checks passed. The exact fixed limit was 2 USDPR per BTC below the new ask, so `NATIVE_QUALIFICATION_PRICE_DEPTH_FEE_MARGIN_REQUIRED` blocked the attempt. The limit was not widened or repriced. This was a market-bound guard outcome, not an HTTP error or uncertain exchange submission.

Final book exchange timestamp: 1792207437555; local receipt: 1792207438086. Full condition reconstruction from the saved actual read bundle: `authorized_native_qualification/preflight_block_analysis.json`. The code checks this condition before `read_api_key`, `api_signer`, nonce-manager construction or exchange transport setup. No new mandate intent or transmission exists, and the original nonce logical dump is unchanged.

## A–J requested results

| Item | Actual result |
|---|---|
| A — $10 residual issue | A narrow supervised two-lot BTC / one-lot IOC-abort route is implemented and tested. A general small native-stop exception remains unverified. |
| B — exchange qualification | No. The approved attempt stopped before any entry or native stop. No trigger or closing fill was manufactured. |
| C — genuine trades permitted/executed | This mandate approved at most one qualification entry; zero entries occurred. No autonomous session is authorized. The stopped attempt will not be restarted. |
| D — actual position size | Approved test size was exactly 0.0002 BTC; actual filled and remaining size is zero. Unattended qualified capacity remains zero. |
| E — regression | 2,675 passed; zero failures/errors/skips. Phase-0 and strategy freeze passed, with identical source before/after. |
| F — new exact trading mandate | None. The genuine approval applies only to this stopped tiny qualification. Another attempt needs a new exact proposal and human approval. |
| G — execution command | The one approved invocation used `scripts/run_native_qualification.py execute` with the exact proposal, genuine approval, matching release and a new output directory, under process-bound caffeinate. It exited at preflight. Do not rerun it. No autonomous trading launch is eligible. |
| H — worker running | No. The worker stopped; no duplicate or restart was launched. Both old heartbeats remain PAUSED. |
| I — actual fills/P&L | New attempt: zero fills, fees, funding and realized P&L. Original Oct15 net remains +0.050512 TEST USDPR. |
| J — remaining blocker | Immediate attempt: current ask exceeded the exact approved BUY limit. Broader activation: missing genuine team Stop Limit trigger/linked closing evidence, unverified small native-stop behavior and elapsed Oct16 overnight creation window. |

## Authoritative terminal evidence

| Local readback ms | Positions | Open orders | Reconciliation ready |
|---:|---:|---:|---|
| 1792207525491 | 0 | 0 | True |
| 1792207528378 | 0 | 0 | True |

Terminal account history contains the same original BUY order 62755970305 / fill 800659111758533 (0.0002 BTC at 81512, fee 0.014672) and SELL order 62805581662 / fill 260274449763192 (0.0002 BTC at 81909, fee 0.014743). Gross +0.0794; fees 0.029415; 12 actual funding events +0.000527; net +0.050512 TEST USDPR on Oct15. No new task profit is claimed. No organizer whitelisting or reset claim is made.

Unsigned terminal reconciliation waited for the prior public rate window to expire, then used existing rate controls and a 180-second bound. Raw terminal receipts and accounting are in `authorized_native_qualification/terminal_reconciliation/`. Original BUY/SELL proofs remain byte-identical. The original UNKNOWN entry and immutable resolution remain valid. Original nonce/configuration dumps are unchanged. The qualification journal legitimately acquired fresh account checkpoints/events during approved final checks; it is not falsely reported byte-identical. Its integrity and checkpoint checksums pass, and it contains zero new order intents/transmissions for this mandate. See `post_attempt_preservation.json`.

Source: `d02d56ddced4d14679963842d4729ab06d51998b43d95dfb330fb4556fa3c5e0`. Full XML SHA-256: `0ca82d4a09eb5461039a92f334bf0f2d1fd40440ecb3d6c6ff0b5a842a064ac4`. The source-matching receipt remains valid; source/config/floors were not changed after approval. All 10 protected file hashes still match baseline.

## Engineering findings retained

The complete preapproval A–J engineering report, primary official documentation, bounded historical evidence limits, narrow implementation and offline qualification tests remain in `preapproval_report.md`. Native Stop Market historical acceptance is not Stop Limit trigger/closing qualification. The dedicated path leaves ordinary/unattended partial-fill gates intact, aborts an exact one-lot entry without inventing a small stop, resolves lost ACKs only by exact original identity, settles known trigger children before cleanup and never retries an uncertain order. An accepted untriggered stop would remain incomplete qualification.

Local operation depends on this Mac, process, power and internet. No worker, recurring monitor, replacement mandate, next-day renewal or extended signing window was started. The stopped mandate will not be reused. A further attempt requires fresh account/book evidence and a new exact human decision.
