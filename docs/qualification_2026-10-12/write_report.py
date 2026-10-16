"""Local report generator only. No network, signer or order client."""
import json,hashlib,sys
from pathlib import Path
from decimal import Decimal as D
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'algo-trading-bot'))
from exchange.paper_operations import active_source_hash,atomic_json
r=json.loads((OUT/'proposal_review/readiness.json').read_text())
t=json.loads((OUT/'regression_release/test_receipt.json').read_text())
s=json.loads((OUT/'signer_preflight_final.json').read_text())
before=json.loads((OUT/'source_before.json').read_text())
paths=list((ROOT/'scripts').glob('*.py'))+[p for p in (ROOT/'algo-trading-bot').rglob('*.py')
    if not {'venv','.venv','__pycache__'}&set(p.parts)]
paths += [ROOT/p for p in before['files'] if p.startswith('configs/')]
files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
comparison=dict(existing_changed=[p for p,h in before['files'].items() if files.get(p)!=h],
    added=[p for p in files if p not in before['files']],source_hash=active_source_hash(ROOT),files=files)
atomic_json(OUT/'source_after.json',comparison)
assert not comparison['existing_changed']
assert t['passed'] and t['source_hash']==t['source_hash_after']==r['source_hash']==r['source_hash_after']==comparison['source_hash']
p=r.get('selected_proposal');status=r['status']
summary=dict(status=status,source_hash=comparison['source_hash'],files_added=comparison['added'],
    existing_source_files_changed=[],tests=t['totals'],full_regression_passed=t['passed'],
    phase0_passed=t['checks_before']['phase0']['exit_code']==0,
    strategy_freeze_passed=t['checks_before']['strategy_freeze']['exit_code']==0,
    execution_mode='PAPER',allow_live_orders=False,protection_enabled=False,
    actual_exchange_submissions=0,actual_wallet_signatures=0,actual_fill_verified=False,
    sole_signer_host_confirmed=False,local_signer_check=s['status'],
    normal_partial_fill_exit_ready=False,actual_protection_ready=False,controlled_execution_ready=False,
    qualification_execution_authorized=False,practice_ready=False,live_ready=False,
    organizer_whitelisting_confirmed=False,selected_proposal=p,proposal_hash=r.get('selected_proposal_hash'),
    readiness_path=str(OUT/'proposal_review/readiness.json'),
    required_human_decisions=['Verify the shown wallet identities and sole signing host',
        'Explicitly approve this exact proposal including unverified stop risk, qualification-only 50 bps spread ceiling and possible manual residual recovery'])
atomic_json(OUT/'final_summary.json',summary)
lines=['# Team Anchorium — one bounded testnet qualification proposal','',
    '**No signed action or actual trade has been submitted. Approval is still required.**',
    'This separate qualification experiment does not certify the frozen VWAP strategy or normal protection. The user explicitly requested preparation of an experimental risk-acceptance route. General trading stays PAPER/false; global protection stays disabled.','',
    '## Account and signer observations','',
    'Registered team wallet: `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`.',
    'Approved API wallet: `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`.',
    'The initial public read (17:30:34–17:30:48 UTC, 12 October) observed 1,000,000 USDPR, unifiedAccount, a valid approved agent, all ten markets at 1x CROSS, no positions or orders, and a restored, checksummed read-only account checkpoint. It is preserved separately and does not authorize an action.',
    f'The final public preparation ran {r["started_utc"]}–{r["finished_utc"]}; its full account, agent, margin, fee, rate, clock and three-book observations are in `proposal_review/readiness.json`. The selected market’s 1x CROSS and available capacity were checked again. Account reconciliation was restored after reopening SQLite and rechecked at completion.',
    'The final local signer check derived only the API public address, verified its match, rejected a second local lease owner, allocated no nonce, and made no signature. This proves current-host ownership only. The human still must confirm that no other machine/process signs with this API key.',
    'The installed official SDK is configured with the TESTNET URL, par-only asset mapping and the registered team address as account_address; the approved API signer acts for that team. Actual proof must come from userFills queried using the team address. The [official participant guide](https://perpetual-alpha26.github.io/docs/) documents this attribution, ordinary $10 minimum and doubled par fee rates.','',
    '## Objective entry rule and market selection','',
    'One qualification LONG only. Inspect BTC, ETH and HYPE; require a fresh two-sided book, spread at most 50 bps, mark/oracle divergence at most 50 bps, midpoint/oracle divergence at most 100 bps, quantity at most 10% of both best-level sizes, current margin and a freshly reconciled flat account. Round the BUY limit down from ask × 1.0005 using runtime price rules. Round quantity down from 25 / max(limit, mark). Reject entry below $10. Select the smallest spread among markets whose every possible whole-lot remainder has a supported exact closing shape at the reviewed exit floor.',
    'The 50 bps ceiling is a **qualification-only proposed risk exception requiring human acceptance**. The production scanner’s 15 bps ceiling, 0.40% ATR floor, 300 completed bars, Top-3 and frozen UTC strategy remain unchanged. This is an algorithmic execution-connectivity experiment, not a VWAP signal or a strategy-performance trade. Prices are generated by the documented rule. No automatic entry repeat or size increase is allowed.','',
    '| Market | Observed spread (bps) | Eligible for experimental review | Rejection |','|---|---:|---|---|']
