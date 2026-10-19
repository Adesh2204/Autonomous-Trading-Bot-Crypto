# Anchorium V5.2 terminal runbook

The running worker is PUBLIC ONLY. It detects funding and evaluates readiness,
but has no signer or accepted trading mandate. Funding or the scored opening
cannot promote it into trading. All routine software checks and unsigned reviews
in this release were performed by Codex; actual human acceptance remains human.

## Current dashboard and emergency stop

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
export ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false
export HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY
RELEASE="$PWD/docs/activation_v5_2_2026-10-19/regression_release_final/test_receipt.json"
.venv/bin/python scripts/anchorium_cli.py dashboard --state runtime/pas-btc-ewy-v5-2
```

Single snapshots: `status --state runtime/pas-btc-ewy-v5-2` or
`report --state runtime/pas-btc-ewy-v5-2`. Funding/account scans are normally every
300 seconds, with explicit ages; public rate waits can take up to 180 seconds.
An acknowledged stream alone does not establish fresh candles or a signal.

Local public emergency stop:

```sh
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/pas-btc-ewy-v5-2
.venv/bin/python scripts/anchorium_cli.py report --state runtime/pas-btc-ewy-v5-2
```

The observer is already running. Only if it has stopped and its terminal result,
actual remaining exposure/orders, persistence and source identity have been
reviewed, the exact unsigned startup command is:

```sh
.venv/bin/python scripts/anchorium_cli.py start --venue pas \
  --state runtime/pas-btc-ewy-v5-2 --markets pas:BTC pas:EWY \
  --scan-seconds 60 --readiness-release "$RELEASE"
```

Do not run a duplicate. No restart restores signing authority. The standalone
observer depends on this Mac, Python, power, internet and exchange; Codex/app can
be closed. App-based supervision then stops. The process-bound caffeinate helper
cannot guarantee uptime through power, process or network failure.

## Outstanding external evidence

Review `EXTERNAL_EVIDENCE_REQUEST.txt`. The next concrete action is to obtain an
attributable original organizer/venue response addressing registered wallet,
the exact old CLOID, PAS minimum-lot native/residual semantics and credit.
No changed message has been sent. The older permission to send a different
exact October 17 draft is not reused for this request.

The official opening is October 19 12:00 UTC /17:30 IST; end November 6 at the
same UTC time. Neither the date nor practice USDPR establishes scored funding.
Do not reset the UNKNOWN, durable nonce, consumed attempt or original journals.

## Configuration and supervised qualification

There is currently no accepted configuration, executable PAS qualification or
scored-session mandate. Current unsigned proposals are snapshots, not reusable
approved limits. The genuine account is still unfunded in USDP and selected
markets remain 20x CROSS. Registration and shared historical barriers remain.

After attributable registration evidence, funding and admissible historical
handling exist, `ORGANIZER_RECORD` must name a real reviewed confirmation JSON
with the retained original record; `CONFIG_REVIEW` must be a new directory:

```sh
.venv/bin/python scripts/anchorium_cli.py configuration-review \
  --organizer-confirmation "$ORGANIZER_RECORD" --output "$CONFIG_REVIEW"
```

Use the actual paired `account_configuration_plan.json` and `discovery.json`
returned by that review as `CONFIG_PLAN`/`CONFIG_DISCOVERY`. Choose a new local
`CONFIG_ACCEPTANCE` destination. The human, in a genuine TTY, reviews the plan
and types `APPROVE PAS CONFIGURATION <full_plan_hash>`:

```sh
.venv/bin/python scripts/anchorium_cli.py configuration-approve \
  --plan "$CONFIG_PLAN" --discovery "$CONFIG_DISCOVERY" \
  --release "$RELEASE" --output "$CONFIG_ACCEPTANCE"
```

Only within that genuine approval's lifetime, after review of all displayed
checks and exact actions:

```sh
.venv/bin/python scripts/anchorium_cli.py configuration-apply \
  --plan "$CONFIG_PLAN" --discovery "$CONFIG_DISCOVERY" \
  --release "$RELEASE" --acceptance "$CONFIG_ACCEPTANCE" \
  --output "$NEW_CONFIGURATION_RESULT"
