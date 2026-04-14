import pytest
import json
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
            status="passed",
        )
        # Creates: tmp_path/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/
    """
    scan_root = tmp_path / "requests" / "qa"
    scan_root.mkdir(parents=True)

    def _make(
        dp_id,
        request_id,
        version_dir_name,
        status="passed",
        sas_files=None,
    ):
        terminal = "msoc" if status == "passed" else "msoc_new"

        delivery_dir = scan_root / dp_id / "packages" / request_id / version_dir_name / terminal
        delivery_dir.mkdir(parents=True)

        if sas_files is not None:
            for name, size in sas_files:
                f = delivery_dir / name
                f.write_bytes(b"\x00" * size)

        return str(delivery_dir), str(scan_root)

    return _make


@pytest.fixture
def lexicons_dir(tmp_path):
    """Set up lexicons directory with standard test lexicons."""
    lexicons_dir = tmp_path / "lexicons"
    lexicons_dir.mkdir()

    # Create soc._base lexicon (base for soc.qar)
    soc_base = {
        "id": "soc._base",
        "statuses": ["pending", "passed", "failed"],
        "transitions": {
            "pending": ["passed", "failed"],
            "passed": [],
            "failed": []
        },
        "dir_map": {
            "msoc": "passed",
            "msoc_new": "pending"
        },
        "actionable_statuses": ["passed", "failed"],
        "metadata_fields": {}
    }

    soc_base_path = lexicons_dir / "soc" / "_base.json"
    soc_base_path.parent.mkdir(parents=True)
    with open(soc_base_path, "w") as f:
        json.dump(soc_base, f)

    # Create soc.qar lexicon (extends soc._base with derive_hook)
    soc_qar = {
        "extends": "soc._base",
        "derive_hook": "pipeline.lexicons.soc.qa:derive",
        "metadata_fields": {
            "passed_at": {
                "type": "datetime",
                "set_on": "passed"
            }
        }
    }

    soc_qar_path = lexicons_dir / "soc" / "qar.json"
    with open(soc_qar_path, "w") as f:
        json.dump(soc_qar, f)

    return str(lexicons_dir)


@pytest.fixture
def make_crawler_config(tmp_path, lexicons_dir):
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
            ScanRoot(
                path=sr["path"],
                label=sr.get("label", "default"),
                lexicon=sr.get("lexicon", "soc.qar"),
                target=sr.get("target", "packages"),
            )
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
            lexicons_dir=lexicons_dir,
        )

    return _make
