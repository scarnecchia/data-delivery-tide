# pattern: Imperative Shell
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScanRoot:
    path: str
    label: str


@dataclass
class PipelineConfig:
    scan_roots: list[ScanRoot]
    registry_api_url: str
    output_root: str
    schema_path: str
    overrides_path: str
    log_dir: str
    db_path: str
    dp_id_exclusions: list[str]
    crawl_manifest_dir: str
    crawler_version: str


def load_config(path: str | None = None) -> PipelineConfig:
    if path is None:
        path = os.getenv("PIPELINE_CONFIG")
        if path is None:
            path = "pipeline/config.json"

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    with open(config_path) as f:
        data = json.load(f)

    scan_roots = [ScanRoot(path=root["path"], label=root["label"]) for root in data["scan_roots"]]

    return PipelineConfig(
        scan_roots=scan_roots,
        registry_api_url=data["registry_api_url"],
        output_root=data["output_root"],
        schema_path=data["schema_path"],
        overrides_path=data["overrides_path"],
        log_dir=data["log_dir"],
        db_path=data["db_path"],
        dp_id_exclusions=data.get("dp_id_exclusions", []),
        crawl_manifest_dir=data.get("crawl_manifest_dir", "pipeline/crawl_manifests"),
        crawler_version=data.get("crawler_version", "1.0.0"),
    )


_settings = None


def __getattr__(name):
    global _settings
    if name == "settings":
        if _settings is None:
            _settings = load_config()
        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
