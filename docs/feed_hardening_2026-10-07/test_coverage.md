# Feed hardening test coverage

These are offline fixtures, not funded execution certification. The retained `regression_initial.xml` records the first full run's one failed fake-engine interface test. The fixture was corrected rather than adding a permissive production fallback. `regression.xml` and `test_receipt.json` record the final complete run and source hash.

| Requirement | Evidence |
|---|---|
| Receiver responsive while REST repair blocks | `test_feed_hardening.py::test_receiver_stays_responsive_during_slow_rest_repair` |
| Quiet market with healthy transport | `test_quiet_market_does_not_kill_transport_with_pongs` |
| Pong deadline remains enforced despite other traffic | `test_missing_pong_is_not_hidden_by_book_messages` |
| Host/client processing pause distinguished | `test_host_pause_has_distinct_attribution`; updated legacy receive-stall test |
| Single reconnect owner | `test_single_reconnect_owner` |
| Bounded jittered backoff | `test_backoff_is_bounded_and_jittered` |
| Canonical subscriptions reset without growth | `test_subscription_set_is_reset_and_idempotent`; existing `test_ws_duplicate_reconnect_cleanup_and_aggregate_budget` |
| Close-frame code/reason retained | `test_close_frame_retains_server_code_and_reason` |
| Old socket generation cannot mutate state | `test_old_generation_callbacks_cannot_mutate_current_book` |
| REST retry failure does not restart healthy socket | `test_rest_retry_exhaustion_does_not_reconnect_a_healthy_socket` |
| Duplicate concurrent reads coalesced | `test_identical_inflight_public_reads_are_coalesced` |
| Candle response weight cannot spend safety reserve | `test_candle_response_weight_cannot_spend_safety_reserve`; existing `test_unknown_and_stale_budget_restrict_optional` and safety-budget tests |
| Recovery reads cancel without upstream submission | `test_cancelled_recovery_read_never_contacts_upstream` |
| 300 completed rows retained beside open bar | `test_open_bar_does_not_evict_completed_history` |
| Bounded repair without invented bars | `test_history_repair_is_bounded_and_never_fills_a_missing_bar`; existing raw-staleness/invalid-history tests |
| One stale market does not globally block a healthy one | `test_crypto_recovery_safety.py::test_one_stale_symbol_does_not_block_other_healthy_symbols` |
| Fresh book does not override stale candle/context | Parametrized `test_independent_stale_clock_pauses_only_that_market` |
| Reconnect waits for authoritative account barrier | `test_reconnect_does_not_resume_until_account_callback_passes`; `test_stream_generation_change_during_account_read_cannot_resume` |
| Recovery does not invent fills or strategy state | `test_paper_recovery_cannot_invent_missing_strategy_or_fill_evidence`; actual event reconciliation suite |
| Checkpoint/backup recovery and corruption handling | `test_practice_operations.py`; `test_restart_opportunity_diagnostics.py` |
| Formal feed certificate needs no forced signal or trade | `test_feed_certification_does_not_require_a_trade_or_signal` |
| Missing acks, stale final feed, insufficient windows, unresolved error or real orders fail certification | Parametrized `test_feed_certification_fails_closed_with_exact_blocker` |
| PAPER/default locks and frozen strategy | `scripts/phase0_check.py`, `scripts/check_strategy_freeze.py`, `test_phase0_order_lock.py` |
| Global single-position/signing owner protection retained | `test_single_position_compliance.py`, nonce ownership/reliability suites |

A live socket close can be reproduced safely during PAPER observation. Network/host failures in fixtures establish fail-closed behavior but do not certify a particular real network or prove a baseline drop's cause. The new raw diagnostic fields and bounded soaks supply that missing evidence. Unsafe funded failure scenarios remain explicitly offline-tested.
