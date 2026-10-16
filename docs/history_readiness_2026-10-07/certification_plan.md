# Controlled testnet certification plan — inactive

No order has been submitted under this plan. It is not an approval file and
cannot enable the exchange transport. PAPER/false remains enforced.

The request requires every readiness gate to pass and explicit authorization
before the first real order. The repository also requires manual verification
of the funded team account. Current blockers are recorded in the final report.

## Before signing

Verify the current team address and API agent `anchorium-bot-1`, approval expiry,
USDPR balance and unified mode. Read metadata for `par`, actual user fees,
coin/side capacity, current leverage, positions and both ordinary/trigger orders.
Reconcile actual fills/funding. Use fresh public completed candles/books/contexts.
Keep mark, oracle and executable bid/ask separate.

The current reviewed bot policy uses 1x cross margin. Do not change that policy
to match the exchange's current 20x/10x settings. Any exchange configuration
action requires separate authorization; this task performed none.

Review and approve the independent protection distance and execution allowance.
The existing one-ATR/0.5% proposal remains disabled and unapproved. Confirm nonce
ownership, clock, aggregate request reserves and one signing process. Never
infer signer health from a public approval alone.

Only after those checks pass may the human approve the exact certification
budget and activation. A proposed maximum entry notional of 10–15 USDPR is
small, but it is not yet an approved budget and may be infeasible at runtime
precision/liquidity. Each normalized order must still satisfy the venue minimum
and all existing price, size, depth, capacity, compliance and risk guards.

## LONG, then SHORT

Use the existing bot executor and exact-action SDK permits. Preserve real
candidate provenance and all risk guards; do not spoof a strategy signal,
bypass the scanner, or manually trade through the website. If no authorized
valid candidate exists, record NO_TRADE and wait. A future dedicated test-entry
mode would require its own reviewed authorization and may not masquerade as a
production strategy trade.

For each direction, retain the normalized request and individual exchange
status. A request-level `ok` is not proof of a fill. An IOC may fill partially.
Reconcile actual fill IDs, quantity, price, fee and the authoritative account
position. Protect only that actual quantity with independent reduce-only
protection, then verify the accepted trigger/order state.

Use an authorized reduce-only exit and inspect its actual result. Re-read fills,
positions and open orders, including triggers. Confirm flat exposure and resolve
any remaining order before another entry. Account for reported closed P&L,
actual fees and funding in the explicit observed window. Never substitute
expected price/size, candle touches, estimated fees or a successful helper return.

LONG must finish flat and reconciled before SHORT begins. The durable global
position lock includes partial exposure and unresolved entry/exit orders.

## Failure and recovery cases

Cancel a reviewed resting order only after live certification is authorized;
verify its status and disappearance from the authoritative open-order snapshot.
Partial fills, ambiguous responses and crashes may use offline fixtures when
live conditions are unsafe or unavailable. Label those results OFFLINE_TESTED.

On a disconnect, block entries, reconnect and resubscribe, then REST-reconcile
account state before resuming. On restart, begin UNKNOWN, not flat. Recover
positions, orders, fills, funding and protection, including unresolved CLOIDs.
For an ambiguous protection submission, query status, orders, fills and actual
position before considering a resend. Do not create duplicate protection.

Existing exposure at startup blocks new entries until its strategy management
and protection state are recovered. If any required evidence is missing, stop
the certification and retain the state for review. During the current locked
phase no real entry, protective, cancel or exit action is authorized.

## Required evidence before unattended practice

The certification record must contain actual LONG and SHORT entry/exit fills,
fees, position signs/quantities, protection results, final authoritative flat
state and reconciled accounting. Distinguish real exchange results from fixture
and PAPER results. Keep one active signing process for the API wallet; do not
start a second trader on a laptop/server pair. Begin supervised operation first.

The [official guide](https://perpetual-alpha26.github.io/docs/) describes per-order
statuses, IOC partial fills, reduce-only orders and account-query separation.
This plan adds project-specific approval and recovery requirements; it does not
claim they have already been satisfied.
