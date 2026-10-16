# Team Anchorium — approved qualification outcome

**The approved attempt stopped at final market validation. No order was signed or submitted. No qualifying fill was obtained.**

Proposal: `876707f1612b45525795ae76ad10caf2cd36f0fb1f1b17389fd9ae63e6b9f218`. The previous proposal `1e05298b4ab50142ccb991995cc954ef9bbab9080d4c5536a22a51a79e08b4f2` was never reused.

The human replied “Yes” to the exact proposal and all eight risk acknowledgments. Codex completed the approval JSON at 2026-10-14T10:47:08.934000+05:30. Its final entry-transmission deadline was 2026-10-14T10:48:23.158000+05:30 and authorization expiry was 2026-10-14T10:49:53.158000+05:30. This authorization is now expired.

The authorized order was one BUY 0.0002 `par:BTC` IOC at limit 83,610, maximum 16.7220 test USDPR, 1x CROSS, with exact residual reduce-only exits above 82,171 and the unchanged attempt limits. No protective stop was authorized or certified.

## Why the trade did not happen

The existing launcher returned `QUALIFICATION_LOCKED / P0_CURRENT_PRICE_OR_CAP_REQUIRED`. Its final guard compares the approved fixed order with a new executable quote: an IOC must reach the current ask while staying within the configured 20-bps upper price allowance and all notional limits. Preparation passing does not guarantee that the same fixed price passes later. The guard was preserved; the order was not repriced, replaced or retried.

The error occurred in `build_runtime` at `check_entry`, before API-key loading for signing, NonceManager construction, or EmergencySDKTransport construction. There was no SDK execution runtime or actual exchange entry. The launcher does not persist that failed quote, so its exact bid/ask cannot be reconstructed from this output. The later successful account-check quote is a different observation.

## Evidence after the blocked attempt

- Qualification journal SQLite integrity: `ok`; its one recovery snapshot checksum was verified.
- Actual order intents: 0. Signed API action reservations: 0. Signed management actions: 0. Entry-consumption marker was never set.
- The failed builder's journal is preserved, including `last_clean_shutdown=False`. It has one startup/reconciliation snapshot, not a certified completed execution shutdown. No journal or nonce record was reset or relabeled.
- A separate `/info`-only account check observed the registered wallet at 2026-10-14T10:50:26.413000+05:30: zero positions, zero open orders, no reported fills and healthy account reconciliation.
- Reported account equity/collateral: 1,000,000 USDPR; margin used 0.
- The independent read-only journal has two verified checkpoints, matching source identities, clean shutdown and zero action rows. Its clean status is not substituted for the failed execution builder's lifecycle.
- No actual-wallet signature was created. No order, cancel, protection, transfer or account-setting change was submitted.
- No actual trade fees or realized trade P&L exist to certify. No `WHITELIST_TRADE_PROOF.json` was generated. Organizer whitelist confirmation remains unverified.

## Safety and source

The full 2,046-test source-bound receipt remains valid. Source hash: `90c913950d7c7f23bfa176612356e0995d9fef5976be54fc449695b8cc1bf882`. Strategy-freeze verification passes. `signal_brain.py`, all production strategy rules, wallet settings, protection settings and PAPER/false locks are unchanged. No code was modified, no new recurring task was created and no uncertain or failed order was repeated.

## Current state

The account was observed flat after the failed preflight; this is not a completed trade. The goal of a genuine qualifying practice fill remains outstanding. The expired authorization is retained as historical evidence and must not be reused. Any subsequent attempt needs a fresh read-only proposal and new approval of its exact prices and risks. Codex will handle the routine file and Terminal operations if another attempt is authorized.
