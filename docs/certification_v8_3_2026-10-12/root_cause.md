# V8.3 root cause in plain language

The blocker is a missing verified way to protect and close a very small **actual** position. It is not a missing wallet balance, an order-price rounding error, or simply too small an entry request.

An entry can pass the $10 minimum and then fill only part of its quantity. An exit can also partly fill. The remaining exposure can be just one exchange lot. The existing local safeguards refuse a new close or protective order whose price times that genuine remaining quantity is below $10. No signed request reaches the exchange in that case.

That local behavior is confirmed at these unchanged boundaries:

- `algo-trading-bot/exchange/base_exchange.py`: `MarketSpec.normalize_order` keeps the general minimum for both entry and reduce-only requests.
- `algo-trading-bot/exchange/exchange_rules.py`: `HyperliquidOrderValidator.validate` independently checks the minimum before reducing-position validation; it does not waive it for a full close.
- `algo-trading-bot/exchange/hyperliquid_execution.py`: previews and execution use the normalized order and central validator rather than bypassing them through an SDK helper.
- `algo-trading-bot/exchange/partial_fill_safety.py`: `exact_full_close_size` preserves the true remainder, refuses unrepresentable dust, enforces the correct opposite direction, and refuses an unverified subminimum close. `partial_path_assessment` examines the smallest possible fill and last exit remainder, not merely the total entry value.
- `algo-trading-bot/exchange/testnet_certification.py`: `require_safe_partial_path` blocks certification entry; the SDK boundary repeats that check. Fixed-quantity protection covers the actual reconciled fill, not an imagined full entry.

The official SDK's `market_close` calls an ordinary reduce-only IOC with the actual position quantity. Changing to this helper does not establish a server-side exemption. A dynamic position TP/SL or a parent-attached stop also does not establish distinct minimum treatment.

The published documentation describes the general minimum, supported reduce-only closes and protection, but the inspected primary sources do not explicitly establish the small-position exceptions needed here. **Unknown acceptance is not the same as a proven universal rejection.** We did not make a real order to experiment with this unknown.

The V8.3 one-lot investigation expands the read-only review from three candidates to **all ten official markets**. It retrieves runtime precision and mapping, mark/oracle/funding, actual L2 levels and side-specific account capacity. A one-lot request could avoid a sub-lot partial if matching obeys the documented lot granularity, but it first needs to satisfy the minimum at entry, protection and the conservative exit price. The observations found no qualifying market. Marks do not substitute for executable quotes when a book is empty or one-sided.

The verified safe behavior is therefore to preserve the existing entry block. The new review adds evidence and regression coverage; it does not add an exception or an activation capability. Current execution, protection, residual reconciliation, bounded attempts, durable recovery and operator escalation remain unchanged and are included in the full regression.

The missing evidence is authoritative confirmation of the exact full-close **and** protective-order treatment for small par positions, or a documented equivalent safe mechanism. That evidence must come before a narrow exception can be implemented, tested and proposed for human-approved execution.
