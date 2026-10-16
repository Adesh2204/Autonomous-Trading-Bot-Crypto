# Team Anchorium — V8.4 final execution investigation

12 October 2026. Production remains `EXECUTION_MODE=PAPER`,
`ALLOW_LIVE_ORDERS=false`. Independent protection remains disabled.

## 1. Direct verdict

**Keep the certification entry blocked. No actual order was submitted.**

There is useful new evidence: two existing `par:HYPE` orders below $10 really
closed complete positions. We verified their original orders and matching actual
fills. However, they cover three and seven lots. We have not established the
one-lot case or safe sub-$10 protective-stop acceptance. No complete supported
entry → partial-fill protection → residual-close route is ready.

I have not turned those two examples into a general exception, increased the
entry size, or bypassed an ordinary minimum check. Passing offline tests does
not establish what an exchange will accept.

## 2. Exact root cause

The ordinary order normalizer and central validator both reject orders below
$10, including full-position reduce-only closes. The residual helper likewise
refuses an unverified small remainder. These are local rejections before HTTP.

The certification admission check considers the smallest runtime lot at the
reviewed protection and exit prices. A $25 request can receive a tiny partial
fill, and a nearly completed exit can leave a tiny remainder. Increasing the
requested entry does not solve that problem.

The missing capability is **verified safe treatment of every possible remainder
in the selected small test, including protection**. An account balance, an API
approval, or a normal close helper does not establish that capability.

## 3. Confirmed exchange behavior

These are public records from another counterparty. They are **not Team
Anchorium trades or results**. Four historical event rows represent two order IDs.

| Existing testnet order | Actual event UTC | Starting position | Original reduce-only IOC close | Original price × size | Matched actual fill | Post-fill quantity |
| --- | --- | --- | --- | --- | --- | --- |
| 61997055149 | 6 Oct, 15:38:11.928 | HYPE SHORT -0.03 | BUY 0.03 at 93.218 | 2.79654 USDPR | BUY 0.03 at 92.847 | 0 |
| 61745948135 | 3 Oct, 14:11:33.873 | HYPE LONG +0.07 | SELL 0.07 at 87.933 | 6.15531 USDPR | SELL 0.07 at 88.202 | 0 |

Independent `orderStatus` and narrow-window `userFillsByTime` rereads completed
at **12 October, 10:22:14.751 UTC / 15:52:14.751 IST**. Both returned filled
reduce-only IOC orders, matching sizes, opposite directions, genuine starting
positions and USDPR-denominated actual fills. These prove the two particular
historical full closes succeeded. The HYPE lot is 0.01, so these were three/seven
lots. They do not prove arbitrary smaller closes or full-position protection.

No `par` trigger-order example appeared in the bounded historical sample.
Therefore protective acceptance below $10 remains **unverified**, rather than
being claimed supported or universally rejected.

