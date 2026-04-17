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
