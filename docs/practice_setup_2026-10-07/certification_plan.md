# Next funded tests — prepared, inactive

This is a sequence for later explicit human activation. It is not an approval
file and cannot enable orders. Keep PAPER/false and protection disabled now.

## 1. Finish the setup checks

Manually verify the registered team wallet and approved API wallet identities.
Complete the deliberate all-ten 1x CROSS configuration and reread each setting.
The helper's approval applies only to that setting; it cannot place an order.

The API-key address match and local nonce ownership check passed. Before any
later signed order, check them again, using the same durable nonce database,
healthy clock/rates and exactly one signing process on one host. Confirm current
funding, unified mode, API expiry, metadata, positions, ordinary/trigger orders,
and actual fill/funding reconciliation. Reject existing or unresolved exposure.

The independent policy is configured at one entry ATR beyond the normal stop
with a 0.5% execution allowance and reduce-only semantics. Real installation,
acceptance and recovery of that protection still need certification. It remains
disabled until explicitly authorized for the controlled test.

Collect usable current `par:` candles/books/contexts. Preserve the 300 bars,
0.40% ATR floor, 15 bps spread and Top-3 rules. Missing/stale candles are not a
reason to invent data, use native markets or bypass scanner provenance.

## 2. Approve one bounded certification session

The human must explicitly approve the exact session scope and a small maximum
notional/risk budget after the prerequisites pass. No amount is approved by this
document. Runtime precision, venue minimum, liquidity, side capacity and risk
guards determine whether that budget is feasible. The million-unit balance is
not the test size.

The existing executor requires real candidate provenance and exact-action SDK
permits. If no qualifying candidate exists, record NO_TRADE and wait. A separate
test-entry mode would require its own reviewed authorization and must be labeled
as a connectivity certification, never a production-strategy trade.

## 3. LONG first, then completely flat

Retain the order request, each exchange order status and actual fill IDs. An
HTTP success or accepted order is not a fill. Observe actual quantity, price,
fee and positive position from the account. Install reduce-only independent
protection for the actual filled quantity and verify its accepted trigger state.

Use the authorized reduce-only SELL exit. Reconcile actual exit fills, reported
fees, closed P&L and funding for the explicit observed window. Reread the account
until position is zero, ordinary/trigger orders are cleared and the durable
global position lock is authoritatively flat. No guessed fills or estimated
fees may stand in for those account events.

## 4. SHORT only after LONG is flat and reconciled

Observe a real SELL entry fill and the correct negative account position.
Protect only the actual quantity. Use an authorized reduce-only BUY exit.
Verify actual exit fills, fees/funding/P&L, zero position and no leftover orders.
Never overlap these directions or begin a second entry with unresolved orders.

## 5. Recovery, then supervised practice

Within separately approved bounds, verify cancellation, public/account
disconnect and REST reconciliation, then a controlled restart. Startup begins
UNKNOWN and must recover actual positions/orders/fills/protection before new
entries. Resolve ambiguous actions by account/order-status reads before any
resend. Do not deliberately create dangerous exposure to force a partial fill
or crash scenario. Cases tested only with fixtures stay labeled OFFLINE_TESTED.

Only after actual LONG/SHORT accounting and funded recovery are certified should
the human authorize supervised practice. Keep one API wallet owner, one host,
one active trader and one global `par` position, including partial fills and
unresolved orders. A PAPER run or successful private-key derivation cannot
approve unattended trading.

The [official participant guide](https://perpetual-alpha26.github.io/docs/)
describes exchange order/fill semantics. The stricter approval, risk and recovery
requirements here are project policy. No real test under this plan has run.
