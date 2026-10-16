# Unsent request for authoritative par small-position rules

No message has been sent. No test order has been submitted.

We are preparing one operator-approved LONG round trip on Hyperliquid testnet, DEX par, at 1x CROSS and at most 25 test USDPR notional. The published participant guide gives a $10 order minimum. An IOC entry, or a partial IOC exit, can leave a position whose entire size is worth less than $10.

Please confirm independently for each of these:

1. Does a bounded reduce-only IOC for the exact entire remaining par position receive a minimum-notional exemption below $10?
2. Does a reduce-only stop-limit protecting that exact entire remaining position receive the same exemption? Does grouping na versus positionTpsl matter, and are explicit size or zero-size semantics required?
3. What are the exact conditions, supported fields and official reference? If either exception is unavailable, what supported bounded method safely flattens such a remainder without opening additional exposure?

Our adapter currently retains the published minimum. We will not increase the position, submit an oversized reduce-only order, substitute a market helper, or assume an undocumented exemption. Certification entry remains blocked until a safe closing path is established and offline-tested. Any actual test also requires separate exact human approval.
