# PAS funding is visible — live trading is still NO-GO

The supplied public wallet now has **100,000 USDP**. That resolves the previously missing-balance observation, not trading readiness. Both PAS markets currently report **20× CROSS**, not the approved **1×**, and the genuine completed-candle gates still fail. No live process was activated, no account settings were changed, and no exchange action was signed or submitted.

## What the fresh account reads show

Unsigned Hyperliquid Testnet `/info` requests completed at **12:05:20–12:05:57 UTC on 19 October**. The [timestamped public receipts](pas_funding_readiness_2026-10-19.json) retain requests, responses and receipt times. The large `perpDexs` and `spotMeta` responses are explicitly excerpted; their original response bundle is retained locally with its SHA-256 recorded in the committed evidence. These are observations, not an account-ownership or organizer-registration certificate.

| Account observation | User-supplied address `0x94EA16ecE139e246A1D84E71aaCF7dD1F47CB12C` | Older artifact address `0xe590711084f687d278516f4882c075a862cd73cb` |
|---|---|---|
| USDP, token **3307** | **100,000.0** total; 0 held; **100,000.0** available after maintenance | **100,000.0** total; 0 held; **100,000.0** available after maintenance |
| Separate legacy USDPR, token **3032** | 1,000,000.050512 | 999,999.985251 |
| Account mode | `unifiedAccount` | `unifiedAccount` |
| PAS margin used / positions / open orders | 0 / 0 / 0 | 0 / 0 / 0 |
| PAS `activeAssetData.availableToTrade` | 100,000 in each direction for BTC and EWY | 100,000 in each direction for BTC and EWY |
| PAS BTC / EWY leverage | **20× CROSS / 20× CROSS** | **20× CROSS / 20× CROSS** |
| Returned historical executions | 2 `par:BTC` fills; no PAS fills in the returned history | 2 `par:BTC` fills; no PAS fills in the returned history |
| Returned funding-rate events | 12 historical PAR events | 3 historical PAR events |

The per-DEX clearinghouse summaries report zero account value, raw USD and withdrawable amount for these flat unified accounts. That does **not** negate the spot/unified USDP balance: the [official API documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/spot) names `spotClearinghouseState` as the unified-account balance source of truth. Offline replay of the supplied wallet's actual response schema through `HyperliquidAccount.get_equity()` returns 100,000 USDP equity/collateral and zero used margin; its `withdrawable` field deliberately remains unknown instead of inventing free margin.

The supplied wallet's public agent list contains `anchorium-bot-1`, address `0x46c9bed595770150752e7fa3806449f81e0ec6f9`, with an unexpired reported approval. The older wallet lists a different agent. No private key was loaded or matched to either public agent. **Both wallets being funded cannot establish which wallet is registered for this team.** The original team-address distinction and all historical PAR evidence remain intact. `userFunding` rows are funding-rate payments, not proof of the initial collateral-credit source or organizer eligibility.

## Genuine candles still block startup

The [fresh capped candle diagnostic](pas_funding_candles_2026-10-19.json) used the existing shared **300 requested candle slots per rolling minute** limit, recalculating the second asset's window after its budget wait. It did not synthesize, forward-fill, use PAR/native markets, or lower the history/freshness requirement.

| Market | Requested completed UTC window | Genuine completed bars | Newest observed close | Result |
|---|---|---:|---|---|
| `pas:BTC` | 07:04 through 12:03 starts | **299 / 300** | **12:03 UTC** (12:02 candle start) | 12:03-start bar missing; at the common end-of-run clock the close was **171,806 ms** old, over the 120,000 ms gate |
| `pas:EWY` | 07:05 through 12:04 starts | **56 / 300** | **08:01 UTC** (08:00 candle start) | **244 missing**; close **14,691,806 ms** old |

These are counts from the requested recent five-hour windows, not all available historical bars. A new observation may change them. Even a future five-hour pass would not certify the scanner's complete UTC-anchor input or a connected/recovered stream; those stricter existing requirements remain unchanged. Older diagnostic files were not overwritten.

## Books, collateral and caps are present, not certified for trading

Runtime metadata identifies PAS at DEX index **271**, collateral token **3307 = USDP**, and both canonical active markets. BTC size precision is 5 decimals and EWY is 3; neither is borrowed from PAR. Current published/API caps agree at $10 million for each market and $50 million DEX-wide. Oracle-derived OI at the metadata observation was $185,048.977800 BTC, $13,985.136 EWY and $937,981.183598 across the DEX. This is a point-in-time calculation, not a pending-order-inclusive permission.

Fresh two-sided books at approximately 12:05:55–12:05:57 UTC showed BTC **82,280 / 82,315** (about **4.25 bps** spread) and EWY **158.41 / 158.51** (about **6.31 bps**). Minimum best-level notional was $493.6800 BTC and $498.9915 EWY. Both observed spreads were below the unchanged 15 bps ceiling; that does not certify executable size, continuing liquidity, slippage, or a current signal. The unchanged scanner still ranks eligible BTC/EWY candidates using its existing liquidity/volatility/spread factors and selects at most one global position.

