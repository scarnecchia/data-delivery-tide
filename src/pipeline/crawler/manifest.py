# pattern: Functional Core
import hashlib
from typing import TypedDict

from pipeline.crawler.fingerprint import FileEntry
from pipeline.crawler.parser import ParsedDelivery, ParseError


class ParsedMetadata(TypedDict):
    request_id: str
    project: str
    request_type: str
    workplan_id: str
    dp_id: str
    version: str


class CrawlManifest(TypedDict):
    crawled_at: str
    crawler_version: str
    delivery_id: str
    source_path: str
    scan_root: str
    parsed: ParsedMetadata
    lexicon_id: str
    status: str
    fingerprint: str
    files: list[dict]
    file_count: int
    total_bytes: int


class ErrorManifest(TypedDict):
    error_at: str
    crawler_version: str
    raw_path: str
    scan_root: str
    error: str


def make_delivery_id(source_path: str) -> str:
    """Compute delivery ID as SHA-256 hex of source_path.

    Must match the algorithm in pipeline.registry_api.db.make_delivery_id().
    """
    return hashlib.sha256(source_path.encode()).hexdigest()


def build_manifest(
    parsed: ParsedDelivery,
    files: list[FileEntry],
    fingerprint: str,
    crawler_version: str,
    crawled_at: str,
    lexicon_id: str,
) -> CrawlManifest:
    """Build a crawl manifest dict from parsed metadata and file inventory."""
    delivery_id = make_delivery_id(parsed.source_path)
    return {
        "crawled_at": crawled_at,
        "crawler_version": crawler_version,
        "delivery_id": delivery_id,
        "source_path": parsed.source_path,
        "scan_root": parsed.scan_root,
        "parsed": {
            "request_id": parsed.request_id,
            "project": parsed.project,
            "request_type": parsed.request_type,
            "workplan_id": parsed.workplan_id,
            "dp_id": parsed.dp_id,
            "version": parsed.version,
        },
        "lexicon_id": lexicon_id,
        "status": parsed.status,
        "fingerprint": fingerprint,
        "files": [dict(f) for f in files],
        "file_count": len(files),
        "total_bytes": sum(f["size_bytes"] for f in files),
    }


def build_error_manifest(
    error: ParseError,
    crawler_version: str,
    error_at: str,
) -> tuple[str, ErrorManifest]:
    """Build an error manifest dict and its deterministic filename.

    Returns (filename, manifest_dict) where filename is sha256 hex of raw_path.
    """
    filename = hashlib.sha256(error.raw_path.encode()).hexdigest()
    manifest = {
        "error_at": error_at,
        "crawler_version": crawler_version,
        "raw_path": error.raw_path,
        "scan_root": error.scan_root,
        "error": error.reason,
    }
    return filename, manifest
