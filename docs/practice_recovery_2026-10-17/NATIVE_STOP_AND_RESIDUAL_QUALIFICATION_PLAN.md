# NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN

**Native trigger/closing qualification and subminimum native protection remain incomplete. No venue prohibition is proved.**

| Category | What the evidence establishes |
| --- | --- |
| Documented | Mark triggers; default full-position tracking versus fixed explicit size; parent/child cancellation behavior; triggered limits may remain unfilled through gaps. |
| Exchange verified | The historical exact one-lot BTC reduce-only IOC close; current account flatness; own history contains no native trigger record. |
| Unknown on registered par | Subminimum native Stop Limit exception and exact wire semantics; genuine parent/trigger/child fills; actual residual protection and native cleanup. |

The [TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) explains sizing and gap/cancellation behavior. The [exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) exposes positionTpsl grouping; it does not itself establish a registered-par subminimum exemption. The [error reference](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) lists the ordinary minimum-notional rejection. Documentation establishes semantics, not successful execution on this account.

Every sampled market's minimum lot is worth less than 10 TEST USDPR. A conventional LONG stop limit below current mark is lower still. Larger initial size cannot rule out a one-lot partial residual. Runtime precision, partial-fill guards and normal minimum checks remain unchanged. No zero-size sentinel, grouping bypass or larger risk allowance was added.

1. First obtain admissible resolution of the exact new UNKNOWN. Do not sign while it remains.
2. Request venue/operator evidence for registered-par full-position/subminimum Stop Limit semantics, including the exact supported wire and residual behavior. The old exact IOC close is not native-stop proof.
3. Only once the barrier permits and a venue-compliant route exists, prepare a fresh source-bound supervised test for exact human approval. The old mandate stays consumed. Reserve bounded cleanup time and exact partial-abort authority.
4. Reconcile a genuine opening fill. A full-size above-minimum native stop can provide acceptance evidence; abort any naturally occurring one-lot partial only through its separately approved exact-position IOC route.
5. Observe only natural trigger movement within the approved time. Reconcile the actual parent, exact reported children, SELL fills, fees/funding and residuals. Cancel only owned protection, verify cancellation, and require two authoritative flat/zero-order reads.
6. An untriggered accepted stop or full-size close leaves native trigger/residual qualification incomplete. If the venue cannot supply supported small-position semantics or genuine evidence, keep unattended entries blocked. Do not force trades, self-trade or manufacture triggers.

No new code correction is justified by the available venue evidence. Existing isolated full-size and scoped IOC infrastructure is retained; unattended qualified capacity is zero.
