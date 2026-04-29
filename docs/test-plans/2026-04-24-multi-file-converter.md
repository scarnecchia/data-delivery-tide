# Multi-File Converter — Human Test Plan

**Implementation plan:** `docs/implementation-plans/2026-04-24-multi-file-converter/`
**Generated:** 2026-04-25

## Prerequisites

- RHEL target machine (or local dev with `uv`) with Python 3.10+
- `uv pip install -e ".[converter,dev]"` completed
- Registry API running (`uv run registry-api`)
- `uv run pytest tests/converter/test_engine.py -v` all 31 tests passing
- At least one scan root configured with real SAS7BDAT files on a network share

## Phase 1: Multi-File Discovery and Conversion

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Identify a delivery directory containing 3+ `.sas7bdat` files of varying sizes (e.g., 1MB, 50MB, 500MB). Note the file names and their case (some should be `.SAS7BDAT` uppercase). | Files exist on network share at `{scan_root}/{dpid}/packages/{req}/{ver}/{status}/` |
| 1.2 | Run the crawler to register the delivery: observe the delivery appears in `GET /deliveries` with `parquet_converted_at: null` and no `metadata.conversion_error`. | Delivery registered, no conversion fields set yet. |
| 1.3 | Run `uv run registry-convert --limit 1` targeting that delivery. | CLI exits 0. |
| 1.4 | Verify `{source_path}/parquet/` directory was created. | Directory exists on the network share. |
| 1.5 | Verify each SAS file has a corresponding `{stem}.parquet` file inside `parquet/`. Confirm that an uppercase-extension file like `DATA.SAS7BDAT` produced `DATA.parquet`. | One Parquet file per SAS file, stems match, case-insensitive discovery worked. |
| 1.6 | Open each Parquet file with `pyarrow.parquet.read_table()` or `parquet-tools`. Verify row count matches the source SAS file. | Row counts match. Schema looks reasonable. |
| 1.7 | `GET /deliveries/{id}` and verify: `output_path` ends with `/parquet` (directory, not a file), `parquet_converted_at` is an ISO timestamp, `metadata.converted_files` lists all Parquet filenames alphabetically. | Registry state matches on-disk reality. |
| 1.8 | `GET /events?after=0` and find the `conversion.completed` event for this delivery. Verify `file_count`, `total_rows`, `total_bytes` look plausible. | Event payload aggregates are correct. |

## Phase 2: Partial Failure

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Create a delivery directory with 3 SAS files. Corrupt one by truncating it to 100 bytes (`head -c 100 good.sas7bdat > bad.sas7bdat`). | One file is unreadable, two are valid. |
| 2.2 | Register via crawler, then run `uv run registry-convert --limit 1`. | CLI exits 0. |
| 2.3 | Verify 2 Parquet files exist in `parquet/` and the corrupted file has no corresponding Parquet. | Partial conversion succeeded. |
| 2.4 | `GET /deliveries/{id}`: verify `parquet_converted_at` is set, `output_path` is the directory, `metadata.converted_files` lists the 2 good files, and `metadata.conversion_errors` has a key for the bad file with `class` and `message` fields. | Registry reflects partial success correctly. |
| 2.5 | Verify the `conversion.completed` event has `file_count: 2`, `failed_count: 1`, and `total_rows` matching the 2 good files. | Event aggregates account for the failure. |

## Phase 3: Total Failure and Skip Guard

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | Create a delivery directory where every SAS file is corrupted (truncated / zeroed out). Register via crawler. | Delivery exists, no conversion error yet. |
| 3.2 | Run `uv run registry-convert --limit 1`. | CLI exits 0, logs show failure. |
| 3.3 | `GET /deliveries/{id}`: verify `parquet_converted_at` is null, `metadata.conversion_error.class == "multi_file_failure"`, and `metadata.conversion_errors` has entries for each corrupted file. | Total failure recorded correctly. |
| 3.4 | Verify a `conversion.failed` event was emitted. | Event exists with `error_class: "multi_file_failure"`. |
| 3.5 | Run `uv run registry-convert --limit 1` again (same delivery). Verify it is **skipped** (no re-conversion attempt, "skipped errored delivery" in logs). | Skip guard blocks re-processing. |
| 3.6 | Run `uv run registry-convert --limit 1 --include-failed`. Verify the delivery is retried (conversion_error cleared, conversion attempted again). | `--include-failed` bypasses the skip guard. |

## Phase 4: Skip Guards (Already Converted, Excluded dp_id)

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | Take a delivery that was successfully converted in Phase 1. Run `uv run registry-convert` again. | Skipped with reason "already_converted". No new PATCH, no new event, no new Parquet files written. |
| 4.2 | Configure `dp_id_exclusions` in `pipeline/config.json` to include a specific dp_id. Register a delivery under that dp_id. Run `uv run registry-convert`. | Skipped with reason "excluded_dp_id". |

## Phase 5: Empty Directory / No SAS Files

| Step | Action | Expected |
|------|--------|----------|
| 5.1 | Register a delivery whose `source_path` directory exists but contains no `.sas7bdat` files (only `.lst`, `.pdf`, etc.). Run `uv run registry-convert --limit 1`. | Skipped with reason "no_sas_file". No PATCH sent, no event emitted. |
| 5.2 | Check converter logs for this delivery. | No `dir_contents` field appears in any log record (diagnostic logging removed). |

