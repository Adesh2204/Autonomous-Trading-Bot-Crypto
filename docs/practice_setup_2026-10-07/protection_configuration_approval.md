# Emergency protection — approved configuration, disabled execution

The user's pasted request on 7 October 2026 specifies one additional entry ATR
beyond the existing normal stop, a 0.5% execution allowance and reduce-only
protection. It directs this policy to be reviewed, approved, configured and kept
disabled until controlled certification. This document records approval for
those exact configuration values, derived from that explicit user request.

Source request:
`/Users/adesh/.codex/attachments/7fe88c39-894a-4897-ac40-4bba73e717a7/Pasted text.txt`.

Configured in `configs/reliability_policy.json`:

```json
{
  "enabled": false,
  "approval_reference": "docs/practice_setup_2026-10-07/protection_configuration_approval.md",
  "atr_distance_multiple": "1",
  "execution_slippage_fraction": "0.005"
}
```

For LONG, the emergency trigger is normal stop minus one entry ATR. For SHORT,
it is normal stop plus one entry ATR. The normal strategy stop/target and the
frozen ATR calculation remain unchanged. The exchange order is sized from the
actual observed filled position and must be reduce-only.

An accepted protective order remains present while the bot is connected too.
It can still operate after a local crash/disconnection; it is not created only
after the bot has already crashed. It may activate during ordinary operation if
the price reaches the emergency trigger. The lifecycle must remove obsolete
protection after authoritative flat reconciliation before allowing a new entry.

The 0.5% allowance is a bounded execution limit, not a guaranteed fill. It can
leave protection unfilled during a large move or insufficient liquidity. Runtime
precision, actual size, liquidation-price geometry, account truth, exact-action
validation and protection recovery still apply. These settings are engineering
choices, not an empirically validated crypto performance improvement.

**This document does not approve entry/exit/protection submissions or activate
trading.** Protection remains disabled, `EXECUTION_MODE=PAPER` and
`ALLOW_LIVE_ORDERS=false`. The user's separately requested 1x CROSS account
configuration has a different narrow authorization scope and cannot enable
orders. Controlled real LONG/SHORT tests still require the complete readiness
gate and later explicit activation after manual account verification.
