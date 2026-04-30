# GH20 Phase 1: Crawler Functional Core dataclasses

**Goal:** Replace the four `TypedDict` types in `crawler/fingerprint.py` and `crawler/manifest.py` with `@dataclass(frozen=True)`. Replace the bare `tuple[str, ErrorManifest]` returned by `build_error_manifest` with a named `ErrorManifestResult` dataclass.

**Architecture:** Type-layer substitution inside the crawler's Functional Core. The on-disk JSON manifest format is unchanged because `dict(f) for f in files` becomes `dataclasses.asdict(f) for f in files` and `build_manifest` returns a dataclass that callers serialize via `dataclasses.asdict(...)`. No new modules; new types live alongside the functions that produce them.

**Tech Stack:** Python 3.10+ stdlib `dataclasses`; no new dependencies.

**Scope:** 1 of 5 phases of GH20. Touches `src/pipeline/crawler/fingerprint.py`, `src/pipeline/crawler/manifest.py`, and the matching tests in `tests/crawler/test_fingerprint.py` and `tests/crawler/test_manifest.py`. Phase 2 (crawler/main.py) depends on this phase and is the only phase that must come after.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH20.AC1: Crawler Functional Core types are dataclasses
- **GH20.AC1.1 Success:** `FileEntry` in `fingerprint.py` is a frozen dataclass; `compute_fingerprint` accepts and returns correctly typed values.
- **GH20.AC1.2 Success:** `ParsedMetadata`, `CrawlManifest`, `ErrorManifest` in `manifest.py` are frozen dataclasses.
- **GH20.AC1.3 Success:** `build_error_manifest` returns a named `ErrorManifestResult` dataclass with `.filename: str` and `.manifest: ErrorManifest` fields.
- **GH20.AC1.4 Failure:** Passing a dict where a `FileEntry` is expected raises `TypeError`.
- **GH20.AC1.5 Edge:** `build_manifest` constructs `CrawlManifest` using keyword arguments; all fields accounted for.

### GH20.AC5: Cross-cutting — no serialization regression
- **GH20.AC5.3 Success:** Crawl manifest JSON files written to disk are unchanged (verified via golden-output assertion in `test_manifest.py`).

---

## Codebase verification findings

- `src/pipeline/crawler/fingerprint.py:6-9` — `FileEntry(TypedDict)` with three str/int/str fields. The `compute_fingerprint` function (lines 12-28) reads via subscript: `f["filename"]`, `f["size_bytes"]`, `f["modified_at"]`. After dataclass migration, these reads must become attribute access.
- `src/pipeline/crawler/manifest.py:9-16` — `ParsedMetadata(TypedDict)` with six str fields.
- `src/pipeline/crawler/manifest.py:18-30` — `CrawlManifest(TypedDict)` with twelve fields. Note: `files: list[dict]` in the TypedDict — a weakly-typed escape hatch. After migration, the field stays `list[dict]` because the manifest is serialized straight to JSON and consumers (the registry POST payload, the on-disk manifest reader) treat `files` as a JSON-shape list. The dataclass `FileEntry` is converted to plain dicts before insertion via `dataclasses.asdict(f)`.
- `src/pipeline/crawler/manifest.py:33-39` — `ErrorManifest(TypedDict)` with five str fields.
- `src/pipeline/crawler/manifest.py:49-79` — `build_manifest` returns a dict literal. Migration: replace literal with `CrawlManifest(...)` keyword construction. The inner `parsed` field becomes `ParsedMetadata(...)`, and the inner `files` becomes `[dataclasses.asdict(f) for f in files]`.
- `src/pipeline/crawler/manifest.py:82-99` — `build_error_manifest` returns `(filename, manifest_dict)` as a bare tuple. Migration: define `ErrorManifestResult` dataclass with `.filename` and `.manifest` fields; return `ErrorManifestResult(filename=..., manifest=ErrorManifest(...))`.
- `tests/crawler/test_fingerprint.py` — uses subscript reads on `FileEntry` instances inside the file inventory it constructs. Tests construct `FileEntry` via TypedDict syntax `FileEntry(filename=..., size_bytes=..., modified_at=...)` — that syntax keeps working for frozen dataclasses (kwargs-based constructor). Subscript reads inside test assertions, if any, must become attribute reads. (Verify per file.)
- `tests/crawler/test_manifest.py` — heavy subscript access on the returned manifest: `manifest["delivery_id"]`, `manifest["files"][0]["filename"]`, `manifest["parsed"]["request_id"]`, `manifest["error_at"]`, etc. Migration requires rewriting each subscript to attribute access for the top-level `CrawlManifest`/`ErrorManifest` and for the inner `ParsedMetadata`. The `manifest["files"][0]["filename"]` shape stays as nested dict subscript because `files` remains `list[dict]` (see codebase finding above).
- `tests/crawler/test_manifest.py:230-234` — currently does `assert manifest["raw_path"] == ...` where `manifest` is the second element of the tuple from `build_error_manifest`. After migration, the call site changes to `result = build_error_manifest(...)`, then `assert result.manifest.raw_path == ...`.
- `src/pipeline/crawler/main.py:184` — reads `manifest["delivery_id"]`. This is in scope for Phase 2, not Phase 1, but flagged here because Phase 1's change of return type makes this read a `TypeError` — Phase 2 will switch it to `manifest.delivery_id`. **Phase 1 must not be merged ahead of Phase 2 to a long-lived branch without that follow-up landing too**, since a frozen dataclass does not support subscript. (Both phases land together via the security-hardening branch — see "Notes for executor" at the bottom of this file.)

