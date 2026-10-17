# Overnight autonomous engine — final engineering release

Updated 2026-10-17T21:30:50.080000+05:30. **Verdict: BLOCKED_EXTERNAL_EVIDENCE.** The standalone observation engine is demonstrated and the final changed source passes its full release suite. Genuine autonomous trading is not qualified or authorized. No new actual-wallet signing or exchange write occurred.

## A. Engineering changes

Recoverable branch: `codex/overnight-recovery-2026-10-17`, starting commit `a9e222c6549686651c3565155ed555fa7ee04739`. The prior dirty/untracked working source is preserved in `source_before.tar.gz`; database snapshots and exact dump hashes are in `baseline.json`. This is not a claim that inherited changes were newly committed. Original NSE source is untouched.

| Source | Defect or purpose |
| --- | --- |
| `algo-trading-bot/exchange/competition_windows.py` | Reject actual runtime construction outside the published finite windows; no implicit Oct17–18 permission. |
| `algo-trading-bot/exchange/execution_journal.py` | Atomically persist append-only intent audit events alongside durable reservations/state changes. |
| `algo-trading-bot/exchange/hyperliquid_execution.py` | Preserve sanitized causal exceptions and link genuinely ready recovery to new terminal audit records. |
| `algo-trading-bot/exchange/intent_audit.py` | Checksum-chain append-only evidence; never backfill or resolve historical UNKNOWN. |
| `algo-trading-bot/exchange/long_session.py` | Apply the published-window check before release/key/actual runtime construction. |
| `algo-trading-bot/exchange/sdk_transport.py` | Record signed/dispatch/HTTP-response boundaries without secrets; retain the separate fixed-leverage transport. |
| `algo-trading-bot/exchange/terminal_app.py` | Visible local UNKNOWN and session accounting, refreshed dashboard command, read-only restart provenance, stronger proposal blockers. |
| `algo-trading-bot/exchange/terminal_evidence.py` | Unsigned exact-lot two-sided capacity, stressed conditional costs and observed-session accounting with defined bases. |
| `algo-trading-bot/exchange/terminal_observer.py` | Refresh capacity clocks after candle recovery; publish independent capacity, counts and actual-account diagnostics. |
| `algo-trading-bot/test_overnight_terminal_evidence.py` | Adversarial/property-style capacity, accounting, immutable-audit, stale-dashboard and window tests. |
| `scripts/phase0_check.py` | Allow the explicitly requested codex recovery branch only with migration-branch ancestry. |

The frozen brain/methods/parameters, production scanner ranking/Top-3, order quantity precision, risk geometry, 10% both-best-level participation and 5 bps depth policy remain unchanged. Diagnostic ranking never feeds production signals. Existing native stop identity/trigger/child management, exact residual guards, durable nonce lease, bounded signer, global account lease and deterministic LONG orchestration were reused rather than rebuilt.

The new ledger records PERSISTED, signing, signed, dispatch attempt, HTTP response, legacy acceptance/terminal outcome, UNKNOWN and verified recovery stages. DISPATCHED is an attempt, not proof of delivery; HTTP acknowledgement is not acceptance or a fill. Fill/fee accounting still requires account records. The ledger grants no authorization or UNKNOWN resolution and is not backfilled into old trading history. Update/delete triggers and checksums protect the application audit chain. Original exceptions now retain sanitized causal details. No venue idempotency guarantee is invented; local durable identity and pre-HTTP claims prevent blind resubmission.

## B. Blocker resolution

