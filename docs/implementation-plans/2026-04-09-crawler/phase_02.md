# Crawler Service Implementation Plan

**Goal:** Build the filesystem crawler intake layer for the healthcare data pipeline

**Architecture:** Functional Core / Imperative Shell. Pure functions handle parsing, fingerprinting, and manifest construction. Thin imperative shell handles filesystem I/O, manifest writing, and HTTP calls.

**Tech Stack:** Python 3.10+, stdlib only (no new runtime deps), pytest + httpx for testing

**Scope:** 5 phases from original design (phases 1-5)

**Codebase verified:** 2026-04-09

---

## Acceptance Criteria Coverage

This phase implements and tests:

### crawler.AC3: Crawl Manifests
- **crawler.AC3.1 Success:** Manifest written to `pipeline/crawl_manifests/<delivery_id>.json` with all required fields
- **crawler.AC3.2 Success:** Manifest `delivery_id` matches SHA-256 hex of `source_path`
- **crawler.AC3.3 Success:** Manifest `files` array contains complete inventory with filename, size_bytes, modified_at
- **crawler.AC3.4 Success:** Re-crawling same unchanged delivery overwrites manifest with identical content (idempotent)
- **crawler.AC3.5 Success:** Manifest includes `crawler_version` and `crawled_at` timestamp

### crawler.AC4: Error Manifests
- **crawler.AC4.1 Success:** Unparseable path produces error manifest in `pipeline/crawl_manifests/errors/`
- **crawler.AC4.2 Success:** Error manifest contains raw_path, scan_root, error reason, and crawler_version
- **crawler.AC4.3 Success:** Error manifest filename is deterministic hash of raw_path (idempotent on re-crawl)
- **crawler.AC4.4 Edge:** Excluded dp_ids do NOT produce error manifests (they are expected, not errors)

### crawler.AC8: Tests (partial)
- **crawler.AC8.2 Success:** Fingerprint unit tests verify determinism, ordering invariance, and change detection

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Create fingerprint.py with compute_fingerprint()

**Verifies:** crawler.AC8.2

**Files:**
- Create: `src/pipeline/crawler/fingerprint.py`
- Create: `tests/crawler/test_fingerprint.py`

**Implementation:**

`fingerprint.py` is Functional Core — zero I/O. Takes a list of file inventory dicts, sorts by filename, concatenates `filename:size_bytes:modified_at` for each, SHA-256 hashes the result, returns `"sha256:<hex>"`.

```python
# pattern: Functional Core
import hashlib
from typing import TypedDict


class FileEntry(TypedDict):
    filename: str
    size_bytes: int
    modified_at: str


def compute_fingerprint(files: list[FileEntry]) -> str:
    """Compute a deterministic fingerprint from a file inventory.

    Sorts by filename to ensure ordering invariance, then hashes the
    concatenated filename:size_bytes:modified_at strings.

    Returns "sha256:<hex>" or "sha256:empty" if no files.
    """
    if not files:
        return "sha256:" + hashlib.sha256(b"").hexdigest()

    sorted_files = sorted(files, key=lambda f: f["filename"])
    content = "\n".join(
        f"{f['filename']}:{f['size_bytes']}:{f['modified_at']}"
        for f in sorted_files
    )
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()
```

**Testing:**

Tests must verify each AC listed above. Follow project conventions: class-based grouping.

- **crawler.AC8.2 (determinism):** Same file list produces same fingerprint on repeated calls
- **crawler.AC8.2 (ordering invariance):** Files in different order produce identical fingerprint
- **crawler.AC8.2 (change detection):** Changing any field (filename, size_bytes, modified_at) produces a different fingerprint
- **Additional:** Empty file list produces a consistent fingerprint, single file works

Test file structure:

```python
class TestComputeFingerprint:
    # determinism, ordering, change detection, empty, single
```

**Verification:**

Run: `uv run pytest tests/crawler/test_fingerprint.py -v`
Expected: All tests pass

**Commit:** `feat(crawler): implement fingerprint computation`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create manifest.py with build_manifest() and build_error_manifest()

**Verifies:** crawler.AC3.1, crawler.AC3.2, crawler.AC3.3, crawler.AC3.5, crawler.AC4.1, crawler.AC4.2, crawler.AC4.3

**Files:**
- Create: `src/pipeline/crawler/manifest.py`
- Create: `tests/crawler/test_manifest.py`

**Implementation:**

`manifest.py` is Functional Core — zero I/O. Two functions that build manifest dicts without writing to disk.

The `delivery_id` computation MUST match the registry API's algorithm: `hashlib.sha256(source_path.encode()).hexdigest()`. This is the same formula used in `src/pipeline/registry_api/db.py:make_delivery_id()`.

```python
# pattern: Functional Core
import hashlib
from typing import TypedDict
from pipeline.crawler.parser import ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import FileEntry


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
    qa_status: str
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
        "qa_status": parsed.qa_status,
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
```

**Testing:**

Tests must verify each AC listed above. Follow project conventions: class-based grouping.

- **crawler.AC3.1:** `build_manifest()` returns dict with all required fields (crawled_at, crawler_version, delivery_id, source_path, scan_root, parsed, qa_status, fingerprint, files, file_count, total_bytes)
- **crawler.AC3.2:** delivery_id in manifest matches `hashlib.sha256(source_path.encode()).hexdigest()`
- **crawler.AC3.3:** files array contains all entries with filename, size_bytes, modified_at
- **crawler.AC3.5:** manifest includes crawler_version and crawled_at
- **crawler.AC4.1/AC4.2:** `build_error_manifest()` returns dict with raw_path, scan_root, error reason, crawler_version, error_at
- **crawler.AC4.3:** error manifest filename is deterministic hash of raw_path; same raw_path produces same filename

Test file structure:

```python
class TestBuildManifest:
    # AC3.1, AC3.2, AC3.3, AC3.5

class TestBuildErrorManifest:
    # AC4.1, AC4.2, AC4.3
```

Use a helper function following the project's factory pattern:

```python
def make_parsed_delivery(**overrides) -> ParsedDelivery:
    defaults = {
        "request_id": "soc_qar_wp001",
        "project": "soc",
        "request_type": "qar",
        "workplan_id": "wp001",
        "dp_id": "mkscnr",
        "version": "v01",
        "qa_status": "passed",
        "source_path": "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc",
        "scan_root": "/requests/qa",
    }
    defaults.update(overrides)
    return ParsedDelivery(**defaults)
```

**Verification:**

Run: `uv run pytest tests/crawler/test_manifest.py -v`
Expected: All tests pass

**Commit:** `feat(crawler): implement manifest builders`
<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->
