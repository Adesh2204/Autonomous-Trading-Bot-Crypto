# V8.9 operator start

No current proposal passed the 13 October read-only observation. Do not execute an old proposal.

Run this from the project root:

```bash
.venv/bin/python scripts/watch_testnet_qualification.py \
  --duration-seconds 300 \
  --output-directory "docs/qualification_watcher_v8_9_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \
  --test-receipt docs/qualification_watcher_v8_9_2026-10-13/regression_release/test_receipt.json \
  --final-account-audit
```

This is read-only. Press Ctrl+C once to stop. It exits at a ready proposal or the bounded observation window; an ongoing check has an absolute limit of duration + 180 seconds. It never restarts itself. Use a new output directory for each deliberate run.

If AWAITING_HUMAN_APPROVAL appears, the terminal and operator_handoff.json show the actual proposal hash, source-bound test receipt, proposal.json, unfilled approval template, copy command and the exact existing execute command. Review the exact bounds and deadline first. No template fields are filled automatically. No execute flag exists in the watcher.

The six approval acknowledgments must be explicit human decisions: verified wallets; sole signing host; one entry; unverified stop risk; the isolated 50 bps spread limit; possible manual residual recovery. The proposal's 25 USDPR cap, exact smaller quantity and prices, one entry/two exits/five signed-action limit remain binding. Approval timestamps must be genuine, not backdated, and the proposal must still be current.

If the run ends NO_CURRENT_QUALIFICATION_PROPOSAL, read readiness.json for the blocking depth or residual. There is no order to approve. Do not change strategy, opening minimum, depth policy, signer or global locks.

Any EMERGENCY_EXIT_REQUIRED after a separately authorized attempt means: stop new entries; preserve qualification.sqlite and original order identity; read original orderStatus, team userFills, frontendOpenOrders and par positions; report the exact residual or UNKNOWN; never blindly resend, erase the consumed entry, or expand the price/size limit. Expired/revoked permission cannot resume writes. Obtain explicit recovery authorization if existing bounds cannot close.

No protective stop is verified. Historical narrow IOC full-close evidence does not guarantee future fills. A 25 USDPR entry cap is not a guaranteed loss cap. No actual fill or whitelist qualification has been claimed.
