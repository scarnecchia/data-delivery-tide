# Multi-File Converter Implementation Plan

**Goal:** Rework the converter engine to handle deliveries containing multiple SAS7BDAT files, with partial success support.

**Architecture:** Replace the single-file discovery and output path functions with multi-file versions. Rewrite `convert_one` to iterate over all SAS files, collect per-file results, and issue a single PATCH + event. The core `convert_sas_to_parquet` function is unchanged.

**Tech Stack:** Python 3.10+, pyreadstat, pyarrow, pytest

**Scope:** 2 phases from original design (phases 1-2). This is Phase 1: Engine rework.

**Codebase verified:** 2026-04-24

---

## Acceptance Criteria Coverage

This phase implements and tests:

### multi-file-converter.AC1: Multi-file discovery
- **multi-file-converter.AC1.1 Success:** `_find_sas_files(source_path)` returns a sorted list of all `.sas7bdat` files (case-insensitive) in the delivery directory.
- **multi-file-converter.AC1.2 Exclusion:** Non-SAS files (`.lst`, `.pdf`, `.md`, etc.) are excluded from the list.
- **multi-file-converter.AC1.3 Empty:** Returns an empty list when the directory contains no SAS files.

### multi-file-converter.AC2: Per-file conversion
- **multi-file-converter.AC2.1 Output path:** Each SAS file produces `{source_path}/parquet/{file_stem}.parquet` (not `{dir_name}.parquet`).
- **multi-file-converter.AC2.2 Core unchanged:** `convert_sas_to_parquet` is called unchanged for each file -- atomic write, schema locking, tmp-then-rename all preserved.
- **multi-file-converter.AC2.3 Interrupt propagation:** `KeyboardInterrupt` / `SystemExit` during any file conversion propagates immediately (operator intent).

### multi-file-converter.AC3: Partial success
- **multi-file-converter.AC3.1 Partial marking:** If at least one file succeeds, the delivery is marked as converted (`parquet_converted_at` set, `output_path` set to the `parquet/` directory).
- **multi-file-converter.AC3.2 Error recording:** Per-file errors are recorded in `metadata.conversion_errors` (dict keyed by filename, value is `{class, message, at, converter_version}`).
- **multi-file-converter.AC3.3 Success recording:** Successfully converted filenames are recorded in `metadata.converted_files` (list of Parquet filenames).
- **multi-file-converter.AC3.4 Event payload:** `conversion.completed` event is emitted with aggregate stats: `file_count`, `total_rows`, `total_bytes`, `failed_count`.

### multi-file-converter.AC4: Total failure
- **multi-file-converter.AC4.1 Failure marking:** If all files fail, delivery gets `metadata.conversion_error` (singular) with `class: "multi_file_failure"` and a summary message.
- **multi-file-converter.AC4.2 Error details:** Individual file errors are still recorded in `metadata.conversion_errors` (plural).
- **multi-file-converter.AC4.3 Failure event:** `conversion.failed` event is emitted.
- **multi-file-converter.AC4.4 Skip guard:** The existing skip guard (`metadata.get("conversion_error")`) blocks re-processing on subsequent runs.

### multi-file-converter.AC5: Empty directory handling
- **multi-file-converter.AC5.1 Skip:** If `_find_sas_files` returns an empty list, `convert_one` returns `skipped` with `reason="no_sas_file"`.
- **multi-file-converter.AC5.2 No side effects:** No PATCH, no event emission, no metadata changes for empty directories.

### multi-file-converter.AC6: Skip guard changes
- **multi-file-converter.AC6.1 Simplified guard:** "Already converted" skip guard trusts `parquet_converted_at` flag only -- no file/directory existence check.
- **multi-file-converter.AC6.2 Other guards unchanged:** All other skip guards (excluded dp_id, conversion_error) unchanged.

### multi-file-converter.AC7: Output path contract
- **multi-file-converter.AC7.1 Directory path:** `output_path` stored in the registry is the `parquet/` directory path (string), not a single file.
- **multi-file-converter.AC7.2 Builder replaced:** `_build_output_path` is replaced or updated to return the directory.

### multi-file-converter.AC8: Logging
- **multi-file-converter.AC8.1 Per-file logging:** Per-file success/failure is logged with `delivery_id`, `source_path`, `filename`, and outcome.
- **multi-file-converter.AC8.2 Summary logging:** Delivery-level summary is logged with aggregate counts.

