# pattern: test file
import hashlib
from datetime import UTC, datetime

from pipeline.crawler.fingerprint import FileEntry
from pipeline.crawler.manifest import (
    build_error_manifest,
    build_manifest,
    make_delivery_id,
)
from pipeline.crawler.parser import ParsedDelivery, ParseError


def make_parsed_delivery(**overrides) -> ParsedDelivery:
    """Factory helper following project conventions."""
    defaults = {
        "request_id": "soc_qar_wp001",
        "project": "soc",
        "request_type": "qar",
        "workplan_id": "wp001",
        "dp_id": "mkscnr",
        "version": "v01",
        "status": "passed",
        "source_path": "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc",
        "scan_root": "/requests/qa",
    }
    defaults.update(overrides)
    return ParsedDelivery(**defaults)


class TestMakeDeliveryId:
    """Verify delivery_id computation matches registry API algorithm."""

    def test_delivery_id_matches_sha256_of_source_path(self):
        """Delivery ID is deterministic SHA-256 hex of source_path."""
        source_path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc"
        expected = hashlib.sha256(source_path.encode()).hexdigest()

        delivery_id = make_delivery_id(source_path)

        assert delivery_id == expected

    def test_delivery_id_deterministic(self):
        """Same source_path always produces same delivery_id."""
        source_path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc"

        id1 = make_delivery_id(source_path)
        id2 = make_delivery_id(source_path)

        assert id1 == id2


