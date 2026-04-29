# SAS-to-Parquet Converter — Test Requirements

Maps every acceptance criterion from `docs/design-plans/2026-04-16-sas-to-parquet-converter.md` to an automated test (with type + file anchor) or a documented human verification step. All file paths are anchored in the worktree root `/Users/scarndp/dev/Sentinel/qa_registry/.worktrees/sas-to-parquet-converter/`.

Anchor format: `tests/path/file.py::TestClass::test_method`. Absolute paths are given where the file sits outside the conventional `tests/` tree.

---

## AC1: Conversion core produces valid Parquet

### sas-to-parquet-converter.AC1.1
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_roundtrip_row_count_matches`
- **What it verifies**: `convert_sas_to_parquet` produces a Parquet file readable by `pq.read_table` with the same row count as the source SAS file.

### sas-to-parquet-converter.AC1.2
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_uses_zstd_by_default`
- **What it verifies**: Output Parquet applies zstd compression by default.
- **Notes**: Uses 1000-row fixture; pyarrow may skip compression on tiny row groups, so the test needs enough varied rows for the codec to actually apply.

### sas-to-parquet-converter.AC1.3
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_embeds_all_four_file_metadata_keys`
- **What it verifies**: SAS column labels are embedded under `sas_labels` as JSON bytes readable via `pq.read_metadata(path).metadata[b'sas_labels']`.

### sas-to-parquet-converter.AC1.4
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_embeds_all_four_file_metadata_keys`
- **What it verifies**: `sas_value_labels`, `sas_encoding`, and `converter_version` keys are all present in Parquet file-level metadata.
- **Notes**: Same test as AC1.3; one test covers all four embedded keys.

### sas-to-parquet-converter.AC1.5
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_one_row_group_per_chunk`
- **What it verifies**: Streaming write produces one Parquet row group per chunk (25 rows / chunk_size=10 → 3 row groups).

### sas-to-parquet-converter.AC1.6
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_no_column_labels_yields_empty_dict`
- **What it verifies**: SAS file with no column labels produces Parquet with an empty `sas_labels` dict (key present, not missing).
- **Notes**: Also covered at the helper level by `TestBuildColumnLabels::test_none_labels_returns_empty_dict`.

---

## AC2: Atomic writes and cleanup

### sas-to-parquet-converter.AC2.1
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertAtomicWrite::test_final_path_only_exists_on_success`
- **What it verifies**: Writer uses a `{stem}.parquet.tmp-{uuid}` tmp file then `os.replace`; no tmp file remains after successful write.

### sas-to-parquet-converter.AC2.2
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertAtomicWrite::test_exception_during_write_cleans_up_tmp`
- **What it verifies**: Exception raised mid-stream (via injected `chunk_iter_factory`) unlinks the tmp file before re-raising.

### sas-to-parquet-converter.AC2.3
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertAtomicWrite::test_source_missing_leaves_no_tmp_file`
- **What it verifies**: Exception raised before the writer opens (e.g., `FileNotFoundError` from pyreadstat) leaves no tmp file behind.

### sas-to-parquet-converter.AC2.4
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_output_path_constructed_as_expected`
- **What it verifies**: Final Parquet path is exactly `{source_path}/parquet/{stem}.parquet`.
- **Notes**: Engine-level output-path derivation additionally covered by `tests/converter/test_engine.py::TestConvertOneHappyPath::test_build_output_path_parent_delivery`.

### sas-to-parquet-converter.AC2.5
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath::test_output_path_constructed_as_expected`
- **What it verifies**: Parent `parquet/` directory is created if missing (asserts `not out.parent.exists()` before, exists after).

---

## AC3: Schema drift detection

### sas-to-parquet-converter.AC3.1
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSchemaStability::test_multiple_chunks_same_schema_succeeds`
- **What it verifies**: Chunks 2..N that match the locked chunk-1 schema write successfully (250 rows / chunk_size=100 → 3 row groups written).

