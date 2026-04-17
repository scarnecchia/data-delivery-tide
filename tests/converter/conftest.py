# pattern: test file

from pathlib import Path

import pandas as pd
import pyreadstat
import pytest


def _make_test_sas_file(
    df: pd.DataFrame,
    path: Path,
    column_labels: dict[str, str] | None = None,
    variable_value_labels: dict[str, dict] | None = None,
) -> None:
    """
    Write a test SAS file in SAV format (SPSS).

    Since pyreadstat doesn't support writing SAS7BDAT directly in
    the current version, we use SAV (SPSS) format which supports value labels.
    Tests will use read_file_in_chunks with read_sav to read these files.

    Note: SAV format is compatible with pyreadstat.read_file_in_chunks
    and preserves SAS-like metadata (column_labels, variable_value_labels).
    """
    col_labels = None
    if column_labels:
        col_labels = [column_labels.get(c, "") for c in df.columns]

    pyreadstat.write_sav(
        df,
        str(path),
        column_labels=col_labels,
        variable_value_labels=variable_value_labels,
    )


def _iter_sav_chunks(source_path: Path, chunk_size: int):
    """
    Test-friendly chunk iterator that uses SAV (SPSS) format.

    Since tests use SAV files instead of SAS7BDAT, this iterator
    wraps read_file_in_chunks with read_sav.
    """
    return pyreadstat.read_file_in_chunks(
        pyreadstat.read_sav,
        str(source_path),
        chunksize=chunk_size,
    )


@pytest.fixture
def sas_fixture_factory(tmp_path):
    """
    Factory that creates test SAS-like files in SAV (SPSS) format.

    Since pyreadstat doesn't support writing SAS7BDAT directly in
    the current version, we use SAV format which preserves SAS metadata.

    Usage:
        path = sas_fixture_factory(
            df=pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}),
            column_labels={"a": "A label", "b": "B label"},
            variable_value_labels={"a": {1: "one", 2: "two"}},
        )
        # path is now a .sav file that can be read with sav_chunk_iter_factory
    """
    def _make(
        *,
        df: pd.DataFrame,
        column_labels: dict[str, str] | None = None,
        variable_value_labels: dict[str, dict] | None = None,
        filename: str = "test.sas7bdat",
    ) -> Path:
        sav_filename = Path(filename).with_suffix(".sav").name
        path = tmp_path / sav_filename

        _make_test_sas_file(df, path, column_labels, variable_value_labels)
        return path

    return _make


@pytest.fixture
def sav_chunk_iter_factory():
    """
    Fixture that provides the test chunk iterator factory using SAV (SPSS) format.

    Pass this to convert_sas_to_parquet(..., chunk_iter_factory=sav_chunk_iter_factory)
    """
    return _iter_sav_chunks
