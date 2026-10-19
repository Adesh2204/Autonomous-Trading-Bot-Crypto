# V5.3 opening-day operator commands

The worker is a public-only PAS observer. It detects funding and evaluates BTC/EWY automatically. It has no signer. Actual BUY/SELL execution already runs without individual prompts inside a genuinely accepted, finite session. This release does not manufacture that acceptance or relax account, exit, nonce, or strategy checks.

Run from this clone only:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
export ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false
export HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY
RELEASE="$PWD/docs/opening_v5_3_2026-10-19/regression_release_final/test_receipt.json"
STATE="$PWD/runtime/pas-btc-ewy-v5-2"
```

## Status and health

```sh
.venv/bin/python scripts/anchorium_cli.py dashboard --state "$STATE" --once
.venv/bin/python scripts/anchorium_cli.py status --state "$STATE"
.venv/bin/python scripts/anchorium_cli.py opening-check --state "$STATE" --release "$RELEASE"
.venv/bin/python scripts/anchorium_cli.py doctor --venue pas
```

`opening-check` reports the 14 requested statuses independently and exits nonzero while trading is unauthorized. Without original organizer/native evidence it keeps those statuses false, even if a cached report says otherwise. Optional arguments are `--discovery`, `--organizer-confirmation`, and `--native-protection-evidence`. The identity result binds the operator-reviewed registered team and current public API-agent approval; it does not certify local key ownership. No new execution gate was added by this diagnostic.

The observer is already running. Do not start a duplicate. Funding/account reads normally run every 300 seconds, with an account event prompting an earlier read subject to the existing pacing. Detection may lag arrival; it never grants permission. All times and ages are explicit. A book/context heartbeat is not a current completed candle.

## Fresh public evidence

Use a new, unused output directory for each invocation:

```sh
.venv/bin/python scripts/anchorium_cli.py funding --output docs/opening_v5_3_2026-10-19/operator-funding
.venv/bin/python scripts/anchorium_cli.py history-review --output docs/opening_v5_3_2026-10-19/operator-history
.venv/bin/python scripts/anchorium_cli.py discover --venue pas --output docs/opening_v5_3_2026-10-19/operator-discovery
```

An incomplete history/discovery command now exits nonzero. Warmup, freshness, account funding and signing permission are separate. Historical USDPR is not PAS USDP. The scored interval is October 19, 2026 12:00 UTC / 17:30 IST through November 6 at the same UTC time.

## Configuration after actual funding and account review

`ORGANIZER_RECORD` must be the real `organizer_confirmation.json`, with its retained original record and reviewed provenance. The October 7 identity verification for PAR configuration is not scored PAS registration evidence. `CONFIG_REVIEW` and the acceptance/result paths must be unused destinations. Today's unsigned plan remains blocked by zero USDP, historical uncertainty and missing registration evidence.

```sh
.venv/bin/python scripts/anchorium_cli.py configuration-review \
  --organizer-confirmation "$ORGANIZER_RECORD" --output "$CONFIG_REVIEW"
CONFIG_PLAN="$CONFIG_REVIEW/account_configuration_plan.json"
CONFIG_DISCOVERY="$CONFIG_REVIEW/discovery.json"
.venv/bin/python scripts/anchorium_cli.py configuration-approve \
  --plan "$CONFIG_PLAN" --discovery "$CONFIG_DISCOVERY" \
  --release "$RELEASE" --output "$CONFIG_ACCEPTANCE"
.venv/bin/python scripts/anchorium_cli.py configuration-apply \
  --plan "$CONFIG_PLAN" --discovery "$CONFIG_DISCOVERY" \
  --release "$RELEASE" --acceptance "$CONFIG_ACCEPTANCE" --output "$CONFIG_RESULT"