for c in r['candidates']:
    q=c.get('quote',{});spread=(D(q['ask'])-D(q['bid']))/D(q['mid'])*10000 if q else None
    lines.append(f'| {c["symbol"]} | {str(spread) if spread is not None else "unknown"} | {c["eligible_for_risk_review"]} | {c.get("blocker", "—")} |')
if p:
    selected=next(c for c in r['candidates'] if c['symbol']==p['symbol']);q=D(p['quantity']);e=D(p['entry_limit']);floor=D(p['exit_bound'])
    lines+=['','## Exact proposal — not authorization','',f'Proposal hash: `{r["selected_proposal_hash"]}`.','',
        f'- Network/DEX/market: TESTNET / par / **{p["symbol"]}**; leverage **1x CROSS**.',
        f'- One BUY LIMIT IOC: **{p["quantity"]}** coin at **{p["entry_limit"]} USDPR or better**.',
        f'- Maximum submitted entry notional: **{q*e} USDPR**; hard workflow notional ceiling **25 USDPR**.',
        f'- Reviewed bid/ask: {p["reference_bid"]} / {p["reference_ask"]}; mark/oracle: {p["reference_mark"]} / {p["reference_oracle"]}.',
        f'- Observed margin: {selected["active_asset"]["availableToTrade"][0]} USDPR on the long side; selected leverage {selected["active_asset"]["leverage"]}.',
        f'- Runtime lot: {selected["spec"]["size_decimals"]} size decimals; one BTC lot is 0.0001, reviewed entry notional {D(".0001")*e}.',
        f'- Immediately after authoritative fill/position reconciliation, SELL **exactly the actual remaining position**, reduce-only IOC, priced from current bid × 0.998. Reviewed initial exit limit: **{r["expected_immediate_exit_limit"]}**. Never submit an exit below **{p["exit_bound"]}**.',
        '- At most two bounded exit attempts, each sized from freshly reconciled actual exposure. An uncertain order is read back, never blindly resubmitted. Own-order cancellations alone are permitted if an unexpected resting remainder appears; all other orders/account administration are prohibited. The entire capability is capped at five signed actions.',
        f'- Estimated combined taker fees at the reviewed immediate limits: **{r["estimated_round_trip_fee_at_reviewed_limits"]} USDPR**, at {D(p["taker_fee_rate"])*100}% per fill. Estimated loss at those limits: **{r["estimated_loss_at_reviewed_immediate_exit"]} USDPR**. Estimated loss if the complete exit fills at the approved floor: **{q*(e-floor)+q*(e+floor)*D(p["taker_fee_rate"])} USDPR**, excluding funding. These are estimates, not caps or promised outcomes.',
        '- The exact price/quantity/source/policy are bound to the approval. Approval must occur within five minutes of the observed proposal, last at most five minutes, and remain valid at every signed action. Fresh account/market/metadata/fee checks repeat before execution. A changed or expired proposal aborts; it is not automatically repriced. A fresh proposal with changed limits needs a new explicit decision.']
