# Team Anchorium — October 15 actual qualification outcome

**GENUINE PRACTICE ENTRY FILLED. EMERGENCY_EXIT_REQUIRED: 0.0002 BTC LONG REMAINS OPEN.**

The latest repeated direct exchange observations, ending 2026-10-15T10:18:59.807000+05:30, show the exact 0.0002 BTC long and no open orders. No exit order was submitted. The workflow has halted; no further automatic entries or exits are running. No verified protective stop was submitted. Manual or separately authorized recovery is required. Do not reuse the halted mandate.

## 1. Session and genuine authorization

Session `66b034a017f6b460631bba11def79c9d61c50ff7c81d88c251086555e97d4049` was genuinely accepted with the user's “I approve” reply to the exact session and all nine acknowledgments. Acceptance timestamp 2026-10-15T10:15:02.353000+05:30. The acceptance JSON and human-message provenance are in `session_preparation/`. No October 14 authorization was reused.

Approved scope: Hyperliquid TESTNET par:BTC BUY IOC exactly 0.0002 BTC, 1x CROSS, maximum opening 20 TEST USDPR, maximum BUY price 100,000, one entry, at most two bounded exact-position reduce-only exits, one original-entry cancellation and four signed actions. The original session ended no later than 23:59 IST today, with last entry 23:57:30 and five-minute individual envelopes/90-second reserve. The actual attempt is now consumed and halted, so those clock limits are not permission to restart it.

## 2. Regression and source validation

**2,248 passed; zero failures, errors or skips.** Freeze and Phase-0 passed before and after. Source `2806a21a449f5d18e1a0ce6cf76f194c31604ca647ac6d6db5fb7fa4b43675e7` matches the completed regression, approved mandate and final runtime hash. Today's production change was only three explicit date constants from October 14 to October 15. Tests update the calendar assertion and add four date/reuse/expiry cases. No trading strategy or production safety setting changed.

The original UNKNOWN row and immutable PROVEN_NOT_TRANSMITTED certificate remain unchanged. Actual execution advanced the API nonce exactly once and appended its journal event; earlier records were not deleted. See `post_execution_audit.json`, today's SQLite backups, source diffs and `regression_release/test_receipt.json`/XML/log.

## 3. Watcher status

The existing persistent watcher started after genuine approval, selected one eligible fresh BTC envelope, handed off its exclusive nonce lease and shared rate budget, and stopped after the single attempt. Its final health says stopped with the lease released. No process restart, duplicate entry or replacement order occurred. Production remains PAPER/false; protected autonomous trading remains disabled.

The source-bound read-only preflight confirmed registered wallet `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`, approved API `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`, unified account, 1,000,000 TEST USDPR, 1x CROSS, sufficient margin, no initial position/orders, fresh quotes/depth, clock and local signer ownership. Source/nonce/account/price checks ran at signing boundaries. Sole-host use was reaffirmed in the accepted nine acknowledgments.

## 4. Entry reached exchange HTTP

**YES — exactly one signed HTTP POST.** Transmission began 2026-10-15T10:16:29.950000+05:30; exchange response HTTP **200** at 2026-10-15T10:16:30.830000+05:30. One nonce was allocated. No cancel or exit action was signed/submitted. The actual immutable wire limit was **81593 USDPR/BTC**, selected from fresh conditions inside the approved envelope; it was not an old preview price.

Read-only account-observer reports contain an `exchange_orders_submitted=0` field describing that observer's own read-only role. It is not a total of the signed execution path. The actual transport journal independently records the one POST and response.

## 5. Exchange acceptance and execution

The exchange accepted the IOC and filled its complete **0.0002 BTC** at **81,512.0 USDPR/BTC**. Actual notional **16.30240 TEST USDPR**, below the approved 20 cap. Fill timestamp **2026-10-15T10:16:30.641000+05:30**. Actual entry fee **0.014672 USDPR**. Later direct orderStatus reads say filled, remaining order size zero, and repeat the original client-order ID and original size. Actual user fills were queried for the registered team wallet; this is not a hypothetical paper fill.

## 6. Actual filled quantity