### sas-to-parquet-converter.AC3.2
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSchemaDrift::test_dtype_drift_raises_schema_drift_error`
- **What it verifies**: A chunk with a dtype-mismatched column (int → str) raises `SchemaDriftError` before writing.
- **Notes**: Structural drift (missing column) additionally covered by `test_column_missing_raises_schema_drift_error`. Uses the `chunk_iter_factory` test seam to force deterministic drift.

### sas-to-parquet-converter.AC3.3
- **Test type**: unit
- **Test file**: `tests/converter/test_convert.py::TestConvertSchemaDrift::test_schema_drift_cleans_up_tmp`
- **What it verifies**: `SchemaDriftError` propagates with the tmp file unlinked and no final Parquet written.

---

## AC4: Exception classification

### sas-to-parquet-converter.AC4.1–AC4.9
- **Test type**: unit
- **Test file**: `tests/converter/test_classify.py::TestClassifyException::test_known_exception_classes`
- **What it verifies**: Each exception type maps to its designated `ErrorClass`. The parametrised table covers all nine cases:
  - AC4.1 `FileNotFoundError` → `source_missing`
  - AC4.2 `PermissionError` → `source_permission`
  - AC4.3 `OSError` → `source_io`
  - AC4.4 `pyreadstat.ReadstatError` → `parse_error`
  - AC4.5 `UnicodeDecodeError` → `encoding_mismatch`
  - AC4.6 `SchemaDriftError` → `schema_drift`
  - AC4.7 `MemoryError` → `oom`
  - AC4.8 `pyarrow.ArrowException` (both `ArrowTypeError` and `ArrowInvalid`) → `arrow_error`
  - AC4.9 `ValueError`/`RuntimeError` (fallthrough) → `unknown`
- **Notes**: Narrower-before-broader ordering explicitly guarded by `test_filenotfound_preferred_over_oserror` and `test_permission_preferred_over_oserror`. Subclass matching verified by `test_subclasses_match_parent_class`.

---

## AC5: Engine orchestration and skip guards

### sas-to-parquet-converter.AC5.1
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneHappyPath::test_success_patches_and_emits`
- **What it verifies**: Eligible delivery converts, engine PATCHes `output_path` + `parquet_converted_at`, emits `conversion.completed`.
- **Notes**: Integration confidence also provided by `tests/converter/test_engine.py::TestConvertOneIntegration::test_real_sas_real_parquet_stubbed_http`, which exercises the real conversion core against a real SAS fixture.

### sas-to-parquet-converter.AC5.2
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneSkipGuards::test_skip_when_already_converted_and_file_exists`
- **What it verifies**: Delivery with non-null `parquet_converted_at` AND existing file is skipped — no conversion, no PATCH, no event.
- **Notes**: Edge case "flag set but file missing → re-convert" covered by `test_reconvert_when_file_deleted_despite_flag`.

### sas-to-parquet-converter.AC5.3
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneSkipGuards::test_skip_when_conversion_error_set`
- **What it verifies**: Delivery with `metadata.conversion_error` set is skipped — no work, no events.
- **Notes**: `conversion_error: null` semantic verified by `test_null_conversion_error_does_not_skip` (AC7.3 interaction).

### sas-to-parquet-converter.AC5.4
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneFailure::test_parse_error_patches_and_emits_failed`
- **What it verifies**: Classified exception results in PATCH of `metadata.conversion_error = {class, message, at, converter_version}` plus `conversion.failed` event emission.
- **Notes**: Each error class route through the engine covered by parametrised `test_each_exception_classifies_on_failure_path`. Message length cap covered by `test_error_message_truncated_to_500_chars`.

### sas-to-parquet-converter.AC5.5
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneFailure::test_no_retry_after_failure`
- **What it verifies**: `convert_fn` is invoked exactly once per engine call — no automatic retry on classified failure.

### sas-to-parquet-converter.AC5.6
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneLogging::test_success_emits_structured_log` and `::test_failure_emits_structured_log`
- **What it verifies**: A structured log line with `outcome` field is emitted via `JsonFormatter` on both success and failure paths, carrying `delivery_id`, `source_path`, and (on failure) `error_class` / `error_message`.

---

## AC6: Events schema migration

### sas-to-parquet-converter.AC6.1
- **Test type**: unit
- **Test file**: `tests/registry_api/test_db.py::TestMigrateEventsCheckConstraint` (four cases)
- **What it verifies**: Events table CHECK constraint accepts `conversion.completed` and `conversion.failed` on fresh DBs; old-schema DBs migrate without losing existing rows; migration is idempotent; non-whitelisted event types still rejected with `sqlite3.IntegrityError`.
- **Notes**: Pydantic-side literal guard tested by `tests/registry_api/test_models.py::TestEventRecord` for the new literal values and rejection of `nonsense`.

### sas-to-parquet-converter.AC6.2
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneHappyPath::test_success_patches_and_emits`
- **What it verifies**: `conversion.completed` payload contains exactly `{delivery_id, output_path, row_count, bytes_written, wrote_at}`.
- **Notes**: Phase 1 Task 5 `TestEmitEvent` tests that `POST /events` accepts the shape; the engine-side assertion above confirms the payload the engine actually produces.

