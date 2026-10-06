# Independent emergency protection: proposed practice policy

This is an infrastructure design decision made under the user's request to prepare practice. It does not activate trading, approve a funded account, or change the frozen strategy. The normal strategy stop, target, ATR calculation and management methods remain untouched.

The proposed settings are saved in [protection_policy.proposed.json](</Users/adesh/Autonomous Trading Bot - Crypto /configs/protection_policy.proposed.json>). The file deliberately has `enabled=false` and `approval_reference=null`; the production reliability file remains disabled too. Loading either configuration grants no exchange permission.

## The proposed settings in easy language

- **Emergency distance: one ATR beyond the existing normal stop.** For a LONG position, subtract one entry ATR from the normal stop. For a SHORT position, add one entry ATR. ATR is the strategy's existing measure of price movement; this layer does not recalculate or retune it.
- **Execution allowance: 0.5% beyond the trigger.** The existing protection implementation constructs a bounded execution price. This limits the accepted execution price; it does not guarantee a fill during a gap or an empty order book.
- **Order behavior: reduce-only, tied to actual account exposure.** Protection cannot open a position or increase its size. It uses the observed filled quantity, not the original requested quantity.
- **Strategy management continues normally.** The independent order sits beyond the normal stop and is a fallback for connectivity/process failure. Accepted exchange orders can remain there while the local bot is offline.

These are starting engineering choices, not values optimized on crypto results. One additional ATR gives the normal management room without placing a far-away arbitrary percentage stop. The 0.5% allowance is deliberately bounded; practice must establish whether it is suitable for actual liquidity. Emergency losses can exceed the ordinary strategy-stop loss, and the order can remain unfilled if price moves beyond its execution limit.

## Checks required before a future order

The protection manager already requires management evidence, current actual position direction/quantity, market precision, an emergency trigger beyond the normal stop, and a trigger on the safe side of a known liquidation price. Missing evidence or impossible geometry pauses new entries; it does not fabricate a stop or place an unvalidated one.

The existing lifecycle also tracks partial positions, uncertain submissions, restart reconciliation and obsolete protection after confirmed flat exposure. If an ordinary exit is followed by a pending protection cancellation, the account must remain blocked from a new entry until confirmed safe. The single global position invariant remains in force.

## Activation decision

Today the project remains PAPER with `ALLOW_LIVE_ORDERS=false`. No protective, exit or entry exchange action is allowed.

After the wallet is funded and configured, the human verification must confirm the actual team account, API agent and expiry, unified mode, fee scaling, leverage/margin, emergency-policy approval reference and exchange reconciliation. At that point an explicitly approved enabled reliability configuration can be supplied to the future testnet launcher. A proposed JSON file or funding observation alone does not satisfy those gates.

Funded practice must check accepted trigger/reduce-only order parameters, exact filled size, cancellation after confirmed exits, partial fills, actual liquidation/margin checks and recovery. Offline tests are useful engineering evidence but are not funded-account certification.

The participant guide supports trigger protective orders but does not prescribe these distance/allowance values. This policy belongs to Anchorium's operating controls.
