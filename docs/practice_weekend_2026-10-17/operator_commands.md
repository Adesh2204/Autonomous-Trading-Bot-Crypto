# Local operation after the consumed qualification

The approved qualification ran exactly once and stopped. Its original CLOID remains UNKNOWN locally; independent post-expiry exchange reads show no position, open orders or new fills. The nonce was legitimately advanced and remains preserved. **No command here grants authority to retry, clear UNKNOWN, cancel, sign, launch or renew trading.** The agent performs ordinary Terminal operations; the user need not edit files or type commands.

Safe local diagnostics:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python scripts/anchorium_cli.py doctor
```

The exact consumed command was recorded in `qualification_launch_receipt.json` and the final A–I report. It used the original 2,726-test receipt and source, the 59445fe5... exact proposal and genuine approval, and output `authorized_qualification_refresh_2026-10-17_1143`. **Do not rerun it.** The five-minute authority expired; its invocation and signing attempt remain durably consumed.

The later freshness repair is an offline engineering release. Its complete receipt is `freshness_repair_regression_release/test_receipt.json`; it cannot renew the old approval or certify a native exchange stop. `post_attempt_preservation_receipt.json` verifies that original proofs/certificate and the new UNKNOWN/nonce were preserved.

Before another signing action: formally review the actual UNKNOWN intent using the original source, nonce, transmission-claim history and raw exchange records; satisfy the actual native/partial-residual gates; then present one new exact human mandate. Flatness or `unknownOid` alone does not clear the lock.

When those prerequisites really exist, the existing standalone CLI grammar supports this **future gated template**, whose placeholder files currently do not exist:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare --practice-weekend \
  --markets par:BTC --maximum-notional 1000 \
  --release docs/practice_weekend_2026-10-17/freshness_repair_regression_release/test_receipt.json \
  --native-protection-evidence ACTUAL_VALIDATED_NATIVE_PROOF.json \
  --output NEW_EXACT_SESSION_DIRECTORY
```

The notional above is a proposed ceiling, never a liquidity override. A real fresh market set, risk/price/quantity caps, session ID, start, entry cutoff and hard expiry must be independently checked and exactly accepted. The Oct17–18 contract preserves <=24 hours, one position, two total attempts, 1x, carried 1% session loss, no midnight reset, no automatic renewal and October 18 23:57 IST absolute maximum.

Only after valid proof, cleared lifecycle gates and genuine exact session acceptance, the existing execution grammar is:

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/anchorium_cli.py start --authorized \
  --mandate NEW_EXACT_SESSION_DIRECTORY/mandate.json \
  --acceptance NEW_EXACT_SESSION_DIRECTORY/acceptance.json \
  --release docs/practice_weekend_2026-10-17/freshness_repair_regression_release/test_receipt.json \
  --native-protection-evidence ACTUAL_VALIDATED_NATIVE_PROOF.json \
  --state runtime/practice-weekend-terminal --markets par:BTC --scan-seconds 60
```

No runnable accepted autonomous session or validated native proof is asserted. The autonomous command was not executed. No observer-only process was substituted for trading. The standalone runtime needs no Codex or paid LLM; signing stops at its finite deadline, independently of later observation. Local Mac/process/power/internet availability remains necessary; caffeinate is not failover or an uptime guarantee.