### sas-to-parquet-converter.AC6.3
- **Test type**: unit
- **Test file**: `tests/converter/test_engine.py::TestConvertOneFailure::test_parse_error_patches_and_emits_failed`
- **What it verifies**: `conversion.failed` payload contains exactly `{delivery_id, error_class, error_message, at}`.

### sas-to-parquet-converter.AC6.4
- **Test type**: integration
- **Test file**: `tests/registry_api/test_routes.py::TestEmitEvent` (multiple cases, including the WebSocket broadcast test using `TestClient.websocket_connect("/ws/events")`)
- **What it verifies**: `POST /events` persists via `insert_event` and broadcasts via the existing `ConnectionManager` to connected WebSocket clients.
- **Notes**: `EventCreate` model validation tested in isolation at `tests/registry_api/test_models.py::TestEventCreate`.

---

## AC7: Registry query surface

### sas-to-parquet-converter.AC7.1
- **Test type**: integration
- **Test file**: `tests/registry_api/test_db.py::TestListDeliveriesPagination` (plus route-level assertions in `tests/registry_api/test_routes.py::TestListDeliveries`)
- **What it verifies**: `GET /deliveries?converted=false&limit=N&after=delivery_id` returns only rows with null `parquet_converted_at`, sorted ascending by `delivery_id`, strictly greater than the cursor, capped at `limit` (further capped at 1000 server-side).

### sas-to-parquet-converter.AC7.2
- **Test type**: integration
- **Test file**: `tests/registry_api/test_routes.py::TestUpdateDelivery` / `TestPatchMetadataMerge` (happy-path case writing `conversion_error` while preserving `qa_passed_at` + `other`)
- **What it verifies**: PATCH with `metadata.conversion_error` shallow-merges into existing metadata without clobbering other top-level keys.
- **Notes**: Combined-status-plus-metadata interaction covered by the status-plus-metadata test in the same class.

### sas-to-parquet-converter.AC7.3
- **Test type**: integration
- **Test file**: `tests/registry_api/test_routes.py::TestPatchMetadataMerge` (clear case — PATCH `{"metadata": {"conversion_error": null}}`)
- **What it verifies**: PATCH with `conversion_error: null` sets the key to `None` while preserving the rest of the metadata dict.
- **Notes**: Skip-guard interaction at the engine layer verified by `tests/converter/test_engine.py::TestConvertOneSkipGuards::test_null_conversion_error_does_not_skip`.

---

## AC8: Backfill CLI

### sas-to-parquet-converter.AC8.1
- **Test type**: unit
- **Test file**: `tests/converter/test_cli.py::TestRunMainLoop::test_empty_backlog_exits_zero`
- **What it verifies**: `registry-convert` with empty backlog exits 0 immediately; `convert_one_fn` never invoked.

### sas-to-parquet-converter.AC8.2
- **Test type**: unit
- **Test file**: `tests/converter/test_cli.py::TestRunMainLoop::test_processes_all_deliveries`
- **What it verifies**: CLI pages through all unconverted deliveries and invokes the engine for each before exiting 0.
- **Notes**: Paging correctness verified separately by `TestIterUnconverted::test_pages_multiple_times` and `test_stops_on_empty_page`.

### sas-to-parquet-converter.AC8.3
- **Test type**: unit
- **Test file**: `tests/converter/test_cli.py::TestRunMainLoop::test_limit_caps_processing`
- **What it verifies**: `--limit M` caps total processing at M deliveries regardless of backlog size.

