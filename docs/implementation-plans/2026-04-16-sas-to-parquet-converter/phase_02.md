# SAS-to-Parquet Converter — Phase 2: Conversion core

**Goal:** Pure functional core that streams a SAS7BDAT file through pyreadstat chunks into a single Parquet file with zstd compression, embedding SAS labels/encoding in Parquet file-level metadata. Plus a pure exception classifier.

**Architecture:** Two files in `src/pipeline/converter/`: `convert.py` (Functional Core) and `classify.py` (Functional Core). Atomic write via tmp-then-rename. Schema locked after chunk 1; mismatches raise a custom `SchemaDriftError`. No I/O outside the target file(s) — no network, no registry, no config.

**Tech Stack:** pyreadstat (>=1.2,<2), pyarrow (>=18,<19), stdlib (pathlib, uuid, datetime, json, os, tempfile), pytest.

**Scope:** Phase 2 of 6 from design plan `docs/design-plans/2026-04-16-sas-to-parquet-converter.md`.

**Codebase verified:** 2026-04-16.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### sas-to-parquet-converter.AC1: Conversion core produces valid Parquet
- **sas-to-parquet-converter.AC1.1 Success:** `convert_sas_to_parquet` produces a Parquet file readable by `pq.read_table` with the same row count as the source SAS file
- **sas-to-parquet-converter.AC1.2 Success:** Output Parquet uses zstd compression by default (overridable via parameter)
- **sas-to-parquet-converter.AC1.3 Success:** SAS column labels are embedded in Parquet file-level metadata under key `sas_labels` as JSON; readable via `pq.read_metadata(path).metadata[b'sas_labels']`
- **sas-to-parquet-converter.AC1.4 Success:** SAS value labels embedded under key `sas_value_labels`; SAS encoding embedded under key `sas_encoding`; converter version embedded under key `converter_version`
- **sas-to-parquet-converter.AC1.5 Success:** Streaming write uses `pq.ParquetWriter` with one row group per chunk (default 100k rows)
- **sas-to-parquet-converter.AC1.6 Edge:** SAS file with no column labels produces Parquet with empty `sas_labels` dict (not missing key)

### sas-to-parquet-converter.AC2: Atomic writes and cleanup
- **sas-to-parquet-converter.AC2.1 Success:** Converter writes to `{stem}.parquet.tmp-{uuid}` then `os.replace` to final path
- **sas-to-parquet-converter.AC2.2 Failure:** Exception during chunked write unlinks the tmp file before re-raising
- **sas-to-parquet-converter.AC2.3 Failure:** Exception before writer opens does not leave a tmp file
- **sas-to-parquet-converter.AC2.4 Success:** Final Parquet path is exactly `{source_path}/parquet/{stem}.parquet`
- **sas-to-parquet-converter.AC2.5 Success:** Parent `parquet/` directory is created if missing

### sas-to-parquet-converter.AC3: Schema drift detection
- **sas-to-parquet-converter.AC3.1 Success:** Chunk 1 locks the schema; subsequent chunks matching the locked schema write successfully
- **sas-to-parquet-converter.AC3.2 Failure:** Chunk N with a dtype-mismatched column raises `SchemaDriftError` before writing that chunk
- **sas-to-parquet-converter.AC3.3 Failure:** On `SchemaDriftError`, tmp file is cleaned up

### sas-to-parquet-converter.AC4: Exception classification
- **sas-to-parquet-converter.AC4.1 Success:** `FileNotFoundError` classifies to `source_missing`
- **sas-to-parquet-converter.AC4.2 Success:** `PermissionError` classifies to `source_permission`
- **sas-to-parquet-converter.AC4.3 Success:** `OSError` (non-file-not-found, non-permission) classifies to `source_io`
- **sas-to-parquet-converter.AC4.4 Success:** `pyreadstat.ReadstatError` classifies to `parse_error`
- **sas-to-parquet-converter.AC4.5 Success:** `UnicodeDecodeError` classifies to `encoding_mismatch`
- **sas-to-parquet-converter.AC4.6 Success:** `SchemaDriftError` classifies to `schema_drift`
- **sas-to-parquet-converter.AC4.7 Success:** `MemoryError` classifies to `oom`
- **sas-to-parquet-converter.AC4.8 Success:** `pyarrow.ArrowException` classifies to `arrow_error`
- **sas-to-parquet-converter.AC4.9 Edge:** Any other `Exception` subclass classifies to `unknown`

---

## Engineer Briefing

**Critical knowledge about the libraries** (verified via internet research, April 2026):

