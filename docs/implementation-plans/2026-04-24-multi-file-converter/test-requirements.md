# Test Requirements: Multi-File Converter

## Automated Tests

| AC | Criterion | Test Type | Expected Test Location | Phase |
|----|-----------|-----------|------------------------|-------|
| multi-file-converter.AC1.1 | `_find_sas_files` returns sorted list of all `.sas7bdat` files (case-insensitive) | unit | tests/converter/test_engine.py::TestHelpers::test_find_sas_files_sorted_case_insensitive | 1 |
| multi-file-converter.AC1.2 | Non-SAS files excluded from discovery list | unit | tests/converter/test_engine.py::TestHelpers::test_find_sas_files_excludes_non_sas | 1 |
| multi-file-converter.AC1.3 | Empty list when directory has no SAS files | unit | tests/converter/test_engine.py::TestHelpers::test_find_sas_files_empty_dir | 1 |
| multi-file-converter.AC2.1 | Each SAS file produces `{source_path}/parquet/{file_stem}.parquet` | unit | tests/converter/test_engine.py::TestConvertOneHappyPath::test_output_named_per_file_stem | 1 |
| multi-file-converter.AC2.2 | `convert_sas_to_parquet` called unchanged per file (atomic write, schema locking preserved) | unit | tests/converter/test_engine.py::TestConvertOneHappyPath::test_convert_fn_called_per_file | 1 |
| multi-file-converter.AC2.3 | `KeyboardInterrupt` / `SystemExit` propagates immediately | unit | tests/converter/test_engine.py::TestConvertOneInterrupt::test_keyboard_interrupt_propagates | 1 |
| multi-file-converter.AC2.3 | `SystemExit` propagates immediately | unit | tests/converter/test_engine.py::TestConvertOneInterrupt::test_system_exit_propagates | 1 |
| multi-file-converter.AC3.1 | Partial success: delivery marked converted (`parquet_converted_at` set, `output_path` = `parquet/` dir) | unit | tests/converter/test_engine.py::TestConvertOnePartialSuccess::test_partial_marks_converted | 1 |
| multi-file-converter.AC3.2 | Per-file errors in `metadata.conversion_errors` (dict keyed by filename) | unit | tests/converter/test_engine.py::TestConvertOnePartialSuccess::test_partial_records_per_file_errors | 1 |
| multi-file-converter.AC3.3 | Successful filenames in `metadata.converted_files` (list of Parquet filenames) | unit | tests/converter/test_engine.py::TestConvertOnePartialSuccess::test_partial_records_converted_files | 1 |
| multi-file-converter.AC3.4 | `conversion.completed` event with `file_count`, `total_rows`, `total_bytes`, `failed_count` | unit | tests/converter/test_engine.py::TestConvertOnePartialSuccess::test_partial_event_payload_aggregates | 1 |
| multi-file-converter.AC4.1 | Total failure: `metadata.conversion_error` (singular) with `class: "multi_file_failure"` | unit | tests/converter/test_engine.py::TestConvertOneTotalFailure::test_total_failure_sets_conversion_error | 1 |
| multi-file-converter.AC4.2 | Individual file errors in `metadata.conversion_errors` (plural) on total failure | unit | tests/converter/test_engine.py::TestConvertOneTotalFailure::test_total_failure_records_per_file_errors | 1 |
| multi-file-converter.AC4.3 | `conversion.failed` event emitted on total failure | unit | tests/converter/test_engine.py::TestConvertOneTotalFailure::test_total_failure_emits_failed_event | 1 |
| multi-file-converter.AC4.4 | Skip guard blocks re-processing when `metadata.conversion_error` is set | unit | tests/converter/test_engine.py::TestConvertOneSkipGuards::test_skip_guard_conversion_error | 1 |
| multi-file-converter.AC5.1 | No SAS files: returns `skipped` with `reason="no_sas_file"` | unit | tests/converter/test_engine.py::TestConvertOneEmptyDir::test_no_sas_files_returns_skipped | 1 |
| multi-file-converter.AC5.2 | No PATCH, no event emission for empty directories | unit | tests/converter/test_engine.py::TestConvertOneEmptyDir::test_no_sas_files_no_side_effects | 1 |
| multi-file-converter.AC6.1 | "Already converted" guard trusts `parquet_converted_at` only (no file existence check) | unit | tests/converter/test_engine.py::TestConvertOneSkipGuards::test_skip_guard_trusts_flag_only | 1 |
| multi-file-converter.AC6.2 | Excluded dp_id and conversion_error skip guards unchanged | unit | tests/converter/test_engine.py::TestConvertOneSkipGuards::test_skip_guard_excluded_dp_id | 1 |
| multi-file-converter.AC7.1 | `output_path` stored in registry is the `parquet/` directory path (not a single file) | unit | tests/converter/test_engine.py::TestConvertOneHappyPath::test_output_path_is_directory | 1 |
| multi-file-converter.AC7.2 | `_build_parquet_dir` returns `Path("{source_path}/parquet")` | unit | tests/converter/test_engine.py::TestHelpers::test_build_parquet_dir | 1 |
| multi-file-converter.AC8.1 | Per-file log records with `delivery_id`, `source_path`, `filename`, outcome | unit | tests/converter/test_engine.py::TestConvertOneLogging::test_per_file_log_fields | 1 |
| multi-file-converter.AC8.2 | Delivery-level summary log with aggregate counts | unit | tests/converter/test_engine.py::TestConvertOneLogging::test_summary_log_fields | 1 |
| multi-file-converter.AC9.1 | `dir_contents` diagnostic logging removed (not present in skip log) | unit | tests/converter/test_engine.py::TestConvertOneEmptyDir::test_no_dir_contents_in_log | 1 |
| multi-file-converter.AC2.1 | (integration) Multiple SAS files produce correct Parquet files under `parquet/` | integration | tests/converter/test_engine.py::TestConvertOneIntegration::test_multi_file_real_conversion | 1 |
| multi-file-converter.AC3.1 | (integration) PATCH payload has `output_path` as directory, `metadata.converted_files` | integration | tests/converter/test_engine.py::TestConvertOneIntegration::test_multi_file_real_conversion | 1 |
| multi-file-converter.AC3.4 | (integration) Event payload has correct `file_count`, `total_rows`, `total_bytes` | integration | tests/converter/test_engine.py::TestConvertOneIntegration::test_multi_file_real_conversion | 1 |

## Human Verification

| AC | Criterion | Justification | Verification Approach |
|----|-----------|---------------|----------------------|

No human verification rows. Every AC (AC1 through AC9, all sub-items) maps to automated tests. Phase 2 defines no acceptance criteria (documentation only) and therefore has no test requirements.