### multi-file-converter.AC9: Diagnostic removal
- **multi-file-converter.AC9.1 Remove diagnostic:** The temporary `dir_contents` diagnostic logging added during debugging is removed.

---

## Phase 1: Engine Rework

**Files:**
- Modify: `src/pipeline/converter/engine.py` (265 lines currently)
- Modify: `tests/converter/test_engine.py` (605 lines currently)

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Replace `_find_sas_file` with `_find_sas_files` and `_build_output_path` with `_build_parquet_dir`

**Verifies:** multi-file-converter.AC1.1, multi-file-converter.AC1.2, multi-file-converter.AC1.3, multi-file-converter.AC7.2

**Files:**
- Modify: `src/pipeline/converter/engine.py:21-49` (replace both functions)
- Modify: `tests/converter/test_engine.py:13` (update import)

**Implementation:**

Replace `_build_output_path` (lines 21-31) with `_build_parquet_dir`:

```python
def _build_parquet_dir(source_path: str) -> Path:
    return Path(source_path) / "parquet"
```

Replace `_find_sas_file` (lines 34-49) with `_find_sas_files`:

```python
def _find_sas_files(source_path: Path) -> list[Path]:
    return sorted(
        p for p in source_path.iterdir()
        if p.is_file() and p.suffix.lower() == ".sas7bdat"
    )
```

Update import in `test_engine.py` line 13 to import both new functions:
```python
from pipeline.converter.engine import convert_one, ConversionResult, _build_parquet_dir, _find_sas_files
```

**Testing:**

Tests must verify each AC listed above:
- multi-file-converter.AC1.1: `_find_sas_files` returns sorted list of all `.sas7bdat` files including mixed casing (`.SAS7BDAT`, `.sas7bdat`)
- multi-file-converter.AC1.2: Non-SAS files (`.lst`, `.pdf`) present in directory are excluded from results
- multi-file-converter.AC1.3: Empty directory returns empty list; directory with only non-SAS files returns empty list
- multi-file-converter.AC7.2: `_build_parquet_dir` returns `Path("{source_path}/parquet")` (directory, not file)

These are pure functions tested directly. Add a new test class `TestHelpers` at the top of the test file (before `TestConvertOneHappyPath`). Update existing `test_build_output_path_parent_delivery` and `test_build_output_path_sub_delivery` to test `_build_parquet_dir` instead.

Follow project testing patterns: use `tmp_path` fixture for filesystem tests on `_find_sas_files`, direct assertion for `_build_parquet_dir`.

**Verification:**
Run: `uv run pytest tests/converter/test_engine.py::TestHelpers -v`
Expected: All tests pass

**Commit:** `refactor: replace single-file helpers with multi-file _find_sas_files and _build_parquet_dir`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Rewrite `convert_one` for multi-file iteration

**Verifies:** multi-file-converter.AC2.1, multi-file-converter.AC2.2, multi-file-converter.AC2.3, multi-file-converter.AC3.1, multi-file-converter.AC3.2, multi-file-converter.AC3.3, multi-file-converter.AC3.4, multi-file-converter.AC4.1, multi-file-converter.AC4.2, multi-file-converter.AC4.3, multi-file-converter.AC4.4, multi-file-converter.AC5.1, multi-file-converter.AC5.2, multi-file-converter.AC6.1, multi-file-converter.AC6.2, multi-file-converter.AC7.1, multi-file-converter.AC8.1, multi-file-converter.AC8.2, multi-file-converter.AC9.1

**Files:**
- Modify: `src/pipeline/converter/engine.py:52-264` (rewrite `convert_one` and `_handle_failure`)
- Modify: `tests/converter/test_engine.py` (rewrite test classes)

**Implementation:**

Rewrite `convert_one` (lines 52-198) to:

1. GET delivery, apply skip guards (dp_id exclusion unchanged, conversion_error unchanged).
2. **Simplify "already converted" guard** (AC6.1): remove the `output_path.exists()` check. Trust `parquet_converted_at` alone. The guard at current line 109 becomes:
   ```python
   if delivery.get("parquet_converted_at"):
   ```
   This removes the need to compute `output_path` before the guard, but `_build_parquet_dir` is still needed below for the conversion loop.
