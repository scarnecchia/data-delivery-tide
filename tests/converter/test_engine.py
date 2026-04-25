# pattern: test file

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pandas as pd
import pyarrow.parquet as pq
import pyreadstat

from pipeline.converter.convert import ConversionMetadata
from pipeline.converter.engine import convert_one, ConversionResult, _build_parquet_dir, _find_sas_files


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
    def test_multiple_files_all_succeed(self, tmp_path):
        """AC2.1, AC3.1, AC3.3, AC3.4, AC7.1: Multiple files all succeed."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "alpha.sas7bdat").write_bytes(b"")
        (source_dir / "beta.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir)))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"pq")
            rows = 10 if src.stem == "alpha" else 20
            bytes_w = 100 if src.stem == "alpha" else 200
            return ConversionMetadata(
                row_count=rows, column_count=2, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=bytes_w, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )

        assert result.outcome == "success"

        # PATCH: AC7.1 - output_path is directory, not file
        assert len(http.patches) == 1
        _, patch = http.patches[0]
        assert patch["output_path"] == str(source_dir / "parquet")
        assert patch["parquet_converted_at"] == fake_wrote_at.isoformat()

        # AC3.3 - converted_files lists parquet filenames
        assert "metadata" in patch
        assert patch["metadata"]["converted_files"] == ["alpha.parquet", "beta.parquet"]

        # Event: AC3.4 - aggregate stats
        assert len(http.events) == 1
        event_type, _, payload = http.events[0]
        assert event_type == "conversion.completed"
        assert payload["file_count"] == 2
        assert payload["total_rows"] == 30  # 10 + 20
        assert payload["total_bytes"] == 300  # 100 + 200
        assert payload["failed_count"] == 0

    def test_single_file_backward_compat(self, tmp_path):
        """Backward compatibility: single file works, output_path is now directory."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir)))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"pq")
            return ConversionMetadata(
                row_count=5, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=50, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )

        assert result.outcome == "success"
        _, patch = http.patches[0]
        assert patch["output_path"] == str(source_dir / "parquet")
        assert patch["metadata"]["converted_files"] == ["data.parquet"]

    def test_mixed_case_extension_discovered_and_converted(self, tmp_path):
        """AC1.1: Mixed-case .SAS7BDAT files are discovered and converted."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "file1.sas7bdat").write_bytes(b"")
        (source_dir / "file2.SAS7BDAT").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir)))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"pq")
            return ConversionMetadata(
                row_count=1, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=1, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )

        assert result.outcome == "success"
        _, patch = http.patches[0]
        # Both files should be converted despite different casing
        converted = patch["metadata"]["converted_files"]
        assert len(converted) == 2
        assert "file1.parquet" in converted
        assert "file2.parquet" in converted


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
    def test_skip_when_already_converted_flag_set(self, tmp_path):
        """AC6.1: parquet_converted_at set (flag-only, no file check) -> skip."""
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(
            str(source_dir), parquet_converted_at="2026-04-15T00:00:00+00:00"
        ))

        def should_not_be_called(src, out, **kwargs):
            raise AssertionError("convert_fn should not be invoked on already converted delivery")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=should_not_be_called,
        )

        assert result.outcome == "skipped"
        assert result.reason == "already_converted"
        assert http.patches == []
        assert http.events == []

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


class TestConvertOnePartialSuccess:
    """AC3.1, AC3.2, AC3.3, AC3.4: At least one succeeds, rest fail."""

    def test_partial_success_patches_with_converted_files_and_errors(self, tmp_path):
        """3 files, 1 fails. Verify success PATCH with converted_files and conversion_errors."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "good1.sas7bdat").write_bytes(b"")
        (source_dir / "bad.sas7bdat").write_bytes(b"")
        (source_dir / "good2.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir)))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def selective_convert(src, out, **kwargs):
            if src.stem == "bad":
                raise ValueError("simulated bad file")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"pq")
            rows = 5 if src.stem == "good1" else 10
            return ConversionMetadata(
                row_count=rows, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=50, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=selective_convert,
        )

        assert result.outcome == "success"

        # PATCH: AC3.1, AC3.2, AC3.3
        _, patch = http.patches[0]
        assert patch["output_path"] == str(source_dir / "parquet")
        assert set(patch["metadata"]["converted_files"]) == {"good1.parquet", "good2.parquet"}

        # AC3.2: per-file errors recorded
        errors = patch["metadata"]["conversion_errors"]
        assert "bad.sas7bdat" in errors
        assert errors["bad.sas7bdat"]["class"] == "unknown"
        assert "simulated bad file" in errors["bad.sas7bdat"]["message"]
        assert "converter_version" in errors["bad.sas7bdat"]

        # Event: AC3.4 - aggregate stats
        _, _, payload = http.events[0]
        assert payload["file_count"] == 2  # successes only
        assert payload["total_rows"] == 15  # 5 + 10
        assert payload["failed_count"] == 1