## External dependency findings

N/A — `dataclasses` is stdlib. No external research required.

## Note on the design's "tests pass without modification" claim

The design document (`design.md`) states under AC1 and AC5: "Existing tests pass without modification." That claim is contradicted by `tests/crawler/test_manifest.py`, which subscripts the returned manifest (`manifest["delivery_id"]`, etc.) — operations that raise `TypeError` on a frozen dataclass. The design's "Additional Considerations" section acknowledges this: *"`dict`-style subscript access on a dataclass raises `TypeError`, so any test using `result["field"]` rather than `result.field` will fail."*

This phase resolves the contradiction: **the test file is rewritten to use attribute access**, no test names are added or removed, and no behavioural assertions change. This is consistent with the design's intent (no public API change, no shape change to JSON output) — only the in-Python access syntax changes for tests that touched the now-deprecated dict-style return.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Convert `FileEntry` to a frozen dataclass and update `compute_fingerprint`

**Verifies:** GH20.AC1.1 (FileEntry is a frozen dataclass), GH20.AC1.4 (passing a dict raises TypeError).

**Files:**
- Modify: `src/pipeline/crawler/fingerprint.py` (lines 1-28).

**Implementation:**

Replace the `TypedDict` definition with a frozen dataclass and switch the subscript reads inside `compute_fingerprint` to attribute reads:

```python
# pattern: Functional Core
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FileEntry:
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

    sorted_files = sorted(files, key=lambda f: f.filename)
    content = "\n".join(
        f"{f.filename}:{f.size_bytes}:{f.modified_at}"
        for f in sorted_files
    )
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()
```

Notes:
- Drop the `from typing import TypedDict` import — no longer used.
- The `dataclass(frozen=True)` declaration auto-derives `__init__`, `__eq__`, and `__hash__`. Existing call sites in `crawler/main.py:23` (`FileEntry(filename=..., size_bytes=..., modified_at=...)`) keep working unchanged because dataclasses also accept kwargs.

**Verification:**

```bash
uv run python -c "
from dataclasses import is_dataclass, fields
from pipeline.crawler.fingerprint import FileEntry

assert is_dataclass(FileEntry), 'FileEntry must be a dataclass'
assert FileEntry.__dataclass_params__.frozen, 'FileEntry must be frozen'
fnames = {f.name for f in fields(FileEntry)}
assert fnames == {'filename', 'size_bytes', 'modified_at'}, fnames

# Construction via kwargs still works.
e = FileEntry(filename='a.sas7bdat', size_bytes=10, modified_at='2026-01-01T00:00:00Z')
assert e.filename == 'a.sas7bdat'

# Frozen: assignment raises.
try:
    e.filename = 'b'
except Exception as exc:
    assert type(exc).__name__ == 'FrozenInstanceError', type(exc).__name__
else:
    raise AssertionError('frozen dataclass must not allow attribute assignment')

print('OK')
"
```

Expected output: `OK`.

**Commit:** deferred to Task 5 (single commit for the whole phase).
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Convert `ParsedMetadata`, `CrawlManifest`, `ErrorManifest` to frozen dataclasses; introduce `ErrorManifestResult`; rewrite `build_manifest` and `build_error_manifest`

**Verifies:** GH20.AC1.2, GH20.AC1.3, GH20.AC1.5.

**Files:**
- Modify: `src/pipeline/crawler/manifest.py` (lines 1-99).

**Implementation:**

Full file after the rewrite:

