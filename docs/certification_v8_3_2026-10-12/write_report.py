"""Generate the V8.3 report from saved, source-bound read-only evidence."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal as D, ROUND_CEILING
import hashlib, json, sqlite3, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash, atomic_json

def load(name):return json.loads((OUT/name).read_text())
def local(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).astimezone(ZoneInfo('Asia/Kolkata')).isoformat()
def fmt(value):return 'Unavailable' if value is None else str(value)

review=load('market_preflight_verified/review.json');tests=load('regression_release/test_receipt.json')
signer=load('signer_preflight.json');timing=load('signer_preflight_timing.json')
checks=load('checks_after.json');modified=load('modified_files.json');a=review['account_readiness']
assert tests['passed'] and tests['totals']==dict(tests=1522,failures=0,errors=0,skipped=0)
assert tests['source_hash']==tests['source_hash_after']==active_source_hash(ROOT)==review['source_hash']==review['source_hash_after']
assert signer['status']=='LOCAL_IDENTITY_AND_OWNERSHIP_VERIFIED'
assert not review['eligible_markets'] and len(review['markets'])==10
assert review['account_observed_flat'] and not review['global_protection_enabled']
assert checks['strategy_freeze']['passed'] and checks['phase0']['passed']
old=json.loads((ROOT/'docs/certification_v8_2_2026-10-12/source_manifest.json').read_text())['files']
assert all((ROOT/p).is_file() and hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in old.items())
sqlite=[]
for p in sorted(OUT.rglob('*.sqlite')):
    with sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True) as db:
        sqlite.append(dict(path=str(p.relative_to(OUT)),integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
            intents=db.execute('SELECT count(*) FROM intents').fetchone()[0],
            api_actions=db.execute('SELECT count(*) FROM api_actions').fetchone()[0],
            signed_management=db.execute('SELECT count(*) FROM signed_management').fetchone()[0]))
assert all(x['integrity']=='ok' and x['intents']==x['api_actions']==x['signed_management']==0 for x in sqlite)
flags=dict(PARTIAL_FILL_EXIT_READY=False,ACTUAL_PROTECTION_READY=False,CONTROLLED_EXECUTION_READY=False,
    LONG_CERTIFIED=False,SHORT_CERTIFIED=False,FUNDED_RECOVERY_CERTIFIED=False,PRACTICE_READY=False,LIVE_READY=False,
    OFFLINE_ONE_LOT_REVIEW_TESTED=True)
summary=dict(status='PREFLIGHT_BLOCKED',authorization_status='NO_ORDER_AUTHORIZED',
    source_hash=tests['source_hash'],source_hash_before=load('inspection_before.json')['source_hash'],
    root_cause='Smallest partial fill or exit remainder is below the retained minimum; exact close and protection exemptions unverified',
    chosen_safe_action='Preserve certification entry block; no verified executable approach A, B or C',
    eligible_markets=[],safest_eligible_market=None,selected_trade_size=None,authorization_proposal=None,
    venue_subminimum_close='NOT_ESTABLISHED_BY_AUTHORITATIVE_DOCUMENTATION',
    venue_subminimum_protection='NOT_ESTABLISHED_BY_AUTHORITATIVE_DOCUMENTATION',
    actual_exchange_order_submissions=0,actual_wallet_signatures=0,realized_pnl=None,
    realized_pnl_status='REALIZED_PNL_NOT_CERTIFIED',flags=flags,tests=tests['totals'],
    new_tests=35,checks_after=checks,modified_source_files=modified,
    market_preflight_started_utc=review['started_utc'],market_preflight_finished_utc=review['finished_utc'],
    account_observed_ms=a['observed_ms'],account_readiness_reasons=a['reasons'],
    signer_check_scope=signer['nonce_ownership']['ownership_scope'],
    remote_signer_ownership_verified=False,sqlite_audit=sqlite,
    all_v8_2_source_and_config_files_unchanged=True,
    next_action='Obtain authoritative par confirmation of the full-position sub-$10 close and protective-order rules or an equivalent safe mechanism')
atomic_json(OUT/'final_summary.json',summary)
markets=[];details=[]
for row in review['markets']:
    n=row['limit_notionals'] or {}
    reasons='; '.join(row['blockers'])
    markets.append(f"| {row['symbol']} | {row['lot_size']} | {row['mark_lot_notional']} | {fmt(n.get('entry_limit'))} | {fmt(n.get('exit_bound'))} | {reasons} |")
    if row['prices']:
        depth=row['depth'];px=row['prices']
        minimum_lots=int((D(10)/D(n['entry_limit'])).to_integral_value(rounding=ROUND_CEILING))
        details.append(f"| {row['symbol']} | {px['entry_limit']} | {px['stop_trigger']} | {px['stop_limit']} | {row['spread_bps']} | {depth['best_bid_quantity']} / {depth['best_ask_quantity']} | {depth['entry_quantity_within_limit']} / {depth['exit_quantity_within_bound']} | {minimum_lots} |")
text=f'''# Team Anchorium — V8.3 execution safety investigation

**Verdict: investigation complete; first actual trade remains blocked.** No signed order, actual-wallet signature, cancellation, transfer, leverage change or autonomous activation occurred in this task. PAPER mode and the order lock remain enforced. We did not choose an executable trade because none of the three allowed approaches is supported by the current evidence.

## 1. Verified root cause

The existing code rejects a sub-$10 exact full-position reduce-only close before it reaches Hyperliquid. Both generic normalization and central exchange validation retain that minimum. The exact-residual and protection helpers refuse to enlarge the real position or silently discard dust. This behavior is demonstrated offline and the execution code remains unchanged.

An entry worth more than $10 is insufficient: it can partly fill. An exit can also leave a small remainder. The safety gate therefore reviews **one runtime lot**, not simply the whole requested order. A possible remainder below the minimum needs a verified closing and protection mechanism before entry can be allowed.

The precise missing fact is server acceptance of an exact full-position close and protective stop below the minimum on **testnet par**. We did not establish these exemptions in the authoritative documentation inspected. This is an evidence gap, not proof that every such server request must fail. Details and primary references are in [venue_behavior.md](venue_behavior.md) and [root_cause.md](root_cause.md).

## 2. Chosen safe solution

| Allowed approach | Result |
| --- | --- |
| A: verified subminimum full-position close | Not established; protection treatment also unknown. |
| B: liquid one lot above $10 at entry and reviewed exit bounds | No eligible market among all ten. |
| C: another documented equivalent safe mechanism | No equivalent guarantee established. Ordinary SDK market-close, dynamic TP/SL and batch requests do not prove it. |

The implemented safe action is **retain the certification entry block** and make its all-market reasons reproducible. No minimum exception, oversized reduce-only order, top-up, abnormal order price or exposure increase has been introduced. Existing exact sizing, opposite direction, actual-fill protection, two bounded exits, duplicate prevention, durable uncertainty and operator escalation remain regression-tested infrastructure, not certified actual exchange behavior.

## 3. Source files added

{chr(10).join('- `'+x['path']+'`' for x in modified)}

The exchange module reviews one genuine runtime lot at current executable quotes and conservative test exit bounds. The launcher retrieves all ten official market specifications, books, mark/oracle/funding and side-specific account capacity through read-only `/info`. It preserves unavailable prices as unavailable and records independent minimum, liquidity, price and capacity blockers. Its output cannot deserialize as an executable proposal or grant an SDK permit.

Every one of the **{len(old)} existing V8.2 source/configuration files is byte-identical**. `signal_brain.py` and all manifest-frozen methods/state rules remain unchanged. The existing certification execution allowlist and transport are unchanged because no newly eligible safe market was found. Evidence/report files were added under this directory; the original NSE repository was untouched.

## 4. Tests and integrity

- **1,522 passed; 0 failures; 0 errors; 0 skipped.** This includes all 1,487 baseline tests plus 35 new tests.
- Focused final run: **117 passed** (V8.1, V8.2 and new V8.3 tests). The first focused attempt had one new test-fixture setup error; corrected fixture and original failed XML are preserved in `test_attempts.json` and `targeted_initial.xml`.
- Phase-0 permanent Angel/exchange lockout checks: PASS. Frozen strategy verification before and after regression: PASS (1 full file, 8 methods, 32 parameters).
- VWAP, EMA, ATR, 0.40% volatility floor, 15 bps spread ceiling, 300 completed UTC bars and Top-3 are unchanged. This read-only test review does not run or certify the strategy feed.
- Reviewed source hash: `{tests['source_hash']}`. Before/after regression and final public review source identities match.
- Full regression XML SHA-256: `{tests['xml_sha256']}`. The complete receipt is `regression_release/test_receipt.json`.
- All {len(sqlite)} investigation SQLite files passed integrity checks; each has zero order intents, signed-management records and API actions.

The tests cover independent minimum checks at entry versus protection/exit, all ten runtime-lot examples, empty books, stale/future observations, depth, side capacity, leverage, market identity, price divergence, unchanged notional cap, and real read-only runtime composition. Existing regression tests continue to cover partial fills, rejected exits/protection, unknown status, exact residuals and restart recovery. Synthetic success does not certify par acceptance.

## 5. Safest eligible market

**None.** BTC has the largest observed lot value but still fails the minimum and the unchanged 10%-of-best-level depth test in the final snapshot. SP500 also fails those checks. ETH passes the reviewed spread/depth/capacity conditions but its smallest possible fill is far below the minimum. Neither is an eligible recommendation.

## 6. Minimum-lot notional and trade size

Final public review: **{review['started_utc']} to {review['finished_utc']}** — approximately **15:16:53–15:17:06 IST on 12 October**. Values are test USDPR contract notional under the published price-times-size rule. Metadata and price observations were freshly read per market; quotes are snapshots, not future guarantees.

| Market | Runtime lot | Lot at observed mark | Lot at reviewed LONG entry limit | Lot at conservative stop/exit limit | Blockers |
| --- | ---: | ---: | ---: | ---: | --- |
{chr(10).join(markets)}

All ten mark-based lot values are below 10. Eight had usable two-sided books; all eight were below 10 at entry and stop/exit limits. BRENT and HYPE had no usable two-sided book, so their entry and protection prices were not invented from marks or candles. **Selected trade size: none; submitted quantity: zero.**

For example, one BTC lot would request about **8.3512** at the reviewed entry limit, and **8.2223** at the conservative exit. Two lots would exceed the minimum at entry, but could still fill just one lot or leave one lot after closing. Increasing notional would not remove that possibility.

Additional actual snapshot details, for inspection only:

| Market | Entry limit | Stop trigger | Stop/exit limit | Spread bps | Best bid/ask quantities | Entry/exit depth within limits | Lots needed merely to exceed entry minimum |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
{chr(10).join(details)}

These prices reproduce the existing isolated certification geometry: BUY limit within 5 bps, fixed test trigger about 1% below current bid, and limit about 0.5% below that trigger; a later discretionary close remains within the existing 20 bps allowance and absolute exit bound. They do not change normal strategy stops or the disabled catastrophic protection policy. Book depth is observed now; a future stop may lack liquidity and a stop-limit can remain unfilled after a gap. These are **invalid one-lot order reviews**, not executable proposals.

## 7. Sub-$10 close/protection evidence

The [current participant guide](https://perpetual-alpha26.github.io/docs/) gives the general $10 order minimum and warns that IOC closes can partially fill or be rejected. [Hyperliquid's error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) documents minimum-value rejections. Neither source inspected explicitly establishes the needed exemption.

[Position TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) documents dynamic position sizing and partial-parent behavior, while the [exchange schema](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint) documents grouping and reduce-only fields. Distinct position-attached minimum treatment remains unknown. The installed SDK 0.24.0 `market_close` reads the actual position and submits an ordinary opposite-side reduce-only IOC through `order`. No separate dust mechanism is demonstrated by that client method.

No actual small-close/protection experiment occurred. An undocumented exception may exist, but implementation cannot assume it. A general minimum exemption has not been added.

## 8. PARTIAL_FILL_EXIT_READY

**FALSE.** No current market avoids the subminimum remainder problem, and small-close/protection acceptance remains unverified.

## 9. CONTROLLED_EXECUTION_READY and account checks

**CONTROLLED_EXECUTION_READY = FALSE. ACTUAL_PROTECTION_READY = FALSE.** The normal protection policy remains configured but disabled. A real protective order has never been accepted or verified in this task.

| Fresh read-only check | Observation |
| --- | --- |
| Team wallet | `{review['team_wallet']}` |
| Approved API wallet | `{review['api_wallet']}`; local key-derived public address matches |
| Testnet/par | Mandatory verified runtime metadata; official ten prefixed markets |
| Unified mode | `{a['account_mode']}` |
| Reported USDPR collateral | `{a['collateral']}` |
| Available long collateral | `activeAssetData.availableToTrade[0]` reports 1,000,000 for each of the eight priced reviews; all ten raw active-asset responses preserved. Spot total is not substituted for capacity. |
| Leverage | All ten `1x CROSS`; read only, no setting change |
| Positions/orders | Zero before and after review, including frontend trigger-order list |
| API agent expiry | `{local(a['agent_expiry_ms'])}`; valid at the observed account check |
| Taker fee estimate | `{review['taker_fee_rate']}` per fill; current positive base user rate doubled per the documented par fee scale. No actual fee or P&L measured. |
| Clock at account check | Healthy; later final offset `{review['clock_final']['offset_ms']}` ms is separately recorded |
| Account action budget | `{a['account_budget']['nRequestsUsed']}` used of `{a['account_budget']['nRequestsCap']}`; no action used by this task |
| Public read budget | Final weight `{review['rates']['ip_weight']}` within 1200 with 120 reserve; no public upstream failures in the verified run |
| Local nonce ownership | Correct API binding, second local process rejected, no nonce allocation, lease released |
| Remote signer ownership | Not established by a local lease; sole-host confirmation remains a future approval requirement |
| Durable certification account barrier | Not run/authorized. Public account readiness correctly retains `ACCOUNT_RECONCILIATION_REQUIRED`. A flat snapshot does not grant durable execution readiness. |

The account observation was **{local(a['observed_ms'])}**; local signer check was **{local(timing['started_ms'])} to {local(timing['finished_ms'])}**. These are timestamped evidence and must be repeated before any future controlled attempt. The public fee/mark/funding values are observations, not actual realized accounting. Net actual P&L remains **unknown/not certified**, rather than being reported as zero or a PAPER result.

The sandbox reads failed with `INFO_RETRY_BUDGET_EXHAUSTED`; those failed attempts are preserved. Separately reviewed, bounded public reads outside that environment succeeded. The environment failure is not a claim that the venue feed was down. The earlier initial all-market probe preserved two unavailable books as raw evidence; the tested final inspector gives the explicit `NO_EXECUTABLE_TWO_SIDED_BOOK` reason without constructing synthetic prices.

## 10. Exact authorization proposal

**No executable proposal is ready.** Market, quantity, approved trade prices and actual-round-trip fee estimate are therefore not selected for authorization. No approval file has been created. The review JSON cannot be used as a `CertificationProposal` or as a permit.

After the missing venue rules are confirmed and any narrow supported implementation is offline-tested, a fresh source-bound account/market preflight must produce an exact bounded trade for explicit human approval. The current review cap stays at 25 USDPR; it is not itself human authorization. No request is being made to approve an unsafe trade.

## 11. The single next action

**Obtain authoritative par confirmation of both the exact full-position sub-$10 close and its protective-order treatment, or an equivalent documented safe mechanism.** The ready-to-copy question is [organizer_question_draft.md](organizer_question_draft.md); it has not been sent. Keep PAPER/false while this evidence is missing.

```ini
EXECUTION_MODE=PAPER
ALLOW_LIVE_ORDERS=false
PARTIAL_FILL_EXIT_READY=FALSE
ACTUAL_PROTECTION_READY=FALSE
CONTROLLED_EXECUTION_READY=FALSE
LONG_CERTIFIED=FALSE
SHORT_CERTIFIED=FALSE
FUNDED_RECOVERY_CERTIFIED=FALSE
PRACTICE_READY=FALSE
LIVE_READY=FALSE
```
'''
(OUT/'report.md').write_text(text)
print(json.dumps({'report':str(OUT/'report.md'),'tests':tests['totals'],'eligible_markets':[],'flags':flags}))
