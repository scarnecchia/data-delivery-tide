# pattern: Imperative Shell
import json
import os
import sys
from datetime import datetime, timezone

from pipeline.config import settings
from pipeline.json_logging import get_logger
from pipeline.crawler.parser import parse_path, derive_qa_statuses, ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import compute_fingerprint, FileEntry
from pipeline.crawler.manifest import build_manifest, build_error_manifest
from pipeline.crawler.http import post_delivery, RegistryUnreachableError


def inventory_files(source_path: str) -> list[FileEntry]:
    """Stat all .sas7bdat files in a directory."""
    files: list[FileEntry] = []
    for entry in os.scandir(source_path):
        if entry.is_file() and entry.name.endswith(".sas7bdat"):
            stat = entry.stat()
            files.append(
                FileEntry(
                    filename=entry.name,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                )
            )
    return files


def walk_roots(scan_roots: list) -> list[tuple[str, str]]:
    """Find all msoc/msoc_new directories under configured scan roots.

    Returns list of (source_path, scan_root_path) tuples.
    Skips non-existent scan roots (checked by caller before this is called).
    """
    results = []
    for root in scan_roots:
        root_path = root.path
        if not os.path.isdir(root_path):
            continue
        for dirpath, dirnames, _ in os.walk(root_path):
            basename = os.path.basename(dirpath)
            if basename in ("msoc", "msoc_new"):
                results.append((dirpath, root_path))
                dirnames.clear()  # don't descend further
    return results


def crawl(config, logger) -> int:
    """Run a full crawl cycle. Returns count of deliveries processed.

    Two-pass approach:
    1. Walk, parse, inventory, fingerprint, write manifests for all deliveries
    2. Derive failed statuses (pending deliveries superseded by newer versions),
       then POST all deliveries to the registry API with final qa_status values
    """
    manifest_dir = config.crawl_manifest_dir
    error_dir = os.path.join(manifest_dir, "errors")
    os.makedirs(manifest_dir, exist_ok=True)
    os.makedirs(error_dir, exist_ok=True)

    exclusions = set(config.dp_id_exclusions)
    # Single timestamp for the entire crawl run — all manifests from this run
    # share the same crawled_at. This marks the run, not individual processing.
    now = datetime.now(timezone.utc).isoformat()

    # Check scan roots existence, log warnings for missing
    for root in config.scan_roots:
        if not os.path.isdir(root.path):
            logger.warning(
                f"scan root does not exist, skipping: {root.path}",
                extra={"scan_root": root.path},
            )

    candidates = walk_roots(config.scan_roots)
    logger.info(f"found {len(candidates)} delivery candidates")

    # --- Pass 1: Parse, inventory, fingerprint, write manifests ---
    # Collect successful deliveries with their file data for pass 2
    parsed_deliveries: list[ParsedDelivery] = []
    delivery_data: dict[str, tuple[list[FileEntry], str, dict]] = {}  # source_path -> (files, fingerprint, manifest)

    for source_path, scan_root in candidates:
        result = parse_path(source_path, scan_root, exclusions)

        if result is None:
            # Excluded dp_id — skip silently, no error manifest
            continue

        if isinstance(result, ParseError):
            filename, error_manifest = build_error_manifest(
                result, config.crawler_version, now,
            )
            error_path = os.path.join(error_dir, f"{filename}.json")
            with open(error_path, "w") as f:
                json.dump(error_manifest, f, indent=2)
            logger.warning(
                f"parse error: {result.reason}",
                extra={"scan_root": scan_root, "source_path": source_path},
            )
            continue

        # result is ParsedDelivery
        files = inventory_files(source_path)
        fingerprint = compute_fingerprint(files)
        manifest = build_manifest(
            result, files, fingerprint, config.crawler_version, now,
        )

        # Write crawl manifest
        delivery_id = manifest["delivery_id"]
        manifest_path = os.path.join(manifest_dir, f"{delivery_id}.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        parsed_deliveries.append(result)
        delivery_data[result.source_path] = (files, fingerprint, manifest)

    # --- Pass 2: Derive failed statuses, POST to registry ---
    resolved_deliveries = derive_qa_statuses(parsed_deliveries)
    processed = 0

    for delivery in resolved_deliveries:
        files, fingerprint, manifest = delivery_data[delivery.source_path]
        delivery_id = manifest["delivery_id"]

        payload = {
            "request_id": delivery.request_id,
            "project": delivery.project,
            "request_type": delivery.request_type,
            "workplan_id": delivery.workplan_id,
            "dp_id": delivery.dp_id,
            "version": delivery.version,
            "scan_root": delivery.scan_root,
            "qa_status": delivery.qa_status,  # may be "failed" after derivation
            "source_path": delivery.source_path,
            "file_count": len(files),
            "total_bytes": sum(f["size_bytes"] for f in files),
            "fingerprint": fingerprint,
        }
        post_delivery(config.registry_api_url, payload)

        logger.info(
            f"processed delivery {delivery_id[:12]}... (qa_status={delivery.qa_status})",
            extra={
                "scan_root": delivery.scan_root,
                "source_path": delivery.source_path,
                "delivery_id": delivery_id,
            },
        )
        processed += 1

    logger.info(f"crawl complete: {processed} deliveries processed")
    return processed


def main():
    """Entry point for `python -m pipeline.crawler.main`."""
    config = settings
    logger = get_logger("crawler", log_dir=config.log_dir)

    try:
        crawl(config, logger)
    except RegistryUnreachableError as exc:
        logger.error(f"registry unreachable, aborting: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
