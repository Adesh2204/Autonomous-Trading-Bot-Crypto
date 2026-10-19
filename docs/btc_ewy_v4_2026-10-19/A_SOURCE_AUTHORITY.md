# A — Source authority

Baseline: `6d37a929e23e295cd35a4aa137a077b6533b711bf085d292fff8c2103420ca42`, matched to 2,979 tests and original XML before changes. Current V4: `56ee079f7b8403811674d429aff3b9143a1810290bdd9a23f319b7cedd47170c`. Baseline HEAD: `bcc94ff3e3c9ccdc8b516d14930a77b76df2abf3`. The clone was clean before V4 report creation.

Inventory scope: all four available Anchorium/NSE checkouts identified through saved Codex projects and Git worktree registration. Unrelated projects were excluded. All other checkouts were read only; no reset, cleanup, checkout or merge occurred.

| Checkout | HEAD | Branch | Source SHA-256 |
|---|---|---|---|
| /Users/adesh/Autonomous Trading Bot - Crypto  | bcc94ff3e3c9ccdc8b516d14930a77b76df2abf3 | codex/par-native-qualification-2026-10-18 | 6d37a929e23e295cd35a4aa137a077b6533b711bf085d292fff8c2103420ca42 |
| /Users/adesh/.local/share/kilo/worktree-pool/autonomous-trading-bot-crypto-07cf180eab19/spurious-rayon | 14dbe1eef80601d660a5ca4ab7ac3389111c0b12 | detached | 5c6c167aa538cb16dc457b0b35311aaba81cf4115b188fe0ef091ed72a336ea6 |
| /Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot/.kilo/worktrees/excited-topaz | f9f1cf4a940293545acc035afca0cf861449556a | detached | 4b8e846c74dc5bfc51c7413d1d498f13c6589a6af66302413540d50a27aa429a |
| /Users/adesh/Desktop/SUPER PROJECTS /Autonomous Trading Bot | 30849008d0a5cfa17f36b505af104f99b6a35cbf | main | 26defd28d7809cf77c2bdcf740cc358895b3104c0efea1bee61d6fcd090801b7 |

The reviewer commit 731ceb86bbaf150e7ad6cd8c4a1a419b47fefab3 predates the verified release. The five compared signed/scored/configuration/observer modules differ by 470 added and 36 removed lines between that commit and the V3 baseline. Scored contracts and exact configuration workflow are present in the current release; old checkout observations do not prove those paths absent. Per-file hashes and exact comparison are in source_authority.json.

All 53 original SQLite dumps remain identical with integrity ok. Original BUY/SELL proofs, source-matched releases, UNKNOWN/nonce and consumed-attempt records are preserved. strategy_freeze.json and signal_brain.py remain byte-identical. The V4 manifest lists every changed Python file and configuration hash.

Official schedule, participant guide, account/client/stream/rate/nonces, monitored behaviour and fairness rules were reviewed and archived with source hashes. The guide has unnumbered headings; its fourteenth main heading is Rate limits. No separate numbered Section 14 addendum was linked by the reviewed official pages. Any private addendum remains unverified without its source. See rules_review.json.
