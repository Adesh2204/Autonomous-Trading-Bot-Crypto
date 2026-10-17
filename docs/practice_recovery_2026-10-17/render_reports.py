"""Report-only rendering from preserved records; no signer or account writes."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import time

P = Path(__file__).resolve().parent
ROOT = P.parents[1]
OLD = ROOT / 'docs/practice_weekend_2026-10-17'
read = lambda p: json.loads(p.read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
dump = lambda name, value: (P / name).write_text(json.dumps(value, indent=2) + '\n')
stamp = lambda ms: datetime.fromtimestamp(ms / 1000, ZoneInfo('Asia/Kolkata')).isoformat()
a = read(P / 'public_audit_with_network/audit.json')
v = read(P / 'verification_receipt.json')
pres = read(P / 'preservation_receipt.json')
local = read(P / 'original_local_evidence.json')
manifest = read(P / 'original_signing_source_manifest.json')
prior = read(OLD / 'final_summary.json')
assert a['terminal_flat'] and not a['errors'] and pres['passed']
assert v['full_release_valid'] and not v['source_changed']
assert local['new_intent_in_effective_unresolved_view'] and local['original_row']['state'] == 'UNKNOWN'
assert manifest['source_hash'] == prior['approved_attempt_source_hash']
now = time.time_ns() // 1000000
source = v['source_hash_after']
row = local['original_row']
account = a['account_final']
new_fills = [x for x in account['fills'] if x['timestamp_ms'] >= prior['worker']['accepted_ms']]
new_funding = [x for x in account['funding_events'] if x['timestamp_ms'] >= prior['worker']['accepted_ms']]
assert not new_fills and not new_funding
history = a['own_historical_orders']
assert not history['matched_original_cloid']

unknown = dict(
    classification='STILL_UNRESOLVED_UNKNOWN', formally_resolved=False,
    cloid=row['cloid'], nonce=1792217834069,
    mandate_id=prior['qualification']['mandate_id'],
    signing_source=manifest['source_hash'], source_reconstructed_against_complete_manifest=True,
    accepted_ms=prior['worker']['accepted_ms'], expired_ms=prior['worker']['expiry_ms'],
    quantity='0.0002', selected_buy_price='81518', local_state='UNKNOWN', exchange_oid=None,
    causal_diagnosis='Source/receipt chronology reconstructs 5526ms readiness age against 5000ms. This is an inference, not a recorded final-guard reason.',
    original_exception='ExchangeError only; TRANSMISSION_UNCERTAIN wrapper',
    guarded_signature_created_in_original_attempt=True, exact_signature_count=None,
    recorded_transmission_claims=0, explicit_original_pre_http_failure_record=False,
    original_native_http_boundary_telemetry=False,
    mandatory_claim_path_verified=True,
    proof_limit='Mandatory pre-HTTP claim source and absent claim support the diagnosis; the existing exact certificate requires additional explicit causal evidence. No absence-only certificate is created.',
    new_immutable_certificate_appended=False, raw_row_deleted_or_changed=False,
    nonce_reset=False, future_signing_permitted=False,
    exchange_readbacks=a['final_readbacks'], history_rows=history['row_count'],
    history_possibly_truncated=history['possibly_truncated'], matched_cloid_history_rows=0,
    new_fills=new_fills, new_funding=new_funding,
    authoritative_historical_position_endpoint_available=False,
    position_history_limit='Retained authoritative snapshots and reported fills are available; no continuous historical position feed or new terminal order record was recovered.',
    existing_certificate_scope='Only the original historical 3b744e33... intent; not this CLOID or mandate.',
    missing_evidence=[
        'Original explicit final pre-HTTP rejection tied to this action/nonce and validated source, or equivalent independently verified causal evidence admissible to the immutable framework.',
        'Alternatively an authoritative venue rejection/terminal record identifying this original action; a bare unknownOid or not-found response is insufficient.'
    ],
    no_new_signatures_or_exchange_writes_in_this_review=True)
dump('UNKNOWN_INTENT_RESOLUTION_REPORT.json', unknown)

native = dict(
    status='NATIVE_AND_SUBMINIMUM_QUALIFICATION_INCOMPLETE', source_hash=source,
    documented=[
        'TP/SL uses mark-price triggers. Default position-form sizing follows the full position; explicit sizing is fixed.',
        'Parent-associated children may be canceled on partial-parent cancellation.',
        'A Stop Limit can trigger and remain unfilled through a gap.',
        'The API exposes positionTpsl grouping and an ordinary minimum-notional error.'
    ],
    exchange_verified=[
        'Historical exact 0.0001 BTC full-position reduce-only IOC close, order 62228843959; narrowly scoped evidence only.',
        'Current own order history contains four records, all non-trigger Limit orders; no native trigger/child proof.',
        'Two current authoritative account readbacks are flat with no open orders.'
    ],
    unknown=[
        'Registered par accepts position-associated subminimum native Stop Limit and its exact supported wire/size semantics.',
        'Actual native parent acceptance, natural trigger, child identity, closing fills and owned cleanup.',
        'Native protection of an actual one-lot residual and all residual closure behavior.'
    ],
    venue_prohibition_proven=False, all_sampled_one_lot_mark_values_below_10=True,
    current_qualified_unattended_notional='0', partial_fill_guard_changed=False,
    lot_precision_changed=False, production_source_changed=False,
    next_steps=[
        'Resolve this UNKNOWN through admissible identity-bound evidence; preserve original intent, nonce and consumed mandate.',
        'Obtain authoritative registered-par guidance or genuine records for full-position/subminimum Stop Limit semantics. Do not invent a zero-size sentinel or reuse IOC evidence for native triggers.',
        'Only after the barrier permits signing, prepare a fresh source-bound supervised qualification with exact human approval and bounded cleanup.',
        'A full-size order above minimum can establish full-size native acceptance; any natural one-lot partial uses only separately approved scoped IOC abort. It does not establish small native protection.',
        'Wait only within approved bounds for a natural trigger. Reconcile exact parent/children/fills and residuals; verify owned cancellation and two flat/zero-order readbacks.',
        'If no natural trigger or small-residual evidence exists, remain INCOMPLETE and do not launch unattended trading.'
    ],
    sources=[
        'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl',
        'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint',
        'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses'
    ])
dump('NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.json', native)

table = '\n'.join('| {symbol} | {one_lot_mark_notional} | {liquidity_only_quantity} | {liquidity_only_notional} |'.format(**x) for x in a['markets'])
largest = max(a['markets'], key=lambda x: float(x['liquidity_only_notional']))
summary = dict(
    status='BLOCKED_UNKNOWN_AND_NATIVE_VENUE_EVIDENCE_REQUIRED', updated_ms=now,
    source_hash=source, source_modified=False, execution_mode='PAPER', allow_live_orders=False,
    unknown=unknown, native=native, verification=v,
    account=dict(as_of_ms=a['final_readbacks'][-1]['observed_ms'], readbacks=a['final_readbacks'],
                 positions=[], open_orders=[], equity=account['reported_account_equity']),
    current_eligible_executable_long_notional='0', current_qualified_unattended_notional='0',
    liquidity_only_snapshots=a['markets'],
    greatest_liquidity_only_estimate=dict(symbol=largest['symbol'], quantity=largest['liquidity_only_quantity'], notional=largest['liquidity_only_notional']),
    qualification_proposal_created=False, autonomous_mandate_created=False,
    approval_requested=False, signer_or_worker_launched=False,
    actual_new_fills=[], actual_new_fees='0', actual_new_funding='0',
    actual_new_observed_cashflow='0', qualification_realized_pnl_certified=False,
    historical_oct15_net='0.050512', collateral='TEST USDPR',
    preservation_passed=True, actual_order_or_nonce_database_modified=False,
    public_requests=a['requests'], actual_public_errors=[],
    sandbox_dns_attempt_preserved=True, initial_failure='INFO_DNS_FAILED; no HTTP status or 429',
    mac_dependency='No worker is running. Future local operation depends on this Mac, process/app, power and internet; no remote failover or automatic renewal.')
dump('release_summary.json', summary)
dump('current_status.json', {k: summary[k] for k in ('status','updated_ms','source_hash','source_modified','execution_mode','allow_live_orders','current_eligible_executable_long_notional','qualification_proposal_created','autonomous_mandate_created','approval_requested','signer_or_worker_launched')})

unknown_md = f'''# UNKNOWN_INTENT_RESOLUTION_REPORT

Reviewed {stamp(now)}. **Classification: STILL UNKNOWN. Future signing: blocked.**

The exact intent is `{row['cloid']}`, nonce **1792217834069**, mandate `{unknown['mandate_id']}`. The genuine acceptance was {stamp(unknown['accepted_ms'])}; authority expired {stamp(unknown['expired_ms'])}. Its selected wire was BUY 0.0002 BTC at 81,518, within the approved limits.

The full source manifest was reconstructed from unchanged current files plus preserved pre-repair files: `{manifest['source_hash']}`. It matches the actual signed-source release and launch provenance. SDK 0.24.0's guarded path checks the exact action, allocates the durable nonce, signs, then enters native transmit. Native transmit checks again and must persist its claim transaction before the only HTTP sink. Raw SDK POST is blocked. No claim exists for this mandate. SQLite integrity/checkpoint checks and post-attempt database preservation pass.

Those facts support a pre-HTTP stop. The recorded public receipts reconstruct readiness age of approximately 5,526 ms; source requires <=5,000 ms. However, the original native route did not record a final pre-HTTP causal reason or complete HTTP boundary telemetry. The durable result records only `ExchangeError` / `TRANSMISSION_UNCERTAIN`. We cannot promote the reconstruction into the framework's required explicit final-guard rejection record. The historical immutable certificate is deliberately restricted to its original different source/intent; it is not a generic clearance mechanism.

Fresh unsigned review made **{a['requests']} public requests**, with zero venue errors. The own-wallet historicalOrders response returned **{history['row_count']} records**, below its 2,000-row cap, all from the earlier Limit orders; no exact-CLOID match or new fill appears. Complete paginated fills/funding from time zero contain only the original October 15 events. Two readbacks at {stamp(a['final_readbacks'][0]['observed_ms'])} and {stamp(a['final_readbacks'][1]['observed_ms'])} show no position/order and `unknownOid` for the exact CLOID. Retained post-expiry snapshots agree. These are authoritative account snapshots, not a positive rejection/terminal order record. No continuous historical-position endpoint was available.

**No certificate was appended; the UNKNOWN row, nonce, consumed invocation and old certificate remain unchanged.** The existing effective qualification view still includes this intent, so the unresolved-order barrier legitimately continues to block entry.

Required proof: recover an original explicit pre-HTTP rejection tied to this nonce/action/source, or equivalent independently validated causal evidence admissible to the immutable framework; alternatively obtain an authoritative venue rejection/terminal record tied to this action. A bare not-found response, more flatness observations or a new approval does not resolve this barrier. `VENUE_OPERATOR_REVIEW_PACKET.md` contains the exact public identifiers and requested records. No message has been sent on the operator's behalf.

Evidence: `original_local_evidence.json`, `original_signing_source_manifest.json`, `public_audit_with_network/info_receipts.jsonl`, `public_audit_with_network/audit.json`, `preservation_receipt.json`, and the unchanged original qualification result/provenance under `../practice_weekend_2026-10-17/`.
'''
(P / 'UNKNOWN_INTENT_RESOLUTION_REPORT.md').write_text(unknown_md)

native_md = '''# NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN

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
'''
(P / 'NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.md').write_text(native_md)

freshness_md = f'''# Signing-data freshness verification

Source `{source}` is unchanged and matches the passing full **2,753-test** release. This review reran **381 targeted tests**, zero failures/errors/skips, including nine task-local supplemental cases. Full regression was not repeated because production and source-bound test files did not change. The original XML/receipt hashes were revalidated by both release readers.

The supplemental tests explicitly accept ages **4,900 ms** and **5,000 ms**, reject **5,100 ms**, and drive realistic SDK callback delays of 4,900/5,000/5,100/**5,526 ms**. They exercise genuine offline evidence reacquisition for the same immutable request, one nonce and one submission, durable duplicate-return behavior, own UNKNOWN rejection and other historical UNKNOWN blocking. All signatures use ephemeral offline fixtures; they prove software behavior only.

Existing targeted cases cover changed account/orders/read failure, fees/funding, depth, price corridor, reference/metadata, source/revocation, health/lease/budget, native parent/child identity, partial aborts, unresolved cancellation, exact closes, LONG lifecycle and cross-midnight carried limits. Exact pre-HTTP error/nonce/CLOID telemetry is tested without exporting keys or signatures.

The native boundary reacquires readiness when necessary, rereads positions/orders/positions and current metadata/funding/book at callbacks, reruns central validation for the same reserved wire, and preserves quantity/price/CLOID, lease generation, nonce ownership, approval/source and five-second limits. UNKNOWN and already-started transport cannot use recovery to create a replacement attempt. Mandatory pre-HTTP claims prevent a second transmission of the same action; durable submit returns the original intent.

Remaining limits: exchange state can change after the last read; separate REST reads are not an atomic venue transaction. Slow network/rate waits can exhaust freshness or the cleanup/approval window and must fail closed. Trigger placement has its separate unchanged checks. Offline tests do not prove real-exchange acceptance, native triggering or uninterrupted streams. No actual signing or exchange retest was performed in this review.

Full XML SHA-256: `{v['full_xml_sha256']}`. Full receipt: `{v['full_receipt_sha256']}`. Targeted XML: `{v['focused_xml_sha256']}`. Fresh Phase-0 and frozen-strategy checks passed. Journal/checkpoint/nonce preservation passed.
'''
(P / 'FRESHNESS_REPAIR_VERIFICATION_REPORT.md').write_text(freshness_md)

command = '''.venv/bin/python scripts/anchorium_cli.py start --authorized \\
  --mandate "$NEW_VALIDATED_MANDATE_JSON" \\
  --acceptance "$GENUINE_ACCEPTANCE_JSON" \\
  --release docs/practice_weekend_2026-10-17/freshness_repair_regression_release/test_receipt.json \\
  --native-protection-evidence "$QUALIFIED_NATIVE_PROOF_JSON" \\
  --state runtime/terminal'''
(P / 'VENUE_OPERATOR_REVIEW_PACKET.md').write_text(f'''# Venue/operator review packet — not sent

Hyperliquid TESTNET, dex=par, coin=par:BTC. Registered team: 0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C. API public address: 0x46c9BED595770150752E7fA3806449F81E0Ec6f9.

Original CLOID `{row['cloid']}`, nonce **1792217834069**, exact reserved BUY IOC 0.0002 BTC at 81,518, non-reduce-only. Source `{manifest['source_hash']}`. Accepted {stamp(unknown['accepted_ms'])}, expired {stamp(unknown['expired_ms'])}. The original local outcome is UNKNOWN, numeric exchange OID absent; no transmission claim is recorded. Current source diagnostics cannot be retroactively treated as original telemetry.

Requested evidence:

1. Recover original positive pre-HTTP rejection/transport evidence tied to the exact nonce/action/source, or supply authoritative venue rejection/terminal order records for the exact identity. Repeated not-found/flat snapshots alone will not satisfy the current immutable resolver.
2. Confirm registered-par semantics and exact supported wire for full-position positionTpsl Stop Limit below 10 TEST USDPR, including whether it resizes with residuals and how children/partial fills/cancellations are represented. Supply genuine parent/child/fill records or authoritative applicable specifications.

Latest unsigned readbacks: {stamp(a['final_readbacks'][0]['observed_ms'])} / {stamp(a['final_readbacks'][1]['observed_ms'])}, flat and zero orders; exact CLOID unknownOid both. Own historicalOrders returned four older Limit records. Complete fill/funding reconciliation shows only the earlier October 15 round trip. This packet contains public identities and records only; it contains no keys, signatures or signed payload.

Requested review does not authorize retrying the BUY, changing the nonce, clearing raw history, signing a replacement or starting trading.
''')

report = f'''# Final practice recovery — A–K operator report

Updated {stamp(now)}. **Trading remains blocked. The new UNKNOWN could not be formally resolved from the available evidence. No new approval was requested and no signer or trading worker was launched.**

| Question | Verified answer |
| --- | --- |
| A. New UNKNOWN formally resolved? | **No.** Exact CLOID/nonce/source reviewed; original causal rejection telemetry is missing. Raw UNKNOWN and nonce are preserved. |
| B. Freshness fixed and verified? | **Yes, offline.** Unchanged five-second boundary; 381 targeted checks passed, including 4,900/5,000/5,100 ms and SDK delays. No actual exchange retest. |
| C. Native Stop Limit qualified? | **No.** No genuine accepted/triggered parent-to-child closing chain. |
| D. Subminimum residual protection/closure? | Native protection **unknown**. Only the historical exact one-lot BTC full-position IOC close is verified; it is not a general/native exemption. |
| E. Fresh genuine qualification permitted? | **No**, while the effective UNKNOWN barrier remains. Expired/consumed approval cannot be reused. |
| F. Maximum executable LONG now? | **0 eligible/qualified TEST USDPR.** Observed liquidity-only upper estimates are below; largest {largest['symbol']} ≈{largest['liquidity_only_notional']}, BTC 48.96240. They are snapshots, not an executable signal or risk allocation. |
| G. Complete regression passed? | Existing source-matched **2,753 passed**, 0 failures/errors/skips; hashes revalidated. **381 targeted tests rerun** in this review passed. No production-source changes, so full suite was not rerun. |
| H. Autonomous session eligible for approval? | **No.** UNKNOWN, native/residual proof and a future exact approval remain prerequisites. Proposed bankroll remains unallocated. |
| I. Exact VS Code launch interface? | Existing authorized CLI shown below. A runnable authorized command cannot be completed until genuine mandate/acceptance/native proof files exist. |
| J. Genuine new orders/P&L? | **No confirmed new orders or fills**, no new fees/funding. No completed qualification round trip. October 15 net remains **+0.050512 TEST USDPR**, separate from today. |
| K. Exact remaining dependency? | Identity-bound causal/terminal evidence for this UNKNOWN, registered-par small-native semantics and genuine native trigger/residual evidence. Then fresh exact human authorization. More software-only tests cannot supply those venue records. |

## Formal UNKNOWN review

`{row['cloid']}`, nonce **1792217834069**, mandate `{unknown['mandate_id']}`. The original source was reconstructed exactly as `{manifest['source_hash']}`. The mandatory pre-HTTP claim path and absence of a claim support the pre-HTTP diagnosis; the original native worker saved only a generic exception, without the explicit causal evidence required by the current immutable framework. No certificate or terminal record was fabricated. See [UNKNOWN_INTENT_RESOLUTION_REPORT.md](UNKNOWN_INTENT_RESOLUTION_REPORT.md).

Fresh review completed **63 unsigned /info requests**, zero venue errors. Two authoritative readbacks at {stamp(a['final_readbacks'][0]['observed_ms'])} and {stamp(a['final_readbacks'][1]['observed_ms'])} show no positions/orders and unknownOid for the exact CLOID. Four own historical order records contain no matching action. Complete paginated fills/funding show no new activity. These facts establish observed account truth, not nontransmission. An initial sandbox DNS failure was preserved separately; it had no HTTP status or 429.

## Native and residual route

The [venue TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) documents mark triggers, position versus fixed sizing and gap/cancellation risks. It does not provide our missing registered-par subminimum execution proof. No supported exception has been independently established, and no venue-wide prohibition is inferred. See [NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.md](NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.md) and [VENUE_OPERATOR_REVIEW_PACKET.md](VENUE_OPERATOR_REVIEW_PACKET.md). No messages were sent.

## Current observed liquidity

Books observed {stamp(a['markets'][0]['observed_ms'])} through {stamp(a['markets'][-1]['observed_ms'])}. Retain 10% of **both** best levels, finite depth within 5 bps, actual lot rounding and current 1x account maxTradeSz. Estimates are capped at the proposed 10,000 maximum; displayed depth binds far earlier. They exclude unqualified native/residual protection, unresolved-order, frozen-signal and full future risk/allocation gates. No current quote authorizes signing.

| Market | One-lot mark value | Liquidity-only quantity | Liquidity-only notional, TEST USDPR |
| --- | ---: | ---: | ---: |
{table}

BRENT, GOLD and SP500 estimates are below the normal 10 minimum and cannot support a normal opening order at these observations. All ten one-lot mark values are below 10, so simply increasing initial size does not eliminate a possible subminimum residual. No current evidence supports 1,000–10,000 notional execution through these books.

## Verification and exact launch interface

Current source `{source}`. Full XML `{v['full_xml_sha256']}`; receipt `{v['full_receipt_sha256']}`. Full release remains valid for this unchanged source. Supplemental tests were kept under docs; no strategy, lot precision, configuration, floor or production source was changed. Fresh Phase-0/strategy-freeze checks pass. Actual SQLite dumps, checkpoint checksums, original BUY/SELL proofs, historical certificate, new UNKNOWN and nonce are preserved. See [FRESHNESS_REPAIR_VERIFICATION_REPORT.md](FRESHNESS_REPAIR_VERIFICATION_REPORT.md).

The real execution-enabled interface, from this cloned repository's VS Code Terminal, is:

```sh
{command}
```

**This is an interface template, not a launchable authorization.** Its three named mandate/acceptance/proof inputs do not exist in valid form. Do not substitute old approvals. No command was launched. After future prerequisites and exact approval, the authorized runtime implements the deterministic SCAN → BUY → VERIFY → PROTECT → MANAGE → SELL → RECONCILE lifecycle and can continue observing after its bounded signer closes; it requires no continuous Codex/LLM credits.

The proposed Oct17–18 contract remains LONG-only, one position, two total entry attempts, 1x CROSS, <=24h and no later than Oct18 23:57 IST, carried 1% session loss, 0.5% trade risk, proposed 20,000 allocation, bounded protection/recovery and no midnight reset/renewal. It has no accepted session, signing authority or authorized bankroll. Native Stop Limit does not guarantee a loss cap or fill through a gap.

## Actual accounting and next action

No new BUY/SELL fill, fee or funding occurred in the reconciled October 17 window. Observed new cashflow is 0; qualification P&L remains uncertified. Historical October 15: gross +0.0794, fees 0.029415, funding +0.000527, **net +0.050512 TEST USDPR**. Remaining positions/orders are empty in both timestamped readbacks. No organizer whitelist/reset claim is made.

The immediate next action is the exact causal/terminal evidence review in the packet, followed by registered-par native/residual evidence. Extra approval alone cannot bypass either barrier. No new qualification or autonomous proposal was generated. No next-day session, heartbeat, retry or restart was scheduled. No worker is running; future local operation depends on this Mac, process/app, power and internet.
'''
(P / 'final_report.md').write_text(report)
(P / 'implementation_report.md').write_text(report)
files = ['operator_request.md','original_local_evidence.json','original_signing_source_manifest.json',
         'public_audit_with_network/audit.json','public_audit_with_network/info_receipts.jsonl',
         'focused_verification.xml','verification_receipt.json','preservation_receipt.json',
         'UNKNOWN_INTENT_RESOLUTION_REPORT.json','UNKNOWN_INTENT_RESOLUTION_REPORT.md',
         'NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.json','NATIVE_STOP_AND_RESIDUAL_QUALIFICATION_PLAN.md',
         'FRESHNESS_REPAIR_VERIFICATION_REPORT.md','VENUE_OPERATOR_REVIEW_PACKET.md','final_report.md','release_summary.json']
dump('artifact_hashes.json', dict(source_hash=source, created_ms=now, files={x: sha(P/x) for x in files}))
print(json.dumps(dict(status=summary['status'], formally_resolved=False, targeted_tests=381,
                      source_unchanged=True, actual_account_flat=True, reports_saved=True)))
