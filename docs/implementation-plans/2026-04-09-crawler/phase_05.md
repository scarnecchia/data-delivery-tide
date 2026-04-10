# Crawler Service Implementation Plan

**Goal:** Build the filesystem crawler intake layer for the healthcare data pipeline

**Architecture:** Functional Core / Imperative Shell. Pure functions handle parsing, fingerprinting, and manifest construction. Thin imperative shell handles filesystem I/O, manifest writing, and HTTP calls.

**Tech Stack:** Python 3.10+, stdlib only (no new runtime deps), pytest + httpx for testing

**Scope:** 5 phases from original design (phases 1-5)

**Codebase verified:** 2026-04-09

---

## Acceptance Criteria Coverage

This phase implements and tests:

### crawler.AC2: Filesystem Crawler
- **crawler.AC2.1 Success:** Crawler discovers all `msoc` and `msoc_new` directories under configured scan_roots
- **crawler.AC2.2 Success:** File inventory includes all `.sas7bdat` files with correct size_bytes and modified_at
- **crawler.AC2.3 Success:** Crawler POSTs valid DeliveryCreate payload to registry API for each parsed delivery
- **crawler.AC2.4 Success:** Crawler processes multiple scan_roots in a single run
- **crawler.AC2.5 Failure:** Non-existent scan_root is logged and skipped (does not abort entire crawl)
- **crawler.AC2.6 Edge:** Empty delivery directory (no .sas7bdat files) is still processed with file_count=0
- **crawler.AC2.7 Success:** Pending delivery with a newer version for the same workplan+dp_id is POSTed with qa_status=`failed`
- **crawler.AC2.8 Success:** Pending delivery that is the highest version for its workplan+dp_id retains qa_status=`pending`
- **crawler.AC2.9 Success:** Passed delivery (`msoc`) is never marked as `failed` regardless of newer versions

### crawler.AC3: Crawl Manifests (partial — writing to disk)
- **crawler.AC3.4 Success:** Re-crawling same unchanged delivery overwrites manifest with identical content (idempotent)

### crawler.AC4: Error Manifests (partial — writing to disk)
- **crawler.AC4.4 Edge:** Excluded dp_ids do NOT produce error manifests (they are expected, not errors)

### crawler.AC5: Retry and Abort (partial — exit code)
- **crawler.AC5.4 Failure:** Crawler exits non-zero when RegistryUnreachableError is raised

### crawler.AC7: Idempotency
- **crawler.AC7.1 Success:** Running crawler twice on same directory tree produces identical registry state and manifests
- **crawler.AC7.2 Success:** Unchanged fingerprint means registry `last_updated_at` is not modified on re-crawl

### crawler.AC8: Tests (partial)
- **crawler.AC8.3 Success:** Integration tests use temp directory trees and mocked HTTP
- **crawler.AC8.4 Success:** Test fixtures follow existing project conventions (class-based grouping, factory helpers)

---

<!-- START_TASK_1 -->
### Task 1: Add crawl_manifest_dir and crawler_version to PipelineConfig

**Verifies:** None (infrastructure — config plumbing for Phase 5)

**Files:**
- Modify: `src/pipeline/config.py:15-23` (PipelineConfig dataclass — will have dp_id_exclusions from Phase 1)
- Modify: `src/pipeline/config.py:40-49` (load_config function)
- Modify: `pipeline/config.json` (add new fields)

**Implementation:**

Add two new fields to `PipelineConfig`:

```python
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
```

In `load_config()`, add to the return:

```python
crawl_manifest_dir=data.get("crawl_manifest_dir", "pipeline/crawl_manifests"),
crawler_version=data.get("crawler_version", "1.0.0"),
```

In `pipeline/config.json`, add:

```json
"crawl_manifest_dir": "pipeline/crawl_manifests",
"crawler_version": "1.0.0"
```

**Verification:**

Run: `uv run pytest tests/test_config.py -v`
Expected: All existing config tests still pass

**Commit:** `feat(crawler): add crawl_manifest_dir and crawler_version to config`
<!-- END_TASK_1 -->

<!-- START_SUBCOMPONENT_A (tasks 2-5) -->

<!-- START_TASK_2 -->
### Task 2: Add derive_qa_statuses() pure function to parser.py

