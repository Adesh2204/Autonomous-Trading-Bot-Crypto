# Full-day watcher — running verified

Exact mandate `fbad5fe98614a88acfdd3ac079e2644f46371265cf6600a2b04f604a63deb1a5` was genuinely approved and recorded at 12:48:52 IST, 15 October 2026. The existing watcher was launched once and its process and live output were verified at 12:52:30 IST, 15 October 2026. No expired mandate was reused and no trading code was changed.

- Worker PID: **70469**. Process-bound idle-sleep prevention PID: **70470**, attached to the worker.
- Output/state directory: `/Users/adesh/Autonomous Trading Bot - Crypto /docs/profit_day_2026-10-15/authorized_session`.
- Authorization: **ACTIVE**, bounded to TESTNET `par:BTC`, one closing path and one possible exact-position reduce-only SELL IOC of 0.0002 BTC.
- Closing-path/signing cutoff: **23:57 IST today**. Absolute expiry: **23:59 IST, 15 October 2026**. No auto-restart, renewal, BUY, enlargement, second SELL or loss fallback.
- Initial approved profit floor: **81,811 USDPR/BTC**; current logged floor **81811**. The session floor can rise but cannot be lowered.
- Latest actual observation: **12:52:30 IST, 15 October 2026**, bid/ask **80958.0 / 80976.0**; candidate **False**.
- Latest verified remaining quantity: **0.0002 BTC LONG**. No flat-account or realized-round-trip-profit claim is made.
- Feed evidence: `WS_ACKNOWLEDGED_REPEATED`; connected True; confirmed subscriptions 1; duplicate subscriptions 0; actual distinct-timestamp BTC updates 40; recorded socket errors 0. The raw transport diagnostic retains its own state label; active channel evidence is not a blanket feed certification.
- Local exclusive signer lease healthy: **True**. Sole ownership on other machines relies on the user's explicit attestation.
- Signed API actions since acceptance: **0**. A profitable SELL has not been claimed. Original BUY proofs remain unchanged.

The read-only follow-up is active every five minutes. It inspects this existing process and may report meaningful improvement, execution outcome, failure, required operator action or completion. It cannot sign, restart, retry or renew the session and must stop when this bounded run ends.

No verified protective stop exists. The position remains exposed until genuine exchange closure is proved. The deadline does not cap market losses. Keep this Mac powered and connected and the app running for follow-up supervision; process-bound idle-sleep prevention cannot prevent power loss, lid/forced sleep or an app/host failure. See [official scheduled-task requirements](https://learn.chatgpt.com/docs/automations?surface=app).

The full 2,363-test source-bound receipt remains valid; frozen strategy and global PAPER/false locks are unchanged. Actual SELL fill IDs, fees, funding, final position/orders and net P&L will be reported only from real exchange records. Partial/rejected/uncertain execution ends automatic orders and requires separate recovery.
