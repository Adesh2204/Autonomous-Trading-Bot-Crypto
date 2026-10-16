# V8.2 root cause and remediation

## Exact causes

1. `MarketSpec.normalize_order` and `HyperliquidOrderValidator.validate` enforce the documented $10 minimum for entry, close and stop requests. Removing either one would not establish venue acceptance.
2. Entry notional is not filled notional. A valid 25 USDPR IOC can fill one runtime lot; a reduce-only exit can also leave one lot. Increasing the requested entry quantity does not remove either risk.
3. Generic size normalization rounds down. For an authoritative full close, silently rounding an unrepresentable residual could falsely suggest the entire position was requested for closure. The certification path now rejects such a residual explicitly.
4. V8.1 recovery understood only generic rejected/canceled statuses. Named documented terminal rejections could remain UNKNOWN. V8.2 resolves only explicit known terminal outcomes with the original CLOID/market identity and actual matched fills; unknown and missing observations stay unresolved.
5. A stored protection plan must match the position at verification, rather than just matching its own order readback. V8.2 verifies the current full quantity again.

## Implemented safe behavior

`partial_fill_safety.py` evaluates the smallest entry fill AND exit remainder at reviewed prices using runtime lot size. It grants no undocumented exception. Entry remains blocked when one lot is below the minimum.

Protection and close sizing use the exact authoritative remaining position, correct opposite direction, approved quantity ceiling and unchanged bounded price. No dust is rounded away and no close is enlarged to reach $10. Ordinary supported partials use actual quantity. Subminimum or unrepresentable residuals are recorded durably and halt with operator review; they cannot produce another entry or a false flat/P&L certificate.

Rejection recovery distinguishes an explicit zero-fill rejection from partial fills followed by cancellation. It preserves real filled quantity, fees/accounting, original IDs and durable attempt consumption. Unknown outcomes never authorize a retry or clear exposure.

Read-only preflight checks all ten leverage settings, saves a non-executable exact review proposal when ordinary price/account gates pass but partial safety fails, and keeps that wrapper distinct from an executable proposal or operator approval.

No strategy, production threshold, minimum-order rule, global PAPER lock or disabled production protection policy was changed. This is a verified conservative failure-handling improvement; it does not create verified subminimum venue support.
