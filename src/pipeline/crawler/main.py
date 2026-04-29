# pattern: Imperative Shell
import json
import os
import sys
from datetime import datetime, timezone

from pipeline.config import settings
from pipeline.json_logging import get_logger
from pipeline.crawler.parser import parse_path, derive_statuses, ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import compute_fingerprint, FileEntry
from pipeline.crawler.manifest import build_manifest, build_error_manifest
from pipeline.crawler.http import post_delivery, RegistryUnreachableError, RegistryClientError
from pipeline.lexicons import load_all_lexicons


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


def walk_roots(
    scan_roots: list,
    valid_terminals: set[str],
    exclusions: set[str] | None = None,
    logger=None,
) -> list[tuple[str, str]]:
    """Find all terminal directories under configured scan roots.

    Descends exactly 5 levels following the canonical structure:
    scan_root / <dpid> / <target> / <request_id> / <version_dir> / <terminal>

    valid_terminals: set of terminal directory names to match.
    exclusions: dpid directory names to skip entirely.

    Returns list of (source_path, scan_root_path) tuples.
    Skips non-existent scan roots.
    """
    if exclusions is None:
        exclusions = set()
    results = []
    for root in scan_roots:
        root_path = root.path
        target = root.target
        if not os.path.isdir(root_path):
            continue

        # Level 1: dpid directories
        try:
            dpid_entries = list(os.scandir(root_path))
        except OSError:
            if logger:
                logger.warning(
                    "scandir failed, skipping",
                    extra={"path": root_path},
                    exc_info=True,
                )
            continue
        for dpid_entry in dpid_entries:
            if not dpid_entry.is_dir(follow_symlinks=False):
                continue
            if dpid_entry.name in exclusions:
                continue

            # Level 2: only enter the target directory
            target_path = os.path.join(dpid_entry.path, target)
            if not os.path.isdir(target_path):
                if logger:
                    logger.warning(
                        f"dpid missing target directory: {dpid_entry.name}/{target}",
                        extra={"scan_root": root_path, "dpid": dpid_entry.name, "target": target},
                    )
                continue

            # Level 3: request_id directories
            try:
                request_entries = list(os.scandir(target_path))
            except OSError:
                if logger:
                    logger.warning(
                        "scandir failed, skipping",
                        extra={"path": target_path},
                        exc_info=True,
                    )
                continue
            for request_entry in request_entries:
                if not request_entry.is_dir(follow_symlinks=False):
                    continue

                # Level 4: version directories
                try:
                    version_entries = list(os.scandir(request_entry.path))
                except OSError:
                    if logger:
                        logger.warning(
                            "scandir failed, skipping",
                            extra={"path": request_entry.path},
                            exc_info=True,
                        )
                    continue
                for version_entry in version_entries:
                    if not version_entry.is_dir(follow_symlinks=False):
                        continue

                    # Level 5: check for terminal directories
                    try:
                        terminal_entries = list(os.scandir(version_entry.path))
                    except OSError:
                        if logger:
                            logger.warning(
                                "scandir failed, skipping",
                                extra={"path": version_entry.path},
                                exc_info=True,
                            )
                        continue
                    for terminal_entry in terminal_entries:
                        if terminal_entry.is_dir(follow_symlinks=False) and terminal_entry.name in valid_terminals:
                            results.append((terminal_entry.path, root_path))

    return results


