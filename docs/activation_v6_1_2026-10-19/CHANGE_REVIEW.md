# V6.1 continuation review

Configuration was genuinely accepted through the existing CLI on the prior verified source. The helper submitted exactly two leverage actions, recorded both acknowledgements and 1x CROSS readbacks, and a separate actual PAS discovery confirmed both settings. Original qualification records remain unchanged; the shared nonce history advanced legitimately for those approved actions. `baseline_after_human_configuration.json` starts this continuation after those writes and includes the new configuration journal.

## Source changes

- Extract the existing execution scanner's candidate-selection expression into `selected_markets()`, preserving its ordinary BTC/EWY result byte-for-byte in meaning. No indicator, threshold, ranking factor, or state transition is changed. The frozen brain and all freeze-manifest methods remain unchanged.
- Add an isolated read-only PAS subclass that selects all ten canonical markets only with a read-only public client and no execution authorization. It reuses the existing scanner and frozen brain. The result distinguishes observations from BTC/EWY production scope, exposes failures, retains authentic history, and never supplies expected profits or entry permits.
- Add a finite, unaccepted historical-isolation design with exact original UNKNOWN/nonce/source/evidence binding, independent current account rules, original record preservation, explicit session ceilings, and separate qualification/session approval requirements. Signed execution does not import or consume this design. It is not a production bypass.
- Quantify every possible subminimum residual size in an unsigned native-test proposal. One observed lot cannot silently qualify other sizes or native stops.
- Expose only read-only `pas-ranking` and `trading-isolation-review` entry points. Existing central entry-market, minimum, approval, account, nonce, source, risk and protection gates remain.

## Validation

38 new offline tests cover scope/authority rejection, real frozen-brain parity for BTC/EWY within a ten-market observation, unchanged default scanner selection, source/completeness/ranking integrity, exact finite isolation limits and changed-evidence rejection, and subminimum-size coverage calculations. Together with the relevant earlier suites, 178 focused tests passed. Full source-matched regression passed: 3,195 tests, zero failures/errors/skips; identical source hash before and after. Strategy-freeze verification and production PAPER/false lockout checks passed before and after.

The public BTC/EWY reader remains on its separate verified frozen V5.3 source. It is deliberately independent of edited source and contains no signer or exchange transport. Genuine data can become stale again; no bars or signals are fabricated to improve readiness.