```

The separate configuration capability permits only the exact BTC/EWY 1x CROSS
changes; source/account/agent/nonce/rate/clock/historical checks and final exchange
readbacks are mandatory. It permits no transfer or order. Never repeat an
uncertain invocation.

Unsigned supervised-test preparation, using new output directories:

```sh
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:BTC \
  --output "$NEW_BTC_NATIVE_REVIEW"
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:EWY \
  --output "$NEW_EWY_NATIVE_REVIEW"
```

These do not require completed ordinary native qualification to be prepared.
They cannot execute. No PAS subminimum native/residual exception or dispatch
command is presently admitted. An ordinary session acceptance cannot substitute
for genuine route evidence or independently reviewed qualification-only
authority. The historical PAR qualification command must not be used for PAS.
Any necessary narrow route implementation after external evidence needs a new
source-matched release. An accepted but untriggered stop is not a completed test.

## Exact finite session approval and conditional startup

The current contract does not support valid preapproval of today's missing
funding/native/organizer evidence. Later real discovery and native evidence must
exist before a mandate is prepared. Approval ordering, the five-minute genuine
acceptance window and the finite session expiry have not been extended.

Only after all conditions and any necessary reviewed route implementation pass,
set `NATIVE_PROOF`/`ORGANIZER_RECORD` to genuine retained evidence, and choose a
new `SESSION_REVIEW` directory. The notional is a requested ceiling, constrained
by actual capital, risk, fees, funding, both-side 10% BBO/5-bps depth and lot size:

```sh
.venv/bin/python scripts/anchorium_cli.py prepare --venue pas \
  --markets pas:BTC pas:EWY --minutes 60 --maximum-notional 1000 \
  --release "$RELEASE" --organizer-confirmation "$ORGANIZER_RECORD" \
  --native-protection-evidence "$NATIVE_PROOF" --output "$SESSION_REVIEW"
```

If only one market has independently admissible evidence, explicitly request
only that market. A blocked proposal produces no executable mandate. Use
`MANDATE` only for a real generated `mandate.json`. The operator reviews its full
hash, team/API/host, PAS/USDP scope, LONG-only direction, bankroll/notional,
one-position rule, loss/action/attempt budgets, closing/recovery terms, source,
raw evidence and expiry, then types `APPROVE <full_mandate_hash>` in a real TTY:

```sh
.venv/bin/python scripts/anchorium_cli.py approve --mandate "$MANDATE" \
  --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
```

Set `ACCEPTANCE_FILE` to the actual file printed by that successful human
acceptance. No such file was created in this preparation. After stopping and
reviewing the public observer, this is the conditional authorized launch:

```sh
.venv/bin/python scripts/anchorium_cli.py start --venue pas --authorized \
  --wait-for-readiness --state runtime/pas-btc-ewy-v5-2-authorized \
  --mandate "$MANDATE" --acceptance "$ACCEPTANCE_FILE" \
  --release "$RELEASE" --native-protection-evidence "$NATIVE_PROOF"
```

The wait has no signer and creates no approval. It binds the exact accepted
files and consumes one wait per mandate across output directories. Cancellation,
expiry, corruption, source change or unhealthy terminal reconciliation blocks
dispatch. A successful wait stops its collector before the existing runtime
builder performs final checks and can construct a signer. There is one dispatch,
no blind retry, restart, extension or silent renewal. Routine orders during the
valid session need no individual prompts. A genuine signal is never forced.

For an actually authorized worker, use its own state directory to stop/report:

```sh
.venv/bin/python scripts/anchorium_cli.py stop --state runtime/pas-btc-ewy-v5-2-authorized
.venv/bin/python scripts/anchorium_cli.py report --state runtime/pas-btc-ewy-v5-2-authorized
```

Stop revokes entries; any risk cleanup remains within original unexpired
authority. After expiry signing stops. Stopping a process does not prove a
position closed. Inspect actual original order/fill identities, fees/funding,
remaining positions/orders and two authoritative flat/zero-order readbacks.
Unknown outcomes remain unknown. Preserve both sides of every actual trade;
paper/scenario PnL never establishes realized performance.
