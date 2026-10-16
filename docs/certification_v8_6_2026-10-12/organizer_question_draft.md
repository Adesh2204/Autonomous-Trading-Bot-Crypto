# One-lot par protective-stop clarification — UNSENT

This is a draft for the human operator. No message or exchange order has been sent.

We independently verified six historical sub-$10 exact full-position reduce-only
IOC closes on Hyperliquid testnet `par` (original OIDs: 62391880965, 62228843959,
61841673908, 61878767079, 61912483832, 61956380536). We implemented only their
observed market/direction/quantity scope, with fresh position reconciliation,
exact-size SDK permits and the ordinary opening-order minimum intact.

Those IOC closes do not establish stop-loss acceptance. Our 12 October bounded
read of 12 public accounts' open orders and two additional capped histories found
no stop example. We retain the entry block and seek a separately verifiable rule.

Please confirm for the **testnet par DEX**, separately for Stop Limit, Stop Market
and `positionTpsl`:

1. Can a held position below $10, including **one runtime lot**, receive an exact-size,
   opposite-side, reduce-only stop? Which minimum exceptions, if any, apply?
2. What size and grouping must be used? Does the notional check use limit, trigger,
   mark or another price, at placement, triggering, or both?
3. Can a separately submitted stop protect exactly an IOC entry's actual partial
   fill? What happens after a partial exit/trigger fill leaves a small remainder?
4. Please provide the venue rule or an existing original `par` stop OID with size,
   reduce-only flag, trigger/limit prices, accepted readback and actual position
   coverage, plus any resulting fills. A small fill of a larger submitted order
   does not establish small-order admission.
5. If unsupported, is there a documented native mechanism that protects and closes
   the remainder without adding exposure or oversizing an order?

We will not open or enlarge a position to manufacture evidence. PAPER/false remains
locked. Any later exact, bounded trade requires a fresh preflight and explicit
human approval; this question is not an activation request.