class TestConvertOneTotalFailure:
    """AC4.1, AC4.2, AC4.3, AC4.4: All files fail."""

    def test_all_files_fail(self, tmp_path):
        """All files fail. Verify multi_file_failure + conversion_errors."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "file1.sas7bdat").write_bytes(b"")
        (source_dir / "file2.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir)))

        def always_fail(src, out, **kwargs):
            raise RuntimeError(f"always fails: {src.name}")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=always_fail,
        )

        assert result.outcome == "failure"

        # PATCH: AC4.1, AC4.2
        _, patch = http.patches[0]
        err = patch["metadata"]["conversion_error"]
        assert err["class"] == "multi_file_failure"
        assert "all 2 files failed" in err["message"]

        # AC4.2: individual errors also recorded
        errors = patch["metadata"]["conversion_errors"]
        assert len(errors) == 2
        assert "file1.sas7bdat" in errors
        assert "file2.sas7bdat" in errors

        # Event: AC4.3
        event_type, _, _ = http.events[0]
        assert event_type == "conversion.failed"

    def test_skip_guard_blocks_errored_delivery(self, tmp_path):
        """AC4.4: Skip guard blocks re-processing errored deliveries."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data.sas7bdat").write_bytes(b"")

        conversion_error = {
            "class": "multi_file_failure",
            "message": "all 1 files failed conversion",
        }
        http = _StubHttp(_make_delivery(
            str(source_dir),
            metadata={"conversion_error": conversion_error},
        ))

        def should_not_be_called(src, out, **kwargs):
            raise AssertionError("should not convert errored delivery")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=should_not_be_called,
        )

        assert result.outcome == "skipped"
        assert result.reason == "errored"


class TestConvertOneEmptyDir:
    """AC5.1, AC5.2, AC9.1: Empty directory handling."""

    def test_no_sas_files_skips_with_no_side_effects(self, tmp_path):
        """AC5.1, AC5.2: No SAS files -> skip, no PATCH, no event, no dir_contents diagnostic."""
        source_dir = tmp_path / "empty"
        source_dir.mkdir()

        http = _StubHttp(_make_delivery(str(source_dir)))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=lambda *a, **k: pytest.fail("should not convert"),
        )

        assert result.outcome == "skipped"
        assert result.reason == "no_sas_file"
        assert http.patches == []
        assert http.events == []

    def test_no_diagnostic_dir_contents_logged(self, tmp_path, caplog):
        """AC9.1: No dir_contents diagnostic in logs."""
        import logging
        source_dir = tmp_path / "empty"
        source_dir.mkdir()

        http = _StubHttp(_make_delivery(str(source_dir)))

        caplog.set_level(logging.INFO, logger="converter")
        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=lambda *a, **k: pytest.fail(""),
            log_dir=None,
        )

        # Check that no log record has dir_contents
        for record in caplog.records:
            assert not hasattr(record, "dir_contents")


