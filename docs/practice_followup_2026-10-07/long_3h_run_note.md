# Three-hour PAPER run: started and monitored

**This run is in progress. No final three-hour result is being claimed yet.**

- Started: **2026-10-07T14:41:07.216208+05:30**.
- Expected completion: **2026-10-07T17:41:07.216208+05:30**, allowing for normal shutdown latency.
- Duration: **3 hours / 10,800 seconds**.
- Host: this Mac, using the existing `readiness-2026-10-07-paced-source` hypothetical ledger.
- Execution: **PAPER**, live-order permission **false**, independent protection **disabled**.
- Code and policy match the passing 1,278-test suite and saved checkpoint. Strategy freeze passed. No active strategy or exchange code was edited.

The launcher executes the existing practice command with the longer duration. The wrapper saves health samples approximately every 30 seconds and a final source-bound receipt after shutdown. A temporary `caffeinate` process prevents idle sleep while the supervisor runs. **Keep the Mac lid open and the network connected**; shutdown, lid closure or network loss can interrupt the run.

The thread monitor checks every **15 minutes**. It stays quiet for unchanged conditions and reports meaningful improvements, failures, required user action or completion. It is instructed to stop after the bounded run finishes or fails. Scheduled-task guidance came from [OpenAI Docs](https://learn.chatgpt.com/docs/automations?surface=app); the actual monitor schedule and current-thread target were verified in the installed automation configuration.

## Current observation, not the final result

Snapshot: 2026-10-07T09:17:57.188578+00:00. Scanner cycles in this run: 2. Scan result: **NO_TRADE**. Scanner-qualified observations: **0**. Real orders: **0**.

| Market | Recorded completed rows | Latest close age at scan export, seconds | At least 300 rows and fresh close |
| --- | --- | --- | --- |
| `par:BRENT` | 570 | 16.3 | YES |
| `par:BTC` | 555 | 916.3 | NO |
| `par:ETH` | 492 | 4696.3 | NO |
| `par:EWJ` | 503 | 4036.3 | NO |
| `par:EWY` | 557 | 796.3 | NO |
| `par:GOLD` | 519 | 3076.3 | NO |
| `par:HYPE` | 542 | 1696.3 | NO |
| `par:SP500` | 517 | 3196.3 | NO |
| `par:USDEUR` | 551 | 1156.3 | NO |
| `par:USDJPY` | 525 | 2716.3 | NO |

This measures actual recorded rows and close timestamps. Gaps in the last 300 rows are reported separately in the progress JSON. These monitoring measurements do not change strategy admission rules. A fresh history, healthy book/context feed, scanner qualification and an actual strategy signal are different checks. One successful observation does not establish continuous reliability or funded-practice readiness.

The requirements stay at **300 completed bars, 0.40% ATR floor, 15 bps maximum spread and Top-3**. No bars are invented and no historical CSV is substituted for current data.

## Protection and controlled certification

The approved independent policy remains one entry ATR beyond the normal strategy stop, a 0.5% execution allowance and reduce-only. It stays disabled throughout this PAPER run. A future controlled certification still needs usable current data, current account/nonce/clock/reconciliation checks, a defined small risk budget and the required explicit session activation. This monitor cannot enable orders or protection and cannot start funded LONG/SHORT tests.

## Where evidence is saved

- [Launch and preflight identity](<docs/practice_followup_2026-10-07/long_3h_launch.json>).
- [Current per-market progress](<docs/practice_followup_2026-10-07/long_3h_progress.json>).
- [Health samples](<docs/practice_followup_2026-10-07/long_3h_health_samples.jsonl>).
- [Process output](<docs/practice_followup_2026-10-07/long_3h_process.log>).
- [Completion receipt, currently in progress](<docs/practice_followup_2026-10-07/long_3h_paper_receipt.json>).

The final monitor will save `long_3h_report.md` and `long_3h_summary.json` here after verifying duration, source hashes, clean shutdown, state/backup integrity, scanner outcomes, simulated accounting and reconnects. Simulated results remain separate from the actual team wallet and official competition score.

Manual status check from the project root:

```sh
.venv/bin/python scripts/check_practice_health.py --state-directory runtime/paper/readiness-2026-10-07-paced-source
.venv/bin/python docs/practice_followup_2026-10-07/inspect_long_paper.py
```

A degraded-data health result can occur while the process is running normally and refusing unsafe data. No automatic restart or duplicate collector is configured.
