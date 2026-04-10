import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from pipeline.config import ScanRoot
from pipeline.crawler.main import walk_roots, inventory_files, crawl
from pipeline.crawler.http import RegistryUnreachableError


class TestWalkRoots:
    """AC2.1, AC2.4, AC2.5 — Discover msoc/msoc_new directories."""

    def test_ac2_1_discovers_msoc_and_msoc_new_directories(self, delivery_tree):
        """AC2.1: Crawler discovers both msoc and msoc_new directories."""
        passed_path, scan_root = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
        )
        pending_path, _ = delivery_tree(
            dp_id="nsdp",
            request_id="soc_qar_wp002",
            version_dir_name="soc_qar_wp002_nsdp_v01",
            qa_status="pending",
        )

        scan_roots = [ScanRoot(path=scan_root, label="qa")]
        results = walk_roots(scan_roots)

        assert len(results) == 2
        paths = [r[0] for r in results]
        assert passed_path in paths
        assert pending_path in paths

    def test_ac2_4_processes_multiple_scan_roots(self, tmp_path):
        """AC2.4: Crawler processes deliveries from multiple scan roots."""
        # Root 1
        scan_root1 = tmp_path / "requests" / "qa"
        v1_path = scan_root1 / "mkscnr" / "packages" / "soc_qar_wp001" / "soc_qar_wp001_mkscnr_v01" / "msoc"
        v1_path.mkdir(parents=True)

        # Root 2
        scan_root2 = tmp_path / "requests" / "qm"
        v2_path = scan_root2 / "nsdp" / "packages" / "soc_qar_wp002" / "soc_qar_wp002_nsdp_v01" / "msoc_new"
        v2_path.mkdir(parents=True)

        scan_roots = [
            ScanRoot(path=str(scan_root1), label="qa"),
            ScanRoot(path=str(scan_root2), label="qm"),
        ]
        results = walk_roots(scan_roots)

        assert len(results) == 2
        assert (str(v1_path), str(scan_root1)) in results
        assert (str(v2_path), str(scan_root2)) in results

    def test_ac2_5_non_existent_scan_root_skipped(self, tmp_path):
        """AC2.5: Non-existent scan_root is skipped (does not cause error)."""
        existing_root = tmp_path / "requests" / "qa"
        existing_root.mkdir(parents=True)
        v1_path = existing_root / "mkscnr" / "packages" / "soc_qar_wp001" / "soc_qar_wp001_mkscnr_v01" / "msoc"
        v1_path.mkdir(parents=True)

        missing_root = tmp_path / "nonexistent"

        scan_roots = [
            ScanRoot(path=str(existing_root), label="qa"),
            ScanRoot(path=str(missing_root), label="missing"),
        ]
        results = walk_roots(scan_roots)

        # Should only find the existing root's delivery
        assert len(results) == 1
        assert str(v1_path) in results[0][0]


class TestInventoryFiles:
    """AC2.2, AC2.6 — File inventory with metadata."""

    def test_ac2_2_inventory_sas_files_with_metadata(self, delivery_tree):
        """AC2.2: File inventory includes all .sas7bdat files with correct size_bytes and modified_at."""
        source_path, _ = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
            sas_files=[
                ("dataset1.sas7bdat", 1024),
                ("dataset2.sas7bdat", 2048),
            ],
        )

        result = inventory_files(source_path)

        assert len(result) == 2
        filenames = {f["filename"] for f in result}
        assert "dataset1.sas7bdat" in filenames
        assert "dataset2.sas7bdat" in filenames

        # Check sizes
        sizes = {f["filename"]: f["size_bytes"] for f in result}
        assert sizes["dataset1.sas7bdat"] == 1024
        assert sizes["dataset2.sas7bdat"] == 2048

        # Check modified_at is ISO format
        for f in result:
            assert f["modified_at"]  # not empty
            datetime.fromisoformat(f["modified_at"])  # should not raise

    def test_ac2_6_empty_delivery_directory_inventory_empty(self, delivery_tree):
        """AC2.6: Empty delivery directory (no .sas7bdat files) returns empty inventory."""
        source_path, _ = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
            sas_files=[],  # no files
        )

        result = inventory_files(source_path)

        assert result == []