```

The human reviews the exact plan and types `APPROVE PAS CONFIGURATION <full_plan_hash>` in the existing real-TTY workflow. Application permits only the exact BTC/EWY 1x CROSS changes. Acknowledgment plus independent 1x readbacks are required. This is not order approval. Never retry an uncertain application.

## Protection and original UNKNOWN

These two commands prepare unsigned, bounded reviews; they cannot execute:

```sh
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:BTC --output "$BTC_NATIVE_REVIEW"
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:EWY --output "$EWY_NATIVE_REVIEW"
```

There is no currently admitted PAS qualification execution command or subminimum-stop exception. Do not use the historical PAR executor as a substitute. Genuine linked native-stop closing fills and an independently supported residual route remain absent. A stop acceptance alone, offline tests, a larger initial order, or a software watcher does not prove every possible partial remainder can be protected and closed.

Original unresolved CLOID: `0xac0eea156fcec80986dd67c9057b6ded`; original nonce: `1792217834069`. Read `public_audit/audit.json` here and the prior `docs/activation_v5_2_2026-10-19/targeted_forensic.json`. The fresh direct statuses remain `unknownOid`; current flatness does not establish historical nontransmission. No state, nonce, consumed attempt or certificate was reset. Required evidence is the original attributable terminal/rejection or causally linked nontransmission record, plus the complete relevant fill/fee/funding history; alternatively a separately reviewed and expressly accepted finite shared-domain isolation policy. No such isolation is implemented or approved.

## Exact session and automatic execution

Only after funding, configuration, original historical safety, registration, authentic current data and genuine PAS protective/residual qualification are independently resolved:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare --venue pas \
  --markets pas:BTC pas:EWY --minutes 60 --maximum-notional 1000 \
  --release "$RELEASE" --organizer-confirmation "$ORGANIZER_RECORD" \
  --native-protection-evidence "$NATIVE_PROOF" --output "$SESSION_REVIEW"
MANDATE="$SESSION_REVIEW/mandate.json"
.venv/bin/python scripts/anchorium_cli.py approve --mandate "$MANDATE" \
  --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
```

The 60-minute / 1000-USDP figures are review proposal ceilings, not a mandate accepted in this work. A blocked proposal creates no executable mandate. The human reviews the exact source, wallets, host, limits and risk acknowledgments and types `APPROVE <full_mandate_hash>` once. No such acceptance was created here. A future source change requires a new matched release and review. The current contract requires real funded discovery and qualification before acceptance, and does not preapprove missing funding/protection.

Set `ACCEPTANCE_FILE` to the genuine acceptance path printed by that command. Stop/review the public observer first, then launch the exact accepted scope:

```sh
.venv/bin/python scripts/anchorium_cli.py stop --state "$STATE"
.venv/bin/python scripts/anchorium_cli.py report --state "$STATE"
.venv/bin/python scripts/anchorium_cli.py start --venue pas --authorized \
  --wait-for-readiness --state runtime/pas-btc-ewy-v5-3-authorized \
  --mandate "$MANDATE" --acceptance "$ACCEPTANCE_FILE" --release "$RELEASE" \
  --native-protection-evidence "$NATIVE_PROOF"
```

This wait never creates consent. It requires clean collector shutdown and final account/preflight checks before one runtime handoff. The accepted session needs no individual BUY/SELL prompts. Existing LONG-only scope, one global position, finite loss/action/attempt budgets, risk exits and expiry remain. No signal is forced and no profit is guaranteed. Restart never renews authority.

## Stop, emergency review and actual P&L

```sh
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/pas-btc-ewy-v5-3-authorized
.venv/bin/python scripts/anchorium_cli.py status --state runtime/pas-btc-ewy-v5-3-authorized
.venv/bin/python scripts/anchorium_cli.py report --state runtime/pas-btc-ewy-v5-3-authorized
.venv/bin/python scripts/anchorium_cli.py discover --venue pas --output "$EMERGENCY_PUBLIC_REVIEW"
```

Stopping revokes new entries; owned risk cleanup must remain within the original unexpired authority. Process death or expiry does not prove closure. Review exact order identities, reported fills, fees, funding, remaining positions/orders and two authoritative flat readbacks. Never report paper/synthetic P&L as actual or as an official score. UNKNOWN outcomes require reconciliation, not a blind retry.

If only the public worker has stopped, review its terminal result and persistence first. A new unsigned start after that review is:

```sh
.venv/bin/python scripts/anchorium_cli.py start --venue pas --state "$STATE" \
  --markets pas:BTC pas:EWY --scan-seconds 60 --readiness-release "$RELEASE"
```

The standalone process depends on this Mac, Python, power, internet and exchange availability. It is independent of the Codex app; caffeinate cannot guarantee availability through a crash, power loss or network failure. External alert delivery was not configured or tested. The measured soak is bounded observation, not an overnight availability guarantee.
