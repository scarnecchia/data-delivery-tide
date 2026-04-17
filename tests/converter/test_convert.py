# pattern: test file

import json
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd
import pytest

from pipeline.converter.convert import convert_sas_to_parquet
from pipeline.converter.convert import (
    ConversionMetadata,
    _build_column_labels,
    _file_metadata_bytes,
)
from pipeline.converter.classify import SchemaDriftError


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


class TestConvertSasToParquetHappyPath:
    def test_roundtrip_row_count_matches(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
        # AC1.1
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": ["x", "y", "z", "w", "v"]})
        src = sas_fixture_factory(df=df)
        out = tmp_path / "parquet" / "test.parquet"

        result = convert_sas_to_parquet(src, out, chunk_iter_factory=sav_chunk_iter_factory)

        assert out.exists()
        assert result.row_count == 5
        table = pq.read_table(out)
        assert table.num_rows == 5

    def test_output_path_constructed_as_expected(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
        # AC2.4, AC2.5
        df = pd.DataFrame({"a": [1]})
        src = sas_fixture_factory(df=df, filename="x.sas7bdat")
        out = tmp_path / "parquet" / "x.parquet"
        assert not out.parent.exists()

        convert_sas_to_parquet(src, out, chunk_iter_factory=sav_chunk_iter_factory)

        assert out.parent.exists()
        assert out.exists()

    def test_uses_zstd_by_default(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
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

        convert_sas_to_parquet(src, out, chunk_size=1000, chunk_iter_factory=sav_chunk_iter_factory)

        meta = pq.read_metadata(out)
        # Arrow exposes compression at the row group column chunk level.
        # With 1000 varied rows, zstd kicks in for at least one column.
        rg = meta.row_group(0)
        codecs = {rg.column(i).compression.upper() for i in range(meta.num_columns)}
        assert "ZSTD" in codecs, f"expected ZSTD in row group codecs, got {codecs}"

    def test_embeds_all_four_file_metadata_keys(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
        # AC1.3, AC1.4
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        src = sas_fixture_factory(
            df=df,
            column_labels={"a": "A label", "b": "B label"},
            variable_value_labels={"a": {1: "one", 2: "two"}},
        )
        out = tmp_path / "test.parquet"

        convert_sas_to_parquet(src, out, converter_version="9.9.9", chunk_iter_factory=sav_chunk_iter_factory)

        file_meta = pq.read_metadata(out).metadata
        assert b"sas_labels" in file_meta
        assert b"sas_value_labels" in file_meta
        assert b"sas_encoding" in file_meta
        assert b"converter_version" in file_meta
        import json as _json
        assert _json.loads(file_meta[b"sas_labels"]) == {"a": "A label", "b": "B label"}
        assert file_meta[b"converter_version"] == b"9.9.9"

    def test_no_column_labels_yields_empty_dict(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
        # AC1.6
        df = pd.DataFrame({"a": [1, 2]})
        src = sas_fixture_factory(df=df)  # no column_labels
        out = tmp_path / "test.parquet"

        convert_sas_to_parquet(src, out, chunk_iter_factory=sav_chunk_iter_factory)

        file_meta = pq.read_metadata(out).metadata
        import json as _json
        loaded = _json.loads(file_meta[b"sas_labels"])
        assert isinstance(loaded, dict)
        assert loaded == {} or all(v == "" for v in loaded.values())

    def test_one_row_group_per_chunk(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
        # AC1.5: two chunks -> two row groups.
        df = pd.DataFrame({"a": list(range(25))})
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"

        convert_sas_to_parquet(src, out, chunk_size=10, chunk_iter_factory=sav_chunk_iter_factory)

        meta = pq.read_metadata(out)
        # 25 rows, chunk_size=10 -> 3 row groups (10, 10, 5).
        assert meta.num_row_groups == 3


class TestConvertAtomicWrite:
    def test_final_path_only_exists_on_success(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
        # AC2.1: tmp file is used; on success no tmp files remain.
        df = pd.DataFrame({"a": [1]})
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"
        convert_sas_to_parquet(src, out, chunk_iter_factory=sav_chunk_iter_factory)

        # No lingering tmp files.
        assert list(tmp_path.glob("test.parquet.tmp-*")) == []
        assert out.exists()

    def test_source_missing_leaves_no_tmp_file(self, tmp_path):
        # AC2.3: exception before the writer opens -> no tmp file.
        out = tmp_path / "parquet" / "test.parquet"
        # Note: pyreadstat raises ReadstatError (subclass of Exception) when file doesn't exist,
        # not FileNotFoundError. This is caught and re-raised by convert_sas_to_parquet.
        with pytest.raises(Exception):  # ReadstatError is caught by convert_sas_to_parquet
            convert_sas_to_parquet(tmp_path / "does_not_exist.sav", out)

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


class TestConvertSchemaStability:
    def test_multiple_chunks_same_schema_succeeds(self, sas_fixture_factory, sav_chunk_iter_factory, tmp_path):
        # AC3.1: chunks 2 through N match chunk 1 -> all write.
        df = pd.DataFrame({
            "int_col": list(range(250)),
            "str_col": [f"s{i}" for i in range(250)],
            "float_col": [float(i) * 1.5 for i in range(250)],
        })
        src = sas_fixture_factory(df=df)
        out = tmp_path / "test.parquet"

        result = convert_sas_to_parquet(src, out, chunk_size=100, chunk_iter_factory=sav_chunk_iter_factory)

        assert result.row_count == 250
        assert result.column_count == 3
        meta = pq.read_metadata(out)
        assert meta.num_row_groups == 3  # 100, 100, 50

        # Round-trip the data.
        table = pq.read_table(out)
        assert table.num_rows == 250
        assert set(table.column_names) == {"int_col", "str_col", "float_col"}
