# Multi-File Converter Design

## Summary

Rework the converter engine to handle deliveries containing multiple SAS7BDAT files. The current engine assumes one SAS file per delivery directory and fails when it finds zero or more than one. Real deliveries contain dozens to hundreds of SAS files. The fix: loop over all SAS files in the directory, convert each to its own Parquet file in a shared `parquet/` subdirectory, and support partial success so one bad file doesn't brick the whole delivery.

## Definition of Done

The converter engine processes all SAS files in a delivery directory, producing one Parquet file per SAS file in a shared `parquet/` subdirectory. Partial success is supported: if some files fail, the rest are still converted. The delivery is marked converted unless *all* files fail. Per-file errors are recorded in `metadata.conversion_errors` (dict keyed by filename). `output_path` becomes the `parquet/` directory path. A new `metadata.converted_files` list tracks which Parquet files were produced. Event payloads carry aggregate stats (file count, total rows, total bytes, failure count). Non-SAS files are ignored silently. The core `convert_sas_to_parquet` function is unchanged — only the engine orchestration layer changes.

**Out of scope:** daemon re-trigger on re-crawl, retry of per-file failures, changes to the registry API schema or DB columns.

## Acceptance Criteria

### multi-file-converter.AC1: Multi-file discovery

- **multi-file-converter.AC1.1**: `_find_sas_files(source_path)` returns a sorted list of all `.sas7bdat` files (case-insensitive) in the delivery directory.
- **multi-file-converter.AC1.2**: Non-SAS files (`.lst`, `.pdf`, `.md`, etc.) are excluded from the list.
- **multi-file-converter.AC1.3**: Returns an empty list when the directory contains no SAS files.

### multi-file-converter.AC2: Per-file conversion

- **multi-file-converter.AC2.1**: Each SAS file produces `{source_path}/parquet/{file_stem}.parquet` (not `{dir_name}.parquet`).
- **multi-file-converter.AC2.2**: `convert_sas_to_parquet` is called unchanged for each file — atomic write, schema locking, tmp-then-rename all preserved.
- **multi-file-converter.AC2.3**: `KeyboardInterrupt` / `SystemExit` during any file conversion propagates immediately (operator intent).

### multi-file-converter.AC3: Partial success

- **multi-file-converter.AC3.1**: If at least one file succeeds, the delivery is marked as converted (`parquet_converted_at` set, `output_path` set to the `parquet/` directory).
- **multi-file-converter.AC3.2**: Per-file errors are recorded in `metadata.conversion_errors` (dict keyed by filename, value is `{class, message, at, converter_version}`).
- **multi-file-converter.AC3.3**: Successfully converted filenames are recorded in `metadata.converted_files` (list of Parquet filenames).
- **multi-file-converter.AC3.4**: `conversion.completed` event is emitted with aggregate stats: `file_count`, `total_rows`, `total_bytes`, `failed_count`.

### multi-file-converter.AC4: Total failure

- **multi-file-converter.AC4.1**: If all files fail, delivery gets `metadata.conversion_error` (singular) with `class: "multi_file_failure"` and a summary message.
- **multi-file-converter.AC4.2**: Individual file errors are still recorded in `metadata.conversion_errors` (plural).
- **multi-file-converter.AC4.3**: `conversion.failed` event is emitted.
- **multi-file-converter.AC4.4**: The existing skip guard (`metadata.get("conversion_error")`) blocks re-processing on subsequent runs.

### multi-file-converter.AC5: Empty directory handling

- **multi-file-converter.AC5.1**: If `_find_sas_files` returns an empty list, `convert_one` returns `skipped` with `reason="no_sas_file"`.
- **multi-file-converter.AC5.2**: No PATCH, no event emission, no metadata changes for empty directories.

### multi-file-converter.AC6: Skip guard changes

- **multi-file-converter.AC6.1**: "Already converted" skip guard trusts `parquet_converted_at` flag only — no file/directory existence check.
- **multi-file-converter.AC6.2**: All other skip guards (excluded dp_id, conversion_error) unchanged.

### multi-file-converter.AC7: Output path contract

- **multi-file-converter.AC7.1**: `output_path` stored in the registry is the `parquet/` directory path (string), not a single file.
- **multi-file-converter.AC7.2**: `_build_output_path` is replaced or updated to return the directory.

### multi-file-converter.AC8: Logging

- **multi-file-converter.AC8.1**: Per-file success/failure is logged with `delivery_id`, `source_path`, `filename`, and outcome.
- **multi-file-converter.AC8.2**: Delivery-level summary is logged with aggregate counts.

### multi-file-converter.AC9: Diagnostic removal

- **multi-file-converter.AC9.1**: The temporary `dir_contents` diagnostic logging added during debugging is removed.

## Architecture

### Approach: Loop in `convert_one`

The change is concentrated in `engine.py`. Replace `_find_sas_file` (singular) with `_find_sas_files` (plural, returns sorted list). `convert_one` iterates over all files, calls the unchanged `convert_sas_to_parquet` for each, collects results, and issues a single PATCH + event.