3. Call `_find_sas_files(source_path)` instead of `_find_sas_file`.
4. **Empty list handling** (AC5.1, AC5.2): if no SAS files found, log and return `skipped` with `reason="no_sas_file"`. **Remove the `dir_contents` diagnostic** (AC9.1) -- just log delivery_id, source_path, outcome, reason.
5. **File iteration loop** (AC2.1, AC2.2, AC2.3): for each SAS file, compute output as `parquet_dir / f"{sas_file.stem}.parquet"`. Call `convert_fn(sas_file, output, ...)` in a try/except. On `KeyboardInterrupt`/`SystemExit`, propagate immediately. On other exceptions, classify via `classify_exception`, record in failures dict. On success, append to successes list and accumulate row_count/bytes_written. **Log per-file outcome** (AC8.1).
6. **Total failure path** (AC4.1-AC4.4): if no successes, PATCH `metadata.conversion_error` (singular, `class: "multi_file_failure"`, summary message like `"all {n} files failed conversion"`) AND `metadata.conversion_errors` (plural, per-file dict). Emit `conversion.failed` event. Return `ConversionResult(outcome="failure", ...)`.
7. **Success/partial success path** (AC3.1-AC3.4, AC7.1): PATCH `output_path` (the `parquet/` directory as string), `parquet_converted_at`, `metadata.converted_files` (list of Parquet filenames), and if any failures, `metadata.conversion_errors`. Emit `conversion.completed` with `file_count`, `total_rows`, `total_bytes`, `failed_count`. **Log delivery-level summary** (AC8.2). Return `ConversionResult(outcome="success", ...)`.

`_handle_failure` (lines 201-264) can be removed entirely -- its logic is inlined into the per-file loop (KeyboardInterrupt/SystemExit propagation) and the total-failure path (classify, PATCH, emit).

Also update the `ConversionResult.reason` field comment (line 18) to list all valid values:
```python
reason: str | None = None  # "already_converted", "errored", "excluded_dp_id", "no_sas_file", or None
```

The `convert_fn` and `http_module` injection seams remain unchanged.

Here is the complete rewritten `convert_one` and supporting logic:

