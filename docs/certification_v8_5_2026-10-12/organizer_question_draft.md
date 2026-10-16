# Small-position protective-stop clarification — UNSENT

This is a draft for the human operator. No message or order has been sent.

We verified six existing sub-$10 exact full-position reduce-only IOC closes on
the Hyperliquid **testnet `par` DEX**, including one runtime lot on BTC, ETH,
HYPE, BRENT and EWJ. Order IDs are 62391880965, 62228843959, 61841673908,
61878767079, 61912483832 and 61956380536. Original sizes/prices, filled statuses
and matched fill `startPosition` values show full reductions to zero. These
records are manual limit IOC orders, **not protective-stop evidence**.

Before opening our first bounded position, please confirm separately:

1. Can an already held position below $10, including a single runtime lot,
   receive an **exact-size, opposite-side, reduce-only Stop Limit**? Is the
   answer different for Stop Market or position-attached `positionTpsl`?
2. Which grouping and size semantics are supported? Does the $10 check apply
   at placement, at triggering, or both? Is notional evaluated using the
   submitted limit, trigger price, mark, or another price?
3. If an entry fills only partly, can we place a separate stop covering exactly
   the actual filled position? If a stop executes only partly, how is the
   residual protected and closed without increasing exposure or oversizing?
4. Please provide an authoritative venue rule or an existing `par` stop example
   with original order ID, exact size, reduce-only flag, trigger/limit prices,
   accepted readback, actual position quantity and any resulting fills. A small
   fill of a larger submitted order does not establish the exception.
5. If this protection is unsupported, is there a documented native mechanism
   that protects and closes such a residual without adding exposure?

Illustration only, **not a trade request**: one `par:ETH` lot is currently
`0.0001`; near the observed 2546 price it is about 0.25 USDPR. We will not open
or enlarge a position merely to test or satisfy a minimum. We keep PAPER mode
and all actual order locks enabled pending clarification and a later exact
human-approved trade proposal.