```python
# pattern: Functional Core
import dataclasses
import hashlib
from dataclasses import dataclass

from pipeline.crawler.fingerprint import FileEntry
from pipeline.crawler.parser import ParseError, ParsedDelivery


@dataclass(frozen=True)
class ParsedMetadata:
    request_id: str
    project: str
    request_type: str
    workplan_id: str
    dp_id: str
    version: str


@dataclass(frozen=True)
class CrawlManifest:
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


@dataclass(frozen=True)
class ErrorManifest:
    error_at: str
    crawler_version: str
    raw_path: str
    scan_root: str
    error: str


@dataclass(frozen=True)
class ErrorManifestResult:
    filename: str
    manifest: ErrorManifest


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
    """Build a crawl manifest from parsed metadata and file inventory."""
    delivery_id = make_delivery_id(parsed.source_path)
    return CrawlManifest(
        crawled_at=crawled_at,
        crawler_version=crawler_version,
        delivery_id=delivery_id,
        source_path=parsed.source_path,
        scan_root=parsed.scan_root,
        parsed=ParsedMetadata(
            request_id=parsed.request_id,
            project=parsed.project,
            request_type=parsed.request_type,
            workplan_id=parsed.workplan_id,
            dp_id=parsed.dp_id,
            version=parsed.version,
        ),
        lexicon_id=lexicon_id,
        status=parsed.status,
        fingerprint=fingerprint,
        files=[dataclasses.asdict(f) for f in files],
        file_count=len(files),
        total_bytes=sum(f.size_bytes for f in files),
    )


def build_error_manifest(
    error: ParseError,
    crawler_version: str,
    error_at: str,
) -> ErrorManifestResult:
    """Build an error manifest and its deterministic filename.

    Returns ErrorManifestResult(filename, manifest) where filename is
    the SHA-256 hex of error.raw_path.
    """
    filename = hashlib.sha256(error.raw_path.encode()).hexdigest()
    manifest = ErrorManifest(
        error_at=error_at,
        crawler_version=crawler_version,
        raw_path=error.raw_path,
        scan_root=error.scan_root,
        error=error.reason,
    )
    return ErrorManifestResult(filename=filename, manifest=manifest)
```

Key changes from the previous version:
- All four `TypedDict` definitions become `@dataclass(frozen=True)`.
- New `ErrorManifestResult` dataclass replaces the bare `tuple[str, ErrorManifest]` return type.
- `build_manifest`'s `total_bytes` aggregation becomes `sum(f.size_bytes for f in files)` (attribute access, since `files` are now `FileEntry` dataclasses).
- `build_manifest`'s `files=[dict(f) for f in files]` becomes `files=[dataclasses.asdict(f) for f in files]`. This is required: `dict(f)` raises `TypeError` for a dataclass instance.
- `from typing import TypedDict` is removed.
- `import dataclasses` is added (used for `asdict`); `from dataclasses import dataclass` is added (used for the decorator).

**Verification:**

```bash
uv run python -c "
from dataclasses import is_dataclass
from pipeline.crawler.manifest import (
    ParsedMetadata, CrawlManifest, ErrorManifest, ErrorManifestResult,
    build_manifest, build_error_manifest,
)
from pipeline.crawler.parser import ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import FileEntry

for cls in (ParsedMetadata, CrawlManifest, ErrorManifest, ErrorManifestResult):
    assert is_dataclass(cls), f'{cls.__name__} must be a dataclass'
    assert cls.__dataclass_params__.frozen, f'{cls.__name__} must be frozen'

# build_error_manifest returns ErrorManifestResult.
err = ParseError(raw_path='/x', scan_root='/y', reason='bad')
result = build_error_manifest(err, crawler_version='0.1.0', error_at='2026-01-01T00:00:00Z')
assert isinstance(result, ErrorManifestResult)
assert result.manifest.raw_path == '/x'

# build_manifest returns CrawlManifest with nested ParsedMetadata.
parsed = ParsedDelivery(
    request_id='r', project='p', request_type='t', workplan_id='w',
    dp_id='dp', version='v01', status='pending',
    source_path='/sp', scan_root='/sr',
)
files = [FileEntry(filename='a.sas7bdat', size_bytes=10, modified_at='2026-01-01T00:00:00Z')]
m = build_manifest(parsed, files, 'sha256:fp', '0.1.0', '2026-01-01T00:00:00Z', 'soc.qar')
assert isinstance(m, CrawlManifest)
assert isinstance(m.parsed, ParsedMetadata)
assert m.files == [{'filename': 'a.sas7bdat', 'size_bytes': 10, 'modified_at': '2026-01-01T00:00:00Z'}]
assert m.total_bytes == 10
print('OK')
"
```

Expected output: `OK`.

**Commit:** deferred to Task 5.
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-5) -->
<!-- START_TASK_3 -->
### Task 3: Update `tests/crawler/test_fingerprint.py` to use attribute access

