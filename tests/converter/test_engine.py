# pattern: test file

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pandas as pd
import pyarrow.parquet as pq
import pyreadstat

from pipeline.converter.convert import ConversionMetadata
from pipeline.converter.engine import convert_one, ConversionResult, _build_parquet_dir, _find_sas_files
from pipeline.converter.classify import SchemaDriftError


class _StubHttp:
    """Stub http module recording PATCH/emit calls and returning configured delivery dicts."""

    def __init__(self, delivery: dict):
        self.delivery = delivery
        self.patches: list[tuple[str, dict]] = []
        self.events: list[tuple[str, str, dict]] = []

    def get_delivery(self, api_url, delivery_id):
        return self.delivery

    def patch_delivery(self, api_url, delivery_id, updates):
        self.patches.append((delivery_id, updates))
        return self.delivery

    def emit_event(self, api_url, event_type, delivery_id, payload):
        self.events.append((event_type, delivery_id, payload))
        return {"seq": 1, "event_type": event_type, "delivery_id": delivery_id, "payload": payload}


def _make_delivery(source_path: str, parquet_converted_at=None, metadata=None, dp_id="mkscnr"):
    return {
        "delivery_id": "d1",
        "dp_id": dp_id,
        "source_path": source_path,
        "parquet_converted_at": parquet_converted_at,
        "metadata": metadata or {},
        "output_path": None,
    }


class TestHelpers:
    """Tests for helper functions _find_sas_files and _build_parquet_dir."""

    def test_find_sas_files_single_file(self, tmp_path):
        """AC1.1: _find_sas_files returns sorted list with one .sas7bdat file."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data.sas7bdat").write_bytes(b"")

        result = _find_sas_files(source_dir)
        assert result == [source_dir / "data.sas7bdat"]

    def test_find_sas_files_multiple_files_sorted(self, tmp_path):
        """AC1.1: _find_sas_files returns all files in sorted order."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "z_data.sas7bdat").write_bytes(b"")
        (source_dir / "a_data.sas7bdat").write_bytes(b"")
        (source_dir / "m_data.sas7bdat").write_bytes(b"")

        result = _find_sas_files(source_dir)
        assert len(result) == 3
        assert result == [
            source_dir / "a_data.sas7bdat",
            source_dir / "m_data.sas7bdat",
            source_dir / "z_data.sas7bdat",
        ]

    def test_find_sas_files_mixed_case_extension(self, tmp_path):
        """AC1.1: _find_sas_files includes mixed-case extensions (.SAS7BDAT, .sas7bdat)."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data1.sas7bdat").write_bytes(b"")
        (source_dir / "data2.SAS7BDAT").write_bytes(b"")
        (source_dir / "data3.SaS7BdAt").write_bytes(b"")

        result = _find_sas_files(source_dir)
        assert len(result) == 3
        names = {p.name for p in result}
        assert names == {"data1.sas7bdat", "data2.SAS7BDAT", "data3.SaS7BdAt"}

    def test_find_sas_files_excludes_non_sas(self, tmp_path):
        """AC1.2: _find_sas_files excludes non-SAS files (.lst, .pdf, .md, etc.)."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data.sas7bdat").write_bytes(b"")
        (source_dir / "log.lst").write_bytes(b"")
        (source_dir / "report.pdf").write_bytes(b"")
        (source_dir / "README.md").write_bytes(b"")

        result = _find_sas_files(source_dir)
        assert len(result) == 1
        assert result[0].name == "data.sas7bdat"

    def test_find_sas_files_empty_directory(self, tmp_path):
        """AC1.3: _find_sas_files returns empty list for empty directory."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()

        result = _find_sas_files(source_dir)
        assert result == []

    def test_find_sas_files_only_non_sas_files(self, tmp_path):
        """AC1.3: _find_sas_files returns empty list when only non-SAS files present."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "log.lst").write_bytes(b"")
        (source_dir / "report.pdf").write_bytes(b"")

        result = _find_sas_files(source_dir)
        assert result == []

    def test_build_parquet_dir_parent_delivery(self):
        """AC7.2: _build_parquet_dir returns Path(source_path) / 'parquet' (directory, not file)."""
        src = "/data/dpid/packages/req/v1/msoc"
        result = _build_parquet_dir(src)
        assert result == Path("/data/dpid/packages/req/v1/msoc/parquet")

    def test_build_parquet_dir_sub_delivery(self):
        """AC7.2: _build_parquet_dir works for sub-deliveries too."""
        src = "/data/dpid/packages/req/v1/msoc/scdm_snapshot"
        result = _build_parquet_dir(src)
        assert result == Path("/data/dpid/packages/req/v1/msoc/scdm_snapshot/parquet")

    def test_build_parquet_dir_returns_directory_not_file(self):
        """AC7.2: Result is a directory path, not a file path."""
        src = "/some/path"
        result = _build_parquet_dir(src)
        assert str(result).endswith("parquet")
        assert not str(result).endswith(".parquet")


