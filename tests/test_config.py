import json
import pytest

from pipeline.config import load_config, PipelineConfig, ScanRoot
from pipeline.lexicons import LexiconLoadError


def _make_lexicons(tmp_path, lexicon_id="soc.qar"):
    """Create a minimal valid lexicons directory for config tests."""
    parts = lexicon_id.split(".")
    # soc.qar -> soc/qar.json
    lex_dir = tmp_path / "lexicons"
    lex_file = lex_dir / "/".join(parts[:-1]) / f"{parts[-1]}.json"
    lex_file.parent.mkdir(parents=True, exist_ok=True)
    lex_file.write_text(json.dumps({
        "statuses": ["pending", "passed", "failed"],
        "transitions": {"pending": ["passed", "failed"], "passed": [], "failed": []},
        "dir_map": {"msoc": "passed", "msoc_new": "pending"},
        "actionable_statuses": ["passed"],
        "metadata_fields": {},
    }))
    return str(lex_dir)


class TestLoadConfig:
    def test_load_config_from_explicit_path(self, tmp_path):
        """Test loading config from an explicitly provided path."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
                {"path": "/test/qm", "label": "Test QM", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert isinstance(config, PipelineConfig)
        assert isinstance(config.scan_roots[0], ScanRoot)
        assert config.registry_api_url == "http://test:8000"
        assert config.output_root == "/test/output"
        assert config.schema_path == "/test/schema.json"
        assert config.overrides_path == "/test/overrides.json"
        assert config.log_dir == "/test/logs"
        assert config.db_path == "test/registry.db"
        assert len(config.scan_roots) == 2
        assert config.scan_roots[0].path == "/test/qa"
        assert config.scan_roots[0].label == "Test QA"
        assert config.scan_roots[0].lexicon == "soc.qar"
        assert config.scan_roots[1].path == "/test/qm"
        assert config.scan_roots[1].label == "Test QM"
        assert config.scan_roots[1].lexicon == "soc.qar"

    def test_load_config_from_env_var(self, tmp_path, monkeypatch):
        """Test loading config from PIPELINE_CONFIG env var."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/env/qa", "label": "Env QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://env:9000",
            "output_root": "/env/output",
            "schema_path": "/env/schema.json",
            "overrides_path": "/env/overrides.json",
            "log_dir": "/env/logs",
            "db_path": "env/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        monkeypatch.setenv("PIPELINE_CONFIG", str(config_file))
        config = load_config()

        assert config.registry_api_url == "http://env:9000"
        assert config.output_root == "/env/output"
        assert config.scan_roots[0].path == "/env/qa"
        assert config.scan_roots[0].lexicon == "soc.qar"

    def test_load_config_falls_back_to_default(self, monkeypatch):
        """Test fallback to pipeline/config.json relative to package root when no env var is set."""
        monkeypatch.delenv("PIPELINE_CONFIG", raising=False)

        config = load_config()

        assert config.registry_api_url == "http://localhost:8000"
        assert len(config.scan_roots) > 0

    def test_load_config_missing_file_raises(self):
        """Test that FileNotFoundError is raised for nonexistent paths."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")

    def test_load_config_with_dp_id_exclusions(self, tmp_path):
        """Test loading config with dp_id_exclusions field."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
            "dp_id_exclusions": ["nsdp", "excluded"],
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.dp_id_exclusions == ["nsdp", "excluded"]

    def test_load_config_dp_id_exclusions_defaults_to_empty_list(self, tmp_path):
        """Test that dp_id_exclusions defaults to empty list if absent."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.dp_id_exclusions == []

    def test_load_config_target_explicit_packages(self, tmp_path):
        """Test that scan root with explicit target='packages' loads correctly (AC1.1)."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar", "target": "packages"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.scan_roots[0].target == "packages"

    def test_load_config_target_defaults_to_packages(self, tmp_path):
        """Test that scan root without target field defaults to 'packages' (AC1.2)."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.scan_roots[0].target == "packages"

    def test_load_config_target_non_default(self, tmp_path):
        """Test that scan root with non-default target='compare' loads correctly (AC1.3)."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar", "target": "compare"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.scan_roots[0].target == "compare"

    def test_load_config_default_json_all_targets_packages(self, monkeypatch):
        """Test that real config.json loads without target field and all roots default to 'packages' (AC1.4)."""
        monkeypatch.delenv("PIPELINE_CONFIG", raising=False)

        config = load_config()

        assert all(root.target == "packages" for root in config.scan_roots)

    # AC2.1-AC2.3 tests
    def test_load_config_valid_lexicon_reference(self, tmp_path):
        """AC2.1: Scan root with valid lexicon reference loads successfully."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.scan_roots[0].lexicon == "soc.qar"

    def test_load_config_invalid_lexicon_reference(self, tmp_path):
        """AC2.2: Scan root referencing non-existent lexicon ID fails at startup."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.nonexistent"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        with pytest.raises(LexiconLoadError) as exc_info:
            load_config(str(config_file))

        assert "soc.nonexistent" in str(exc_info.value)
        assert "Test QA" in str(exc_info.value)

    def test_load_config_missing_lexicons_dir(self, tmp_path):
        """AC2.3: Missing lexicons_dir in config fails at startup."""
        config_data = {
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        with pytest.raises(ValueError) as exc_info:
            load_config(str(config_file))

        assert "lexicons_dir" in str(exc_info.value)

    def test_loads_converter_version_with_default(self, tmp_path):
        """Test that converter_version defaults to 0.1.0 when absent."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.converter_version == "0.1.0"

    def test_loads_converter_chunk_size_with_default(self, tmp_path):
        """Test that converter_chunk_size defaults to 100_000 when absent."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.converter_chunk_size == 100_000

    def test_loads_converter_compression_with_default(self, tmp_path):
        """Test that converter_compression defaults to zstd when absent."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.converter_compression == "zstd"

    def test_loads_converter_state_path_with_default(self, tmp_path):
        """Test that converter_state_path defaults to pipeline/.converter_state.json when absent."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.converter_state_path == "pipeline/.converter_state.json"

    def test_loads_converter_cli_batch_size_with_default(self, tmp_path):
        """Test that converter_cli_batch_size defaults to 200 when absent."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.converter_cli_batch_size == 200

    def test_loads_converter_cli_sleep_empty_secs_with_default(self, tmp_path):
        """Test that converter_cli_sleep_empty_secs defaults to 0 when absent."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.converter_cli_sleep_empty_secs == 0

    def test_explicit_converter_version_overrides_default(self, tmp_path):
        """Test that explicit converter_version in config overrides the default."""
        _make_lexicons(tmp_path, "soc.qar")

        config_data = {
            "lexicons_dir": "lexicons",
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA", "lexicon": "soc.qar"},
            ],
            "registry_api_url": "http://test:8000",
            "output_root": "/test/output",
            "schema_path": "/test/schema.json",
            "overrides_path": "/test/overrides.json",
            "log_dir": "/test/logs",
            "db_path": "test/registry.db",
            "converter_version": "1.2.3",
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))

        config = load_config(str(config_file))

        assert config.converter_version == "1.2.3"