| Original issue | Root cause / implementation / verification | Status and remaining dependency |
| --- | --- | --- |
| Historical UNKNOWN | Original native worker retained only generic ExchangeError; reconstructed pre-HTTP timing cannot replace admissible original evidence. Raw intent/nonce preserved; new future audit records are not retroactive proof. | **BLOCKED:** positive original causal/terminal evidence or an admissible sanctioned recovery mechanism. |
| Five-second freshness | Existing repaired same-wire reacquisition retained; exact age and SDK-delay tests rerun in focused/final suites. Five seconds is a local evidence policy, not Hyperliquid's documented nonce window. | **RESOLVED offline;** genuine authorized exchange validation remains separate. |
| Native stop lifecycle | Existing parent/child/trigger/partial/cancellation manager and tests retained. No actual native stop event or closing chain recovered. | **BLOCKED:** genuine registered-par acceptance, natural trigger/child SELL fills and cleanup proof. |
| Subminimum residual | Every minimum lot remains below ordinary minimum at sampled marks; historical one-lot BTC full-position IOC proves only that scope. | **BLOCKED:** applicable small-native semantics and genuine residual evidence. No guard/precision bypass. |
| Stale capacity/account display | Capacity now has independent freshness checks after candle recovery; local unresolved journal remains visible despite exchange flatness. | **RESOLVED in software;** fresh data may still be unavailable. |
| Return/fee ambiguity | Session actual cashflows and explicit return/balance bases separated from historical totals and target scenarios. | **RESOLVED display;** empirical expected edge and official score remain unknown. |
| Overnight authorization/window | No current mandate/acceptance; published practice ends Oct16 and scored trading begins Oct19. Actual constructor now rejects a gap interval. | **BLOCKED:** organizer gap permission/exact cutoff and a separately tested applicable authorization route, then exact human approval. |

No certificate was appended for CLOID `0xac0eea156fcec80986dd67c9057b6ded`, nonce **1792217834069**. Its mandate `59445fe546d38a96e486140fda781d09ae8a0942f93a3614fa8abcbc34f5e7ea` remains consumed/expired. See the [formal review packet](../practice_recovery_2026-10-17/VENUE_OPERATOR_REVIEW_PACKET.md) and `UNKNOWN_REVIEW_UPDATE.md`. No organizer/venue message was sent on behalf of the operator.

## C. Liquidity, friction and opportunity observations

These are genuine timestamped public snapshots, not a promise of current fill capacity. The evaluator takes the minimum of both BBO participation caps, both finite 5 bps depth caps, runtime lot rounding, current 1x account limits and a proposed upper cap. Actual authorized allocation, risk budget, venue/residual/protection support and approval remain independent zero/unknown gates. Nothing is enlarged to reach 1,000–10,000 notional.

| Market | Lot-rounded liquidity quantity | Liquidity-only notional | Conditional economic notional | Authorized executable notional | Leading reason |
| --- | ---: | ---: | ---: | ---: | --- |
| par:SP500 | 0.013 | 99.2966 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:USDEUR | 44.5 | 50.01355 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:EWJ | 0.527 | 50.005449 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:EWY | 0.331 | 49.95452 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:ETH | 0.0205 | 49.82935 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:HYPE | 0.62 | 49.56838 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:USDJPY | 0.31 | 49.0606 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:BTC | 0.0006 | 48.93600 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:BRENT | 0.31 | 33.139 | 0 | 0 | NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL, EMPIRICAL_EXPECTED_EDGE_NOT_ESTABLISHED |
| par:GOLD | 0.0024 | 9.99720 | 0 | 0 | BELOW_MINIMUM_WITHIN_BOTH_SIDE_CAPACITY, NO_CURRENT_QUALIFIED_FROZEN_LONG_SIGNAL |

Latest complete scan: 2026-10-17T15:08:06.974000+05:30. Latest gate counts: `{"candidate_occurrences": 0, "markets_with_two_sided_capacity": 9, "candidates_passing_capacity": 0, "conditional_friction_and_stress": 0, "qualified_protection": 0, "authorized": 0, "statistical_expected_edge_verified": 0}`. Capacity counts refer to all observed markets, not a nested count of passing candidate signals. No qualified positive-edge LONG was established. Stale or incomplete completed candles are rejected rather than synthesized; the raw receipts retain their actual last timestamps. A current book does not make stale candle signals current.

The economic engine retains the frozen target geometry and baseline fee-adjusted RR controls. New reporting distinguishes that conditional target scenario from a statistically estimated expected return; the latter stays null without supporting evidence. Stress doubles friction and reserves adverse funding. Passive comparison is fee-only; queue position, missed fills and adverse selection remain unknown. No routing change or post-only activation was made.