**Verifies:** crawler.AC2.7, crawler.AC2.8, crawler.AC2.9

**Files:**
- Modify: `src/pipeline/crawler/parser.py` (add derive_qa_statuses function)
- Modify: `tests/crawler/test_parser.py` (add tests for failed derivation)

**Implementation:**

Add a pure function to `parser.py` that takes a list of `ParsedDelivery` objects and returns a new list with `qa_status` resolved — specifically, any `pending` delivery that has been superseded by a higher version within the same `(workplan_id, dp_id)` group gets replaced with a copy where `qa_status="failed"`.

Since `ParsedDelivery` is frozen, use `dataclasses.replace()` to create modified copies.

```python
from dataclasses import replace
from itertools import groupby


def derive_qa_statuses(deliveries: list[ParsedDelivery]) -> list[ParsedDelivery]:
    """Derive 'failed' status for pending deliveries superseded by newer versions.

    Within each (workplan_id, dp_id) group, any pending delivery that is NOT
    the highest version is marked as failed. Passed deliveries are never changed.

    Returns a new list — does not mutate the input.
    """
    result = []
    key_fn = lambda d: (d.workplan_id, d.dp_id)
    sorted_deliveries = sorted(deliveries, key=key_fn)

    for _key, group in groupby(sorted_deliveries, key=key_fn):
        group_list = list(group)
        if len(group_list) == 1:
            result.append(group_list[0])
            continue

        # Sort by version descending to find the highest
        by_version = sorted(group_list, key=lambda d: d.version, reverse=True)
        highest_version = by_version[0].version

        for delivery in group_list:
            if delivery.qa_status == "pending" and delivery.version != highest_version:
                result.append(replace(delivery, qa_status="failed"))
            else:
                result.append(delivery)

    return result
```

**Testing:**

- **crawler.AC2.7:** Two deliveries for same workplan+dp_id: v01 pending, v02 pending. After derivation, v01 is `failed`, v02 is `pending`.
- **crawler.AC2.8:** Single pending delivery (no newer version). After derivation, remains `pending`.
- **crawler.AC2.9:** v01 is `passed` (msoc), v02 is `pending`. After derivation, v01 stays `passed` (never changed), v02 stays `pending`.
- **Additional:** Multiple groups — ensure derivation is scoped per (workplan_id, dp_id), not global. Empty list returns empty list.

Test class:

```python
class TestDeriveQaStatuses:
    # AC2.7, AC2.8, AC2.9
```

**Verification:**

Run: `uv run pytest tests/crawler/test_parser.py -v`
Expected: All tests pass

**Commit:** `feat(crawler): add failed status derivation for superseded deliveries`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Create crawler main.py with crawl() orchestration function

**Verifies:** crawler.AC2.1, crawler.AC2.2, crawler.AC2.3, crawler.AC2.4, crawler.AC2.5, crawler.AC2.6, crawler.AC2.7, crawler.AC3.4, crawler.AC4.4, crawler.AC5.4

**Files:**
- Create: `src/pipeline/crawler/main.py`

**Implementation:**

`main.py` is the Imperative Shell — it performs all I/O (filesystem walking, file stats, manifest writing, HTTP posting, logging). It orchestrates the Functional Core modules (parser, fingerprint, manifest).

The module provides:
1. `inventory_files(source_path)` — walks a directory, stats all `.sas7bdat` files, returns list of FileEntry dicts
2. `walk_roots(scan_roots)` — yields `(source_path, scan_root)` tuples for every `msoc` or `msoc_new` directory found under any scan root
3. `crawl(config, logger)` — main orchestration in two passes: (a) walk, parse, inventory, fingerprint, write manifests; (b) derive failed statuses, then POST all deliveries to registry
4. `main()` — entry point that loads config, creates logger, calls `crawl()`, handles `RegistryUnreachableError` with `sys.exit(1)`

```python
# pattern: Imperative Shell
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline.config import settings
from pipeline.json_logging import get_logger
from pipeline.crawler.parser import parse_path, derive_qa_statuses, ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import compute_fingerprint, FileEntry
from pipeline.crawler.manifest import build_manifest, build_error_manifest, make_delivery_id
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
    Skips non-existent scan roots with a logged warning (handled by caller).
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
```

**Verification:**

This task is verified by the integration tests in Task 3.