class TestCrawl:
    """AC2.3, AC2.7, AC3.4, AC4.4, AC7.1, AC7.2 — Full crawl orchestration."""

    @patch("pipeline.crawler.main.post_delivery")
    def test_ac2_3_posts_valid_delivery_payload_to_registry(
        self, mock_post, delivery_tree, make_crawler_config
    ):
        """AC2.3: Crawler POSTs valid DeliveryCreate payload to registry API."""
        source_path, scan_root = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
            sas_files=[("dataset.sas7bdat", 1024)],
        )

        config = make_crawler_config(
            scan_roots=[{"path": scan_root, "label": "qa"}],
        )

        logger = MagicMock()
        crawl(config, logger)

        # Verify post_delivery was called
        assert mock_post.called
        call_args = mock_post.call_args[0]
        payload = call_args[1]

        # Verify payload structure
        assert payload["request_id"] == "soc_qar_wp001"
        assert payload["project"] == "soc"
        assert payload["request_type"] == "qar"
        assert payload["workplan_id"] == "wp001"
        assert payload["dp_id"] == "mkscnr"
        assert payload["version"] == "v01"
        assert payload["qa_status"] == "passed"
        assert payload["source_path"] == source_path
        assert payload["file_count"] == 1
        assert payload["total_bytes"] == 1024
        assert payload["fingerprint"].startswith("sha256:")

    @patch("pipeline.crawler.main.post_delivery")
    def test_ac2_7_pending_superseded_by_newer_version_marked_failed(
        self, mock_post, tmp_path, make_crawler_config
    ):
        """AC2.7: Pending delivery with newer version for same workplan+dp_id is POSTed with qa_status=failed."""
        scan_root = tmp_path / "requests" / "qa"
        scan_root.mkdir(parents=True)

        # v01 pending
        v1_path = scan_root / "mkscnr" / "packages" / "soc_qar_wp001" / "soc_qar_wp001_mkscnr_v01" / "msoc_new"
        v1_path.mkdir(parents=True)
        (v1_path / "data.sas7bdat").write_bytes(b"\x00" * 100)

        # v02 pending
        v2_path = scan_root / "mkscnr" / "packages" / "soc_qar_wp001" / "soc_qar_wp001_mkscnr_v02" / "msoc_new"
        v2_path.mkdir(parents=True)
        (v2_path / "data.sas7bdat").write_bytes(b"\x00" * 100)

        config = make_crawler_config(
            scan_roots=[{"path": str(scan_root), "label": "qa"}],
        )

        logger = MagicMock()
        crawl(config, logger)

        assert mock_post.call_count == 2
        calls = mock_post.call_args_list
        payloads = [call[0][1] for call in calls]

        v1_payload = next(p for p in payloads if p["version"] == "v01")
        v2_payload = next(p for p in payloads if p["version"] == "v02")

        assert v1_payload["qa_status"] == "failed"
        assert v2_payload["qa_status"] == "pending"

    @patch("pipeline.crawler.main.post_delivery")
    def test_ac3_4_re_crawling_same_delivery_overwrites_manifest_idempotent(
        self, mock_post, delivery_tree, make_crawler_config
    ):
        """AC3.4: Re-crawling same unchanged delivery overwrites manifest with identical content (idempotent)."""
        source_path, scan_root = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
            sas_files=[("dataset.sas7bdat", 1024)],
        )

        config = make_crawler_config(
            scan_roots=[{"path": scan_root, "label": "qa"}],
        )
        logger = MagicMock()

        # First crawl
        crawl(config, logger)
        manifest_dir = config.crawl_manifest_dir
        manifest_files_1 = list(Path(manifest_dir).glob("*.json"))
        manifest_1 = json.loads(manifest_files_1[0].read_text())

        # Clear mock calls
        mock_post.reset_mock()

        # Second crawl (re-crawl same directory)
        crawl(config, logger)
        manifest_files_2 = list(Path(manifest_dir).glob("*.json"))
        manifest_2 = json.loads(manifest_files_2[0].read_text())

        # Manifests should be identical (except crawled_at which has fine-grained timestamp)
        # Check structure and content, ignore crawled_at since it's set per-run
        assert manifest_1["delivery_id"] == manifest_2["delivery_id"]
        assert manifest_1["fingerprint"] == manifest_2["fingerprint"]
        assert manifest_1["parsed"] == manifest_2["parsed"]
        assert manifest_1["file_count"] == manifest_2["file_count"]
        assert manifest_1["files"] == manifest_2["files"]

    @patch("pipeline.crawler.main.post_delivery")
    def test_ac4_4_excluded_dp_ids_no_error_manifest(
        self, mock_post, tmp_path, make_crawler_config
    ):
        """AC4.4: Excluded dp_ids do NOT produce error manifests (they are expected, not errors)."""
        scan_root = tmp_path / "requests" / "qa"
        scan_root.mkdir(parents=True)

        # Create a delivery with excluded dp_id
        excluded_path = scan_root / "nsdp" / "packages" / "soc_qar_wp001" / "soc_qar_wp001_nsdp_v01" / "msoc"
        excluded_path.mkdir(parents=True)

        config = make_crawler_config(
            scan_roots=[{"path": str(scan_root), "label": "qa"}],
            dp_id_exclusions=["nsdp"],
        )

        logger = MagicMock()
        crawl(config, logger)

        # Check that no error manifest was written
        error_dir = Path(config.crawl_manifest_dir) / "errors"
        error_manifests = list(error_dir.glob("*.json")) if error_dir.exists() else []
        assert len(error_manifests) == 0

        # And post_delivery should not have been called
        assert not mock_post.called

    @patch("pipeline.crawler.main.post_delivery")
    def test_ac7_1_idempotent_crawl_produces_identical_manifests(
        self, mock_post, delivery_tree, make_crawler_config
    ):
        """AC7.1: Running crawler twice on same directory tree produces identical manifests."""
        source_path, scan_root = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
            sas_files=[("dataset.sas7bdat", 1024)],
        )

        config = make_crawler_config(
            scan_roots=[{"path": scan_root, "label": "qa"}],
        )
        logger = MagicMock()

        # First crawl
        crawl(config, logger)
        manifest_files_1 = sorted(Path(config.crawl_manifest_dir).glob("*.json"))
        manifests_1 = [json.loads(f.read_text()) for f in manifest_files_1]

        mock_post.reset_mock()

        # Second crawl
        crawl(config, logger)
        manifest_files_2 = sorted(Path(config.crawl_manifest_dir).glob("*.json"))
        manifests_2 = [json.loads(f.read_text()) for f in manifest_files_2]

        # Should have same number of manifests
        assert len(manifests_1) == len(manifests_2)
        # Core content should match (ignore crawled_at timestamp)
        for m1, m2 in zip(manifests_1, manifests_2):
            assert m1["delivery_id"] == m2["delivery_id"]
            assert m1["fingerprint"] == m2["fingerprint"]
            assert m1["parsed"] == m2["parsed"]
            assert m1["file_count"] == m2["file_count"]
            assert m1["files"] == m2["files"]

    @patch("pipeline.crawler.main.post_delivery")
    def test_ac7_2_unchanged_fingerprint_on_re_crawl(
        self, mock_post, delivery_tree, make_crawler_config
    ):
        """AC7.2: Unchanged fingerprint means registry POST payload fingerprint unchanged on re-crawl."""
        source_path, scan_root = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
            sas_files=[("dataset.sas7bdat", 1024)],
        )

        config = make_crawler_config(
            scan_roots=[{"path": scan_root, "label": "qa"}],
        )
        logger = MagicMock()

        # First crawl
        crawl(config, logger)
        first_payload = mock_post.call_args_list[0][0][1]
        first_fingerprint = first_payload["fingerprint"]

        mock_post.reset_mock()

        # Second crawl
        crawl(config, logger)
        second_payload = mock_post.call_args_list[0][0][1]
        second_fingerprint = second_payload["fingerprint"]

        assert first_fingerprint == second_fingerprint


class TestMain:
    """AC5.4 — Exit code on RegistryUnreachableError."""

    @patch("pipeline.crawler.main.settings")
    @patch("pipeline.crawler.main.get_logger")
    @patch("pipeline.crawler.main.crawl")
    def test_ac5_4_registry_unreachable_exits_nonzero(
        self, mock_crawl, mock_logger, mock_settings
    ):
        """AC5.4: Crawler exits non-zero when RegistryUnreachableError is raised."""
        mock_crawl.side_effect = RegistryUnreachableError("connection refused")
        mock_settings.log_dir = "/tmp"

        from pipeline.crawler.main import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