The [participant guide](https://perpetual-alpha26.github.io/docs/) describes current positive base fees doubled on par; actual earlier fills support 0.09% taker. The existing runtime deliberately keeps its more conservative 6x base-rate bound (currently 0.27% taker) unchanged. No lower fee floor or higher risk allowance was silently substituted to manufacture an opportunity. Actual fill fees always govern realized P&L.

Final unsigned refresh: **2026-10-17T21:32:13.094000+05:30**, 63 public info requests, no recorded errors, no signing or exchange writes. Two authoritative flat/zero-order readbacks occurred at 2026-10-17T21:32:10.326000+05:30 and 2026-10-17T21:32:13.093000+05:30. Original CLOID remains `unknownOid`, with no matching historical-order record or new fill; this does not resolve the local UNKNOWN.

The fresh liquidity-only snapshots below do not include a new strategy signal and are not economically qualified or authorized capacity. Exact per-market books, fees, funding and timestamps remain in `final_account_audit/audit.json` and `info_receipts.jsonl`. The earlier complete-scan table above remains labeled with its own time.

| Market | Fresh lot-rounded quantity | Fresh liquidity-only TEST USDPR | Authorized executable TEST USDPR |
| --- | ---: | ---: | ---: |
| par:BRENT | 0.46 | 49.1832 | 0 |
| par:BTC | 0.0006 | 48.79500 | 0 |
| par:ETH | 0.0207 | 49.89114 | 0 |
| par:EWJ | 0.529 | 50.004254 | 0 |
| par:EWY | 0.333 | 49.91004 | 0 |
| par:GOLD | 0.0120 | 49.98600 | 0 |
| par:HYPE | 0.63 | 49.455 | 0 |
| par:SP500 | 0.013 | 99.2420 | 0 |
| par:USDEUR | 53.4 | 60.01626 | 0 |
| par:USDJPY | 0.31 | 49.0699 | 0 |

## D. Tests and source identity

**2783 passed, 0 failures, 0 errors, 0 skips**, complete final regression. Source before/after: `4aa20fe9c1f8285788dff42e23d247eed2f225b4802bfad26347ef42afd44ac1`. XML SHA-256 `725d6673d3760964c1637d674c2979ebed57807dae602d048fbb22ca24389c0c`; receipt SHA-256 `56510bbef476613a31c2b967a884d59ec29a7dd19b686102b5e1dd03e1c011df`. Fresh Phase-0 and strategy-freeze checks passed before and after, on the dependency-pinned SDK 0.24.0 runtime.

A separate final-source rerun of the explicitly requested signing-boundary suite passed **9/9**, including 4,900/5,000/5,100 ms and delayed-SDK cases. Its receipt is `requested_boundary_receipt.json`; these nine are separate from the full-suite count. `preservation_receipt.json` confirms SQLite integrity/checkpoints and unchanged original trading proofs, UNKNOWN and nonce.

The 2,753-test release was the baseline; 30 new tests cover immutable/atomic audit recording, independent stale evidence, lot/depth bounds, negative stressed economics, defined P&L bases, local UNKNOWN visibility, dead-dashboard claims and finite competition windows. Existing integration suites exercise ambiguous entry/exit, partials, native accepted-but-untriggered/triggered-unfilled cases, fee/depth deterioration, nonce/duplicate/reconnect/crash/expiry/loss/stop behavior and source-bound approvals. All signed test fixtures use ephemeral wallets and have no actual exchange authority.

The first full run exposed a compatibility defect in the new signed audit hook with the separate fixed-leverage configuration sink. It failed before transmission in the ephemeral fixture. That failed release is preserved separately; the hook was corrected without authorizing configuration or making any actual account change. A subsequent run was deliberately interrupted to fix shutdown reporting (preserved without a valid XML/receipt). The complete final suite was then rerun after all corrections. Offline tests cannot certify native venue execution or eliminate all future software/network risk.

## E. Standalone observation and restart demonstration

| Session | Observed source prefix | Completed scan windows | Public receipts | Terminal status | Two flat readbacks |
| --- | --- | ---: | ---: | --- | --- |
| 17aab05ec17b4deabeb7cce4f80c4672 | 84aee19ed62c | 2 | 186 | STOPPED | True |
| 40f89919e997491e958438688d494b59 | 049bbe5d1c4e | 1 | 137 | STOPPED | True |
| ccd16ee5dcdd4abaaf0c8da8d0681c62 | 049bbe5d1c4e | 3 | 233 | STOPPED | True |
| e08884862a5144f0adecf65c0ec1fa59 | 4aa20fe9c1f8 | 1 | 136 | STOPPED | True |

All demonstrations used zero signatures, zero exchange writes and zero execution intents. The same-state duplicate launch returned `PAPER_OWNER_ALREADY_RUNNING`; session-specific stop completed, all background threads stopped, and a restart reacquired account truth without restoring authority. Earlier engineering-source runs are not presented as final-source execution qualification; the final-source smoke run is separately identified. This is a bounded demonstration, not a claim that an entire overnight outage/uptime period was observed. The engine requires no continuous LLM or coding agent.

Final readbacks: 2026-10-17T15:09:02.692000+05:30 and 2026-10-17T15:09:05.199000+05:30, each empty positions/orders. The local historical UNKNOWN remains blocked independently. Mac/process/power/internet remain operational dependencies; there is no remote failover or signing auto-renewal.

## F. Exact operator commands

[OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md) gives verified doctor, read-only start, refreshed dashboard, exact approval workflow, authorized-interface template, graceful stop, restart and accounting commands. Today's usable manual command from this repository is:

```sh
/usr/bin/caffeinate -i .venv/bin/python scripts/anchorium_cli.py start --state runtime/terminal --scan-seconds 60
```

It is strictly **read-only**. No currently valid native proof, new mandate or human acceptance exists for `--authorized`. No dummy files or expired approvals were substituted. An approved future signer must retain LONG-only, one global position, 1x CROSS, exact allocation, two total entry attempts, carried risk/P&L, protection and finite hard expiry; none is an activity target or guaranteed loss cap.

## G. Genuine trading and performance evidence

New entry acknowledgement/fill, protective event, exit fill and qualification P&L: **NOT VERIFIED**. This engineering task performed no actual-wallet signing. Public reconciliation still contains only the October 15 BUY order **62755970305**, fill **800659111758533**, 0.0002 at 81,512, fee 0.014672; SELL order **62805581662**, fill **260274449763192**, 0.0002 at 81,909, fee 0.014743. Gross +0.0794, total fees 0.029415, funding +0.000527, historical net **+0.050512 TEST USDPR**. It is not today's or scored P&L.

Current observation-session reported gross/fees/funding/net are zero, with no new fills. Initial reported balance is 1,000,000.050512; that is neither an approved allocation nor free margin. Session percentages name that first verified balance as denominator; balance change is not cash-flow-adjusted or official oracle-marked performance. Unrealized position values remain separately reported. Sampled drawdown is not an intrabar guarantee; daily volatility/official score stay null when evidence is insufficient.

The [published evaluation](https://perpetual-alpha26.github.io/about) uses oracle-marked return, daily return variability and jury assessment with cross-team normalization. Peer/jury inputs are unavailable, so no financial score or first-place claim is fabricated. The [schedule](https://perpetual-alpha26.github.io/schedule) leaves Oct17–18 outside published practice/scored windows. Registration, exact timezone/cutoff and any gap exception require organizer evidence; a funded public wallet is not organizer permission.

The bounded daily report is in [DAILY_PERFORMANCE.md](DAILY_PERFORMANCE.md); daily opening equity, full-day volatility and official score remain unknown. All demonstration workers are stopped; readback states are timestamped evidence, not a claim of ongoing supervision.

## H. Go/no-go

**BLOCKED_EXTERNAL_EVIDENCE**

Software hardening and bounded standalone read-only operation are demonstrated. Trading still requires admissible resolution of the exact UNKNOWN, genuine native/residual qualification, applicable organizer window permission and a new exact source-bound human approval. Neither more capital nor a new approval alone can erase those prerequisites. No next-day worker, trading monitor, automatic restart, transfer, leverage change or renewal was installed.
