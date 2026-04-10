import os
import pytest
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.config import ScanRoot, PipelineConfig


@pytest.fixture
def delivery_tree(tmp_path):
    """Factory fixture that creates temp directory trees mimicking the network share.

    Usage:
        path, root = delivery_tree(
            dp_id="mkscnr",
            request_id="soc_qar_wp001",
            version_dir_name="soc_qar_wp001_mkscnr_v01",
            qa_status="passed",
        )
        # Creates: tmp_path/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/
    """
    scan_root = tmp_path / "requests" / "qa"
    scan_root.mkdir(parents=True)

    def _make(
        dp_id,
        request_id,
        version_dir_name,
        qa_status="passed",
        sas_files=None,
    ):
        terminal = "msoc" if qa_status == "passed" else "msoc_new"

        delivery_dir = scan_root / dp_id / "packages" / request_id / version_dir_name / terminal
        delivery_dir.mkdir(parents=True)

        if sas_files is not None:
            for name, size in sas_files:
                f = delivery_dir / name
                f.write_bytes(b"\x00" * size)

        return str(delivery_dir), str(scan_root)

    return _make


@pytest.fixture
def make_crawler_config(tmp_path):
    """Factory for creating config objects for crawler tests."""
    def _make(scan_roots=None, manifest_dir=None, **overrides):
        if scan_roots is None:
            scan_roots = []
        if manifest_dir is None:
            manifest_dir = str(tmp_path / "crawl_manifests")

        config_dict = {
            "scan_roots": scan_roots,
            "registry_api_url": "http://localhost:8000",
            "output_root": str(tmp_path / "output"),
            "schema_path": "schema.json",
            "overrides_path": "overrides.json",
            "log_dir": str(tmp_path / "logs"),
            "db_path": str(tmp_path / "registry.db"),
            "dp_id_exclusions": [],
            "crawl_manifest_dir": manifest_dir,
            "crawler_version": "1.0.0",
        }
        config_dict.update(overrides)

        scan_roots_objs = [
            ScanRoot(path=sr["path"], label=sr.get("label", "default"))
            for sr in config_dict["scan_roots"]
        ]

        return PipelineConfig(
            scan_roots=scan_roots_objs,
            registry_api_url=config_dict["registry_api_url"],
            output_root=config_dict["output_root"],
            schema_path=config_dict["schema_path"],
            overrides_path=config_dict["overrides_path"],
            log_dir=config_dict["log_dir"],
            db_path=config_dict["db_path"],
            dp_id_exclusions=config_dict["dp_id_exclusions"],
            crawl_manifest_dir=config_dict["crawl_manifest_dir"],
            crawler_version=config_dict["crawler_version"],
        )

    return _make
