# Verified operator entry points

Run from `/Users/adesh/Autonomous Trading Bot - Crypto `, including its trailing space. The commands below collect evidence only. They do not accept or launch trading.

```sh
cd '/Users/adesh/Autonomous Trading Bot - Crypto '
export ANCHORIUM_PUBLIC_ONLY=true EXECUTION_MODE=PAPER ALLOW_LIVE_ORDERS=false HL_DEX=pas SIGNAL_DATA_MODE=PAS_NATIVE_ONLY
.venv/bin/python scripts/anchorium_cli.py pas-ranking --output /private/tmp/anchorium-new-pas-ranking
.venv/bin/python scripts/anchorium_cli.py trading-isolation-review --minutes 60 --output /private/tmp/anchorium-new-isolation-review
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:BTC --output /private/tmp/anchorium-new-native-btc-review
.venv/bin/python scripts/anchorium_cli.py native-prepare --market pas:EWY --output /private/tmp/anchorium-new-native-ewy-review
```

Choose a new output directory for every retained review. Entry points require the normal PAPER/false PAS environment and verify canonical venue metadata. They never expand the entry-market scope.

Read the already running public observer using its exact frozen source and existing state:

```sh
.venv/bin/python docs/activation_v6_2026-10-19/public_reader_source/scripts/anchorium_cli.py status --state runtime/pas-btc-ewy-v6-public
```

The BTC/EWY 1x CROSS configuration is already completed and independently verified. Do not rerun configuration as a trading-activation step.

There is no verified executable PAS signed-qualification command admitted for the unresolved minimum/residual scope, no accepted trading-isolation implementation, and no valid signed session launch command yet. Do not use the PAR qualification executors, create dummy proof/acceptance files, or reuse configuration approval for orders. An exact signed qualification proposal must first be fully scoped, validated and genuinely accepted interactively. The existing `approve`/`start --authorized` entry points remain gated on real PAS protection proof and an exact finite mandate; file paths that do not exist are not launch instructions.