The [published participant rule](https://perpetual-alpha26.github.io/docs/#price-and-size-rules)
still specifies the ordinary $10 minimum. The inspected official documentation
does not expressly define the full-close exception's scope or protective-order
minimum treatment. Full findings and primary references are in
[venue_behavior.md](</Users/adesh/Autonomous Trading Bot - Crypto /docs/certification_v8_4_2026-10-12/venue_behavior.md>).

## 4. Other native mechanisms investigated

- The installed official SDK 0.24.0 `market_close` uses the observed position,
  opposite direction, reduce-only and ordinary IOC order submission. It supplies
  no separate documented small-position recovery mechanism.
- Position TP/SL and `positionTpsl` describe sizing/grouping. They do not specify
  the missing small-order acceptance rule. A stop-limit can fail to fill after
  a gap; market TP/SL has a different documented tolerance.
- Parent/child TP/SL does not guarantee coverage of a partial parent. Child
  cancellation behavior must be considered separately.
- IOC can partially fill. Batching is not atomic success across every operation.
  No supported FOK route was established in the inspected schema.
- TWAP requires a documented $100 total minimum and still permits partial
  execution. Browser chase, trailing stops and the documented HyperCore writer
  do not establish an equivalent safe tiny-position cleanup/protection path.

These are conclusions about the inspected documented mechanisms, not a claim
that every possible future venue feature is unsupported. No native mechanism
was used experimentally and no contract was deployed.

## 5. Engineering changes and current safe handling

One source file was added:
[test_partial_fill_safety_v8_4.py](</Users/adesh/Autonomous Trading Bot - Crypto /algo-trading-bot/test_partial_fill_safety_v8_4.py>).
It adds **16 meaningful offline containment tests**. Existing production source
and configuration files were preserved. All **215 V8.3 manifest files** match.
The generated legacy dependency inventory was refreshed.

The production mechanism remains:

1. Block entry if the minimum possible remainder has no verified protection and
   exit path.
2. Size exits from actual reconciled positions, with the opposite direction and
   reduce-only. Never round away dust or enlarge a close to reach $10.
3. Keep partial exposure and unresolved orders in durable state.
4. Bound exit attempts. Rejected or uncertain results cannot mean flat.
5. Escalate a residual for operator review. Restart performs reconciliation and
   cannot duplicate the entry or erase the residual.

The new read-only evidence helpers and reports live only in this investigation
directory. They do not expand the production query allowlist, create SDK permits,
approve a proposal or activate an order path.

## 6. Tests and strategy integrity

| Verification | Result |
| --- | --- |
| Previous V8.3 baseline | 1,522 passed |
| New V8.4 tests | 16 passed |
| Focused V8.1/V8.2/V8.4 safety suite | 98 passed, zero failures |
| Complete repository regression | **1,538 passed, zero failures/errors/skips** |
| Phase-0 safety | PASS |
| Frozen strategy | PASS: one file, eight methods, 32 parameters |
| Full regression source hash before/after | Identical |
| Existing V8.3 source/configuration manifest | 215/215 unchanged |

The 12 new central-validator cases cover exact full closes of tiny LONG/SHORT
positions under GTC/IOC/ALO. The four new composition cases leave subminimum
residuals after partial exits, with and without protection rejection, then
exercise recovery/restart without duplicate orders or false flat/P&L claims.

The existing full-suite cases also cover partial entries, rejected exits,
rejected/uncertain protection, lost acknowledgements, unknown order IDs, actual
filled-size reconciliation, durable duplicate prevention, account barriers,
production order locks and restart recovery. All execution fixtures are offline
and use synthetic accounts; no actual-wallet signature or network exchange
transport is allowed in those fixtures.

`signal_brain.py` SHA-256 remains
`bff940ac5ed35f71ed3dfb537ba15d20dcec35a4e62a938d2f0619c6e9309d83`.
VWAP, EMA, ATR, UTC state behavior, the 0.40% floor, 15 bps ceiling, 300 completed
bars, Top-3 and production trading protections are unchanged.

## 7. Fresh read-only account preflight

Successful observation window: **12 October, 10:27:35–10:27:42 UTC /
15:57:35–15:57:42 IST**. These are timestamped snapshots, not future authorization.

| Account check | Observed result |
| --- | --- |
| Network / venue | Hyperliquid testnet / `par` |
| Team wallet | `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` |
| Approved API wallet | `0x46c9BED595770150752E7fA3806449F81E0Ec6f9` |
| USDPR balance | 1,000,000 |
| Account mode | `unifiedAccount` |
| Agent approval | Present; expiry valid at observation |
| All ten markets | 1x CROSS, readback only |
| Positions | 0 initially and finally |
| Frontend open orders, including triggers | 0 initially and finally |
| Actual Team `par` fills returned | 0 |
| Account request budget | 13 used / 10,000 cap |
| Local public-read weight | 458 / 1,200; 120 safety reserve retained |
| Clock | HEALTHY; two fresh references, offset -318 ms |
| Local API address derivation / nonce ownership | MATCH / HEALTHY_LOCAL; no signature or nonce allocation |
| Fresh read-only SQLite | Integrity OK; zero intents, signed management and API action rows |

The readiness helper deliberately reports `ACCOUNT_RECONCILIATION_REQUIRED`:
a fresh flat snapshot does not certify the durable controlled-execution account
barrier. The local signer check excludes a second local owner and releases its
lease afterwards; remote/sole-host ownership is not verified by that check.

Two focused ETH book responses had **zero bid and ask levels**. Their raw server
timestamps support the clock observation only. They were not converted into
quotes, used as liquidity, or counted as usable strategy inputs. No current
executable liquidity was certified, and no broad market scan was repeated.

## 8. Preserved attempts and evidence limitations

The sandbox-only public probe and account attempt failed due to restricted
connectivity; their reports remain. The bounded outside-sandbox history probe
obtained four historical-order responses and three fill responses, then stopped
the next request before HTTP at its conservative weight cap. It is explicitly
incomplete and is not a certificate. The later two exact-order rereads are
complete and independently verified.

An initial account helper required an executable ETH book for its clock
reference and stopped on an empty book. The successful helper used the raw
server timestamps solely for clock evidence and continued the account reads.
The failed attempt and initial helper are preserved. No production freshness,
liquidity or strategy requirement was weakened.

Historical public records are bounded and can be truncated. Other-wallet fills
cannot certify our wallet, protection, recovery or P&L. Read-only evidence,
offline fixture results and a funded account cannot grant signed-action approval.

## 9. Flags and remaining blockers

```ini
HISTORICAL_HYPE_SUBMINIMUM_FULL_CLOSE_OBSERVED = TRUE
ONE_LOT_FULL_CLOSE_CAPABILITY_VERIFIED       = FALSE
SUBMINIMUM_PROTECTION_CAPABILITY_VERIFIED   = FALSE
PARTIAL_FILL_EXIT_READY                     = FALSE
ACTUAL_PROTECTION_READY                     = FALSE
CONTROLLED_EXECUTION_READY                  = FALSE
LONG_CERTIFIED                             = FALSE
SHORT_CERTIFIED                            = FALSE
FUNDED_RECOVERY_CERTIFIED                  = FALSE
PRACTICE_READY                             = FALSE
LIVE_READY                                 = FALSE
```

Remaining blockers are the general one-lot full-close rule, independent small
protective-order acceptance, fresh executable liquidity, future durable account
reconciliation and the later exact human authorization. Current account setup
is observed healthy; it is not the small-position capability proof.

## 10. Single next safe action

**Obtain an authoritative `par` testnet clarification of one-lot full-close and
sub-$10 protective-order rules.** Use the prepared
[organizer question draft](</Users/adesh/Autonomous Trading Bot - Crypto /docs/certification_v8_4_2026-10-12/organizer_question_draft.md>),
which includes the two verified historical order IDs. It has not been sent.

Once the supported scope is established, implement only that exact scope,
rerun its tests and obtain fresh execution/account evidence. Then prepare a
bounded LONG proposal with exact quantities, prices, costs, protection and exit
bounds for explicit human approval. **No ready proposal or actual order exists
now, and no autonomous trading is activated.**
