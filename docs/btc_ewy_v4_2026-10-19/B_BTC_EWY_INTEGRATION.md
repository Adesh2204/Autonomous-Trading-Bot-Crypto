# B — Actual PAS lifecycle integration

Source `56ee079f7b8403811674d429aff3b9143a1810290bdd9a23f319b7cedd47170c`. Runtime BTC/EWY IDs are verified from PAS metadata, never substituted by constants. All account positions and orders remain visible, including out-of-scope markets.

| Stage | Code | Behaviour/evidence |
|---|---|---|
| Candidate universe/ranking | `market_regime_scanner.MarketRegimeScanner.scan` | Filters permitted candidates before unchanged Top-3 selection; 300 bars/UTC brain and thresholds preserved |
| Subscriptions/history | `entry_scope.signal_markets; terminal_observer.observe; ParMarketDataEngine` | PAS signal subscriptions/history limited to BTC/EWY; metadata/cache identity and account truth still cover ten markets |
| Capital/risk | `long_session.AllocatedLongRisk.assess; DailyLongExecution._prepare_context_request` | BTC/EWY entry validation, 1x, both-side participation/depth, source/economics/risk and residual minimum guards |
| Normalization/central guard | `exchange_rules.HyperliquidOrderValidator.validate` | Actual runtime PAS asset/size/price metadata; no PAR/native fallback; rejects other PAS entries |
| Exact contract | `scored_session.ScoredLimits; long_session.LongAuthorization.check_action` | Finite LONG-only BTC/EWY subset; hashes, sole host, original genuine acceptance, expiry and durable per-action consumption |
| Final signed action | `sdk_transport.OfficialSDKTransport.check; entry_scope.require_entry_action` | Every actual new order/modify entry resolves its runtime asset and fails unless PAS BTC/EWY; independent reduce-only management is retained |
| SDK transport | `long_session.LongSDKTransport; sdk_transport.build_exchange` | Official 0.24.0 SDK, TESTNET, account_address team, approved API signer, exact ActionPermit, expiry, nonce and no HTTP retries |
| Acknowledgement/fills/protection/exit | `hyperliquid_execution; position_protection; DailyLongSession; long_session.require_native_evidence` | Intent before wire, real status/fills, trigger-child linkage, partial/uncertain handling and independent minimum protection gates |
| Reconciliation/accounting | `hyperliquid_account; hyperliquid_reconciliation; terminal_evidence.SessionPerformance` | All PAS markets remain visible, shared PAR UNKNOWN/nonce barrier retained, actual fill/fee/funding accounting and two terminal flat readbacks |
| Watchdog/terminal | `terminal_app; trading_status; hyperliquid_client.read_cancellation` | No restored signing, source/expiry/stop guards, truthful active/paused/expired status; thread-local repair cancellation and stable reconnect burst reset |

The baseline consumer audit also reproduced and repaired PAS scanner environment rejection, PAR-only safety reads, incorrect export venue labels and invalid PAS opportunity traces. integration_defects_and_repairs.json records before/after evidence. The full source-matched regression includes actual SDK construction with ephemeral offline wallets, both market input parity, wrong-market/venue/wallet/signer/asset, stale/insufficient data, OI/liquidity/capital, approval/source/expiry, duplicate/unknown, partial fills, rejected and triggered-unfilled stops, disconnect/restart/nonce, risk exhaustion and accounting tests. Routine lifecycle tests run under captured stdin, without per-trade approval prompts. Offline fills are synthetic and certify no venue outcome.

Known boundary: PAS subminimum qualification dispatch remains unavailable until admissible route semantics and independent narrow approval are established. The ordinary minimum and no-new-entry-until-protected guards remain enforced.