- **pyreadstat API (>=1.2,<2)**: `pyreadstat.read_file_in_chunks(read_function, file_path, chunksize=...)` returns a generator yielding `(DataFrame, metadata)` tuples. The `metadata` object is **file-level and identical across all yields** — attributes: `column_labels` (list parallel to column names, entries may be empty strings when no label), `variable_value_labels` (`dict[str, dict[value, label]]`), `file_encoding` (string or None), `column_names` (list), `number_rows` (int).
- **Public exception import**: `from pyreadstat import ReadstatError`. (The implementation file at `pyreadstat/__init__.py` re-exports it in `__all__`; do NOT import from `pyreadstat._readstat_parser`.)
- **pyarrow row groups (>=18,<19)**: Each call to `ParquetWriter.write_table(table)` appends exactly one row group unless `row_group_size` is passed (don't pass it — we want one RG per chunk). Schema is locked at writer construction.
- **File-level metadata**: `schema.with_metadata({b"key": b"value"})` BEFORE instantiating `ParquetWriter(..., schema=schema_with_meta, ...)`. Keys and values are bytes. Readable via `pq.read_metadata(path).metadata` as a `dict[bytes, bytes]`.
- **Schema drift on chunk N**: `pa.Table.from_pandas(df, schema=locked_schema)` raises `pa.lib.ArrowTypeError` (for dtype mismatch) or `pa.lib.ArrowInvalid` (for structural mismatch) when pandas dtypes differ from the locked Arrow schema. Wrap both in our own `SchemaDriftError`.
- **zstd**: `compression="zstd"` on `ParquetWriter`. Optional `compression_level` (default: codec picks). We accept compression as a parameter but do not expose level in this phase.

**Codebase conventions** (verified):

- FCIS pattern: **every file starts with `# pattern: Functional Core` or `# pattern: Imperative Shell` on line 1**. Mandatory.
- Python 3.10+ type syntax: `dict[str, str]`, `list[X]`, `X | None`. Do NOT use `typing.Dict`, `typing.Optional`, or `from __future__ import annotations` (no precedent for it).
- Class-based test structure: `class TestXxx:` with method tests. Fixtures via `tmp_path`. No mocking of libraries — generate real SAS files via `pyreadstat.write_sas7bdat`.
- `src/pipeline/converter/__init__.py` exists and is empty (1 line). Leave it alone unless Phase 3 needs re-exports (it does not).

**Testing guidance**:

- This phase is all pure functions; no HTTP, no DB. Test via direct function calls with `tmp_path`.
- Generate minimal SAS fixtures on the fly using `pyreadstat.write_sas7bdat(df, path, column_labels=..., variable_value_labels=...)`. This is the precedent this phase establishes — no checked-in `.sas7bdat` fixtures. Put any shared fixture helpers in `tests/converter/conftest.py`.
- The schema-drift test needs a SAS file whose later chunk has a different dtype than the first. The cleanest way to force this is to write a pandas DataFrame where a column is `object` (strings) and then swap it for `float` in a second write — but `pyreadstat.write_sas7bdat` writes a single file. Use a **stub/double** approach instead: parameterise `convert_sas_to_parquet` so the test can pass a fake iterator that yields two chunks with intentionally drifting schemas. See Task 5 for the exact stub pattern.
- Coverage ≥ one test per AC case listed above.
- `uv run pytest` must keep 324 pre-existing tests passing and add new tests under `tests/converter/`.

**Commit conventions**: conventional commits (`feat:`, `test:`, `refactor:`). Commit after each task.

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Exception classifier (`classify.py`)

**Verifies:** sas-to-parquet-converter.AC4.1–AC4.9

**Context:** This is the smallest, most independent piece. Build it first so schema drift in Task 3 has a class to map to.

**Files:**
- Create: `src/pipeline/converter/classify.py`
- Create: `tests/converter/__init__.py` (empty)
- Create: `tests/converter/test_classify.py`

**Implementation:**

Contents of `src/pipeline/converter/classify.py`:

```python
# pattern: Functional Core

from typing import Literal

import pyarrow as pa
from pyreadstat import ReadstatError


ErrorClass = Literal[
    "source_missing",
    "source_permission",
    "source_io",
    "parse_error",
    "encoding_mismatch",
    "schema_drift",
    "oom",
    "arrow_error",
    "unknown",
]


class SchemaDriftError(Exception):
    """Raised when a chunk's Arrow schema differs from the locked first-chunk schema."""


def classify_exception(exc: BaseException) -> ErrorClass:
    """
    Map an exception instance to a fixed error class.

    Ordering matters: narrower classes must be checked before their bases.
    FileNotFoundError / PermissionError are OSError subclasses; they must
    be matched first. SchemaDriftError is checked before the general
    pyarrow.ArrowException fallthrough even though we raise it ourselves,
    because a caller could catch-and-rewrap.
    """
    if isinstance(exc, FileNotFoundError):
        return "source_missing"
    if isinstance(exc, PermissionError):
        return "source_permission"
    if isinstance(exc, SchemaDriftError):
        return "schema_drift"
    if isinstance(exc, UnicodeDecodeError):
        return "encoding_mismatch"
    if isinstance(exc, MemoryError):
        return "oom"
    if isinstance(exc, ReadstatError):
        return "parse_error"
    if isinstance(exc, pa.ArrowException):
        return "arrow_error"
    if isinstance(exc, OSError):
        return "source_io"
    return "unknown"
```

Note: `UnicodeDecodeError` is a subclass of `ValueError`, not `OSError`, so ordering with `OSError` is independent. `MemoryError` is a direct `Exception` subclass. `pa.ArrowException` is re-exported at the pyarrow top level (import via `pyarrow as pa; pa.ArrowException`).

**Testing:**

Tests in `tests/converter/test_classify.py`. Use a single parametrised test plus edge cases:

```python
# pattern: test file

import pytest
import pyarrow as pa
from pyreadstat import ReadstatError

from pipeline.converter.classify import classify_exception, SchemaDriftError


class TestClassifyException:
    @pytest.mark.parametrize("exc,expected", [
        (FileNotFoundError("x"),             "source_missing"),
        (PermissionError("x"),               "source_permission"),
        (OSError("x"),                       "source_io"),
        (ReadstatError("x"),                 "parse_error"),
        (UnicodeDecodeError("utf-8", b"", 0, 1, "x"), "encoding_mismatch"),
        (SchemaDriftError("x"),              "schema_drift"),
        (MemoryError("x"),                   "oom"),
        (pa.lib.ArrowTypeError("x"),         "arrow_error"),
        (pa.lib.ArrowInvalid("x"),           "arrow_error"),
        (ValueError("x"),                    "unknown"),
        (RuntimeError("x"),                  "unknown"),
    ])
    def test_known_exception_classes(self, exc, expected):
        assert classify_exception(exc) == expected

    def test_subclasses_match_parent_class(self):
        class MyOSError(OSError): pass
        assert classify_exception(MyOSError()) == "source_io"

    def test_filenotfound_preferred_over_oserror(self):
        # FileNotFoundError is a subclass of OSError; must match the narrower class.
        assert classify_exception(FileNotFoundError()) == "source_missing"

    def test_permission_preferred_over_oserror(self):
        assert classify_exception(PermissionError()) == "source_permission"
```

Map tests must cover every AC4.1–AC4.9 case. The parametrised list does that plus two explicit ordering tests.

**Verification:**

Run: `uv run pytest tests/converter/test_classify.py -v`
Expected: All parametrised + ordering tests pass.

Run: `uv run pytest`
Expected: 324 pre-existing tests + new classify tests all pass.

**Commit:** `feat(converter): add exception classifier for converter errors`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: `ConversionMetadata` dataclass + schema helpers (no I/O)

**Verifies:** sas-to-parquet-converter.AC1.4, AC1.6 (supports the metadata shape)

**Context:** Split out the pure helpers before the big `convert_sas_to_parquet` function, so the writer function stays focused on orchestration and is easier to test.

**Files:**
- Create: `src/pipeline/converter/convert.py` (partial — add dataclass + helpers; the main function lands in Task 3)

**Implementation:**

Start `src/pipeline/converter/convert.py` with:

```python
# pattern: Functional Core

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyreadstat

from pipeline.converter.classify import SchemaDriftError


@dataclass(frozen=True)
class ConversionMetadata:
    row_count: int
    column_count: int
    column_labels: dict[str, str]
    value_labels: dict[str, dict]
    sas_encoding: str
    bytes_written: int
    wrote_at: datetime


def _build_column_labels(
    column_names: list[str], column_labels: list[str] | None
) -> dict[str, str]:
    """
    Zip column names with pyreadstat column_labels list into a dict.

    pyreadstat yields column_labels as a parallel list (same length and order
    as column_names), not a dict. Empty-string entries mean "no label" and are
    preserved as "" in the output dict rather than dropped, so every column
    appears in the map. If column_labels is None or empty, returns {}.
    """
    if not column_labels:
        return {}
    return dict(zip(column_names, column_labels))


def _file_metadata_bytes(
    column_labels: dict[str, str],
    value_labels: dict[str, dict],
    sas_encoding: str,
    converter_version: str,
) -> dict[bytes, bytes]:
    """
    Build the Parquet file-level key-value metadata dict from SAS metadata.

    All keys and values are bytes (Parquet requirement). Values are UTF-8-encoded
    JSON for the dict-shaped fields; plain UTF-8 bytes for scalars.
    """
    return {
        b"sas_labels":        json.dumps(column_labels).encode("utf-8"),
        b"sas_value_labels":  json.dumps(value_labels, default=str).encode("utf-8"),
        b"sas_encoding":      (sas_encoding or "").encode("utf-8"),
        b"converter_version": converter_version.encode("utf-8"),
    }
```

**Why `default=str` on `value_labels`:** pyreadstat `variable_value_labels` may contain non-JSON-native keys (e.g., numpy ints, datetimes). `default=str` makes the serializer fall back to string representation rather than raising. This is a write-only, human-readable embed — no code reads it back into typed values.

**Testing:**

Add `tests/converter/test_convert.py` (this file grows across Tasks 2–5):

```python
# pattern: test file

import json
import pyarrow as pa

from pipeline.converter.convert import (
    ConversionMetadata,
    _build_column_labels,
    _file_metadata_bytes,
)


class TestBuildColumnLabels:
    def test_zips_parallel_lists(self):
        assert _build_column_labels(["a", "b"], ["A label", "B label"]) == {"a": "A label", "b": "B label"}

    def test_empty_strings_preserved_not_dropped(self):
        # AC1.6: a column with no label still appears in the map.
        assert _build_column_labels(["a", "b"], ["", ""]) == {"a": "", "b": ""}

    def test_none_labels_returns_empty_dict(self):
        assert _build_column_labels(["a", "b"], None) == {}

    def test_empty_labels_returns_empty_dict(self):
        assert _build_column_labels(["a", "b"], []) == {}


class TestFileMetadataBytes:
    def test_round_trip_via_json(self):
        meta = _file_metadata_bytes(
            column_labels={"a": "A label"},
            value_labels={"a": {1: "yes", 0: "no"}},
            sas_encoding="UTF-8",
            converter_version="0.1.0",
        )
        assert meta[b"sas_labels"] == b'{"a": "A label"}'
        assert json.loads(meta[b"sas_value_labels"]) == {"a": {"1": "yes", "0": "no"}}
        assert meta[b"sas_encoding"] == b"UTF-8"
        assert meta[b"converter_version"] == b"0.1.0"

    def test_all_values_are_bytes(self):
        meta = _file_metadata_bytes({}, {}, "", "0")
        for k, v in meta.items():
            assert isinstance(k, bytes)
            assert isinstance(v, bytes)

    def test_empty_sas_encoding_ok(self):
        meta = _file_metadata_bytes({}, {}, "", "0")
        assert meta[b"sas_encoding"] == b""

    def test_all_four_keys_present(self):
        meta = _file_metadata_bytes({}, {}, "", "0")
        assert set(meta.keys()) == {b"sas_labels", b"sas_value_labels", b"sas_encoding", b"converter_version"}
```

**Verification:**

Run: `uv run pytest tests/converter/test_convert.py -v`
Expected: All tests pass.

**Commit:** `feat(converter): add ConversionMetadata dataclass and metadata helpers`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: `convert_sas_to_parquet` main function

**Verifies:** sas-to-parquet-converter.AC1.1, AC1.2, AC1.3, AC1.4, AC1.5, AC1.6, AC2.1, AC2.2, AC2.3, AC2.4, AC2.5, AC3.1, AC3.2, AC3.3

**Context:** Heart of the converter. Streams pyreadstat chunks through a locked pyarrow schema into one Parquet file. Atomic write. Schema drift detection with explicit cleanup.

**Files:**
- Modify: `src/pipeline/converter/convert.py` (append to the file started in Task 2)

**Implementation:**

Append the main function and a small chunk-iterator wrapper:

```python
def _iter_sas_chunks(
    source_path: Path, chunk_size: int
) -> Iterator[tuple[pd.DataFrame, object]]:
    """
    Thin wrapper around pyreadstat.read_file_in_chunks so tests can pass a
    fake iterator (Dependency Inversion light — see convert_sas_to_parquet).

    Yields (DataFrame, metadata) tuples. Metadata object is file-level and
    identical across yields per pyreadstat's API.
    """
    return pyreadstat.read_file_in_chunks(
        pyreadstat.read_sas7bdat,
        str(source_path),
        chunksize=chunk_size,
    )


def convert_sas_to_parquet(
    source_path: Path,
    output_path: Path,
    *,
    chunk_size: int = 100_000,
    compression: str = "zstd",
    converter_version: str = "0.1.0",
    chunk_iter_factory=_iter_sas_chunks,
) -> ConversionMetadata:
    """
    Stream a SAS7BDAT file to a Parquet file, one chunk per row group.

    Atomic write: writes to `{output_path}.tmp-{uuid}` then os.replaces.
    Schema is locked after the first chunk; mismatches raise SchemaDriftError.
    Cleans up the tmp file on any exception before re-raising.

    Args:
        source_path: SAS7BDAT input file.
        output_path: Final Parquet path. Parent directory is created if missing.
        chunk_size: Rows per pyreadstat chunk (== rows per Parquet row group).
        compression: Parquet codec (default "zstd").
        converter_version: Embedded in Parquet file-level metadata.
        chunk_iter_factory: Test seam. Defaults to pyreadstat.read_file_in_chunks.
            Must be a callable (source_path, chunk_size) -> Iterator[(df, metadata)].

    Returns:
        ConversionMetadata describing the written file.

    Raises:
        FileNotFoundError: source does not exist.
        SchemaDriftError: a chunk's schema differs from the first chunk.
        pyarrow.lib.ArrowException: arrow-level failures (empty file, I/O).
        pyreadstat.ReadstatError: SAS parse failures.
        OSError: filesystem errors on tmp file or rename.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.tmp-{uuid.uuid4().hex}")

    writer: pq.ParquetWriter | None = None
    locked_schema: pa.Schema | None = None
    file_metadata_obj = None
    row_count = 0

    try:
        chunks = chunk_iter_factory(source_path, chunk_size)
        for df, meta in chunks:
            file_metadata_obj = meta  # identical per pyreadstat API; capture once, harmless to rebind

            if writer is None:
                # First chunk — derive schema, attach file metadata, open writer.
                column_labels = _build_column_labels(
                    list(df.columns), getattr(meta, "column_labels", None)
                )
                value_labels = getattr(meta, "variable_value_labels", {}) or {}
                sas_encoding = getattr(meta, "file_encoding", "") or ""

                first_table = pa.Table.from_pandas(df, preserve_index=False)
                schema_with_meta = first_table.schema.with_metadata(
                    _file_metadata_bytes(column_labels, value_labels, sas_encoding, converter_version)
                )
                locked_schema = schema_with_meta
                writer = pq.ParquetWriter(tmp_path, schema_with_meta, compression=compression)

                # Re-cast the first table to the metadata-bearing schema, then write.
                first_table = first_table.cast(schema_with_meta)
                writer.write_table(first_table)
                row_count += first_table.num_rows
                continue

            # Subsequent chunks — lock schema, catch drift.
            try:
                table = pa.Table.from_pandas(df, preserve_index=False, schema=locked_schema)
            except (pa.lib.ArrowTypeError, pa.lib.ArrowInvalid) as exc:
                raise SchemaDriftError(
                    f"chunk schema differs from locked schema: {exc}"
                ) from exc

            writer.write_table(table)
            row_count += table.num_rows

        if writer is None:
            # Empty file (no chunks yielded). Create an empty Parquet with headers only.
            # This is a legitimate pyreadstat return; treat as zero-row file.
            empty_schema = pa.schema([]).with_metadata(
                _file_metadata_bytes({}, {}, "", converter_version)
            )
            writer = pq.ParquetWriter(tmp_path, empty_schema, compression=compression)
            locked_schema = empty_schema
            file_metadata_obj = None

        writer.close()
        writer = None  # sentinel so the except branch doesn't try to close twice
        os.replace(tmp_path, output_path)

    except BaseException:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    # Build return value from the captured metadata (or empty defaults).
    column_labels_out = _build_column_labels(
        list(locked_schema.names),
        getattr(file_metadata_obj, "column_labels", None) if file_metadata_obj else None,
    )
    value_labels_out = (
        getattr(file_metadata_obj, "variable_value_labels", {}) or {}
        if file_metadata_obj else {}
    )
    sas_encoding_out = (
        getattr(file_metadata_obj, "file_encoding", "") or ""
        if file_metadata_obj else ""
    )

    return ConversionMetadata(
        row_count=row_count,
        column_count=len(locked_schema.names),
        column_labels=column_labels_out,
        value_labels=value_labels_out,
        sas_encoding=sas_encoding_out,
        bytes_written=output_path.stat().st_size,
        wrote_at=datetime.now(timezone.utc),
    )
```

**Why `chunk_iter_factory` parameter:** This is a test seam (the simplest form of dependency injection). The default is the real pyreadstat iterator. Tests can pass a lambda that yields fake `(DataFrame, metadata_stub)` tuples to trigger schema drift deterministically — see Task 5. Production call sites (engine.py in Phase 3) use the default and never pass this parameter.

**Why `os.replace` not `os.rename`:** `os.replace` is atomic and overwrites an existing destination on POSIX and Windows 3.3+. The pipeline targets RHEL; both behaviours matter when the destination already exists (re-run after successful conversion).

**Why catch `BaseException`:** We must clean up the tmp file even if the caller is interrupted (KeyboardInterrupt, SystemExit). We re-raise unchanged; we do not swallow.

**Testing:**

Extend `tests/converter/test_convert.py` with a `TestConvertSasToParquet` class. Add a conftest helper first.

`tests/converter/conftest.py`:

```python
# pattern: test file

from pathlib import Path

import pandas as pd
import pyreadstat
import pytest


@pytest.fixture
def sas_fixture_factory(tmp_path):
    """
    Factory that writes a minimal SAS7BDAT file for tests.

    Usage:
        path = sas_fixture_factory(
            df=pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}),
            column_labels={"a": "A label", "b": "B label"},
            variable_value_labels={"a": {1: "one", 2: "two"}},
        )
    """
    def _make(
        *,
        df: pd.DataFrame,
        column_labels: dict[str, str] | None = None,
        variable_value_labels: dict[str, dict] | None = None,
        filename: str = "test.sas7bdat",
    ) -> Path:
        path = tmp_path / filename
        pyreadstat.write_sas7bdat(
            df,
            str(path),
            column_labels=[column_labels.get(c, "") for c in df.columns] if column_labels else None,
            variable_value_labels=variable_value_labels,
        )
        return path

    return _make
```

Then add in `test_convert.py`:

```python
import pyarrow.parquet as pq
import pandas as pd
import pyarrow as pa

from pipeline.converter.convert import convert_sas_to_parquet
from pipeline.converter.classify import SchemaDriftError


class TestConvertSasToParquetHappyPath:
    def test_roundtrip_row_count_matches(self, sas_fixture_factory, tmp_path):
        # AC1.1
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": ["x", "y", "z", "w", "v"]})
        src = sas_fixture_factory(df=df)
        out = tmp_path / "parquet" / "test.parquet"

        result = convert_sas_to_parquet(src, out)

        assert out.exists()
        assert result.row_count == 5
        table = pq.read_table(out)
        assert table.num_rows == 5

    def test_output_path_constructed_as_expected(self, sas_fixture_factory, tmp_path):
        # AC2.4, AC2.5
        df = pd.DataFrame({"a": [1]})
        src = sas_fixture_factory(df=df, filename="x.sas7bdat")
        out = tmp_path / "parquet" / "x.parquet"
        assert not out.parent.exists()

        convert_sas_to_parquet(src, out)

        assert out.parent.exists()
        assert out.exists()

    def test_uses_zstd_by_default(self, sas_fixture_factory, tmp_path):
        # AC1.2
        # Use a larger dataframe: pyarrow may skip compression on tiny row
        # groups (few rows, highly repetitive data) because the uncompressed
        # size is smaller than the compressed result. 1000 varied rows ensures
        # the writer actually applies the codec and reports it in metadata.
        df = pd.DataFrame({
            "a": list(range(1000)),
            "b": [f"str_value_{i}" for i in range(1000)],
        })
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"

        convert_sas_to_parquet(src, out, chunk_size=1000)

        meta = pq.read_metadata(out)
        # Arrow exposes compression at the row group column chunk level.
        # With 1000 varied rows, zstd kicks in for at least one column.
        rg = meta.row_group(0)
        codecs = {rg.column(i).compression.upper() for i in range(meta.num_columns)}
        assert "ZSTD" in codecs, f"expected ZSTD in row group codecs, got {codecs}"

    def test_embeds_all_four_file_metadata_keys(self, sas_fixture_factory, tmp_path):
        # AC1.3, AC1.4
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        src = sas_fixture_factory(
            df=df,
            column_labels={"a": "A label", "b": "B label"},
            variable_value_labels={"a": {1: "one", 2: "two"}},
        )
        out = tmp_path / "test.parquet"

        convert_sas_to_parquet(src, out, converter_version="9.9.9")

        file_meta = pq.read_metadata(out).metadata
        assert b"sas_labels" in file_meta
        assert b"sas_value_labels" in file_meta
        assert b"sas_encoding" in file_meta
        assert b"converter_version" in file_meta
        import json as _json
        assert _json.loads(file_meta[b"sas_labels"]) == {"a": "A label", "b": "B label"}
        assert file_meta[b"converter_version"] == b"9.9.9"

    def test_no_column_labels_yields_empty_dict(self, sas_fixture_factory, tmp_path):
        # AC1.6
        df = pd.DataFrame({"a": [1, 2]})
        src = sas_fixture_factory(df=df)  # no column_labels
        out = tmp_path / "test.parquet"

        convert_sas_to_parquet(src, out)

        file_meta = pq.read_metadata(out).metadata
        import json as _json
        loaded = _json.loads(file_meta[b"sas_labels"])
        assert isinstance(loaded, dict)
        assert loaded == {} or all(v == "" for v in loaded.values())

    def test_one_row_group_per_chunk(self, sas_fixture_factory, tmp_path):
        # AC1.5: two chunks -> two row groups.
        df = pd.DataFrame({"a": list(range(25))})
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"

        convert_sas_to_parquet(src, out, chunk_size=10)

        meta = pq.read_metadata(out)
        # 25 rows, chunk_size=10 -> 3 row groups (10, 10, 5).
        assert meta.num_row_groups == 3


class TestConvertAtomicWrite:
    def test_final_path_only_exists_on_success(self, sas_fixture_factory, tmp_path):
        # AC2.1: tmp file is used; on success no tmp files remain.
        df = pd.DataFrame({"a": [1]})
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"
        convert_sas_to_parquet(src, out)

        # No lingering tmp files.
        assert list(tmp_path.glob("test.parquet.tmp-*")) == []
        assert out.exists()

    def test_source_missing_leaves_no_tmp_file(self, tmp_path):
        # AC2.3: exception before the writer opens -> no tmp file.
        out = tmp_path / "parquet" / "test.parquet"
        with pytest.raises(FileNotFoundError):
            convert_sas_to_parquet(tmp_path / "does_not_exist.sas7bdat", out)

        # Parent dir was created (AC2.5); no tmp, no final.
        assert list(tmp_path.glob("**/test.parquet.tmp-*")) == []
        assert not out.exists()

    def test_exception_during_write_cleans_up_tmp(self, sas_fixture_factory, tmp_path):
        # AC2.2: inject a failure mid-stream via chunk_iter_factory.
        df = pd.DataFrame({"a": [1, 2, 3]})
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"

        class _Meta:
            column_labels = ["A"]
            variable_value_labels = {}
            file_encoding = "UTF-8"
            column_names = ["a"]

        def boom_after_first_chunk(source_path, chunk_size):
            yield pd.DataFrame({"a": [1]}), _Meta()
            raise RuntimeError("simulated I/O failure")

        with pytest.raises(RuntimeError, match="simulated"):
            convert_sas_to_parquet(src, out, chunk_iter_factory=boom_after_first_chunk)

        assert list(tmp_path.glob("test.parquet.tmp-*")) == []
        assert not out.exists()
```

**Testing for schema drift** goes in Task 4/5 after the fixture stubs stabilise, but the implementation is already exercised through the error path in `test_exception_during_write_cleans_up_tmp`. Keep that test as-is.

**Verification:**

Run: `uv run pytest tests/converter/test_convert.py -v`
Expected: All tests pass.

Run: `uv run pytest`
Expected: Full suite green.

**Commit:** `feat(converter): add streaming SAS-to-Parquet conversion core`
<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 4-5) -->