## Phase 6: Daemon Mode

| Step | Action | Expected |
|------|--------|----------|
| 6.1 | Start the converter daemon: `uv run registry-convert-daemon`. Verify it connects to WebSocket and prints startup log. | Daemon running, WebSocket connected. |
| 6.2 | Crawl a new delivery with SAS files. Wait ~5 seconds. | Daemon picks up the `delivery.created` event and converts the delivery. |
| 6.3 | Verify Parquet files appear at `{source_path}/parquet/`, registry updated, `conversion.completed` event emitted. | Real-time conversion pipeline works end-to-end. |
| 6.4 | Send `SIGTERM` to the daemon process. | Daemon shuts down cleanly, state file written. |
| 6.5 | Restart daemon. Verify it resumes from the last sequence number (no reprocessing). | State file resume works. |

## End-to-End: Crawl-to-Parquet Pipeline

1. Place a new delivery directory on the network share containing 3 SAS7BDAT files (one with an uppercase `.SAS7BDAT` extension) plus 2 non-SAS files (`.lst`, `.pdf`).
2. Run the crawler. Verify the delivery appears in `GET /deliveries` with correct `source_path`, `dp_id`, `lexicon_id`, and `status`.
3. Run `uv run registry-convert --limit 1`.
4. Verify:
   - `{source_path}/parquet/` exists with exactly 3 Parquet files (one per SAS file).
   - Non-SAS files were not touched.
   - `GET /deliveries/{id}` shows `output_path` as the directory, `parquet_converted_at` set, `metadata.converted_files` has 3 entries.
   - `GET /events?after=0` has `conversion.completed` event with `file_count: 3`, `total_rows` matching sum of all 3 files, `failed_count: 0`.
5. Run `uv run registry-convert` again. Verify the delivery is skipped ("already_converted").

## End-to-End: Large File Performance

1. Identify a delivery with a SAS file > 1GB (or the largest available).
2. Run `uv run registry-convert --limit 1` with `time` prefix to measure wall-clock duration.
3. Monitor RSS memory during conversion (e.g., `ps -o rss= -p $(pgrep -f registry-convert)`).
4. Verify conversion completes without OOM. Parquet file is valid and row count matches.
5. Note wall-clock time and peak memory for operational baseline.

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| AC1.1 — sorted, case-insensitive discovery | `TestHelpers::test_find_sas_files_multiple_files_sorted`, `test_find_sas_files_mixed_case_extension` | 1.5 |
| AC1.2 — non-SAS excluded | `TestHelpers::test_find_sas_files_excludes_non_sas` | E2E step 4 |
| AC1.3 — empty list | `TestHelpers::test_find_sas_files_empty_directory`, `test_find_sas_files_only_non_sas_files` | 5.1 |
| AC2.1 — per-file output | `TestConvertOneHappyPath::test_multiple_files_all_succeed`, `TestConvertOneIntegration` | 1.4, 1.5 |
| AC2.2 — convert_fn per file | `TestConvertOneHappyPath::test_multiple_files_all_succeed` | 1.5 |
| AC2.3 — interrupt propagation | `TestConvertOneInterrupt::test_keyboard_interrupt_*`, `test_system_exit_*` | N/A |
| AC3.1 — partial success | `TestConvertOnePartialSuccess` | 2.3, 2.4 |
| AC3.2 — per-file errors | `TestConvertOnePartialSuccess` | 2.4 |
| AC3.3 — converted_files | `TestConvertOnePartialSuccess` | 2.4 |
| AC3.4 — event aggregates | `TestConvertOnePartialSuccess`, `TestConvertOneIntegration` | 1.8, 2.5 |
| AC4.1 — total failure class | `TestConvertOneTotalFailure::test_all_files_fail` | 3.3 |
| AC4.2 — individual errors on total failure | `TestConvertOneTotalFailure::test_all_files_fail` | 3.3 |
| AC4.3 — conversion.failed event | `TestConvertOneTotalFailure::test_all_files_fail` | 3.4 |
| AC4.4 — skip guard on error | `TestConvertOneTotalFailure::test_skip_guard_blocks_errored_delivery` | 3.5 |
| AC5.1 — no SAS files skipped | `TestConvertOneEmptyDir::test_no_sas_files_skips_with_no_side_effects` | 5.1 |
| AC5.2 — no side effects for empty | `TestConvertOneEmptyDir::test_no_sas_files_skips_with_no_side_effects` | 5.1 |
| AC6.1 — flag-only skip guard | `TestConvertOneSkipGuards::test_skip_when_already_converted_flag_set` | 4.1 |
| AC6.2 — excluded dp_id guard | `TestConvertOneSkipGuards::test_skip_when_dp_id_excluded`, `test_skip_when_conversion_error_set` | 4.2 |
| AC7.1 — output_path is directory | `TestConvertOneHappyPath::test_multiple_files_all_succeed` | 1.7 |
| AC7.2 — _build_parquet_dir | `TestHelpers::test_build_parquet_dir_*` | N/A |
| AC8.1 — per-file logging | `TestConvertOneLogging::test_per_file_success_logging` | N/A |
| AC8.2 — summary logging | `TestConvertOneLogging::test_summary_delivery_logging` | N/A |
| AC9.1 — dir_contents removed | `TestConvertOneEmptyDir::test_no_diagnostic_dir_contents_logged` | 5.2 |