class TestConvertOneInterrupt:
    """AC2.3: KeyboardInterrupt and SystemExit propagate immediately."""

    def test_keyboard_interrupt_propagates_no_patch_or_event(self, tmp_path):
        """AC2.3: KeyboardInterrupt during file conversion propagates."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir)))

        def raises_interrupt(src, out, **kwargs):
            raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            convert_one(
                "d1", "http://registry",
                converter_version="0.1.0", chunk_size=100, compression="zstd",
                http_module=http, convert_fn=raises_interrupt,
            )

        assert http.patches == []
        assert http.events == []

    def test_system_exit_propagates_no_patch_or_event(self, tmp_path):
        """AC2.3: SystemExit during file conversion propagates."""
        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(str(source_dir)))

        def raises_exit(src, out, **kwargs):
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            convert_one(
                "d1", "http://registry",
                converter_version="0.1.0", chunk_size=100, compression="zstd",
                http_module=http, convert_fn=raises_exit,
            )

        assert http.patches == []
        assert http.events == []


class TestConvertOneFailure:
    def _setup_failing(self, tmp_path, exc):
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        def raises(src, out, **kwargs):
            raise exc

        return http, raises

    def test_parse_error_in_single_file_total_failure(self, tmp_path):
        """Single file fails -> total_failure path (multi_file_failure)."""
        from pyreadstat import ReadstatError
        http, raises = self._setup_failing(tmp_path, ReadstatError("bad sas"))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )

        assert result.outcome == "failure"

        # PATCH has multi_file_failure class
        _, patch = http.patches[0]
        err = patch["metadata"]["conversion_error"]
        assert err["class"] == "multi_file_failure"
        assert err["converter_version"] == "0.1.0"
        assert "at" in err

        # Event: conversion.failed
        event_type, _, payload = http.events[0]
        assert event_type == "conversion.failed"

    def test_no_retry_after_failure(self, tmp_path):
        """No retry: single failure -> total_failure."""
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

    def test_error_message_truncated_to_500_chars(self, tmp_path):
        """Error message in per-file error dict capped at 500 chars."""
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

        # Individual file error is truncated at 500 chars
        patched = http.patches[0][1]
        per_file_errors = patched["metadata"]["conversion_errors"]
        file_error_msg = per_file_errors["msoc.sas7bdat"]["message"]
        assert len(file_error_msg) == 500


class TestConvertOneLogging:
    """AC8.1, AC8.2: Per-file and summary logging."""

    def test_per_file_success_logging(self, tmp_path, caplog):
        """AC8.1: Per-file success logged with sas_filename."""
        import logging

        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "data.sas7bdat").write_bytes(b"")
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
            log_dir=None,
            http_module=http, convert_fn=fake_convert,
        )

        file_logs = [r for r in caplog.records if getattr(r, "sas_filename", None) == "data.sas7bdat"]
        assert len(file_logs) >= 1, "per-file log with sas_filename not found"

    def test_summary_delivery_logging(self, tmp_path, caplog):
        """AC8.2: Delivery-level summary with aggregate counts."""
        import logging

        source_dir = tmp_path / "delivery"
        source_dir.mkdir()
        (source_dir / "f1.sas7bdat").write_bytes(b"")
        (source_dir / "f2.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"x")
            rows = 5 if src.stem == "f1" else 10
            return ConversionMetadata(
                row_count=rows, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=1, wrote_at=fake_wrote_at,
            )

        caplog.set_level(logging.INFO, logger="converter")
        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            http_module=http, convert_fn=fake_convert,
        )

        # Look for summary log with file_count and total_rows
        summary_logs = [r for r in caplog.records if getattr(r, "file_count", None) == 2]
        assert len(summary_logs) >= 1, "summary log with file_count not found"
        summary = summary_logs[0]
        assert summary.total_rows == 15


class TestConvertOneIntegration:
    def test_multiple_real_sas_files_to_parquet(self, tmp_path, sas_fixture_factory, sav_chunk_iter_factory):
        """AC2.1, AC7.1: Multiple SAS files convert, output_path is directory."""
        source_dir = tmp_path / "dpid" / "packages" / "req" / "v1" / "msoc"
        source_dir.mkdir(parents=True)

        # Create two test SAS files
        df_a = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        df_b = pd.DataFrame({"c": [4, 5], "d": ["p", "q"]})

        sav_a = sas_fixture_factory(df=df_a, filename="alpha.sas7bdat")
        sav_b = sas_fixture_factory(df=df_b, filename="beta.sas7bdat")

        sas_a_path = source_dir / "alpha.sas7bdat"
        sas_b_path = source_dir / "beta.sas7bdat"
        sas_a_path.write_bytes(sav_a.read_bytes())
        sas_b_path.write_bytes(sav_b.read_bytes())

        http = _StubHttp(_make_delivery(str(source_dir)))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http,
            convert_fn=lambda src, out, **kwargs: _convert_sas_with_sav_chunks(
                src, out, sav_chunk_iter_factory, **kwargs
            ),
        )

        assert result.outcome == "success"

        # Both Parquet files exist under parquet/ directory
        pq_a = source_dir / "parquet" / "alpha.parquet"
        pq_b = source_dir / "parquet" / "beta.parquet"
        assert pq_a.exists()
        assert pq_b.exists()

        # Verify contents
        table_a = pq.read_table(pq_a)
        table_b = pq.read_table(pq_b)
        assert table_a.num_rows == 3
        assert table_b.num_rows == 2

        # AC7.1: output_path is directory, not file
        _, patch = http.patches[0]
        assert patch["output_path"] == str(source_dir / "parquet")
        assert "T" in patch["parquet_converted_at"]

        # AC3.3: converted_files lists both
        assert set(patch["metadata"]["converted_files"]) == {"alpha.parquet", "beta.parquet"}

        # Event payload has aggregates
        _, _, payload = http.events[0]
        assert payload["file_count"] == 2
        assert payload["total_rows"] == 5  # 3 + 2
        assert payload["failed_count"] == 0


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