Entry: **0.0002 BTC BUY**. Closed quantity: **0 BTC** in the retained exchange records. No second entry was attempted. No volume was created merely to force a profit/loss.

## 7. Genuine IDs and proof

| Item | Exchange/journal value |
| --- | --- |
| Entry exchange order ID | `62755970305` |
| Original client-order ID | `0x8e73fd40fceb5abb949215079466cb0b` |
| Genuine fill/trade ID | `800659111758533` |
| Market | `par:BTC` |
| Registered account | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Exit order/fill IDs | None — no exit submitted |

`WHITELIST_TRADE_PROOF.json` now contains genuine registered-account fill evidence, IDs, notional, timestamps, original cloid and the explicitly unresolved position. The original workflow proof remains untouched at `session_preparation/authorized_session/WHITELIST_TRADE_PROOF.json`. Raw repeat exchange reads are in `post_execution_read_only/report.json`.

## 8. Open position, exact blocker and required recovery

**0.0002 BTC LONG remains open, without a verified protective stop.** Last observation 2026-10-15T10:18:59.807000+05:30; open orders zero. This is not a completed round trip.

The workflow error is **RATE_LIMITED during post-entry account reconciliation**, after the exchange had already filled the entry and before it created any exit intent. This is not evidence of an exchange-rejected close: no close reached HTTP. The local rate manager can block info requests when rolling public weight/reserve/backoff requirements fail. The retained records do not identify the exact failing info endpoint or establish a venue HTTP 429. API budget counters, signed action count and raw event timeline are preserved rather than inferring an exchange outage.

The independent post-halt observer again confirms the open quantity and fill. Its broader readiness flag is false with `CERTIFICATION_ACCOUNT_CHANGED_DURING_RECOVERY`; account valuation fields moved during the multi-read observation. Do not present that as a fully certified flat reconciliation. The direct before/after position quantities are 0.0002 and all order reads are empty.

**Required now:** inspect the registered team account on **TESTNET**, select **par:BTC**, and close the exact actual long using **reduce-only**. Verify the current quantity before confirming; never open a new BUY or increase exposure. The prior bounded exit policy was SELL IOC for exact held size at fresh bid less 20 bps, never below its 80,141 reviewed floor. The halted/finished mandate must not be reused for signing. If operator recovery requires a different action, price envelope or execution path, obtain separate exact recovery authorization rather than silently changing safety controls. Do not claim closure until exchange closing fills, zero par positions and zero open orders are read back. Preserve all journal/nonce/fill evidence.

Narrow historical full-position closing support is not a guarantee of a future fill. Protective-stop acceptance remains unverified. No further automatic order will be submitted in this session.

## 9. Realized P&L

**A completed-round-trip realized P&L is unavailable.** There is no closing fill. The entry fee is real; transient unrealized P&L and an entry fill's closedPnl=0 are not a closed-trade result. The post-halt snapshot reports unrealized P&L -0.0056 TEST USDPR, which can change. No profit or loss for a completed trade is claimed.

## 10. Organizer whitelisting and readiness

**One genuine algorithmically generated par practice fill attributed to the registered funded team wallet is verified.** The evidence requested for the practice-fill criterion exists. **Organizer whitelisting itself is NOT confirmed.** No organizer message was sent automatically.

Protection readiness, protected controlled execution, general practice readiness and LIVE readiness remain false. The open position needs recovery before any future trading consideration. No scored pa/USDP migration or unrestricted autonomous trading was activated.

The concise next action is manual or separately authorized recovery of the known open 0.0002 BTC long, followed by genuine exchange readback. Earlier preparation details are preserved separately in `preparation_report.md`.

## Final read-only confirmation

At **2026-10-15T10:22:11.476000+05:30**, repeated exchange reads still show **0.0002 BTC LONG**, entry price 81,512.0, and **zero open orders**. No SELL closing fill exists in the query window. The latest transient unrealized P&L is 0.009 test USDPR; no completed-trade P&L is claimed. Evidence: `final_position_read_only/report.json`. Recovery is still needed. Use the registered team account 0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C on TESTNET par:BTC, verify the actual quantity and close that long reduce-only. No further signed action is running.
