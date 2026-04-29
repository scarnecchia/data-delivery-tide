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

    # Create soc.scdm lexicon (sub-lexicon with no sub_dirs)
    soc_scdm = {
        "id": "soc.scdm",
        "statuses": ["pending", "passed", "failed"],
        "transitions": {
            "pending": ["passed", "failed"],
            "passed": [],
            "failed": []
        },
        "dir_map": {
            "scdm": "passed",
            "scdm_new": "pending"
        },
        "actionable_statuses": ["passed", "failed"],
        "metadata_fields": {}
    }

    soc_scdm_path = lexicons_dir / "soc" / "scdm.json"
    with open(soc_scdm_path, "w") as f:
        json.dump(soc_scdm, f)

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
            converter_version=config_dict.get("converter_version", "0.1.0"),
            converter_chunk_size=config_dict.get("converter_chunk_size", 100_000),
            converter_compression=config_dict.get("converter_compression", "zstd"),
            converter_state_path=config_dict.get("converter_state_path", "pipeline/.converter_state.json"),
            converter_cli_batch_size=config_dict.get("converter_cli_batch_size", 200),
            converter_cli_sleep_empty_secs=config_dict.get("converter_cli_sleep_empty_secs", 0),
        )

    return _make


@pytest.fixture
def sub_delivery_setup(tmp_path, make_crawler_config, lexicons_dir):
    """Fixture for sub-delivery tests that handles directory tree creation and lexicon patching.

    Returns a factory function that:
    1. Creates scan root directory
    2. Creates parent and sub directories with optional .sas7bdat files
    3. Patches soc.qar lexicon with sub_dirs configuration
    4. Returns (scan_root_path, config, parent_path, sub_path) tuple
    """
    def _make(
        parent_files=None,
        sub_files=None,
        sub_dir_name="scdm_snapshot",
        sub_lexicon_id="soc.scdm",
        parent_status="passed",
    ):
        """Create sub-delivery test environment.

        Args:
            parent_files: List of (filename, size) tuples for parent directory
            sub_files: List of (filename, size) tuples for sub directory
            sub_dir_name: Name of sub-directory (default "scdm_snapshot")
            sub_lexicon_id: Lexicon ID for sub-directory (default "soc.scdm")
            parent_status: Terminal directory name ("passed" -> msoc, else -> msoc_new)

        Returns:
            Tuple of (scan_root, config, parent_path, sub_path)
        """
        scan_root = tmp_path / "requests" / "qa"
        scan_root.mkdir(parents=True)

        terminal = "msoc" if parent_status == "passed" else "msoc_new"
        parent_path = scan_root / "mkscnr" / "packages" / "soc_qar_wp001" / "soc_qar_wp001_mkscnr_v01" / terminal
        parent_path.mkdir(parents=True)

        # Create parent files
        if parent_files:
            for filename, size in parent_files:
                (parent_path / filename).write_bytes(b"\x00" * size)

        # Create sub-directory
        sub_path = parent_path / sub_dir_name
        sub_path.mkdir()

        # Create sub files
        if sub_files:
            for filename, size in sub_files:
                (sub_path / filename).write_bytes(b"\x00" * size)

        # Patch soc.qar lexicon with sub_dirs
        soc_qar_path = Path(lexicons_dir) / "soc" / "qar.json"
        soc_qar_config = json.loads(soc_qar_path.read_text())
        soc_qar_config["sub_dirs"] = {sub_dir_name: sub_lexicon_id}
        soc_qar_path.write_text(json.dumps(soc_qar_config))

        # Create crawler config
        config = make_crawler_config(
            scan_roots=[{"path": str(scan_root), "label": "qa"}],
        )

        return scan_root, config, parent_path, sub_path

    return _make
