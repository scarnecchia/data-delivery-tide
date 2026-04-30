# pattern: Imperative Shell
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pipeline.lexicons import LexiconLoadError, load_all_lexicons


@dataclass
class ScanRoot:
    path: str
    label: str
    lexicon: str
    target: str = "packages"


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
    lexicons_dir: str
    converter_version: str
    converter_chunk_size: int
    converter_compression: str
    converter_state_path: str
    converter_cli_batch_size: int
    converter_cli_sleep_empty_secs: int
    api_host: str = "127.0.0.1"
    api_port: int = 8000


def load_config(path: str | None = None) -> PipelineConfig:
    if path is None:
        path = os.getenv("PIPELINE_CONFIG")
        if path is None:
            path = str(Path(__file__).resolve().parents[2] / "pipeline" / "config.json")

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    with open(config_path) as f:
        data = json.load(f)

    scan_roots = [
        ScanRoot(
            path=root["path"],
            label=root["label"],
            lexicon=root["lexicon"],
            target=root.get("target", "packages"),
        )
        for root in data["scan_roots"]
    ]

    lexicons_dir_raw = data.get("lexicons_dir")
    if lexicons_dir_raw is None:
        raise ValueError("config missing required field 'lexicons_dir'")

    lexicons_dir = str((config_path.parent / lexicons_dir_raw).resolve())

    loaded_lexicons = load_all_lexicons(lexicons_dir)

    bad_refs = [
        f"scan root '{root.label}' references unknown lexicon '{root.lexicon}'"
        for root in scan_roots
        if root.lexicon not in loaded_lexicons
    ]
    if bad_refs:
        raise LexiconLoadError(bad_refs)

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
        lexicons_dir=lexicons_dir,
        api_host=data.get("api_host", "127.0.0.1"),
        api_port=data.get("api_port", 8000),
        converter_version=data.get("converter_version", "0.1.0"),
        converter_chunk_size=data.get("converter_chunk_size", 100_000),
        converter_compression=data.get("converter_compression", "zstd"),
        converter_state_path=data.get("converter_state_path", "pipeline/.converter_state.json"),
        converter_cli_batch_size=data.get("converter_cli_batch_size", 200),
        converter_cli_sleep_empty_secs=data.get("converter_cli_sleep_empty_secs", 0),
    )


_settings: PipelineConfig | None = None


def __getattr__(name: str) -> PipelineConfig:
    global _settings
    if name == "settings":
        if _settings is None:
            _settings = load_config()
        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