class TestConvertOneHappyPath:
    def test_success_patches_and_emits(self, tmp_path):
        # AC5.1, AC6.2
        source_dir = tmp_path / "dpid" / "packages" / "req" / "v1" / "msoc"
        source_dir.mkdir(parents=True)
        (source_dir / "msoc.sas7bdat").write_bytes(b"unused by stub")

        http = _StubHttp(_make_delivery(str(source_dir)))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"pq")
            return ConversionMetadata(
                row_count=123,
                column_count=4,
                column_labels={},
                value_labels={},
                sas_encoding="UTF-8",
                bytes_written=2,
                wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1",
            "http://registry",
            converter_version="0.1.0",
            chunk_size=100,
            compression="zstd",
            http_module=http,
            convert_fn=fake_convert,
        )

        assert result.outcome == "success"

        # PATCH: AC5.1
        assert len(http.patches) == 1
        delivery_id, patch = http.patches[0]
        assert delivery_id == "d1"
        assert patch["output_path"] == str(source_dir / "parquet" / "msoc.parquet")
        assert patch["parquet_converted_at"] == fake_wrote_at.isoformat()

        # Event: AC6.2
        assert len(http.events) == 1
        event_type, event_delivery_id, payload = http.events[0]
        assert event_type == "conversion.completed"
        assert event_delivery_id == "d1"
        assert set(payload.keys()) == {"delivery_id", "output_path", "row_count", "bytes_written", "wrote_at"}
        assert payload["row_count"] == 123
        assert payload["bytes_written"] == 2
        assert payload["wrote_at"] == fake_wrote_at.isoformat()


    def test_uppercase_sas_extension_found(self, tmp_path):
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.SAS7BDAT").write_bytes(b"unused by stub")

        http = _StubHttp(_make_delivery(str(source_dir)))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"pq")
            return ConversionMetadata(
                row_count=1, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=2, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )
        assert result.outcome == "success"


class TestConvertOneSkipGuards:
    def test_skip_when_already_converted_and_file_exists(self, tmp_path):
        # AC5.2
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        output_file = source_dir / "parquet" / "msoc.parquet"
        output_file.parent.mkdir()
        output_file.write_bytes(b"existing")

        http = _StubHttp(_make_delivery(
            str(source_dir), parquet_converted_at="2026-04-15T00:00:00+00:00"
        ))

        def should_not_be_called(src, out, **kwargs):
            raise AssertionError("convert_fn should not be invoked on skipped delivery")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=should_not_be_called,
        )

        assert result.outcome == "skipped"
        assert result.reason == "already_converted"
        assert http.patches == []
        assert http.events == []

    def test_reconvert_when_file_deleted_despite_flag(self, tmp_path):
        # Edge: parquet_converted_at set but file missing -> re-convert.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(
            str(source_dir), parquet_converted_at="2026-04-15T00:00:00+00:00"
        ))

        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"new")
            return ConversionMetadata(
                row_count=1, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=3, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )
        assert result.outcome == "success"

    def test_skip_when_conversion_error_set(self, tmp_path):
        # AC5.3
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(
            str(source_dir),
            metadata={"conversion_error": {"class": "parse_error", "message": "x"}},
        ))

        def should_not_be_called(src, out, **kwargs):
            raise AssertionError("convert_fn should not be invoked on errored delivery")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=should_not_be_called,
        )
        assert result.outcome == "skipped"
        assert result.reason == "errored"
        assert http.patches == []
        assert http.events == []

    def test_skip_when_dp_id_excluded(self, tmp_path):
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir), dp_id="nsdp"))

        def should_not_be_called(src, out, **kwargs):
            raise AssertionError("convert_fn should not be invoked on excluded dp_id")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=should_not_be_called,
            dp_id_exclusions={"nsdp"},
        )
        assert result.outcome == "skipped"
        assert result.reason == "excluded_dp_id"
        assert http.patches == []
        assert http.events == []

    def test_no_skip_when_dp_id_not_excluded(self, tmp_path):
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir), dp_id="mkscnr"))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"")
            return ConversionMetadata(
                row_count=0, column_count=0, column_labels={}, value_labels={},
                sas_encoding="", bytes_written=0, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
            dp_id_exclusions={"nsdp"},
        )
        assert result.outcome == "success"

    def test_null_conversion_error_does_not_skip(self, tmp_path):
        # AC7.3 interaction: {"conversion_error": null} means processable.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(
            str(source_dir),
            metadata={"conversion_error": None, "other_key": "preserved"},
        ))

        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"")
            return ConversionMetadata(
                row_count=0, column_count=0, column_labels={}, value_labels={},
                sas_encoding="", bytes_written=0, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )
        assert result.outcome == "success"


