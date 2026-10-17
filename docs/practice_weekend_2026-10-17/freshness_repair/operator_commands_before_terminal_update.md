# Local operator commands — October 17–18

The agent performs ordinary Terminal operations. These are reviewable commands, not instructions for the user to type or edit files. No launch command below has been executed. Current state: the earlier response arrived after its execution window expired; no valid acceptance or autonomous session exists, native/subminimum evidence remains incomplete, and the trading worker is absent. The original mandate and response remain preserved. A new response must name the refreshed exact mandate.

Working directory includes its trailing space:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python scripts/anchorium_cli.py doctor
```

The CLI grammar and `doctor` passed locally with the source recorded in this release. PAPER/false remains enforced. Diagnostic success does not grant trading authority.

## One supervised qualification

After the full matching regression, the agent prepares one fresh proposal:

```sh
.venv/bin/python scripts/run_native_qualification.py prepare \
  --test-receipt docs/practice_weekend_2026-10-17/regression_release/test_receipt.json \
  --output docs/practice_weekend_2026-10-17/qualification_refresh_2026-10-17_1143
```

This creates unsigned public account/book evidence and `proposal.json`, not consent. The proposal directory is exclusive and must not be overwritten. Its exact full mandate ID, bounded ask corridor, maximum BUY, fixed stop/floor, fees/funding caps and expiry are in `preparation.json` and the report. Any expired proposal needs a new human decision; there is no automatic refresh/reapproval loop.

After a genuine exact response explicitly accepts the supervised BUY exception while native protection is unqualified, the agent records that response and its true acceptance time in `human_approval_provenance.json` and a matching typed `qualification_approval.json`. Neither file exists before that response. No synthetic acceptance, replay of the consumed old approval, or automated interactive keystroke is permitted.

Only then, while the new exact acceptance is valid and every fresh gate passes, the planned command is:

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/run_native_qualification.py execute \
  --proposal docs/practice_weekend_2026-10-17/qualification_refresh_2026-10-17_1143/proposal.json \
  --approval docs/practice_weekend_2026-10-17/qualification_refresh_2026-10-17_1143/qualification_approval.json \
  --test-receipt docs/practice_weekend_2026-10-17/regression_release/test_receipt.json \
  --output docs/practice_weekend_2026-10-17/authorized_qualification_refresh_2026-10-17_1143
```

This is **not presently launchable**: the approval is absent. The process consumes one invocation even on failed fresh public preflight, selects a single entry price before durable intent, and never reprices/repeats an uncertain wire. It uses the original account journal and nonce directory. Cleanup/stop actions are confined to the explicit five-minute acceptance and its quantity/price/action limits. It requires two terminal authoritative flat/zero-order readbacks and actual fill/fee/funding reconciliation. An accepted stop without a genuine natural trigger is INCOMPLETE qualification.

## Future autonomous session — gated template

After real native trigger/closing proof **and** representable partial-residual protection satisfy every existing entry guard, a new finite session can be proposed using:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare --practice-weekend \
  --markets par:BTC --maximum-notional 1000 \
  --release docs/practice_weekend_2026-10-17/regression_release/test_receipt.json \
  --native-protection-evidence ACTUAL_VALIDATED_NATIVE_PROOF.json \
  --output NEW_EXACT_SESSION_DIRECTORY
```

The capital/maximum-notional arguments here are proposed upper bounds only; fresh liquidity/risk can reduce them and incomplete native/partial evidence blocks the mandate. The placeholder paths do not exist and the command is not represented as a verified runnable session. The actual permitted market set and notional must be rebuilt from fresh evidence, with one exact human acceptance of the resulting session ID, start, cutoffs and hard expiry. October 17 creation/acceptance, at most 24 hours, October 18 23:57 IST absolute maximum, two total entry attempts, one global position, 1x, 1% carried session loss and no midnight reset/renewal apply.

With a real accepted mandate and proof, the existing execution-enabled CLI grammar is:

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/anchorium_cli.py start --authorized \
  --mandate NEW_EXACT_SESSION_DIRECTORY/mandate.json \
  --acceptance NEW_EXACT_SESSION_DIRECTORY/acceptance.json \
  --release docs/practice_weekend_2026-10-17/regression_release/test_receipt.json \
  --native-protection-evidence ACTUAL_VALIDATED_NATIVE_PROOF.json \
  --state runtime/practice-weekend-terminal --markets par:BTC --scan-seconds 60
```

No executable autonomous mandate ID, acceptance, proof or running PID exists yet. The agent will verify process/command/source/mandate ownership after an admissible authorized launch. Without an actual accepted session and proof there is no honest complete “verified execution command.”

After such a launch, the same state directory supports:

```sh
.venv/bin/python scripts/anchorium_cli.py status --state runtime/practice-weekend-terminal
.venv/bin/python scripts/anchorium_cli.py report --state runtime/practice-weekend-terminal
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/practice-weekend-terminal
```

The worker needs no Codex or paid LLM to scan/manage. The signer expires independently; the existing observer can continue after it stops without renewing authority. `stop` requests graceful shutdown, not an unauthorized cancel/close. Unresolved exposure is reported for human review. Local Mac/process/power/internet availability remains necessary; caffeinate is neither remote failover nor an execution guarantee.