<!-- START_TASK_4 -->
### Task 4: Multi-chunk happy-path and schema-stability tests

**Verifies:** sas-to-parquet-converter.AC3.1

**Context:** Verify explicitly that a file whose chunks all share the same schema writes successfully (locking the schema doesn't break valid streams). This is the positive complement to Task 5's drift case.

**Files:**
- Modify: `tests/converter/test_convert.py` (add a new test class)

**Implementation:**

Append to `test_convert.py`:

```python
class TestConvertSchemaStability:
    def test_multiple_chunks_same_schema_succeeds(self, sas_fixture_factory, tmp_path):
        # AC3.1: chunks 2 through N match chunk 1 -> all write.
        df = pd.DataFrame({
            "int_col": list(range(250)),
            "str_col": [f"s{i}" for i in range(250)],
            "float_col": [float(i) * 1.5 for i in range(250)],
        })
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"

        result = convert_sas_to_parquet(src, out, chunk_size=100)

        assert result.row_count == 250
        assert result.column_count == 3
        meta = pq.read_metadata(out)
        assert meta.num_row_groups == 3  # 100, 100, 50

        # Round-trip the data.
        table = pq.read_table(out)
        assert table.num_rows == 250
        assert set(table.column_names) == {"int_col", "str_col", "float_col"}
```

**Verification:**

Run: `uv run pytest tests/converter/test_convert.py::TestConvertSchemaStability -v`
Expected: Passes.

**Commit:** `test(converter): verify multi-chunk schema-stable streaming`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Schema-drift tests via injected iterator

**Verifies:** sas-to-parquet-converter.AC3.2, AC3.3

**Context:** Forcing a real pyreadstat file to exhibit schema drift is awkward. Use the `chunk_iter_factory` seam to feed a deterministic fake iterator whose second chunk has a drifted dtype.

**Files:**
- Modify: `tests/converter/test_convert.py` (add tests to `TestConvertSchemaStability` or a new class)

**Implementation:**

Append:

```python
class TestConvertSchemaDrift:
    def _meta_stub(self, columns):
        class _Meta:
            column_labels = ["" for _ in columns]
            variable_value_labels = {}
            file_encoding = "UTF-8"
            column_names = list(columns)
        return _Meta()

    def test_dtype_drift_raises_schema_drift_error(self, tmp_path):
        # AC3.2: chunk 2 has str where chunk 1 had int -> SchemaDriftError.
        src = tmp_path / "unused.sas7bdat"
        src.write_bytes(b"")  # unused by the stub factory
        out = tmp_path / "test.parquet"

        drift_meta = self._meta_stub(["a"])

        def drift_iter(source_path, chunk_size):
            yield pd.DataFrame({"a": [1, 2, 3]}), drift_meta
            yield pd.DataFrame({"a": ["four", "five"]}), drift_meta  # dtype drift

        with pytest.raises(SchemaDriftError):
            convert_sas_to_parquet(src, out, chunk_iter_factory=drift_iter)

    def test_schema_drift_cleans_up_tmp(self, tmp_path):
        # AC3.3
        src = tmp_path / "unused.sas7bdat"
        src.write_bytes(b"")
        out = tmp_path / "parquet" / "test.parquet"

        drift_meta = self._meta_stub(["a"])

        def drift_iter(source_path, chunk_size):
            yield pd.DataFrame({"a": [1, 2, 3]}), drift_meta
            yield pd.DataFrame({"a": ["four"]}), drift_meta

        with pytest.raises(SchemaDriftError):
            convert_sas_to_parquet(src, out, chunk_iter_factory=drift_iter)

        assert list(out.parent.glob("test.parquet.tmp-*")) == []
        assert not out.exists()

    def test_column_missing_raises_schema_drift_error(self, tmp_path):
        # Structural drift (ArrowInvalid path).
        src = tmp_path / "unused.sas7bdat"
        src.write_bytes(b"")
        out = tmp_path / "test.parquet"

        drift_meta = self._meta_stub(["a", "b"])

        def drift_iter(source_path, chunk_size):
            yield pd.DataFrame({"a": [1], "b": [2]}), drift_meta
            yield pd.DataFrame({"a": [3]}), drift_meta  # missing "b"

        with pytest.raises(SchemaDriftError):
            convert_sas_to_parquet(src, out, chunk_iter_factory=drift_iter)
```

**Verification:**

Run: `uv run pytest tests/converter/test_convert.py::TestConvertSchemaDrift -v`
Expected: All three drift tests pass.

Run: `uv run pytest`
Expected: Full suite green. Phase 2 complete.

**Commit:** `test(converter): cover schema-drift detection via injected iterator`
<!-- END_TASK_5 -->

<!-- END_SUBCOMPONENT_B -->

---

## Phase completion checklist

- [ ] Five tasks committed separately.
- [ ] `uv run pytest` full suite green (324 existing + new converter tests).
- [ ] `src/pipeline/converter/convert.py` and `classify.py` both start with `# pattern: Functional Core` on line 1.
- [ ] No network, no DB, no FastAPI usage anywhere in `src/pipeline/converter/` after this phase.
- [ ] Phase 3 (engine) can import `convert_sas_to_parquet`, `ConversionMetadata`, `SchemaDriftError`, and `classify_exception` without circular-import issues.