class TestConvertOneFailure:
    def _setup_failing(self, tmp_path, exc):
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        def raises(src, out, **kwargs):
            raise exc

        return http, raises

    def test_parse_error_patches_and_emits_failed(self, tmp_path):
        # AC5.4, AC6.3
        from pyreadstat import ReadstatError
        http, raises = self._setup_failing(tmp_path, ReadstatError("bad sas"))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )

        assert result.outcome == "failure"

        # PATCH shape (AC5.4)
        assert len(http.patches) == 1
        _, patch = http.patches[0]
        assert "metadata" in patch
        err = patch["metadata"]["conversion_error"]
        assert err["class"] == "parse_error"
        assert "bad sas" in err["message"]
        assert err["converter_version"] == "0.1.0"
        assert "at" in err

        # Event shape (AC6.3)
        assert len(http.events) == 1
        event_type, _, payload = http.events[0]
        assert event_type == "conversion.failed"
        assert set(payload.keys()) == {"delivery_id", "error_class", "error_message", "at"}
        assert payload["error_class"] == "parse_error"

    def test_schema_drift_classifies_correctly(self, tmp_path):
        http, raises = self._setup_failing(tmp_path, SchemaDriftError("chunk mismatch"))
        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )
        assert result.outcome == "failure"
        assert http.patches[0][1]["metadata"]["conversion_error"]["class"] == "schema_drift"

    @pytest.mark.parametrize("exc,expected_class", [
        (FileNotFoundError("missing"),            "source_missing"),
        (PermissionError("nope"),                 "source_permission"),
        (OSError("generic io"),                   "source_io"),
        (UnicodeDecodeError("utf-8", b"", 0, 1, "x"), "encoding_mismatch"),
        (MemoryError("boom"),                     "oom"),
        (ValueError("unrelated"),                 "unknown"),
    ])
    def test_each_exception_classifies_on_failure_path(self, tmp_path, exc, expected_class):
        import pyarrow as pa
        http, raises = self._setup_failing(tmp_path, exc)
        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )
        assert result.outcome == "failure"
        assert http.patches[0][1]["metadata"]["conversion_error"]["class"] == expected_class
        assert http.events[0][2]["error_class"] == expected_class

    def test_arrow_error_classifies_correctly(self, tmp_path):
        import pyarrow as pa
        http, raises = self._setup_failing(tmp_path, pa.lib.ArrowTypeError("arrow"))
        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )
        assert result.outcome == "failure"
        assert http.patches[0][1]["metadata"]["conversion_error"]["class"] == "arrow_error"

    def test_no_retry_after_failure(self, tmp_path):
        # AC5.5: convert_fn is called exactly once.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        call_count = {"n": 0}

        def counting_raise(src, out, **kwargs):
            call_count["n"] += 1
            raise RuntimeError("one shot")

        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=counting_raise,
        )
        assert call_count["n"] == 1

    def test_missing_sas_file_skips(self, tmp_path):
        # source_path has no .sas7bdat file — skip, don't fail.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        http = _StubHttp(_make_delivery(str(source_dir)))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=lambda *a, **k: pytest.fail("should not be called"),
        )
        assert result.outcome == "skipped"
        assert result.reason == "no_sas_file"
        assert http.patches == []
        assert http.events == []

    def test_empty_directory_skips(self, tmp_path):
        # Empty directory (no files at all) — skip, don't fail.
        source_dir = tmp_path / "empty"
        source_dir.mkdir()
        http = _StubHttp(_make_delivery(str(source_dir)))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=lambda *a, **k: pytest.fail("should not be called"),
        )
        assert result.outcome == "skipped"
        assert result.reason == "no_sas_file"
        assert http.patches == []
        assert http.events == []

    def test_multiple_sas_files_skips(self, tmp_path):
        # Ambiguous: more than one .sas7bdat file — skip, don't fail.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "a.sas7bdat").write_bytes(b"")
        (source_dir / "b.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=lambda *a, **k: pytest.fail("should not be called"),
        )
        assert result.outcome == "skipped"
        assert result.reason == "no_sas_file"
        assert http.patches == []
        assert http.events == []

    def test_error_message_truncated_to_500_chars(self, tmp_path):
        # Guards the _handle_failure 500-char cap on message length.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        huge_message = "x" * 10_000

        def raises_huge(src, out, **kwargs):
            raise ValueError(huge_message)

        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises_huge,
        )

        patched = http.patches[0][1]
        assert len(patched["metadata"]["conversion_error"]["message"]) == 500
        # Event payload is built from the same truncated value.
        assert len(http.events[0][2]["error_message"]) == 500

    def test_keyboard_interrupt_re_raised_no_registry_write(self, tmp_path):
        # Operator interruption must not be recorded as a conversion failure.
        http, raises = self._setup_failing(tmp_path, KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            convert_one(
                "d1", "http://registry",
                converter_version="0.1.0", chunk_size=100, compression="zstd",
                http_module=http, convert_fn=raises,
            )
        assert http.patches == []
        assert http.events == []


class TestConvertOneLogging:
    """
    Verify AC5.6: a structured log line is emitted per conversion attempt
    (success or failure) via the project JsonFormatter.

    Note on caplog + JsonFormatter: pytest's caplog captures records on the
    root logger hierarchy by default. `get_logger("converter", ...)` returns
    a named child logger; caplog sees its records as long as propagation is
    on (default) or we use `caplog.set_level(..., logger="converter")`.
    """
    def test_success_emits_structured_log(self, tmp_path, caplog):
        import logging

        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"x")
            return ConversionMetadata(
                row_count=5, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=1, wrote_at=fake_wrote_at,
            )

        caplog.set_level(logging.INFO, logger="converter")
        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,  # stderr-only; caplog still captures via propagation
            http_module=http, convert_fn=fake_convert,
        )

        success_records = [r for r in caplog.records if getattr(r, "outcome", None) == "success"]
        assert len(success_records) >= 1, f"no success log records found in {caplog.records}"
        record = success_records[0]
        assert record.delivery_id == "d1"
        assert record.source_path == str(source_dir)
        assert record.row_count == 5

    def test_failure_emits_structured_log(self, tmp_path, caplog):
        import logging

        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        def fake_raises(src, out, **kwargs):
            raise ValueError("boom")

        caplog.set_level(logging.ERROR, logger="converter")
        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            http_module=http, convert_fn=fake_raises,
        )

        failure_records = [r for r in caplog.records if getattr(r, "outcome", None) == "failure"]
        assert len(failure_records) >= 1
        record = failure_records[0]
        assert record.delivery_id == "d1"
        assert record.error_class == "unknown"
        assert "boom" in record.error_message


