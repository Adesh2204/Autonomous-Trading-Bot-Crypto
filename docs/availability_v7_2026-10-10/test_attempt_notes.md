# Preserved V7 test attempts

- targeted_a.xml: 122 passed, 1 failure. Narrowing a gapped repair request changed the established sparse-response merge regression. Restored the proven full 300-minute repair scope, retaining exact missing-interval planning; no old test was weakened.
- targeted_a_v2.xml: 123 passed.
- targeted_b.xml: 65 passed, 1 failure. New assertion expected RuntimeError, but the real safety boundary raises MigrationPolicyError. The assertion now requires the actual safety exception; production behavior was correct.
- targeted_b_v2.xml: collection failed due to a patch indentation error. Corrected it before any public run.
- targeted_b_v3.xml: 66 passed. A Decimal-encoding equality regression was subsequently added and belongs to the full final suite.
- The full source-bound regression and all failed artifacts are retained. Only a passing final receipt can authorize the public PAPER evidence collector.

- regression/: 1,399 passed, 1 failed. The existing research-boundary test rejected a requests import in the new research module. HTTP was moved to the standalone public-only command; no test was weakened.
- boundary_checks.xml: 127 passed, including the existing no-network-import invariant.

- regression_final/: 1,401 passed, zero failures/errors/skips, source-stable. Final diagnostics were then tightened to distinguish cache repair and first REST availability, bound rejected future interval retention, and enforce full UTC/fresh mark context in the research feature path. The subsequent release receipt certifies those changes.

Final release regression: **1405 passed, zero failures/errors/skips**; freeze and Phase-0 passed. Source before/after `36324cd3891eb931801ddc2ac9d47cf1e9c47cfbbd6a5a6f9aaddbc410a52685`. Preserved release XML and receipt are in `regression_release/`.