class TestBuildManifest:
    """AC3.1, AC3.2, AC3.3, AC3.5 — Crawl manifest construction."""

    def test_build_manifest_returns_all_required_fields(self):
        """AC3.1: Manifest contains all required fields."""
        parsed = make_parsed_delivery()
        files: list[FileEntry] = [
            {
                "filename": "file1.sas7bdat",
                "size_bytes": 1024,
                "modified_at": "2026-04-01T10:00:00Z",
            },
            {
                "filename": "file2.sas7bdat",
                "size_bytes": 2048,
                "modified_at": "2026-04-01T11:00:00Z",
            },
        ]
        fingerprint = "sha256:abc123"
        crawler_version = "0.1.0"
        crawled_at = datetime.now(UTC).isoformat()

        manifest = build_manifest(
            parsed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        assert "crawled_at" in manifest
        assert "crawler_version" in manifest
        assert "delivery_id" in manifest
        assert "source_path" in manifest
        assert "scan_root" in manifest
        assert "parsed" in manifest
        assert "status" in manifest
        assert "lexicon_id" in manifest
        assert "fingerprint" in manifest
        assert "files" in manifest
        assert "file_count" in manifest
        assert "total_bytes" in manifest

    def test_build_manifest_delivery_id_matches_sha256(self):
        """AC3.2: delivery_id matches SHA-256 of source_path."""
        parsed = make_parsed_delivery()
        files: list[FileEntry] = []
        fingerprint = "sha256:empty"
        crawler_version = "0.1.0"
        crawled_at = datetime.now(UTC).isoformat()

        manifest = build_manifest(
            parsed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        expected_delivery_id = hashlib.sha256(parsed.source_path.encode()).hexdigest()
        assert manifest["delivery_id"] == expected_delivery_id

    def test_build_manifest_files_array_complete(self):
        """AC3.3: files array contains all entries with filename, size_bytes, modified_at."""
        parsed = make_parsed_delivery()
        files: list[FileEntry] = [
            {
                "filename": "file1.sas7bdat",
                "size_bytes": 1024,
                "modified_at": "2026-04-01T10:00:00Z",
            },
            {
                "filename": "file2.sas7bdat",
                "size_bytes": 2048,
                "modified_at": "2026-04-01T11:00:00Z",
            },
        ]
        fingerprint = "sha256:abc"
        crawler_version = "0.1.0"
        crawled_at = datetime.now(UTC).isoformat()

        manifest = build_manifest(
            parsed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        assert len(manifest["files"]) == 2
        assert manifest["files"][0]["filename"] == "file1.sas7bdat"
        assert manifest["files"][0]["size_bytes"] == 1024
        assert manifest["files"][0]["modified_at"] == "2026-04-01T10:00:00Z"
        assert manifest["files"][1]["filename"] == "file2.sas7bdat"
        assert manifest["files"][1]["size_bytes"] == 2048
        assert manifest["files"][1]["modified_at"] == "2026-04-01T11:00:00Z"

    def test_build_manifest_includes_crawler_version_and_crawled_at(self):
        """AC3.5: Manifest includes crawler_version and crawled_at timestamp."""
        parsed = make_parsed_delivery()
        files: list[FileEntry] = []
        fingerprint = "sha256:empty"
        crawler_version = "0.1.0"
        crawled_at = "2026-04-09T15:30:00Z"

        manifest = build_manifest(
            parsed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        assert manifest["crawler_version"] == "0.1.0"
        assert manifest["crawled_at"] == "2026-04-09T15:30:00Z"

    def test_build_manifest_file_count(self):
        """Manifest file_count matches number of files."""
        parsed = make_parsed_delivery()
        files: list[FileEntry] = [
            {
                "filename": "file1.sas7bdat",
                "size_bytes": 1024,
                "modified_at": "2026-04-01T10:00:00Z",
            },
            {
                "filename": "file2.sas7bdat",
                "size_bytes": 2048,
                "modified_at": "2026-04-01T11:00:00Z",
            },
        ]
        fingerprint = "sha256:abc"
        crawler_version = "0.1.0"
        crawled_at = datetime.now(UTC).isoformat()

        manifest = build_manifest(
            parsed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        assert manifest["file_count"] == 2

    def test_build_manifest_total_bytes(self):
        """Manifest total_bytes is sum of all file sizes."""
        parsed = make_parsed_delivery()
        files: list[FileEntry] = [
            {
                "filename": "file1.sas7bdat",
                "size_bytes": 1024,
                "modified_at": "2026-04-01T10:00:00Z",
            },
            {
                "filename": "file2.sas7bdat",
                "size_bytes": 2048,
                "modified_at": "2026-04-01T11:00:00Z",
            },
        ]
        fingerprint = "sha256:abc"
        crawler_version = "0.1.0"
        crawled_at = datetime.now(UTC).isoformat()

        manifest = build_manifest(
            parsed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        assert manifest["total_bytes"] == 3072

    def test_build_manifest_preserves_all_parsed_fields(self):
        """Manifest parsed field contains all ParsedDelivery fields."""
        parsed = make_parsed_delivery(
            request_id="proj_type_wpid",
            project="proj",
            request_type="type",
            workplan_id="wpid",
            dp_id="dpidxx",
            version="v02",
        )
        files: list[FileEntry] = []
        fingerprint = "sha256:empty"
        crawler_version = "0.1.0"
        crawled_at = datetime.now(UTC).isoformat()

        manifest = build_manifest(
            parsed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        assert manifest["parsed"]["request_id"] == "proj_type_wpid"
        assert manifest["parsed"]["project"] == "proj"
        assert manifest["parsed"]["request_type"] == "type"
        assert manifest["parsed"]["workplan_id"] == "wpid"
        assert manifest["parsed"]["dp_id"] == "dpidxx"
        assert manifest["parsed"]["version"] == "v02"

    def test_build_manifest_preserves_status(self):
        """Manifest status matches parsed status."""
        parsed_passed = make_parsed_delivery(status="passed")
        parsed_pending = make_parsed_delivery(status="pending")
        files: list[FileEntry] = []
        fingerprint = "sha256:empty"
        crawler_version = "0.1.0"
        crawled_at = datetime.now(UTC).isoformat()

        manifest_passed = build_manifest(
            parsed_passed, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )
        manifest_pending = build_manifest(
            parsed_pending, files, fingerprint, crawler_version, crawled_at, "test.lexicon"
        )

        assert manifest_passed["status"] == "passed"
        assert manifest_pending["status"] == "pending"
        assert manifest_passed["lexicon_id"] == "test.lexicon"
        assert manifest_pending["lexicon_id"] == "test.lexicon"


class TestBuildErrorManifest:
    """AC4.1, AC4.2, AC4.3 — Error manifest construction."""

    def test_build_error_manifest_returns_filename_and_dict(self):
        """AC4.1: Error manifest is returned as (filename, dict) tuple."""
        error = ParseError(
            raw_path="/requests/qa/invalid/path",
            scan_root="/requests/qa",
            reason="path does not end with msoc or msoc_new",
        )
        crawler_version = "0.1.0"
        error_at = datetime.now(UTC).isoformat()

        filename, manifest = build_error_manifest(error, crawler_version, error_at)

        assert isinstance(filename, str)
        assert isinstance(manifest, dict)

    def test_build_error_manifest_contains_required_fields(self):
        """AC4.2: Error manifest contains raw_path, scan_root, error, crawler_version, error_at."""
        error = ParseError(
            raw_path="/requests/qa/invalid/path",
            scan_root="/requests/qa",
            reason="path does not end with msoc or msoc_new",
        )
        crawler_version = "0.1.0"
        error_at = "2026-04-09T15:30:00Z"

        filename, manifest = build_error_manifest(error, crawler_version, error_at)

        assert manifest["raw_path"] == "/requests/qa/invalid/path"
        assert manifest["scan_root"] == "/requests/qa"
        assert manifest["error"] == "path does not end with msoc or msoc_new"
        assert manifest["crawler_version"] == "0.1.0"
        assert manifest["error_at"] == "2026-04-09T15:30:00Z"

    def test_build_error_manifest_filename_is_sha256_of_raw_path(self):
        """AC4.3: Filename is deterministic SHA-256 hex of raw_path."""
        error = ParseError(
            raw_path="/requests/qa/invalid/path",
            scan_root="/requests/qa",
            reason="some error",
        )
        crawler_version = "0.1.0"
        error_at = datetime.now(UTC).isoformat()

        filename, manifest = build_error_manifest(error, crawler_version, error_at)

        expected_filename = hashlib.sha256(error.raw_path.encode()).hexdigest()
        assert filename == expected_filename

    def test_build_error_manifest_filename_deterministic(self):
        """AC4.3: Same raw_path always produces same filename."""
        error = ParseError(
            raw_path="/requests/qa/invalid/path",
            scan_root="/requests/qa",
            reason="some error",
        )
        crawler_version = "0.1.0"
        error_at = datetime.now(UTC).isoformat()

        filename1, _ = build_error_manifest(error, crawler_version, error_at)
        filename2, _ = build_error_manifest(error, crawler_version, error_at)

        assert filename1 == filename2