class TestConvertOneIntegration:
    def test_real_sas_real_parquet_stubbed_http(self, tmp_path, sas_fixture_factory, sav_chunk_iter_factory):
        source_dir = tmp_path / "dpid" / "packages" / "req" / "v1" / "msoc"
        source_dir.mkdir(parents=True)

        # Create a test SAS file using the fixture factory.
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        sav_path = sas_fixture_factory(df=df, filename="msoc.sas7bdat")
        # Copy the SAV file to the source directory with .sas7bdat extension
        # so the engine can find it.
        sas_path = source_dir / "msoc.sas7bdat"
        sas_path.write_bytes(sav_path.read_bytes())

        http = _StubHttp(_make_delivery(str(source_dir)))

        # Use the sav_chunk_iter_factory since tests use SAV files
        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http,
            convert_fn=lambda src, out, **kwargs: _convert_sas_with_sav_chunks(
                src, out, sav_chunk_iter_factory, **kwargs
            ),
        )

        assert result.outcome == "success"

        # Parquet file was produced at the expected path.
        out = source_dir / "parquet" / "msoc.parquet"
        assert out.exists()
        table = pq.read_table(out)
        assert table.num_rows == 3

        # Engine PATCHed with the same output_path and a well-formed timestamp.
        _, patch = http.patches[0]
        assert patch["output_path"] == str(out)
        assert "T" in patch["parquet_converted_at"]  # ISO 8601

        # Event payload has real row_count / bytes_written.
        _, _, payload = http.events[0]
        assert payload["row_count"] == 3
        assert payload["bytes_written"] > 0


def _convert_sas_with_sav_chunks(src, out, chunk_iter_factory, **kwargs):
    """
    Adapter that calls convert_sas_to_parquet with a custom chunk iterator
    for test SAV files instead of real SAS7BDAT files.
    """
    from pipeline.converter.convert import convert_sas_to_parquet
    return convert_sas_to_parquet(
        src, out,
        chunk_size=kwargs.get('chunk_size', 100_000),
        compression=kwargs.get('compression', 'zstd'),
        converter_version=kwargs.get('converter_version', '0.1.0'),
        chunk_iter_factory=chunk_iter_factory,
    )
