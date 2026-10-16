# Full-day profit-only BTC recovery — preparation

The existing genuine BUY remains the only trade being managed. This work creates a separately approvable profit-only session; it does not activate unrestricted trading. No full-day exchange order is authorized by preparation.

## Scope and expiry

- TESTNET `par:BTC`, registered team account `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`; API signer `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`.
- Existing original BUY: order 62755970305, fill 800659111758533; 0.0002 BTC at 81,512, cost 16.30240 TEST USDPR, actual entry fee 0.014672 USDPR.
- Fixed session expiry: **23:59 IST, 15 October 2026**. No new closing path or SELL signing at/after **23:57 IST**, reserving two minutes for management and reconciliation. Final read-only recovery may finish after expiry if API backoff requires it; signing cannot continue.
- At most one entry into the closing execution path and one reduce-only SELL IOC, for exactly the freshly verified 0.0002 BTC LONG. A changed position or conflicting order stops this fixed-quantity mandate; it never enlarges or automatically adjusts exposure. Any partial residual needs a separate recovery decision.
- No BUY, cancellation, leverage change, second exit, uncertain-order retry, loss-making fallback, renewal or crash auto-resume.

## Isolated implementation

The existing exact full-position close, official SDK transport, central risk/compliance, durable journal, account/signer identity, nonce lease, current precision and five-second signing boundary are reused. Production signal logic is unchanged.

- `exchange/profit_only_session.py`: separate typed PROFIT_ONLY_LONG_SESSION mandate with a fixed calendar deadline; read-only observation lifecycle and profit snapshots.
- `exchange/exit_recovery.py`: dispatches the new observation lifecycle and enforces its signing cutoff/profit-floor high-water mark. Legacy ten-minute and separately approved loss modes retain their original fields and approval semantics. Nonce loss halts the loop; SIGTERM is handled as an interruption; authority is revoked before receiver shutdown.
- `scripts/run_exit_recovery.py`: explicit --full-day read-only preparation and typed mandate loading. Execution mode comes only from the exact accepted mandate.
- `test_profit_only_session.py`: 51 new offline cases; no actual-wallet signatures or venue certification.

## Observation and public budget

The existing acknowledged WebSocket receiver is preferred. It permits at most three connection attempts with bounded backoff. REST fallback is limited to one book read per five seconds and remains subject to the shared rate guard. More than two minutes without a fresh usable book stops this session.

Full account history is reconciled at startup, every five minutes, across an hourly funding boundary, and before a closing candidate. Lightweight position/open-order checks and fee checks run at most once a minute; mark/oracle references refresh about every thirty seconds. A full candidate preflight is rate-bounded and cooldown-limited. A harmless market-only candidate is not a signing permit.

Logs include actual bid/ask and depth, book timestamps/age, mark/oracle, spread, last verified remaining quantity, actual funding cashflows, conservative fee, break-even, rising profit floor, estimated executable net P&L, supporting-evidence ages, connection state and poll counts. Observation cache ages describe successful verification completion; signing always uses the underlying freshly reacquired provider evidence and its original age limits. Unavailable or stale inputs cannot authorize a SELL.

## Profit and fee rules

Net completed P&L = actual SELL proceeds − actual original BUY cost − entry fee − actual exit fee + net reported funding. Before a SELL, this is a conditional estimate only.

The runtime requires at least 0.001 TEST USDPR estimated net profit, after conservative fees and actual funding. The signed SELL limit is fresh bid minus 10 bps, rounded up, never below the approved initial floor or the session's higher observed floor. Current bid allowance remains at most 20 bps; isolated spread ceiling 50 bps and genuine L2 participation 50%. The production scanner's 15-bps ceiling is unchanged.

If the testnet response omits deployerFeeScale, the current userCrossRate is multiplied by the documented maximum sixfold HIP-3 bound; this is not a claimed actual exit fee. Maximum permitted exit-fee bound remains 0.30%. Fresh fees/funding can raise the floor; favorable changes cannot lower it below an already recorded session floor. Reference: [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees).

## Verification

Full regression: **2363 passed**, zero failures/errors/skips; source `62c42d3d627716b0749c933fefdc7b8d4e1c6216de90b1b563403d5a149172b6`. Before/after strategy-freeze and Phase-0 checks passed; XML digest matches the source-bound receipt. The focused run passed 115 cases. Earlier focused fixture failures are preserved: a read-only nonce-health property could not be assigned, and the correct safe UNKNOWN outcome needed to be asserted. No exchange order was involved.

Coverage includes long authorization beyond ten minutes, fixed expiry, late approval/revocation, stale/missing/disconnected books, changing fees/funding, depth/spread, candidate freshness, profitable SELL composition, zero/partial/rejected/uncertain exits, duplicate prevention, signer degradation and durable restart/closing-path locks. These tests do not verify native protective-stop acceptance.

## Host supervision and recovery

After exact approval, the existing CLI is launched once as a detached bounded process. A process-bound macOS idle-sleep assertion can keep the Mac awake while it runs; it cannot prevent power loss, forced sleep, internet loss or app shutdown. No server migration or second signer is introduced. A read-only follow-up checks the existing process; it cannot sign, retry, restart or renew it. The Mac must remain powered and connected. Desktop follow-ups need the app running: [official scheduled-task documentation](https://learn.chatgpt.com/docs/automations?surface=app).

Operator cancellation or revocation blocks subsequent signing. Restart/disconnect never proves flatness. After any rejected/partial/uncertain SELL, preserve the original order identity and inspect actual team fills, remaining position and open orders without resubmitting. No proof of flatness or realized profit is created without genuine exchange records.

## Remaining risks and next action

No verified protective stop exists. The LONG remains exposed until actual exchange closure. The monitoring window is not a maximum-loss limit. A candidate can disappear during mandatory checks; the sole closing path can be consumed without an exchange fill. Partial execution, rejected/uncertain responses, future fee/funding changes and host/network failure can leave an unprotected residual requiring manual intervention. Actual positive realized P&L is not guaranteed.

Both original BUY proofs are unchanged. Organizer whitelisting, native protection certification, normal PRACTICE_READY and LIVE_READY remain unverified/false. PAPER/false defaults remain enforced. The next action is explicit approval of a fresh exact mandate, current fee assumptions, limits and fixed deadline.

## Fresh read-only proposal

Mandate `fbad5fe98614a88acfdd3ac079e2644f46371265cf6600a2b04f604a63deb1a5`. Observation 2026-10-15T12:47:18.592000+05:30; approval deadline 2026-10-15T12:52:18.592000+05:30. Bid / ask 80920.0 / 80944.0; spread 2.965452478624030049918450057 bps. Remaining LONG 0.0002; orders 0; account READY. Reported funding 0.000219; conservative exit-fee bound 0.00270; break-even 81805.13887496239847588488920; approved initial minimum SELL 81811. Conditional net if fully closed at that floor under these reviewed bounds: 0.001169060 TEST USDPR. Executable at this snapshot: False.