```python
def convert_one(
    delivery_id: str,
    api_url: str,
    *,
    converter_version: str,
    chunk_size: int,
    compression: str,
    dp_id_exclusions: set[str] | None = None,
    log_dir: str | None = None,
    http_module=converter_http,
    convert_fn=convert_sas_to_parquet,
) -> ConversionResult:
    logger = get_logger("converter", log_dir=log_dir)

    delivery = http_module.get_delivery(api_url, delivery_id)
    source_path_str = delivery["source_path"]

    # Skip guard 0: dp_id is in the exclusion set.
    if dp_id_exclusions and delivery.get("dp_id") in dp_id_exclusions:
        logger.info(
            "skipped excluded dp_id",
            extra={
                "delivery_id": delivery_id,
                "dp_id": delivery.get("dp_id"),
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "excluded_dp_id",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="excluded_dp_id")

    # Skip guard 1: already converted (trust the flag only).
    if delivery.get("parquet_converted_at"):
        logger.info(
            "skipped already converted",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "already_converted",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="already_converted")

    # Skip guard 2: conversion_error present.
    metadata = delivery.get("metadata") or {}
    if metadata.get("conversion_error"):
        logger.info(
            "skipped errored delivery",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "errored",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="errored")

    # Discover SAS files.
    source_path = Path(source_path_str)
    sas_files = _find_sas_files(source_path)

    if not sas_files:
        logger.info(
            "skipped no sas file",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "no_sas_file",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="no_sas_file")

    # Convert each SAS file.
    parquet_dir = _build_parquet_dir(source_path_str)
    successes: list[tuple[str, int, int]] = []  # (parquet_filename, row_count, bytes_written)
    failures: dict[str, dict] = {}  # sas_filename -> error dict
    wrote_at: str | None = None

    for sas_file in sas_files:
        output = parquet_dir / f"{sas_file.stem}.parquet"
        try:
            conv_meta = convert_fn(
                sas_file,
                output,
                chunk_size=chunk_size,
                compression=compression,
                converter_version=converter_version,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            error_class = classify_exception(exc)
            now = datetime.now(timezone.utc).isoformat()
            failures[sas_file.name] = {
                "class": error_class,
                "message": str(exc)[:500],
                "at": now,
                "converter_version": converter_version,
            }
            logger.warning(
                "file conversion failed",
                extra={
                    "delivery_id": delivery_id,
                    "source_path": source_path_str,
                    "filename": sas_file.name,
                    "outcome": "failure",
                    "error_class": error_class,
                },
            )
            continue

        successes.append((f"{sas_file.stem}.parquet", conv_meta.row_count, conv_meta.bytes_written))
        wrote_at = conv_meta.wrote_at.isoformat()
        logger.info(
            "file converted",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "filename": sas_file.name,
                "outcome": "success",
                "row_count": conv_meta.row_count,
                "bytes_written": conv_meta.bytes_written,
            },
        )

    # Total failure.
    if not successes:
        now = datetime.now(timezone.utc).isoformat()
        error_dict = {
            "class": "multi_file_failure",
            "message": f"all {len(failures)} files failed conversion",
            "at": now,
            "converter_version": converter_version,
        }
        patch_body: dict = {
            "metadata": {
                "conversion_error": error_dict,
                "conversion_errors": failures,
            },
        }
        try:
            http_module.patch_delivery(api_url, delivery_id, patch_body)
        except Exception:
            logger.warning(
                "failed to PATCH conversion_error to registry",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
            )

        event_payload = {
            "delivery_id": delivery_id,
            "error_class": "multi_file_failure",
            "error_message": error_dict["message"],
            "at": now,
        }
        try:
            http_module.emit_event(api_url, "conversion.failed", delivery_id, event_payload)
        except Exception:
            logger.warning(
                "failed to emit conversion.failed event",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
            )

        logger.error(
            "conversion failed",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "failure",
                "file_count": len(failures),
                "failed_count": len(failures),
            },
        )
        return ConversionResult(outcome="failure", delivery_id=delivery_id)

    # At least one success.
    total_rows = sum(r for _, r, _ in successes)
    total_bytes = sum(b for _, _, b in successes)
    converted_files = [name for name, _, _ in successes]

    patch_body = {
        "output_path": str(parquet_dir),
        "parquet_converted_at": wrote_at,
        "metadata": {
            "converted_files": converted_files,
        },
    }
    if failures:
        patch_body["metadata"]["conversion_errors"] = failures

    http_module.patch_delivery(api_url, delivery_id, patch_body)

    event_payload = {
        "delivery_id": delivery_id,
        "output_path": str(parquet_dir),
        "file_count": len(successes),
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "failed_count": len(failures),
        "wrote_at": wrote_at,
    }
    http_module.emit_event(api_url, "conversion.completed", delivery_id, event_payload)

    logger.info(
        "converted",
        extra={
            "delivery_id": delivery_id,
            "source_path": source_path_str,
            "outcome": "success",
            "file_count": len(successes),
            "total_rows": total_rows,
            "total_bytes": total_bytes,
            "failed_count": len(failures),
        },
    )
    return ConversionResult(outcome="success", delivery_id=delivery_id)
```

**Testing:**

Tests must verify each AC listed above. Rewrite the existing test classes to cover multi-file scenarios. The `_StubHttp` and `_make_delivery` helpers remain unchanged. The `fake_convert` pattern is preserved but adapted: callers may want multiple files to succeed or selectively fail.

Test class structure:

**`TestConvertOneHappyPath`** (rewrite):
- multi-file-converter.AC2.1, AC3.1, AC3.3, AC3.4, AC7.1: Multiple SAS files all succeed. Verify PATCH has `output_path` as directory (not file), `parquet_converted_at` set, `metadata.converted_files` lists all Parquet filenames. Verify event has `file_count`, `total_rows`, `total_bytes`, `failed_count=0`.
- multi-file-converter.AC2.1: Verify each Parquet file is named `{sas_stem}.parquet`, not `{dir_name}.parquet`.
- multi-file-converter.AC1.1: Mixed-case `.SAS7BDAT` and `.sas7bdat` files are both discovered and converted.
- Single SAS file: backward compatibility -- works identically to current single-file behavior but output_path is now the directory.

**`TestConvertOneSkipGuards`** (rewrite):
- multi-file-converter.AC6.1: `parquet_converted_at` set (even without file existing on disk) -> skip. This is a behavior change from current code which checks `output_path.exists()`.
- **Remove `test_reconvert_when_file_deleted_despite_flag`** -- this test verifies the old behavior (re-convert when output file is missing despite `parquet_converted_at` being set). AC6.1 intentionally eliminates this behavior; the flag alone is now authoritative.
- multi-file-converter.AC6.2: Excluded dp_id and conversion_error guards unchanged (existing tests adapted).
- **Remove `test_multiple_sas_files_skips`** -- the old engine skipped when multiple SAS files were found. The new engine converts all of them; this is now the happy path, not a skip condition.