Callers (CLI `_run`, daemon `_on_event`) are unchanged — they still call `convert_one(delivery_id, ...)` and get back a `ConversionResult`.

### Data flow

```
convert_one(delivery_id)
  │
  ├─ GET delivery from registry
  ├─ skip guards (unchanged)
  ├─ _find_sas_files(source_path) → list[Path]
  │   └─ empty? → return skipped
  │
  ├─ for each sas_file:
  │   ├─ output = parquet_dir / {stem}.parquet
  │   ├─ try: convert_sas_to_parquet(sas_file, output, ...)
  │   │   └─ success → append to successes
  │   └─ except: classify → append to failures
  │
  ├─ if no successes:
  │   ├─ PATCH metadata.conversion_error (singular) + metadata.conversion_errors (plural)
  │   ├─ emit conversion.failed
  │   └─ return failure
  │
  └─ else (at least one success):
      ├─ PATCH output_path, parquet_converted_at, metadata.converted_files, metadata.conversion_errors
      ├─ emit conversion.completed (aggregates)
      └─ return success
```

### Metadata shapes

**Partial success PATCH:**
```json
{
  "output_path": "/path/to/source/parquet",
  "parquet_converted_at": "2026-04-24T...",
  "metadata": {
    "converted_files": ["dem_l3_racedist.parquet", "enc_l3_stats_y.parquet"],
    "conversion_errors": {
      "bad_file.sas7bdat": {
        "class": "parse_error",
        "message": "truncated at offset 0x...",
        "at": "2026-04-24T...",
        "converter_version": "0.1.0"
      }
    }
  }
}
```

**Total failure PATCH:**
```json
{
  "metadata": {
    "conversion_error": {
      "class": "multi_file_failure",
      "message": "all 3 files failed conversion",
      "at": "2026-04-24T...",
      "converter_version": "0.1.0"
    },
    "conversion_errors": {
      "file1.sas7bdat": {"class": "parse_error", "...": "..."},
      "file2.sas7bdat": {"class": "source_io", "...": "..."},
      "file3.sas7bdat": {"class": "unknown", "...": "..."}
    }
  }
}
```

**conversion.completed event payload:**
```json
{
  "delivery_id": "abc123...",
  "output_path": "/path/to/source/parquet",
  "file_count": 168,
  "total_rows": 50432,
  "total_bytes": 12345678,
  "failed_count": 2,
  "wrote_at": "2026-04-24T..."
}
```

### Existing patterns followed

- Functional Core / Imperative Shell: `_find_sas_files` is pure; `convert_one` is the shell.
- Error classification reuses `classify_exception` from `classify.py`.
- Atomic writes per file via `convert_sas_to_parquet` (unchanged).
- `KeyboardInterrupt`/`SystemExit` propagation matches existing `_handle_failure` pattern.
- Test injection via `convert_fn` parameter preserved.

## Implementation Phases

### Phase 1: Engine rework

**Files:** `src/pipeline/converter/engine.py`, `tests/converter/test_engine.py`

1. Replace `_find_sas_file` with `_find_sas_files` (returns sorted `list[Path]`).
2. Replace `_build_output_path` with `_build_parquet_dir` (returns `source_path / "parquet"`).
3. Rewrite `convert_one` body: iterate files, collect successes/failures, single PATCH + event.
4. Remove `dir_contents` diagnostic logging.
5. Simplify "already converted" skip guard to trust `parquet_converted_at` only.
6. Update all engine tests: multi-file happy path, partial success, total failure, empty dir, skip guards.

### Phase 2: Cleanup and documentation

**Files:** `src/pipeline/converter/CLAUDE.md`, `docs/design-plans/2026-04-24-multi-file-converter.md`

1. Update converter CLAUDE.md contracts and invariants.
2. Finalize design doc.

## Additional Considerations

- **168 files serially**: at ~0.1s per small SAS file, a large delivery takes ~17 seconds. Acceptable for the daemon (offloaded to thread) and CLI (serial by design). Parallelism is a future optimization, not in scope.
- **Metadata blob size**: the registry has a 64KB limit on metadata JSON. 168 filenames in `converted_files` plus a few error dicts is well under that. If deliveries grow to thousands of files, this would need revisiting.
- **Existing errored deliveries**: deliveries stamped with `conversion_error` from the old single-file code need `--include-failed` to clear and retry. This is operational, not a code change.

## Glossary

| Term | Definition |
|------|-----------|
| delivery | A registered directory on the network share, identified by SHA-256 of its `source_path` |
| SAS file | A `.sas7bdat` file produced by SAS software |
| parquet dir | `{source_path}/parquet/` — the shared output directory for all converted files in a delivery |
| partial success | A delivery where some but not all SAS files converted successfully |
| conversion_error (singular) | Metadata key checked by the skip guard — set only on total failure |
| conversion_errors (plural) | Metadata key containing per-file error details — informational, not checked by skip guard |
| converted_files | Metadata key listing Parquet filenames that were successfully produced |
