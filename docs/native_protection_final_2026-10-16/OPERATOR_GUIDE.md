# Tiny native Stop Limit qualification

The exact aac5cd9405582382d7e79d355853211751bef350ffd45e653ae1f487e01437a0 qualification was genuinely approved and attempted once. It stopped before signer setup because the fresh ask 81,412 exceeded the approved BUY limit 81,410. No signed action or order occurred; two terminal readbacks established flat/zero orders. Do not rerun that stopped mandate or its execution example below. See final_report.md. Keep PAPER/false. The commands below document the historical invocation and the interface for a future separately prepared and explicitly approved experiment; they grant no current execution authority.

Prepare fresh unsigned evidence after the source-matching full regression passes:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python scripts/run_native_qualification.py prepare \
  --test-receipt docs/native_protection_final_2026-10-16/repaired_regression_release/test_receipt.json \
  --output docs/native_protection_final_2026-10-16/qualification_preparation_2026-10-17
```

Use a new output directory for every later preparation. A blocked preparation is not approval-ready. `proposal.json` exists only when the fresh full checks pass. Review `preparation.json`, exact mandate ID, quantities, prices, expected costs, approval deadline and required acknowledgments. A 0.0002 BTC entry must fit the unchanged 10% both-side best-depth policy; it is not enlarged or given a wider participation limit to get a proposal through.

The scope is TESTNET `par:BTC`, registered team wallet, existing API wallet, this sole signing host, 1x CROSS, exactly one 0.0002 BTC BUY IOC. A full fill receives one exact native reduce-only Stop Limit under the ordinary $10 minimum. Exactly 0.0001 BTC partial entry is immediately aborted with the existing observed exact full-position reduce-only SELL IOC scope; a small native stop is never assumed. Stop prices use the original controlled-certification geometry (1% trigger below the observed bid and 0.5% execution allowance). This does not modify frozen strategy geometry.

Maximum six signed actions, one entry, one native stop, one owned cancellation round and two bounded resolved IOC closes. Authorization lasts at most five minutes from genuine acceptance; entry additionally needs at least 150 seconds remaining for management/cleanup. Native trigger waiting is at most 120 seconds and may be shorter to reserve cleanup time. All source, policy, preserved close evidence, rate, clock, account, fee, metadata, price, precision, depth, nonce and lease checks remain mandatory. No uncertain-order retry, duplicate entry, restart, extension, price widening, leverage change or account administration is authorized.

After the human explicitly approves the exact ID and every acknowledgment, the agent records the genuine response and creates the corresponding `approval.json`. Preparation does not create an approval. The execution command is then:

```sh
.venv/bin/python scripts/run_native_qualification.py execute \
  --proposal docs/native_protection_final_2026-10-16/qualification_preparation_2026-10-17/proposal.json \
  --approval docs/native_protection_final_2026-10-16/qualification_preparation_2026-10-17/approval.json \
  --test-receipt docs/native_protection_final_2026-10-16/repaired_regression_release/test_receipt.json \
  --output docs/native_protection_final_2026-10-16/authorized_native_qualification
```

This command was parser-checked; its unsigned preparation is exercised against the actual account only after release validation. Its execution composition is tested with ephemeral offline fixtures. It has not been executed with the actual signer. A missing or inexact approval blocks before key access. New output directories prevent proof overwrites.

Ctrl+C or SIGTERM stops the experiment, revokes its in-memory authority, and attempts bounded unsigned terminal reconciliation. It does not guarantee cleanup or flattening. Never restart a stopped/uncertain signer or blindly repeat an order. Inspect `result.json`, raw `info_receipts.jsonl`, the original journal, actual remaining position and orders. A read failure or unresolved child stays UNKNOWN and requires human review.

An accepted but untriggered stop is incomplete qualification. A naturally triggered stop must supply linked actual SELL fills, exact accounting and two authoritative flat/zero-order readbacks. Only the independent raw-proof validator can produce `NATIVE_PROTECTION_PROOF.json`. Even a successful full-size test does not prove one-lot native-stop behavior or activate unattended entries. No trading session is automatically prepared or launched.

The previous October 16 overnight mandate format rejects creation/acceptance on October 17. No date window is silently rolled forward. Any later trading session needs its own eligible source, actual protection scope, fresh size/risk limits and exact human approval.

Local Mac, Python process, power and internet must remain available. Stop Limits can remain unfilled through a gap. Loss-making cleanup, partial fills, rejections, failed cancellation, uncertainty or interruption can leave exposure; the planned loss budget is not a guaranteed cap. The old October 15 and October 16 heartbeats remain PAUSED. No new observer or recurring automation is launched.
