# P0 isolated qualification operator procedure

Preparation is read-only. Global PAPER/false and disabled protection remain in force. The maximum opening ceiling is 1,000 TEST USDPR; it is not a target or a guaranteed maximum loss. The rule chooses the smallest runtime lot quantity whose fixed opening limit reaches the ordinary $10 minimum. No strategy signal is asserted.

From the cloned project root:

```sh
.venv/bin/python scripts/run_emergency_qualification.py \
  --output-directory "docs/qualification_emergency_2026-10-13/operator-$(date -u +%Y%m%dT%H%M%SZ)" \
  --test-receipt docs/qualification_emergency_2026-10-13/regression_release/test_receipt.json \
  --duration-seconds 60 --route auto
```

`auto` tries eligible public IOC candidates first, with GTC as a separate resting candidate. Explicit `--route ioc`, `--route gtc` or `--route alo` selects a preparation route. Only the selected exact proposal can later be approved; this is not permission to fall back or switch route during execution. Read-only `--transport rest` is available; default observation uses acknowledged public WebSocket books with bounded REST fallback.

IOC uses at most 50% of genuine L2 quantity inside the fixed entry price (ask +20 bps, normalized without exceeding it); reviewed exit depth uses bid minus20 bps. GTC/ALO prepares one bid-priced order and checks exit depth. Spread ceiling50 bps, mark/oracle50 bps, mid/oracle100 bps, order/oracle150 bps. These are the isolated proposal policy, not the production15 bps/10% rule.

Every possible whole-lot filled or remaining position must fit the ordinary closing minimum or an already evidenced exact full-position close shape. BTC historical one-lot evidence is not a universal exemption. The normal minimum and stop-validation gates remain intact.

## Approval boundary

Read `proposal.json`, `readiness.json` and `operator_handoff.json`. There must be a successful current source-bound full regression and fresh actual account reconciliation, 1x CROSS, valid agent, margin, metadata, original signer identity and local ownership. Keep remote host ownership labeled as human confirmation.

The operator must explicitly authorize the exact current proposal ID and accept all risks, including NO VERIFIED STOP and possible manual recovery. `approval_REQUIRED_UNFILLED.json` is deliberately blank/false and does not authorize anything. The approved file is `operator_approval.json`, with the exact proposal and new policy hashes, the human approval text, integer current approval/expiry times and every required acknowledgment true. Previous $25 approvals are invalid for this new type/version. Expiry cannot extend beyond five minutes from the observed proposal; entry requires90 seconds remaining.

The saved handoff contains the actual supported `--execute` command. Do not run it until exact human approval. It uses the same tested runner, real SDK0.24.0, the registered TEAM as account_address and the existing durable qualification/nonce state. One entry, one original-entry cancellation if needed, two exact reduce-only IOC exits, maximum four signed actions. No administration, transfer, protective order, reprice, replacement or repeat entry is permitted.

## Exposure and recovery

GTC/ALO is monitored for up to30 seconds from durable transmission time. Any partial fill ends waiting: cancel the original remainder and confirm terminal order status/team fills before exit sizing. Local timing/cancellation is not exchange-side automatic expiry. A disconnected host can leave a resting entry and unprotected exposure.

After an approved attempt, actual team `userFillsByTime`, orderStatus, positions and open orders establish the result. Accepted/posting/SDK fill summaries alone never establish qualification. IOC zero fill and expired GTC are valid failed attempts, never retried automatically. Fees, reported closedPnl, funding and account equity must reconcile.

Save `execution_report.json` and `WHITELIST_TRADE_PROOF.json` from the bounded workflow. Proof must include actual registered account, order/fill IDs, quantity, executed notional and timestamps. A proof of fill is separate from proof of flat and organizer whitelisting. Never create a fabricated proof during preparation.

On uncertainty, stop new entries and preserve `runtime/testnet/anchorium-bot-1/qualification.sqlite`, its checkpoint data and `nonces.sqlite`. Read the original CLOID/OID, team fills, `frontendOpenOrders`, and `clearinghouseState(dex=par)`. UNKNOWN is not flat. Do not resubmit the entry. Resolve the unfilled original entry before closing. Only current, unrevoked exact approval can authorize an exit within its size/floor/attempt limits. Halted/expired/outside-bound exposure needs separate exact recovery approval or manual wallet intervention. Flat requires exchange-confirmed zero positions, zero open orders and durable ready account reconciliation.

Small protective-stop acceptance remains UNVERIFIED. No stop is submitted. Qualification is excluded from strategy performance and does not activate autonomous practice or certify protection/profitability/organizer whitelisting.
