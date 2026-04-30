# pattern: Functional Core (file I/O only; no network, registry, or config)

import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyreadstat

from pipeline.converter.classify import SchemaDriftError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConversionMetadata:
    row_count: int
    column_count: int
    column_labels: dict[str, str]
    value_labels: dict[str, dict[Any, Any]]
    sas_encoding: str
    bytes_written: int
    wrote_at: datetime


def _build_column_labels(
    column_names: list[str], column_labels: list[str | None] | None
) -> dict[str, str]:
    """
    Zip column names with pyreadstat column_labels list into a dict.

    pyreadstat yields column_labels as a parallel list (same length and order
    as column_names), not a dict. Empty-string or None entries mean "no label"
    and are converted to "" in the output dict, so every column appears in the
    map. If column_labels is None or empty, returns {}.
    """
    if not column_labels:
        return {}
    return {name: (label or "") for name, label in zip(column_names, column_labels, strict=False)}


def _file_metadata_bytes(
    column_labels: dict[str, str],
    value_labels: dict[str, dict[Any, Any]],
    sas_encoding: str,
    converter_version: str,
) -> dict[bytes, bytes]:
    """
    Build the Parquet file-level key-value metadata dict from SAS metadata.

    All keys and values are bytes (Parquet requirement). Values are UTF-8-encoded
    JSON for the dict-shaped fields; plain UTF-8 bytes for scalars.
    """
    return {
        b"sas_labels": json.dumps(column_labels).encode("utf-8"),
        b"sas_value_labels": json.dumps(value_labels, default=str).encode("utf-8"),
        b"sas_encoding": (sas_encoding or "").encode("utf-8"),
        b"converter_version": converter_version.encode("utf-8"),
    }


def _iter_sas_chunks(source_path: Path, chunk_size: int) -> Iterator[tuple[pd.DataFrame, object]]:
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
    chunk_iter_factory: Callable[
        [Path, int], Iterator[tuple[pd.DataFrame, object]]
    ] = _iter_sas_chunks,
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
            file_metadata_obj = (
                meta  # identical per pyreadstat API; capture once, harmless to rebind
            )

            if writer is None:
                # First chunk — derive schema, attach file metadata, open writer.
                column_labels = _build_column_labels(
                    list(df.columns), getattr(meta, "column_labels", None)
                )
                value_labels = getattr(meta, "variable_value_labels", {}) or {}
                sas_encoding = getattr(meta, "file_encoding", "") or ""

                first_table = pa.Table.from_pandas(df, preserve_index=False)
                schema_with_meta = first_table.schema.with_metadata(
                    _file_metadata_bytes(
                        column_labels, value_labels, sas_encoding, converter_version
                    )
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
            except (pa.lib.ArrowTypeError, pa.lib.ArrowInvalid, KeyError) as exc:
                raise SchemaDriftError(f"chunk schema differs from locked schema: {exc}") from exc

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
                logger.debug("writer close failed during cleanup", exc_info=True)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                logger.debug("tmp file unlink failed during cleanup", exc_info=True)
        raise

    # Build return value from the captured metadata (or empty defaults).
    assert locked_schema is not None  # set in either branch above
    column_labels_out = _build_column_labels(
        list(locked_schema.names),
        getattr(file_metadata_obj, "column_labels", None) if file_metadata_obj else None,
    )
    value_labels_out = (
        getattr(file_metadata_obj, "variable_value_labels", {}) or {} if file_metadata_obj else {}
    )
    sas_encoding_out = (
        getattr(file_metadata_obj, "file_encoding", "") or "" if file_metadata_obj else ""
    )

    return ConversionMetadata(
        row_count=row_count,
        column_count=len(locked_schema.names),
        column_labels=column_labels_out,
        value_labels=value_labels_out,
        sas_encoding=sas_encoding_out,
        bytes_written=output_path.stat().st_size,
        wrote_at=datetime.now(UTC),
    )