**Verifies:** GH20.AC1.1 (the existing fingerprint tests still pass), GH20.AC5 (no behavioural regression in fingerprint output).

**Files:**
- Modify: `tests/crawler/test_fingerprint.py`.

**Implementation:**

The test file constructs `FileEntry` instances and inspects them. The dataclass keeps the same kwargs constructor, so construction lines need no change. Any subscript reads (`entry["filename"]`, etc.) on `FileEntry` instances must become attribute reads.

Run this grep before editing to find every subscript site:

```bash
grep -nE 'FileEntry\(|files\[[0-9]+\]\["|f\["filename"\]|f\["size_bytes"\]|f\["modified_at"\]' tests/crawler/test_fingerprint.py
```

For every match of the form `<expr>["filename"]` where `<expr>` is a `FileEntry`, rewrite as `<expr>.filename`. Same for `size_bytes` and `modified_at`.

If there are no subscript reads on `FileEntry` (the test file may only construct entries and pass them to `compute_fingerprint`), no rewrites are needed and the file already passes.

**Verification:**

```bash
uv run pytest tests/crawler/test_fingerprint.py -v
```

Expected: all tests pass with the same count as before.

**Commit:** deferred to Task 5.
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Update `tests/crawler/test_manifest.py` to use attribute access on dataclass returns

**Verifies:** GH20.AC1.2, GH20.AC1.3, GH20.AC1.5, GH20.AC5.3.

**Files:**
- Modify: `tests/crawler/test_manifest.py`.

**Implementation:**

Three categories of edits:

1. **Top-level CrawlManifest reads.** Every `manifest["X"]` becomes `manifest.X`. Affected names (per the file): `delivery_id`, `crawled_at`, `crawler_version`, `file_count`, `total_bytes`, `files`, `parsed`, `source_path`, `scan_root`, `lexicon_id`, `status`, `fingerprint`.

2. **Nested ParsedMetadata reads.** `manifest["parsed"]["request_id"]` becomes `manifest.parsed.request_id`. Same for `project`, `request_type`, `workplan_id`, `dp_id`, `version`.

3. **Nested files (still dict).** `manifest["files"][0]["filename"]` becomes `manifest.files[0]["filename"]` — only the outer level changes, because `CrawlManifest.files` is `list[dict]` (FileEntry is converted to dict at construction time).

4. **build_error_manifest unpacking.** Calls of the form

   ```python
   filename, manifest = build_error_manifest(error, "0.1.0", "2026-04-09T15:30:00Z")
   ```

   change to

   ```python
   result = build_error_manifest(error, "0.1.0", "2026-04-09T15:30:00Z")
   filename = result.filename
   manifest = result.manifest
   ```

   Then any `manifest["raw_path"]` etc. become `manifest.raw_path`.

   Alternatively, where the call site only uses the manifest, use `result.manifest.raw_path` directly.

5. **JSON-roundtrip golden assertions.** If a test serialises the manifest to JSON and asserts on the round-tripped dict (e.g., reading the manifest back from disk), wrap the build_manifest result in `dataclasses.asdict(...)` before serialising:

   ```python
   import dataclasses, json
   manifest = build_manifest(...)
   serialised = json.dumps(dataclasses.asdict(manifest))
   ```

   This preserves the on-disk shape (AC5.3). Inspect the test for any direct `json.dumps(manifest)` and update accordingly.

Run this grep to enumerate every subscript site:

```bash
grep -nE 'manifest\[' tests/crawler/test_manifest.py
```

Each match needs review. None of the assertion semantics change; only the access syntax changes.

**Edge case — assertions on the `parsed` sub-dict shape:** if a test asserts on the entire `parsed` dict (e.g. `assert manifest["parsed"] == {"request_id": ..., ...}`), the migration changes that to `assert manifest.parsed == ParsedMetadata(request_id=..., ...)`. Frozen dataclass equality is structural, so the assertion remains semantically identical.

**Verification:**

```bash
uv run pytest tests/crawler/test_manifest.py -v
```

Expected: all tests pass with the same count as before. No test names added or removed.

**Commit:** deferred to Task 5.
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Run the broader test suite (Phase 1 surface), commit

**Verifies:** GH20.AC1 in aggregate; no regressions inside the crawler Functional Core.

**Files:** none changed in this task.

**Implementation:**

Run the test surfaces touched by Phase 1 plus anything that imports `FileEntry` / the manifest types:

```bash
uv run pytest tests/crawler/test_fingerprint.py tests/crawler/test_manifest.py -v
```