lines+=['','## Verified versus unverified risk','',
    '**Verified historical closing evidence:** V8.5 original public readbacks include BTC SELL 0.0001 reduce-only IOC order 62228843959, a filled status and matching fill with startPosition 0.0001 reducing to zero. The zero is derived from the reported fill, not an independent historical position snapshot. This is another account’s record, not Anchorium’s trade. The scoped V8.6 validator checks the same asset ID, direction, size decimals and exact full-position shape. It does not exempt arbitrary dust or stops.',
    'For the selected BTC size, a one-lot remainder is below $10 and uses that narrow historical shape; two- and three-lot remainders remain above $10 at the approved floor and use ordinary full-close checks. Increasing the entry size does not prevent small partial fills. The new workflow explicitly assesses every possible lot remainder.',
    '**Unverified:** Small position-attached stop acceptance, position coverage and trigger/residual behavior are still unproven. No stop will be constructed or submitted in this experiment. The [official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) does not establish the required par sub-$10 exception. IOC closing evidence does not establish protection.',
    '**Residual risk:** A filled position may remain unprotected if a close is rejected, its status cannot be established, connectivity fails, liquidity disappears, or price moves beyond the approved exit floor. Historical closes do not guarantee future acceptance or fills. The entry principal is below $25, but cross margin shares the funded collateral; fees and funding can accumulate. There is no guaranteed total-loss cap. If the sequence cannot prove flat, it preserves the durable exposure/unknown lock and reports EMERGENCY_EXIT_REQUIRED for human action. Restart does not repeat an entry or silently resume writes. Read-only reconciliation is the next recovery step; any additional exit outside the exact authorization requires another explicit decision.',
    '## Regression and integrity','',
    f'Full regression: **{t["totals"]["tests"]} passed; {t["totals"]["failures"]} failures; {t["totals"]["errors"]} errors; {t["totals"]["skipped"]} skipped**. This includes the 1,633 baseline and 49 new qualification cases. The overlapping focused suite had 309 passes. Initial new-test fixture/assertion failures are retained in targeted_initial.xml; they were corrected, and the final suite passed.',
    'Phase-0 and strategy freeze passed. The 219 source/configuration files recorded before this task are unchanged from V8.6; only three new active files were added: `exchange/testnet_qualification.py`, `test_testnet_qualification.py` and `scripts/run_testnet_qualification.py`. No configuration, strategy, normal protection or ordinary minimum validator changed. Legacy inventory refreshed: 1,103,172 occurrences across 475 files, largely preserved cached references, not new broker dependencies.',
    f'Active source hash: `{comparison["source_hash"]}`. Full test XML SHA256: `{t["xml_sha256"]}`. Source identity remained stable across regression and final public preparation. The tests use ephemeral offline signers and a synthetic venue with HTTP prohibited; they are not funded-account evidence.',
    '## Proof and next action','',
    '`proposal_review/WHITELIST_TRADE_PROOF.json` correctly states NO_ACTUAL_PRACTICE_FILL_VERIFIED. Exchange order/fill IDs, executed notional and execution timestamp are null/empty. A future approved runtime can populate proof only from authoritative team-account fills matched to its durable entry ID; hypothetical or SDK-summary-only fills cannot qualify. Flat-account proof is separate and requires actual reconciliation.',
    'The October16 qualification instruction is user-reported organizer communication. The public guide permits approved API-wallet trading for the team and describes ordinary minimums; it does not independently settle the October16 cutoff timezone, whether this particular experimental rule counts, or any extra qualification minimum. Organizer whitelisting remains unconfirmed, even after a future fill. No organizer message was sent.',
    '**Next action:** Review the exact proposal and decide whether to accept the qualification-only 50 bps ceiling and possible unprotected residual/manual recovery. Also verify the shown wallet identities and confirm this Mac is the only signing host. The approval template is deliberately blank/false. Do not fill it with approval merely because the account is funded or because the deadline is approaching.',
    '', '```ini','EXECUTION_MODE=PAPER','ALLOW_LIVE_ORDERS=false','PROTECTION_ENABLED=FALSE',
    'PARTIAL_FILL_EXIT_READY=FALSE','ACTUAL_PROTECTION_READY=FALSE','CONTROLLED_EXECUTION_READY=FALSE',
    'QUALIFICATION_EXECUTION_AUTHORIZED=FALSE','ACTUAL_PRACTICE_FILL_VERIFIED=FALSE',
    'SOLE_SIGNER_HOST_CONFIRMED=FALSE','ORGANIZER_WHITELISTING_CONFIRMED=FALSE','PRACTICE_READY=FALSE','LIVE_READY=FALSE','```','']
(OUT/'report.md').write_text('\n'.join(lines))
print(json.dumps(dict(status=status,proposal_hash=r.get('selected_proposal_hash'),tests=t['totals'],existing_changed=comparison['existing_changed'],new_source_files=comparison['added'])))
