# PAS qualification scope requiring clarification

The human supplied the official Participant Guide again during this review. Its Price and size rules state a $10 minimum for each order. Its stop section requires reduce-only TP/SL. Its close section says `market_close` is a reduce-only IOC that can be partial or rejected. The supplied wording does not establish an exception below the minimum.

Source: https://perpetual-alpha26.github.io/docs/ (checked 19 October 2026).

## Exact questions for the organizer or venue

For PAS/USDP, with runtime BTC lot 0.00001 and EWY lot 0.001:

1. May an exact full-position reduce-only IOC close have notional below $10? Does this apply to every representable residual size in either direction, or only a specific close-all action?
2. May a fixed-size reduce-only Stop Limit with notional below $10 be accepted, armed, triggered, and filled? Does a partial closing fill retain effective coverage of its actual remainder?
3. Does a position-attached stop offer a distinct close-all/resize rule? What exact action fields and stop-limit execution semantics apply, including gap behavior?
4. What actual rejection/status codes distinguish unsupported minimum behavior from liquidity rejection? A rejected close must not be assumed to succeed on retry.

## Current genuine evidence

The account is funded and both BTC/EWY are now 1x CROSS. A bounded read-only review of two public PAS counterparties found no native-stop or subminimum reduce-only records in the sampled order histories. One history reached the 2000-row limit. This is absence of a usable proof in the sample, not proof that the venue rejects every such route. Third-party observations cannot certify Team Anchorium's own stop lifecycle.

A one-lot observation alone cannot cover all other possible small partial fills. The new unsigned native proposals quantify each route's number of possible subminimum sizes at its reviewed prices. Actual production eligibility remains blocked until applicable semantics and genuinely linked order/fill/reconciliation evidence support the admitted scope.

## Proposed next qualification, after semantics and separate approval

Keep a single signer/account lease and original nonce store. Use only one explicitly approved PAS market, one entry of no more than $25, at most six signed actions, no blind retry after ambiguity/rejection, a five-minute hard authority limit with cleanup reserve, exact reduce-only remaining-size exits, and fresh account/book/fee/margin checks. Declare possible rejection, stop-limit gap, and residual exposure explicitly. Preserve every attempt, order, fill, fee and funding record. A stop acknowledgement alone does not qualify trigger execution or a residual exit.

This is a review specification, not an executable signed qualification command or consent. No organizer message has been sent. The existing PAR qualification executors and old configuration-only acceptance must not be repurposed for PAS.
