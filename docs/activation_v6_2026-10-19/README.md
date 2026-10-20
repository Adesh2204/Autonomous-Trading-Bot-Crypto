# Post-funding activation handoff

Do not use the retained V6 request or account-identity wrapper as action acceptance. The V6 request explicitly requires the existing genuine interactive configuration and finite-session approval workflows. No per-order prompts are required during a valid accepted trading mandate.

## Next human action: exact configuration approval

Review [the two-action plan](configuration_review_final/account_configuration_plan.json) and [change review](CHANGE_REVIEW.md). It changes `pas:BTC` and `pas:EWY` from 20x CROSS to 1x CROSS. The displayed historical isolation is configuration-only; it does not clear the original UNKNOWN or authorize orders.

After `regression_release_final/test_receipt.json` records `passed: true`, run this yourself in macOS Terminal:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python docs/activation_v6_2026-10-19/configure_btc_ewy.py
```

The helper first validates the source-matched regression and refreshes actual account/receipt evidence, then displays the entire exact plan. Type the exact approval phrase only after reviewing it. Acceptance immediately invokes the existing configuration-only executor for the two approved changes and verifies exchange readbacks. The helper creates a unique retained evidence directory; it never accepts redirected input or creates trading acceptance.

If the executor reports uncertainty, preserve its evidence and reconcile that exact action. Do not rerun to escape a consumed or UNKNOWN action. The original account/signer/nonce history and all order barriers remain in force.

## Protective qualification and trading

Fresh unsigned proposals are retained in `native_btc_review/qualification_proposal.json` and `native_ewy_review/qualification_proposal.json`. They are blocked because the ordinary minimum can leave a subminimum partial-fill residual without an independently verified PAS protection/closure route. The configuration-only isolation does not remove this or the historical order barrier for trading.

Concrete next actions:

1. Obtain authoritative PAS-specific residual/full-close and native-stop semantics, then review an exact bounded qualification experiment with genuine human acceptance. No prior PAR/synthetic proof qualifies PAS.
2. Obtain a terminal original-order record or separately validate and explicitly accept a trading-specific historical isolation policy. Preserve the original UNKNOWN and consumed attempt meanwhile.
3. After those dependencies pass, prepare a fresh finite PAS mandate from current source, account and market evidence; accept it with the existing CLI `approve` workflow. Only then can conditional activation hand off to one account controller.

There is no valid signed launch command with real mandate/proof/acceptance paths yet. Creating dummy files would not satisfy these requirements. A running public observer is observation, not signed trading.

## Existing public observer

The credential-free public worker uses the frozen source under `public_reader_source/`, state `runtime/pas-btc-ewy-v6-public`, and retained logs `public_reader.log`. It is already running; do not launch a duplicate.

Read status with its matching source:

```sh
.venv/bin/python docs/activation_v6_2026-10-19/public_reader_source/scripts/anchorium_cli.py status --state runtime/pas-btc-ewy-v6-public
```

Stop the public observer using the same CLI and state with `stop`. No trading mandate is renewed automatically. The observation process depends on this Mac, power and internet; its `caffeinate` process is retained in `public_reader_launch.json`.
