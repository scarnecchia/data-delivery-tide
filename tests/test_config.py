import json
import pytest

from pipeline.config import load_config, PipelineConfig, ScanRoot


class TestLoadConfig:
    def test_load_config_from_explicit_path(self, tmp_path):
        """Test loading config from an explicitly provided path."""
        config_data = {
            "scan_roots": [
                {"path": "/test/qa", "label": "Test QA"},
                {"path": "/test/qm", "label": "Test QM"},
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
        assert config.scan_roots[1].path == "/test/qm"
        assert config.scan_roots[1].label == "Test QM"

    def test_load_config_from_env_var(self, tmp_path, monkeypatch):
        """Test loading config from PIPELINE_CONFIG env var."""
        config_data = {
            "scan_roots": [
                {"path": "/env/qa", "label": "Env QA"},
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

    def test_load_config_falls_back_to_default(self, monkeypatch, tmp_path):
        """Test fallback to pipeline/config.json when no env var is set."""
        # Change to a temp directory that has a pipeline/config.json
        config_dir = tmp_path / "pipeline"
        config_dir.mkdir()
        config_file = config_dir / "config.json"

        config_data = {
            "scan_roots": [
                {"path": "/default/qa", "label": "Default QA"},
            ],
            "registry_api_url": "http://default:8000",
            "output_root": "/default/output",
            "schema_path": "/default/schema.json",
            "overrides_path": "/default/overrides.json",
            "log_dir": "/default/logs",
            "db_path": "default/registry.db",
        }
        config_file.write_text(json.dumps(config_data))

        monkeypatch.delenv("PIPELINE_CONFIG", raising=False)
        monkeypatch.chdir(tmp_path)

        config = load_config()

        assert config.registry_api_url == "http://default:8000"
        assert config.output_root == "/default/output"
        assert config.scan_roots[0].path == "/default/qa"

    def test_load_config_missing_file_raises(self):
        """Test that FileNotFoundError is raised for nonexistent paths."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")