**Commit:** `feat(crawler): implement crawler orchestrator`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Create conftest.py and integration tests for crawler

**Verifies:** crawler.AC2.1, crawler.AC2.2, crawler.AC2.3, crawler.AC2.4, crawler.AC2.5, crawler.AC2.6, crawler.AC2.7, crawler.AC3.4, crawler.AC4.4, crawler.AC5.4, crawler.AC7.1, crawler.AC7.2, crawler.AC8.3, crawler.AC8.4

**Files:**
- Create: `tests/crawler/conftest.py`
- Create: `tests/crawler/test_main.py`

**Implementation:**

`conftest.py` provides fixtures for creating temporary directory trees that mimic the network share structure, and for creating mock config objects. Follow existing project conventions: class-based test grouping, factory helpers.

Fixtures:

```python
import os
import pytest
from dataclasses import dataclass


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
```

Factory helper for mock config:

```python
def make_crawler_config(scan_roots, manifest_dir, **overrides):
    """Create a config-like object for crawler tests."""
    ...
```

Integration tests use temp directory trees and mock the HTTP calls via `unittest.mock.patch`.

**Testing:**

- **crawler.AC2.1:** Create temp tree with both `msoc` and `msoc_new` directories, run `walk_roots()`, assert both discovered
- **crawler.AC2.2:** Create `.sas7bdat` files with known sizes, run `inventory_files()`, assert correct filename, size_bytes, modified_at
- **crawler.AC2.3:** Run `crawl()` with mocked `post_delivery`, assert it was called with valid payload matching DeliveryCreate schema fields
- **crawler.AC2.4:** Create temp trees under two different scan roots, run `crawl()`, assert deliveries from both roots processed
- **crawler.AC2.5:** Configure a non-existent scan root alongside a valid one, run `crawl()`, assert warning logged and valid root still processed
- **crawler.AC2.6:** Create delivery dir with no `.sas7bdat` files, run `crawl()`, assert manifest has file_count=0 and delivery is still posted
- **crawler.AC3.4:** Run `crawl()` twice on same tree, read manifest files, assert identical content
- **crawler.AC4.4:** Create tree with excluded dp_id, run `crawl()`, assert no error manifest written for that path
- **crawler.AC5.4:** Mock `post_delivery` to raise `RegistryUnreachableError`, assert `main()` calls `sys.exit(1)` (or use pytest.raises(SystemExit))
- **crawler.AC2.7:** Create two pending deliveries for same workplan+dp_id (v01 and v02), run `crawl()`, assert v01 is POSTed with qa_status=`failed` and v02 with qa_status=`pending`
- **crawler.AC7.1:** Run `crawl()` twice, assert manifests identical and same number of API calls made
- **crawler.AC7.2:** Run `crawl()` twice with same tree, verify fingerprint unchanged in both POST payloads (mock captures call args)

Test file structure:

```python
class TestWalkRoots:
    # AC2.1, AC2.4, AC2.5

class TestInventoryFiles:
    # AC2.2, AC2.6

class TestCrawl:
    # AC2.3, AC2.7, AC3.4, AC4.4, AC7.1, AC7.2

class TestMain:
    # AC5.4
```

**Verification:**

Run: `uv run pytest tests/crawler/test_main.py -v`
Expected: All tests pass

Run: `uv run pytest`
Expected: All tests across entire project pass

**Commit:** `feat(crawler): add integration tests for crawler orchestrator`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Update crawler __init__.py

**Verifies:** None (infrastructure — clean module exports)

**Files:**
- Modify: `src/pipeline/crawler/__init__.py` (currently empty)

**Implementation:**

Add the pattern comment and public API exports:

```python
from pipeline.crawler.parser import parse_path, derive_qa_statuses, ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import compute_fingerprint
from pipeline.crawler.manifest import build_manifest, build_error_manifest, make_delivery_id
from pipeline.crawler.http import post_delivery, RegistryUnreachableError
```

Note: No `# pattern:` comment — barrel/re-export files are exempt from FCIS classification.

**Verification:**

Run: `uv run pytest`
Expected: All tests pass (imports work correctly)

**Commit:** `feat(crawler): wire up crawler module exports`
<!-- END_TASK_5 -->

<!-- END_SUBCOMPONENT_A -->
