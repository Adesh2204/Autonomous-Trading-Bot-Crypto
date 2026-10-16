# Unsent request for authoritative small-position rules

This is a draft for the human operator. No message has been sent.

Team Anchorium is preparing its first bounded Hyperliquid testnet `par` round
trip. We are keeping actual orders disabled until we can establish the cleanup
and protection rules for partial fills. The guide specifies $10 per order.

Please confirm the following separately for this venue:

We have independently verified existing `par:HYPE` full-position reduce-only IOC
closes: order 61997055149 closed SHORT 0.03 (original value 2.79654 USDPR), and
61745948135 closed LONG 0.07 (6.15531 USDPR). Original orders and matching fills
agree. These are three/seven lots; neither establishes one-lot protection.

1. Is an exact **entire current position**, including one runtime lot below $10, accepted as an opposite-side
   `reduceOnly=true` IOC? Is this different from a partial reduction? Please
   specify whether minimum value uses submitted limit price, mark, or another basis.
2. Can a sub-$10 position receive a fixed-size reduce-only Stop Limit/Stop Market,
   and/or full-position `positionTpsl` protection? Please specify exact supported
   size/grouping semantics and validation both at placement and trigger time.
3. If either operation is unsupported, what documented native mechanism closes
   and protects a tiny partial fill or residual without enlarging the position?
4. Could you provide an official documentation reference or an existing testnet
   `par` example with original size/price/reduce-only fields, order status, actual
   position before/after and matched fills? A small fill from a larger original
   order would not resolve the minimum-order question.

Illustrative question only, **not an order proposal**: `par:ETH` quantity `0.0001`
at a reference price around `2500` is about `0.25 USDPR`. We need to know how an
already held position of this size can be protected and flattened if it results
from partial matching. We will not enlarge exposure merely to satisfy $10.
