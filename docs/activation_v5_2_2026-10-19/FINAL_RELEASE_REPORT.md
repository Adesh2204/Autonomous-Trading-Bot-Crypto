# Anchorium V5.2 release and activation decision

**Trading verdict: NO-GO. No exchange action, real-wallet signature or human acceptance was created.**

As of 2026-10-19T08:38:32.617000+00:00. Source `dcb8012f1d55db16d769cec4573015f56534243c275a281a33148c17f76f91e5` from verified V4 `56ee079f7b8403811674d429aff3b9143a1810290bdd9a23f319b7cedd47170c`. **3088 tests passed**, zero failures/errors/skips. XML SHA-256 `1c7edc4c63f82370d2f0e65d3d73a62147f8a06e1275178b195a84b4278f9bef`. Strategy freeze and production-policy lockouts pass before/after; all 53 original journals and protected proof files are preserved.

| Verdict | Actual value |
|---|---|
| AUTOMATION_IMPLEMENTED | TRUE |
| TRADING_AUTHORIZED | FALSE |
| AUTO_TRADING_ACTIVE | FALSE |
| actual_pas_native_protection_qualified | FALSE |
| actual_pas_residual_route_qualified | FALSE |
| pas_subminimum_qualification_dispatch_available | FALSE |
| complete_scored_activation_package_ready | FALSE |

AUTOMATION_IMPLEMENTED is the tested guarded software lifecycle, funding detector, diagnostic state machine, source checks, risk controls and one accepted-mandate conditional handoff. It does not certify a usable PAS subminimum route or a genuine venue experiment. Unsupported PAS residual exceptions remain unimplemented; current native/exit minimum guards can keep all current BTC/EWY entries blocked. Venue evidence and any resulting reviewed narrow adapter/release remain necessary before that route can be used.

## Engineering delivered

- Reproduced and repaired cross-market readiness composition: BTC native/residual evidence cannot qualify an EWY signal. Signal and capacity ages are checked independently; invalid/nonfinite capacity and corrupt cached funding clocks block safely.
- Added `--authorized --wait-for-readiness` for an already genuinely accepted finite PAS mandate. The same pure acceptance validator serves waiting and runtime. Source, original acceptance, release/XML, organizer/discovery and raw native receipt hashes remain bound. The wait is consumed atomically once across state directories; no restart, renewal or acceptance creation exists.
- Waiting has no signer. It stops its public collector, requires healthy persistence and actual terminal flat reconciliation, then calls the existing runtime builder once. Final fresh account/agent/configuration/source/native/nonce/clock/rate/liquidity/risk checks remain mandatory. A stale observed setup never becomes a forced order.
- `AUTO_TRADING_ACTIVE` requires an owned transmitted order and matching actual account fill during the finite session. Merely running a scanner is insufficient. Failed startup/wait now saves a terminal result with unknown residual truth instead of leaving only a running-looking status.
- Frozen strategy, 1x policy, 0.5% protective allowance, one global position, entry universe BTC/EWY, loss/action budgets, original UNKNOWN/nonces and consumed attempt remain unchanged. No fee/profit filter was relaxed.

## Original UNKNOWN: targeted forensic outcome

**UNKNOWN_REMAINS_EXTERNALLY_BLOCKED**. Original CLOID `0xac0eea156fcec80986dd67c9057b6ded`, nonce `1792217834069`. Fresh own historicalOrders returns four records, none identifying this CLOID; two direct orderStatus reads return unknownOid, with current PAR flat/no orders. Complete manifest identity and the original 2,726-test receipt/XML match. 267 original source files were recovered byte-for-byte, including SDK/native transport, authorization and nonce code; three other original content versions are unavailable locally. No complete content reconstruction is claimed.

The recovered guarded SDK signs expiresAfter equal to the original bounded approval expiry and disables raw SDK POST. The original wire payload/explicit causal failure was not retained. The documented two-day nonce horizon has now elapsed. These facts constrain future replay risk; they do not prove nontransmission, a past terminal outcome or complete historical accounting. The original durable nonce, signer-store binding, controls/checkpoints, old certificate identity and consumed terminal attempt were inspected without changes. PAR and PAS retain the same account/signer/nonce/position-safety domains. Distinct collateral and asset IDs do not establish isolation. An independently reviewed finite isolation procedure could be a separate path without asserting nontransmission, but no validated/accepted shared-domain policy exists. No generic certificate or blanket UNKNOWN bypass was added. See targeted_forensic.json and public_audit/.

## Protective execution decision

Retain the existing independent mark-trigger reduce-only fixed-size Stop Limit and exact-position reduce-only IOC cleanup guards. The full natural-trigger-to-linked-SELL-fill experiment is an internal unattended-release criterion in `long_session.require_native_evidence`, not an organizer rule found in the published guide. It cannot usefully be removed merely to activate sooner: genuine PAS armed/triggered/fill evidence and minimum residual semantics are still absent.

