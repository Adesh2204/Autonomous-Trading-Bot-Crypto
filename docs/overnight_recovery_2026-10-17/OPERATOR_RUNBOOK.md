# Standalone VS Code operator runbook

**Current signing verdict: BLOCKED_EXTERNAL_EVIDENCE. Observation can run independently of Codex. No genuine new trading approval exists.**

Open the cloned repository in VS Code. In its Terminal:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
.venv/bin/python scripts/anchorium_cli.py doctor
```

The doctor checks dependency pins, PAPER/false policy and the frozen strategy without loading wallet secrets. It does not certify account registration, protection or trading permission.

## One command for tonight's read-only operation

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/anchorium_cli.py start --state runtime/terminal --scan-seconds 60
```

This observes all ten runtime `par:` markets, uses genuine completed UTC bars, reconciles the registered public account, records receipts and displays diagnostic capacity/cost/accounting information. It cannot sign or submit an order. It intentionally waits when bars, signals, depth or economic evidence are insufficient. Do not add `--authorized` to make a blocked signal trade.

The Mac and Terminal process must stay running with power and internet. Caffeinate prevents idle sleep while that process is alive; it is not remote failover. Codex, its app and continuous paid LLM access are not runtime dependencies. No automatic trading renewal or blind order restart is installed.

## Continuously refreshed dashboard

The worker prints state changes and periodic complete-scan updates. For a separate live view, open a second Terminal in the same repository:

```sh
.venv/bin/python scripts/anchorium_cli.py dashboard --state runtime/terminal
```

The view refreshes every five seconds. Ctrl-C here closes only the view. The dashboard labels local UNKNOWN separately from current exchange positions/orders, shows accounting ages and separates historical account P&L from the current process's reported fills/fees/funding. Conditional target returns are scenarios, not predicted profit or a probability of winning. Authorized capacity remains zero without all prerequisites.

## Normal and emergency stop

Use Ctrl-C in the worker's Terminal, or request a session-specific graceful stop from another Terminal:

```sh
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/terminal
.venv/bin/python scripts/anchorium_cli.py status --state runtime/terminal
.venv/bin/python scripts/anchorium_cli.py report --state runtime/terminal
```

Allow the bounded terminal reconciliation to finish; it can need up to 180 seconds for rate waits and two authoritative snapshots. A stop request is not proof of flatness. Read `terminal_flat`, residual state and errors. If interrupted or unable to reconcile, account state remains UNKNOWN until fresh supported reads. Do not force-kill a trading worker or assume missing local orders means no exchange exposure.

The same stop/SIGINT/SIGTERM path prevents further entries in an authorized runtime and follows only its existing bounded protective/exit authority. It cannot guarantee a fill, invent new closing permission, cancel unrelated orders or close after authority expires. Unresolved exposure requires human recovery review.

## Restart and accounting review

Restart using the read-only start command. It publishes the previous session identity, reacquires exchange truth and never restores signing from the previous process. Logs and status live under the timestamped directory identified by `runtime/terminal/current.json`; `status`, `report` and `dashboard` resolve that pointer automatically. Old terminal snapshots are not treated as current after a dead process.

Accounting has these distinct bases:

- Historical account net uses exchange-reported closed P&L, actual fees and actual funding over its stated history window.
- Session net includes only reported fills/funding since this process began, with incomplete accounting displayed as unknown.
- Session return percentage divides that realized net by the first verified reported balance for this session, never by the proposed 20,000 bankroll.
- Balance change is not cash-flow-adjusted, oracle-marked competition equity or an official score. Reported position unrealized P&L remains separate. Sampled drawdown is not an intrabar maximum.

## Future exact human approval workflow — blocked today

First obtain admissible resolution of the original UNKNOWN, genuine native trigger/child/residual evidence and organizer permission for the intended window. The published schedule ends practice October 16 and begins scored trading October 19; no October 17–18 exception has been verified. The current actual-runtime builder rejects an interval outside the published windows. Changing that requires reviewed organizer evidence and another tested source release, not a flag.

Once those prerequisites genuinely exist, the verified CLI supports:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare --help
.venv/bin/python scripts/anchorium_cli.py approve --help
.venv/bin/python scripts/anchorium_cli.py start --help
```

The exact future workflow is:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare \
  --output "$NEW_PROPOSAL_DIRECTORY" --minutes 60 --maximum-notional 1000 \
  --release docs/overnight_recovery_2026-10-17/regression_release/test_receipt.json \
  --native-protection-evidence "$QUALIFIED_NATIVE_PROOF_JSON"

.venv/bin/python scripts/anchorium_cli.py approve \
  --mandate "$NEW_VALIDATED_MANDATE_JSON" \
  --release docs/overnight_recovery_2026-10-17/regression_release/test_receipt.json \
  --native-protection-evidence "$QUALIFIED_NATIVE_PROOF_JSON"

/usr/bin/caffeinate -i .venv/bin/python scripts/anchorium_cli.py start --authorized \
  --mandate "$NEW_VALIDATED_MANDATE_JSON" --acceptance "$GENUINE_ACCEPTANCE_JSON" \
  --release docs/overnight_recovery_2026-10-17/regression_release/test_receipt.json \
  --native-protection-evidence "$QUALIFIED_NATIVE_PROOF_JSON" --state runtime/terminal
```

These are verified interfaces, not currently launchable trading commands: the named valid mandate, native proof and acceptance inputs are unavailable. `approve` displays the exact mandate and requires the human to type `APPROVE` plus its full ID within its decision window. No acceptance has been generated by this engineering task. Do not substitute old mandate files or dummy evidence. Future approval must bind the exact account, markets, LONG direction, allocation, 1x CROSS, risk, attempts, recovery, source/release/protection and finite expiry. Two entries, 1% carried session loss and current participation/depth restrictions remain ceilings, not targets that must be filled.

The deterministic authorized engine exists; after all gates and exact approval it can scan, enter, verify, protect, manage, exit and reconcile without manual order decisions. This runbook does not claim those venue prerequisites have been met.