**`TestConvertOnePartialSuccess`** (new class):
- multi-file-converter.AC3.1, AC3.2, AC3.3: 3 files, 1 fails. Verify `outcome="success"`, PATCH has `output_path` (directory), `parquet_converted_at`, `metadata.converted_files` (2 entries), `metadata.conversion_errors` (1 entry keyed by failing filename with `class`, `message`, `at`, `converter_version`).
- multi-file-converter.AC3.4: Event payload has `file_count=2`, `total_rows` (sum), `total_bytes` (sum), `failed_count=1`.

**`TestConvertOneTotalFailure`** (new class):
- multi-file-converter.AC4.1, AC4.2: All files fail. Verify PATCH has `metadata.conversion_error` (singular) with `class: "multi_file_failure"` and `metadata.conversion_errors` (plural) with per-file entries.
- multi-file-converter.AC4.3: `conversion.failed` event emitted.
- multi-file-converter.AC4.4: Subsequent call with the patched metadata (containing `conversion_error`) triggers skip guard. Test by calling convert_one with a delivery that has `metadata.conversion_error` set.

**`TestConvertOneEmptyDir`** (new class):
- multi-file-converter.AC5.1: No SAS files -> `outcome="skipped"`, `reason="no_sas_file"`.
- multi-file-converter.AC5.2: No PATCH, no event.
- multi-file-converter.AC9.1: The skip log does NOT contain `dir_contents`.

**`TestConvertOneInterrupt`** (new class):
- multi-file-converter.AC2.3: `KeyboardInterrupt` during file conversion propagates. No PATCH, no event.
- multi-file-converter.AC2.3: `SystemExit` during file conversion propagates. No PATCH, no event.

**`TestConvertOneLogging`** (rewrite):
- multi-file-converter.AC8.1: Per-file log records with `filename` field.
- multi-file-converter.AC8.2: Delivery-level summary log with `file_count`, `total_rows`, `total_bytes`, `failed_count`.

**`TestConvertOneIntegration`** (adapt):
- Adapt the existing integration test (`test_real_sas_real_parquet_stubbed_http`) to use multiple SAV files. Create 2 SAV files via `sas_fixture_factory` with different DataFrames, copy both into source directory as `.sas7bdat` files. The existing `_convert_sas_with_sav_chunks` adapter already handles per-file conversion via `convert_sas_to_parquet` -- it works unchanged since `convert_one` calls `convert_fn` per file. Verify:
  - Both Parquet files exist under `source_dir / "parquet/"` with stems matching the SAS file stems
  - PATCH payload has `output_path` as the `parquet/` directory (not a single file)
  - PATCH payload has `metadata.converted_files` listing both Parquet filenames
  - Event payload has `file_count=2`, `total_rows` equal to sum of both DataFrames' row counts, and `bytes_written > 0`

Example setup sketch:
```python
df_a = pd.DataFrame({"x": [1, 2, 3]})
df_b = pd.DataFrame({"y": [4, 5]})
sav_a = sas_fixture_factory(df=df_a, filename="alpha.sas7bdat")
sav_b = sas_fixture_factory(df=df_b, filename="beta.sas7bdat")
(source_dir / "alpha.sas7bdat").write_bytes(sav_a.read_bytes())
(source_dir / "beta.sas7bdat").write_bytes(sav_b.read_bytes())
```

Use the existing `fake_convert` pattern: a factory that creates output files and returns `ConversionMetadata`. For selective failure, use a `fake_convert` that raises on specific filenames:

```python
def make_selective_convert(fail_names: set[str]):
    def fake_convert(src, out, **kwargs):
        if src.name in fail_names:
            raise ValueError(f"simulated failure for {src.name}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"pq")
        return ConversionMetadata(
            row_count=10, column_count=2, column_labels={}, value_labels={},
            sas_encoding="UTF-8", bytes_written=100,
            wrote_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        )
    return fake_convert
```

Follow project testing patterns: `_StubHttp` for HTTP, `tmp_path` for filesystem, `caplog` for logging, direct AC references in test names/comments.

**Verification:**
Run: `uv run pytest tests/converter/test_engine.py -v`
Expected: All tests pass

**Commit:** `feat: multi-file converter engine with partial success support`
<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->