[Official TP/SL documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl) describes mark triggers, fixed-size orders, parent-partial cancellation behavior and a 10% market-TP/SL tolerance. A Stop Market replacement would materially change the present allowance and contract; it needs independent risk review, route evidence and explicit authorization. An application watcher or immediate IOC is not exchange-resident outage protection. [Official error documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses) documents the ordinary $10 minimum; no reviewed PAS residual exemption has been established.

Separate unsigned BTC/EWY supervised-test proposals were refreshed without requiring production native qualification first. They bound one entry, <=25 TEST USDP, six signed actions, five-minute authority, a 120-second trigger observation with cleanup reserve, one owned cancellation round and at most two resolved cleanup IOC attempts. They remain blocked by unsupported minimum-lot cleanup, funding/configuration/history/organizer/approval conditions. Their observed prices are stale review evidence, not current approved order limits. No PAS qualification execution command is claimed; the PAR command is not a substitute.

## Account, market and advance approval

Configured team `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C`, API `0x46c9BED595770150752E7fA3806449F81E0Ec6f9`. Observed Unified USDP balance: **0**, age at report 11881 ms. Organizer credit amount/provenance remains UNKNOWN. BTC/EWY are still actually 20x CROSS; configuration was not submitted. An older screenshot wallet differs; the prior ambiguous local-record acknowledgment did not resolve organizer registration.

| Market | Fresh probe contiguous bars | Latest completed in probe | Current cache age ms | Current leverage | Authorized capacity |
|---|---:|---:|---:|---|---:|
| pas:BTC | 959 | 1792395300000 | 3812617 | {'type': 'cross', 'value': 20} | 0 |
| pas:EWY | 4053 | 1792396860000 | 2252617 | {'type': 'cross', 'value': 20} | 0 |

Both genuine probe histories now satisfy warmup. Freshness remains independent and is shown by the live controller/cache timestamp. The bounded stream review acknowledged eight subscriptions, received real book/context updates and no current candle update. No candles were synthesized or imported from PAR/mainnet. Book-only capacity is not funded/authorized capacity; expected net profit remains UNKNOWN without a current eligible setup. Actual PAS fills/fees/funding are reported separately in release_summary.json. Historical October 15 PAR net +0.050512 TEST USDPR is not today's PAS return or an official score.

The existing mandate protocol cannot legitimately preapprove this missing-evidence environment: it requires funded fresh source-bound discovery, reviewed organizer provenance, actual native proof and a created/starts/approval/expiry ordering inside the scored phase. The five-minute genuine acceptance window and finite-session limits were preserved. No future-effective substitute or dummy acceptance was generated. A later valid accepted session needs no individual BUY/SELL prompts; the new wait can dispatch once only within that exact accepted scope after readiness and final checks pass.

[Published scored interval](https://perpetual-alpha26.github.io/schedule): October 19 12:00 UTC /17:30 IST to November 6 12:00 UTC /17:30 IST. The old October 17–18 special practice permission gate is not applied to open scored trading. Calendar opening does not establish funding, registration or signing authority.

## Shortest remaining path

- Original organizer wallet binding and applicable PAS scored account/credit evidence; ambiguous local records are insufficient.
- Genuine USDP funding: current observed balance 0; practice USDPR is separate.
- Separate exact 1x CROSS configuration approval and authoritative BTC/EWY readbacks; current selected markets are 20x CROSS.
- Original terminal/rejection evidence OR an independently validated, separately accepted finite shared-domain isolation policy. Neither exists.
- Genuine PAS native protection and safe minimum-lot residual semantics/qualification. No PAS subminimum dispatch or PAR-proof substitution is admitted.
- Fresh authentic completed-bar history and eligible frozen LONG with current finite two-sided liquidity/fees/funding/account risk checks.
- Official scored window open, source-matched release and a genuinely accepted exact finite session; no current session acceptance exists.

**Next concrete action:** obtain an attributable organizer response to [EXTERNAL_EVIDENCE_REQUEST.txt](EXTERNAL_EVIDENCE_REQUEST.txt), which specifies the exact wallet, original action and native/residual records. No changed message has been sent. Then refresh the separately approved configuration and qualification reviews; implement only an admissible route-specific exception if the evidence requires one, with another matched regression. Only after those conditions can the operator create and accept a fresh finite scored mandate using OPERATOR_RUNBOOK.md. No blocked/stale proposal is being submitted for approval.

Public observer PID 71218, caffeinate 71219, session ef5c66c9f26149349e0dd74a6a3b60a7. It detects funding and updates readiness automatically without a signer. Both original trading heartbeats remain PAUSED. The previous observer stopped cleanly with two real flat/zero-order readbacks and healthy SQLite/history. The new observer is independent of Codex/app; it depends on this Mac, Python, power, internet and exchange availability. Source changes stop it. App-based supervision can be interrupted; caffeinate cannot guarantee uptime. No profit, loss cap, ranking or organizer whitelisting is guaranteed.

Validation: full source-matched regression and XML; reproductions.json; focused XML; test_case_manifest.json; preservation_receipt.json; source_manifest.json; targeted_forensic.json; raw public /info receipts; real controller_verification.json; public_observer_verification.json.
