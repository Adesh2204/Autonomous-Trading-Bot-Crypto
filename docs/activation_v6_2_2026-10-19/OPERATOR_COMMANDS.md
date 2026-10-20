# Verified V6.2 operator commands

These existing entry points perform reads and local evidence collection. They grant no exchange-write authority. Use a fresh output directory for each review:

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
export ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY
anchorium_review_dir="$(mktemp -d /private/tmp/anchorium-v6_2.XXXXXX)"
.venv/bin/python scripts/anchorium_cli.py history-review --output "$anchorium_review_dir/history"
.venv/bin/python scripts/anchorium_cli.py pas-ranking --output "$anchorium_review_dir/ranking"
.venv/bin/python scripts/anchorium_cli.py trading-isolation-prepare --minutes 60 --output "$anchorium_review_dir/isolation"
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:BTC --output "$anchorium_review_dir/native-btc"
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:EWY --output "$anchorium_review_dir/native-ewy"
```

The first next external action is to obtain the exact PAS minimum/close-all semantics listed in [the clarification questions](../activation_v6_1_2026-10-19/PAS_ROUTE_CLARIFICATION.md). The ordinary guide and the SDK helper do not establish a subminimum stop or closing-fill guarantee.

The existing `trading-isolation-approve` entry point requires a genuine reviewed PAS mandate and the source-matched release, an exact typed isolation phrase, the bound host, original records and an unexpired policy. It grants no order authority. No executable PAS mandate currently exists, so a fake path is not provided as an approval command.

The next signed scope, after applicable residual semantics and a reviewed implementation exist, must be a separately approved bounded PAS qualification. Refresh prices and scope first. The proposal limits one entry to 25 USDP, at most six signed actions and five minutes, with cleanup time reserved. The current unsigned proposal uses a 10 USDP planned-floor loss ceiling; this is separate from the autonomous session budget and is not a guaranteed realized loss cap or an accepted scope. Record entry/stop/closing IDs, actual fees/funding and two distinct flat/order-free reconciliations. Stop after rejection, partial close or ambiguity; do not create a larger scope by retrying. Do not reset the old consumed attempt or reuse PAR/configuration acceptance.

Only after genuine qualification can a separate finite autonomous mandate be accepted. Its per-entry and cumulative caps are 1,000 / 2,000 USDP; two attempts, one global position and twelve signed actions; 60-minute maximum; 1x CROSS; 100 USDP intended trade risk and 200 USDP session stop, both measured against the 20,000 allocation. Intended risk and stop-limit prices cannot guarantee a realized loss ceiling through a gap. No renewal or midnight reset exists.

Once the verified V6.2 public-reader launch receipt exists, use its frozen source for status:

```sh
.venv/bin/python docs/activation_v6_2_2026-10-19/public_reader_source/scripts/anchorium_cli.py status --state runtime/pas-btc-ewy-v6_2-public
```
