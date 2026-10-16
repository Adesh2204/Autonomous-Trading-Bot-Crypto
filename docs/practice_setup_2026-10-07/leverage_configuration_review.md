# Deliberate 1x CROSS configuration — review

The latest user request explicitly asks to align the exchange to the existing
bot policy, rather than changing the bot to 20x. All ten `par:` markets are in
the scanner universe, so the configuration plan covers all ten. No startup
routine makes this change automatically.

The read-only plan is saved in
`docs/practice_setup_2026-10-07/leverage_plan.json`. It records runtime asset IDs,
current leverage, the desired setting and each exact `updateLeverage` action.

The configuration helper permits only:

```json
{"type":"updateLeverage","asset":"runtime-verified par asset ID","isCross":true,"leverage":1}
```

The illustrative asset string above is never sent. The actual value is an
integer read from verified venue metadata. Other action types, extra fields,
native assets, higher leverage and isolated margin are rejected.

Orders remain locked with `EXECUTION_MODE=PAPER` and `ALLOW_LIVE_ORDERS=false`.
The helper uses a separate configuration approval type, not LIVE trading
approval. Its transport has no order/cancel/general action method and cannot be
used as the production executor's required OfficialSDKTransport. It uses the
pinned official SDK for the one authorized configuration action.

Before applying, the helper requires manual verification of both public wallet
identities. It rechecks real testnet metadata, funding, unified mode, valid API
approval, current flat positions, ordinary/trigger orders, clock and request
budget. The actual API key must derive to the approved API public address.
Account and signer leases prevent a second local configuration/signing owner.
They do not coordinate another host; keep only one deployed signer process.

The nonce database is permanently bound to:

`runtime/testnet/anchorium-bot-1/nonces.sqlite`

Do not move/delete it or replace its lease/history to pass a check. Future
authorized execution using this API key must use that same nonce path and one
host. The local nonce probe allocates no nonce and creates no signature.

Each attempted setting is journaled durably in `configuration.sqlite`. No HTTP
retry or redirect is used. Each result is parsed and `activeAssetData` is read
back. An uncertain transmission/readback stops the whole sequence and retains
an UNKNOWN action for human review; it never blindly repeats. A partially
completed sequence is reported as partial, never as all-ten aligned.

The example confirmation file has false verification and an expired timestamp.
It intentionally cannot authorize anything. An environment flag, the existence
of this review, or the fact that the account has funds is not manual verification.
The requested configuration change remains pending while that verification is
missing. It does not depend on historical CSV provenance or a qualifying trade
signal, because it changes settings on a verified flat account only.

Read-only plan command, with a new output filename:

```sh
.venv/bin/python scripts/configure_par_leverage.py \
  --team-address 0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C \
  --api-wallet-address 0x46c9BED595770150752E7fA3806449F81E0Ec6f9 \
  --state-directory runtime/testnet/anchorium-bot-1 \
  --output docs/practice_setup_2026-10-07/leverage_plan_next.json
```

Applying additionally requires `--apply` and an actual, current
`--manual-confirmation-file`; the agent must obtain the human verification
before creating that record or invoking this path. Leave both bot safety flags
unchanged. This is not a command to begin real trading.
