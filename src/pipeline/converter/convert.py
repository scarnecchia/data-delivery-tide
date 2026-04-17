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