### sas-to-parquet-converter.AC8.4
- **Test type**: unit
- **Test file**: `tests/converter/test_cli.py::TestRunMainLoop::test_shard_filter_skips_out_of_shard`
- **What it verifies**: `--shard I/N` only processes deliveries whose `int(delivery_id[:8], 16) % N == I`.
- **Notes**: Shard helper purity and distribution covered independently by `TestParseShard` and `TestInShard`.

### sas-to-parquet-converter.AC8.5
- **Test type**: unit
- **Test file**: `tests/converter/test_cli.py::TestRunMainLoop::test_include_failed_clears_conversion_error_first` (and negative case `test_without_include_failed_skips_errored`)
- **What it verifies**: `--include-failed` issues a PATCH clearing `metadata.conversion_error` before invoking the engine; without the flag, no clearing PATCH is issued and the engine's skip guard filters the row.

### sas-to-parquet-converter.AC8.6
- **Test type**: unit
- **Test file**: `tests/converter/test_cli.py::TestRegistryUnreachable::test_exits_nonzero_on_unreachable`
- **What it verifies**: `RegistryUnreachableError` from the HTTP client results in exit code 1 and no `convert_one_fn` invocation (no partial work).
- **Notes**: HTTP client retry/exhaustion behaviour covered by `tests/converter/test_http.py::TestRetryBehaviour::test_all_attempts_exhausted_raises_unreachable`.

---

## AC9: Event-driven daemon

### sas-to-parquet-converter.AC9.1
- **Test type**: unit
- **Test file**: `tests/converter/test_daemon.py::TestLoadLastSeq` (multiple cases: missing file → 0, valid file, malformed JSON, missing key, non-numeric value, float coerced to int)
- **What it verifies**: Daemon reads `last_seq` from `converter_state_path` on startup, defaulting to 0 when the file is missing or corrupt.
- **Notes**: End-to-end resume-from-seq covered by `TestDaemonRunnerResume::test_resumes_from_persisted_seq`.

### sas-to-parquet-converter.AC9.2
- **Test type**: unit
- **Test file**: `tests/events/test_consumer.py` (EventConsumer reference client)
- **What it verifies**: Catch-up via `GET /events?after={last_seq}` drains before WebSocket opens.
- **Notes**: The daemon wraps `EventConsumer` and sets `consumer._last_seq` before `consumer.run()`; the catch-up loop lives inside EventConsumer and is tested in its own suite. The daemon's delegation is further guarded by `tests/converter/test_daemon.py::TestDaemonRunnerReconnect::test_reconnect_is_delegated_to_event_consumer` (identity assertion on the injected factory).

### sas-to-parquet-converter.AC9.3
- **Test type**: unit
- **Test file**: `tests/converter/test_daemon.py::TestPersistLastSeq` (all cases) plus `TestDaemonRunnerCallback::test_delivery_created_dispatches_engine` and `::test_non_delivery_created_events_skipped_but_seq_advanced`
- **What it verifies**: `persist_last_seq` writes atomically via tmp-file + fsync + `os.replace`; `_on_event` persists after every processed event, so `load_last_seq` after `run_async` reflects the last event's seq.

### sas-to-parquet-converter.AC9.4
- **Test type**: unit
- **Test file**: `tests/converter/test_daemon.py::TestDaemonRunnerCallback::test_non_delivery_created_events_skipped_but_seq_advanced`
- **What it verifies**: `delivery.status_changed` and `conversion.*` events advance `last_seq` but do not dispatch to the engine; only `delivery.created` triggers `convert_one`.

### sas-to-parquet-converter.AC9.5
- **Test type**: unit (delegated)
- **Test file**: Covered by `EventConsumer` tests in `tests/events/test_consumer.py`
- **What it verifies**: WebSocket disconnect triggers reconnect with exponential backoff.
- **Notes**: The daemon delegates reconnect semantics to `pipeline.events.consumer.EventConsumer`'s `async for websocket in connect(ws_url)` loop. Daemon-side delegation guarded by `tests/converter/test_daemon.py::TestDaemonRunnerReconnect::test_reconnect_is_delegated_to_event_consumer` (asserts the default consumer factory is `EventConsumer`). No new daemon-level reconnect test is needed.

