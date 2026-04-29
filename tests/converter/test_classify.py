# pattern: test file

import pyarrow as pa
import pytest
from pyreadstat import PyreadstatError, ReadstatError

from pipeline.converter.classify import SchemaDriftError, classify_exception


class TestClassifyException:
    @pytest.mark.parametrize(
        "exc,expected",
        [
            (FileNotFoundError("x"), "source_missing"),
            (PermissionError("x"), "source_permission"),
            (OSError("x"), "source_io"),
            (ReadstatError("x"), "parse_error"),
            (PyreadstatError("x"), "parse_error"),
            (UnicodeDecodeError("utf-8", b"", 0, 1, "x"), "encoding_mismatch"),
            (SchemaDriftError("x"), "schema_drift"),
            (MemoryError("x"), "oom"),
            (pa.lib.ArrowTypeError("x"), "arrow_error"),
            (pa.lib.ArrowInvalid("x"), "arrow_error"),
            (ValueError("x"), "unknown"),
            (RuntimeError("x"), "unknown"),
        ],
    )
    def test_known_exception_classes(self, exc, expected):
        assert classify_exception(exc) == expected

    def test_subclasses_match_parent_class(self):
        class MyOSError(OSError):
            pass

        assert classify_exception(MyOSError()) == "source_io"

    def test_filenotfound_preferred_over_oserror(self):
        # FileNotFoundError is a subclass of OSError; must match the narrower class.
        assert classify_exception(FileNotFoundError()) == "source_missing"

    def test_permission_preferred_over_oserror(self):
        assert classify_exception(PermissionError()) == "source_permission"
