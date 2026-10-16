# V7 new test evidence

All are **OFFLINE_FIXTURE**. These prove implementation behavior with controlled inputs, not native-feed or funded-account readiness. The full source-bound release suite also reruns existing normalization, merge, full UTC, scanner, rate-budget, quarantine, one-position, PAPER accounting and checkpoint tests.

| Class / file | Passed case |
|---|---|
| algo-trading-bot.test_candle_availability_v7 | test_exact_completed_reception_delay_and_left_censoring[0] |
| algo-trading-bot.test_candle_availability_v7 | test_exact_completed_reception_delay_and_left_censoring[1000] |
| algo-trading-bot.test_candle_availability_v7 | test_exact_completed_reception_delay_and_left_censoring[180000] |
| algo-trading-bot.test_candle_availability_v7 | test_empty_response_later_supplies_missing_genuine_candle |
| algo-trading-bot.test_candle_availability_v7 | test_never_observed_interval_is_censored_not_zero_delay |
| algo-trading-bot.test_candle_availability_v7 | test_unfinished_ws_candle_is_observed_but_not_completed_sample |
| algo-trading-bot.test_candle_availability_v7 | test_rest_ws_duplicates_and_conflicts_keep_source_identity |
| algo-trading-bot.test_candle_availability_v7 | test_equivalent_decimal_encodings_are_duplicates_not_conflicts |
| algo-trading-bot.test_candle_availability_v7 | test_validator_failures_captured_and_not_accepted[ohlc] |
| algo-trading-bot.test_candle_availability_v7 | test_validator_failures_captured_and_not_accepted[volume] |
| algo-trading-bot.test_candle_availability_v7 | test_validator_failures_captured_and_not_accepted[future] |
| algo-trading-bot.test_candle_availability_v7 | test_validator_failures_captured_and_not_accepted[identity] |
| algo-trading-bot.test_candle_availability_v7 | test_cache_300_gate_separate_from_full_utc[299] |
| algo-trading-bot.test_candle_availability_v7 | test_cache_300_gate_separate_from_full_utc[300] |
| algo-trading-bot.test_candle_availability_v7 | test_scanner_history_gap_remains_separate_from_complete_cache |
| algo-trading-bot.test_candle_availability_v7 | test_freshness_allowance_does_not_require_latest_expected_minute |
| algo-trading-bot.test_candle_availability_v7 | test_out_of_order_wire_rows_are_normalized_without_inventing_rows |
| algo-trading-bot.test_candle_availability_v7 | test_rate_deferral_and_insufficient_samples_preserve_backoff |
| algo-trading-bot.test_candle_availability_v7 | test_adaptive_hint_is_bounded_and_requires_twenty_live_intervals |
| algo-trading-bot.test_candle_availability_v7 | test_healthy_symbol_independent_and_genuine_gap_recovery_recorded |
| algo-trading-bot.test_candle_availability_v7 | test_near_ready_prioritization_never_excludes_old_due_symbol |
| algo-trading-bot.test_candle_availability_v7 | test_dashboard_has_exact_candle_reasons_and_independent_transport |
| algo-trading-bot.test_candle_availability_v7 | test_observation_history_is_bounded_and_does_not_become_execution_interface |
| algo-trading-bot.test_candle_availability_v7 | test_recovery_cache_repair_is_distinct_from_first_source_observation |
| algo-trading-bot.test_candle_availability_v7 | test_future_malformed_intervals_cannot_escape_retention_bound |
| algo-trading-bot.test_external_data_v7 | test_disabled_default_and_no_order_interface |
| algo-trading-bot.test_external_data_v7 | test_provenance_boundaries_and_bad_data_fail[fields0] |
| algo-trading-bot.test_external_data_v7 | test_provenance_boundaries_and_bad_data_fail[fields1] |
| algo-trading-bot.test_external_data_v7 | test_provenance_boundaries_and_bad_data_fail[fields2] |
| algo-trading-bot.test_external_data_v7 | test_provenance_boundaries_and_bad_data_fail[fields3] |
| algo-trading-bot.test_external_data_v7 | test_provenance_boundaries_and_bad_data_fail[fields4] |
| algo-trading-bot.test_external_data_v7 | test_provenance_boundaries_and_bad_data_fail[fields5] |
| algo-trading-bot.test_external_data_v7 | test_provenance_boundaries_and_bad_data_fail[fields6] |
| algo-trading-bot.test_external_data_v7 | test_invalid_mapping_or_units_rejected[fields0] |
| algo-trading-bot.test_external_data_v7 | test_invalid_mapping_or_units_rejected[fields1] |
| algo-trading-bot.test_external_data_v7 | test_invalid_mapping_or_units_rejected[fields2] |
| algo-trading-bot.test_external_data_v7 | test_invalid_mapping_or_units_rejected[fields3] |
| algo-trading-bot.test_external_data_v7 | test_invalid_mapping_or_units_rejected[fields4] |
| algo-trading-bot.test_external_data_v7 | test_missing_or_tick_volume_cannot_enter_vwap[fields0] |
| algo-trading-bot.test_external_data_v7 | test_missing_or_tick_volume_cannot_enter_vwap[fields1] |
| algo-trading-bot.test_external_data_v7 | test_wrong_fx_direction_cannot_silently_invert |
| algo-trading-bot.test_external_data_v7 | test_external_record_cannot_overwrite_native_cache_or_account_truth |
| algo-trading-bot.test_external_data_v7 | test_as_of_reception_prevents_future_leakage_and_stale_signal |
| algo-trading-bot.test_external_data_v7 | test_research_outage_does_not_change_native_engine |
| algo-trading-bot.test_external_data_v7 | test_reference_adapter_can_only_read_allowlisted_public_metadata_and_candles |
| algo-trading-bot.test_external_data_v7 | test_production_cannot_enable_external_mode_or_approve_itself |
| algo-trading-bot.test_external_data_v7 | test_no_production_import_of_external_research_module |
| algo-trading-bot.test_external_data_v7 | test_research_features_cannot_shorten_full_utc_contract_to_300_bars |
| algo-trading-bot.test_external_data_v7 | test_native_quote_mark_context_must_also_be_fresh |

Final result: 1405 passed, 0 failed, 0 errors, 0 skipped. Previous baseline: 1356; added: 49. XML digest and matching before/after source hashes are in the release receipt.