### sas-to-parquet-converter.AC9.6
- **Test type**: unit + human (split coverage)
- **Test file (unit)**: `tests/converter/test_daemon.py::TestDaemonRunnerCancellation::test_cancelled_error_persists_seq_before_reraise`
- **What the unit test verifies**: When `CancelledError` fires mid-`asyncio.to_thread`, `_on_event`'s `except asyncio.CancelledError` branch persists `last_seq` before re-raising. This is the load-bearing correctness invariant — the in-flight thread runs to completion, state is written, and cancellation propagates cleanly.
- **Human follow-up**: Full SIGTERM/SIGINT signal-delivery path (process-level) covered by the Phase 6 manual smoke test in the completion checklist. An operator sends `SIGTERM` to a running daemon, observes that the in-flight conversion completes, that `pipeline/.converter_state.json` reflects the last persisted seq, and that the process exits with code 0.
- **Justification (for the human piece)**: Real signal delivery inside pytest is platform-specific and flaky (Windows has no `add_signal_handler`; POSIX signal timing interacts poorly with pytest's own signal handlers). Wiring `loop.add_signal_handler` is a stdlib concern; the load-bearing application logic (CancelledError → persist → re-raise) is unit-tested directly. A process-level smoke test supplies the remaining confidence at negligible cost.

### sas-to-parquet-converter.AC9.7
- **Test type**: unit
- **Test file**: `tests/converter/test_daemon.py::TestDaemonRunnerResume::test_resumes_from_persisted_seq`
- **What it verifies**: Daemon started with a pre-existing state file containing `last_seq=5` resumes dispatch from seq 6 — older events (seq 3, 5) filtered by the consumer's dedup; only `new1`/`new2` reach the engine.

---

## AC10: End-to-end integration

### sas-to-parquet-converter.AC10.1
- **Test type**: integration (e2e at code scope; not subprocess)
- **Test file**: `tests/test_end_to_end_converter.py::TestEndToEndConverter::test_crawler_to_converter_full_chain`
- **What it verifies**: Crawler → registry (TestClient) → `engine.convert_one` → PATCH updates `parquet_converted_at` + `output_path` → Parquet file exists at the expected path; `conversion.completed` persisted in the events table.
- **Notes**: The daemon subprocess is intentionally NOT spawned — the integration test proves the contract alignment across components via synchronous function calls through TestClient. Daemon behaviour (catch-up, signal handling, WebSocket) is validated in the Phase 5 unit suite and the Phase 6 manual smoke.

### sas-to-parquet-converter.AC10.2
- **Test type**: integration
- **Test file**: `tests/test_end_to_end_converter.py::TestEndToEndConverter::test_crawler_to_converter_full_chain`
- **What it verifies**: Same test asserts both parent and sub-delivery (`scdm_snapshot`) Parquet files exist at `{source_path}/parquet/{stem}.parquet` with correct row counts.
- **Notes**: Engine-level output-path derivation for sub-deliveries additionally covered by `tests/converter/test_engine.py::TestConvertOneHappyPath::test_build_output_path_sub_delivery`.

### sas-to-parquet-converter.AC10.3
- **Test type**: human (documented by CI)
- **Test file**: Verified by full test suite passing in CI (`uv run pytest` green with all new tests).
- **What it verifies**: `uv run pytest` passes with every converter and registry-surface test added across Phases 1–6 — no new failures, no skipped converter tests.
- **Justification**: This AC is a meta-criterion covering the entire suite's health. There is no specific test to write; it's satisfied when CI is green. The phase completion checklists (Phase 1–6) each require `uv run pytest` to pass, and a reviewer confirms this before merge.

---

## Summary

- **Unit tests**: AC1.1–1.6, AC2.1–2.5, AC3.1–3.3, AC4.1–4.9, AC5.1–5.6, AC6.2–6.3, AC8.1–8.6, AC9.1, AC9.3–9.7 (unit portion)
- **Integration tests**: AC6.1, AC6.4, AC7.1–7.3, AC10.1–10.2
- **Delegated to existing suite**: AC9.2 and AC9.5 (EventConsumer reference client, `tests/events/test_consumer.py`)
- **Human verification**: AC9.6 (process-level SIGTERM smoke, split from its unit-test counterpart), AC10.3 (CI green gate)

No AC is uncovered. Every AC either has a deterministic automated test with a precise file anchor above, is delegated to an existing suite with rationale, or has a documented manual verification step with an explicit justification for the automation gap.