## Safe code fixes on PR #2

Work is confined to the existing draft branch `fix/pas-btc-ewy-review-2`, starting from **`f9364de3e536ac47f3e0581b719913694e7e10a8`**, whose recorded main base is `e1f8a53`. No merge, deployment, order or account-administration action is part of this update.

1. **Market-wide entry readiness and launcher leverage gate.** Shared unsigned checks require the correct user and coin and strictly integer **1× CROSS** settings on both runtime-mapped PAS assets. Missing, malformed, isolated, mismatched or unavailable settings fail closed. The launcher's required read-only checks now include this result. The central per-order context provider already calls account readiness on its normal path, and the order validator already rejects wrong requested-market entry leverage; this fix extends readiness to the whole two-market universe rather than claiming that the old validator allowed 20× entries. Existing critical reduce-only/cancel recovery semantics are preserved, with all original identity, approval, reconciliation and exact-action checks still required. This exception is not a new execution permission.
2. **Exact selected-profile certification.** A future certification must include `profile_sha256` equal to the SHA-256 of the exact selected profile bytes. Changing to another profile cannot silently reuse a certificate. Missing hashes invalidate old evidence; no replacement or successful certificate was manufactured.
3. **Unreviewed runtime-source rejection.** Certification rejects tracked modifications and untracked files reported by Git under runtime source, scripts, configs, deployment and `libquant_engine`. A clean commit identifier alone is not accepted as evidence that these paths match the release. This is a startup gate, not a substitute for immutable deployment or final human approval.
4. **Preserved risk-policy bounds.** Alternative profiles cannot raise order-error/reconnect breaker thresholds above the current **3/5**, reduce the **2×** maintenance buffer, or shorten the existing **one-hour** funding-risk horizon. Default profile values were not changed. Existing 1× leverage, one global position, 0.25% risk fraction, 0.5% daily-loss ceiling, 25% exposure/margin ceilings, 3% drawdown ceiling, 15 bps spread and strict OI headroom remain intact.

Offline/no-sign regression coverage was added to the existing safety workflow. The frozen strategy, ranking weights, signal geometry, strategy manifest, historical practice fills and production policy defaults are unchanged. The 300-slot read budget and genuine-candle warmup implementation were inspected; no new candle defect justified changing them.

## Validation and unresolved work

The [validation record](pas_funding_readiness_2026-10-19_validation.json) contains the final focused counts, exact broad-suite baseline comparison, source/evidence hashes and remaining gates. The starting focused suite passed **182 tests**. The final focused suite, including malformed leverage, preserved critical recovery, profile binding, source cleanliness and launcher integration, passed **213 tests**. Nine integration cases call the actual `main`, `read_only_preflight`, profile loader and certification verifier, substituting only unsigned in-memory public responses, clocks and Git boundaries: wrong leverage on each asset stops before certification; both-asset 1× preflight reaches tracked/untracked source rejection and exact selected-profile rejection; a clean offline certificate still stops at the unchanged disabled-protection gate before any runtime/signer is built; weakened profiles stop before public reads. These fixtures are explicitly synthetic offline tests, never substituted for the real missing market candles. The two wrong-leverage regressions fail against the original starting implementation and pass with the fix. Strategy freeze verification remains green: **1 file, 8 methods, 32 parameters**. No signed fixture or live-order test is represented as account certification.

The broader suite is still red; its legacy/discovery/activation/history failures are not erased, ignored as harmless, or made green by loosening production venue/approval barriers. The same selected modules and 34 existing exclusions are compared against the immutable starting head. The new standalone leverage and actual-launcher integration modules are covered separately in the focused workflow. The broad starting result was **1,302 passed / 91 failed / 233 errors**; the stable final result is **1,312 passed / 91 failed / 233 errors**, with **zero new or resolved failed/error node IDs**. Excluded manual, signing-oriented, long-running or incompatible modules are not claimed as tested.

**Priority gates before any future GO:**

1. Confirm the organizer-registered team wallet and its intended, locally owned signer, resolving the different historical address. Public balances and agent records do not complete that step.
2. Obtain separate authorization for any required account configuration; verify both markets at 1× CROSS afterward. **No settings were changed here.**
3. Obtain real complete/fresh PAS history, full UTC scanner input, executable depth and connected/reconnected feed evidence for both markets. Do not fabricate missing bars or substitute another market.
4. Resolve the remaining relevant red-suite failures without weakening PAS-only routing, approvals or UNKNOWN/history barriers; perform authoritative persistent account/order/fill/funding reconciliation.
5. Separately authorize and complete both-market controlled lifecycle, actual fill/partial-fill, protection/exit, restart and supervisor certification on the exact release/profile. Protection remains disabled pending that certification.
6. Obtain final explicit activation approval naming the exact release, registered team wallet/signer, risk limits and controlled activation/rollback steps. Only the separately approved account owner may then start one live process.

**Final decision: NO-GO.** Funding arrival alone is not readiness. Section 14 of the supplied directive is truncated; no missing scoring instructions were inferred.