def crawl(config, logger, token: str | None = None) -> int:
    """Run a full crawl cycle. Returns count of deliveries processed.

    Two-pass approach:
    1. Walk, parse, inventory, fingerprint, write manifests for all deliveries
    2. Derive failed statuses (pending deliveries superseded by newer versions),
       then POST all deliveries to the registry API with final status values
    """
    manifest_dir = config.crawl_manifest_dir
    error_dir = os.path.join(manifest_dir, "errors")
    os.makedirs(manifest_dir, exist_ok=True)
    os.makedirs(error_dir, exist_ok=True)

    # Load lexicons and build mapping
    lexicons = load_all_lexicons(config.lexicons_dir)
    root_lexicon_map = {}
    valid_terminals = set()
    for root in config.scan_roots:
        lex = lexicons[root.lexicon]
        root_lexicon_map[root.path] = (root.lexicon, lex)
        valid_terminals.update(lex.dir_map.keys())

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

    candidates = walk_roots(config.scan_roots, valid_terminals, exclusions, logger)
    logger.info(f"found {len(candidates)} delivery candidates")

    # --- Pass 1: Parse, inventory, fingerprint, write manifests ---
    # Collect successful deliveries with their file data for pass 2
    parsed_deliveries: list[ParsedDelivery] = []
    delivery_data: dict[str, tuple[list[FileEntry], str, dict]] = {}  # source_path -> (files, fingerprint, manifest)
    delivery_lexicons: dict[str, tuple[str, object]] = {}  # source_path -> (lexicon_id, lexicon)

    for source_path, scan_root in candidates:
        lexicon_id, lexicon = root_lexicon_map[scan_root]
        result = parse_path(source_path, scan_root, exclusions, lexicon.dir_map)

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
            result, files, fingerprint, config.crawler_version, now, lexicon_id,
        )

        # Write crawl manifest
        delivery_id = manifest["delivery_id"]
        manifest_path = os.path.join(manifest_dir, f"{delivery_id}.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        parsed_deliveries.append(result)
        delivery_data[result.source_path] = (files, fingerprint, manifest)
        delivery_lexicons[result.source_path] = (lexicon_id, lexicon)

        # --- Sub-delivery discovery ---
        for sub_dir_name, sub_lexicon_id in lexicon.sub_dirs.items():
            sub_path = os.path.join(source_path, sub_dir_name)
            if not os.path.isdir(sub_path):
                continue

            sub_lexicon = lexicons.get(sub_lexicon_id)
            if sub_lexicon is None:
                # Should not happen — loader validates sub_dirs references.
                # Log and skip defensively.
                logger.warning(
                    f"sub_dirs references unknown lexicon '{sub_lexicon_id}', skipping",
                    extra={"source_path": source_path, "sub_dir": sub_dir_name},
                )
                continue

            sub_delivery = ParsedDelivery(
                request_id=result.request_id,
                project=result.project,
                request_type=result.request_type,
                workplan_id=result.workplan_id,
                dp_id=result.dp_id,
                version=result.version,
                status=result.status,
                source_path=sub_path,
                scan_root=result.scan_root,
            )

            sub_files = inventory_files(sub_path)
            sub_fingerprint = compute_fingerprint(sub_files)
            sub_manifest = build_manifest(
                sub_delivery, sub_files, sub_fingerprint,
                config.crawler_version, now, sub_lexicon_id,
            )

            sub_delivery_id = sub_manifest["delivery_id"]
            sub_manifest_path = os.path.join(manifest_dir, f"{sub_delivery_id}.json")
            with open(sub_manifest_path, "w") as f:
                json.dump(sub_manifest, f, indent=2)

            parsed_deliveries.append(sub_delivery)
            delivery_data[sub_delivery.source_path] = (sub_files, sub_fingerprint, sub_manifest)
            delivery_lexicons[sub_delivery.source_path] = (sub_lexicon_id, sub_lexicon)

    # --- Pass 2: Derive statuses by lexicon, POST to registry ---
    # Build lexicon lookup by ID for derivation (includes all loaded lexicons, not just root ones)
    lexicon_by_id = dict(lexicons)

    # Group deliveries by lexicon_id for derivation
    deliveries_by_lexicon: dict[str, list[ParsedDelivery]] = {}
    for delivery in parsed_deliveries:
        lex_id, _ = delivery_lexicons[delivery.source_path]
        deliveries_by_lexicon.setdefault(lex_id, []).append(delivery)

    # Apply derivation per lexicon
    resolved_deliveries = []
    for lex_id, group_deliveries in deliveries_by_lexicon.items():
        lex = lexicon_by_id[lex_id]
        resolved_deliveries.extend(derive_statuses(group_deliveries, lex))

    processed = 0

    for delivery in resolved_deliveries:
        files, fingerprint, manifest = delivery_data[delivery.source_path]
        delivery_id = manifest["delivery_id"]
        lexicon_id, _ = delivery_lexicons[delivery.source_path]

        payload = {
            "request_id": delivery.request_id,
            "project": delivery.project,
            "request_type": delivery.request_type,
            "workplan_id": delivery.workplan_id,
            "dp_id": delivery.dp_id,
            "version": delivery.version,
            "scan_root": delivery.scan_root,
            "lexicon_id": lexicon_id,
            "status": delivery.status,
            "source_path": delivery.source_path,
            "file_count": len(files),
            "total_bytes": sum(f["size_bytes"] for f in files),
            "fingerprint": fingerprint,
        }
        post_delivery(config.registry_api_url, payload, token=token)

        logger.info(
            f"processed delivery {delivery_id[:12]}... (status={delivery.status})",
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

    token = os.environ.get("REGISTRY_TOKEN")

    try:
        crawl(config, logger, token=token)
    except RegistryClientError as exc:
        if exc.status_code == 401:
            logger.error(
                "registry authentication failed — set REGISTRY_TOKEN environment variable"
            )
        elif exc.status_code == 403:
            logger.error(
                "registry authorization failed — token lacks required role (needs write)"
            )
        else:
            logger.error(f"registry client error: {exc}")
        sys.exit(1)
    except RegistryUnreachableError as exc:
        logger.error(f"registry unreachable, aborting: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
