# pattern: Functional Core

from typing import Literal

import pyarrow as pa
from pyreadstat import PyreadstatError, ReadstatError

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
    if isinstance(exc, (ReadstatError, PyreadstatError)):
        return "parse_error"
    if isinstance(exc, pa.ArrowException):
        return "arrow_error"
    if isinstance(exc, OSError):
        return "source_io"
    return "unknown"