Then run the full suite to surface any unanticipated subscript sites elsewhere (the `tests/crawler/test_main.py` suite and `tests/registry_api` suites import `crawler/main.py` indirectly through `crawler.fingerprint` / `crawler.manifest`):

```bash
uv run pytest -x
```

If `tests/crawler/test_main.py` fails with `TypeError: 'CrawlManifest' object is not subscriptable` (or similar on the `manifest["delivery_id"]` read in `crawler/main.py:184`), that is the Phase 2 work — Phase 1 alone is incomplete without Phase 2 because `main.py` still subscripts. **The intended commit cadence is: land Phase 1 + Phase 2 together** (one merge), since Phase 1 in isolation breaks `crawler/main.py`. See "Notes for executor" below.

If `pytest -x` fails only at sites that Phase 2 will fix, document the failure list and proceed to Phase 2 before committing. Otherwise, fix any unexpected failures here.

**Commit:**

```bash
git add src/pipeline/crawler/fingerprint.py \
        src/pipeline/crawler/manifest.py \
        tests/crawler/test_fingerprint.py \
        tests/crawler/test_manifest.py
```

Defer the commit until after Phase 2's edits, then commit Phase 1 + Phase 2 together:

```bash
git commit -m "refactor(crawler): replace TypedDict with frozen dataclasses (GH20 phases 1-2)"
```

Rationale: `crawler/main.py` reads `manifest["delivery_id"]` (line 184) and unpacks `delivery_data` tuples; both break when Phase 1 lands without Phase 2. Treat phases 1 and 2 as one unit at the commit level. Phase 3 onward is independent and commits separately.
<!-- END_TASK_5 -->
<!-- END_SUBCOMPONENT_B -->

---

## Phase 1 Done When

- `FileEntry` is `@dataclass(frozen=True)` in `crawler/fingerprint.py`; no `TypedDict` imports remain in that file.
- `ParsedMetadata`, `CrawlManifest`, `ErrorManifest`, `ErrorManifestResult` are `@dataclass(frozen=True)` in `crawler/manifest.py`; no `TypedDict` imports remain in that file.
- `build_manifest` constructs and returns a `CrawlManifest` instance via keyword arguments; the inner `files` field is built with `dataclasses.asdict(f) for f in files` (so JSON output is unchanged).
- `build_error_manifest` returns `ErrorManifestResult(filename, manifest)`.
- `tests/crawler/test_fingerprint.py` and `tests/crawler/test_manifest.py` pass with the same number of tests as before. No test names added or removed.

## Notes for executor

- **Commit cadence:** Phase 1 and Phase 2 must commit together (single commit). `crawler/main.py:184` reads `manifest["delivery_id"]`, which breaks under a dataclass return. Only Phase 2 fixes that read. Hold the Phase 1 git add until Phase 2's edits are also staged.
- **No worktree:** All work happens on the existing `security-hardening` branch (per team-lead instructions for the GH20 implementation plan).
- **Conflict surface (rebase ordering):**
  - **GH17** (ruff format) touches every file's whitespace; if GH17 has not yet landed by the time Phase 1 starts, run `uv run ruff format src/pipeline/crawler/fingerprint.py src/pipeline/crawler/manifest.py` after the rewrite to keep the formatting diff out of the GH20 commit.
  - **GH19** (type annotations) overlaps signatures in `manifest.py` (`build_manifest`, `build_error_manifest`). The DAG (`docs/project/DAG.md`) places GH19 at Tier 1 and GH20 at Tier 3, so GH19 should already be merged when GH20 starts. If not, the dataclass migration's signatures may need to harmonise with whatever annotation policy GH19 chose.
  - **GH27** (pattern labels) prepends the `# pattern: Functional Core` comment to line 1 of these files. Both files already carry that label (line 1 of each), so this is a no-op for Phase 1.
  - **GH23** (exception logging) does not touch `fingerprint.py` or `manifest.py` — no overlap.
- **Status of design's "no-test-modification" claim:** the codebase verification above documents why `tests/crawler/test_manifest.py` MUST be modified. The claim is a hold-over from the design's first draft; the rewrite preserves test names and assertion semantics, only changing access syntax. This is the minimum necessary change.
- **`files` field stays `list[dict]`:** `CrawlManifest.files` is intentionally not `list[FileEntry]`. The manifest is JSON-serialised to disk (line 187 of `crawler/main.py`), and the registry POST payload reconstructs file metadata from a dict shape. Keeping `files: list[dict]` matches both consumers without forcing a JSON-encoder dance for `FileEntry`. Inside the crawler, `inventory_files` still returns `list[FileEntry]`; the dataclass-to-dict conversion happens only at the manifest construction boundary.
