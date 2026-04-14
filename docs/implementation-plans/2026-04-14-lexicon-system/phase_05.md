# Lexicon System Implementation Plan — Phase 5: Crawler Generalisation

**Goal:** Crawler uses lexicon `dir_map` and derivation hooks instead of hardcoded QA logic. Terminal directory matching, status assignment, derivation, and POST payloads all driven by lexicon configuration.

**Architecture:** `parse_path()` receives a `dir_map` dict instead of hardcoding `msoc`/`msoc_new`. `walk_roots()` uses dir_map keys to filter terminal directories. `derive_qa_statuses()` renamed to `derive_statuses()` and calls `lexicon.derive_hook` when present. `crawl()` passes `lexicon_id` and `status` in POST payload. Manifest updated to carry `status` and `lexicon_id` instead of `qa_status`.

**Tech Stack:** Python 3.10+ stdlib

**Scope:** Phase 5 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### lexicon-system.AC5: Crawler generalisation
- **lexicon-system.AC5.1 Success:** Terminal directory in `dir_map` maps to correct status
- **lexicon-system.AC5.2 Failure:** Terminal directory not in `dir_map` produces ParseError
- **lexicon-system.AC5.3 Success:** Derivation hook called when `derive_hook` is set
- **lexicon-system.AC5.4 Success:** No derivation when `derive_hook` is null
- **lexicon-system.AC5.5 Success:** QA hook marks superseded pending as failed (identical to current behaviour)
- **lexicon-system.AC5.6 Success:** Crawler POST payload includes `lexicon_id` and `status`

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Update `parse_path()` to use dir_map

**Verifies:** None (implementation — tested in Task 4)

**Files:**
- Modify: `src/pipeline/crawler/parser.py:32-113` (parse_path function)
- Modify: `src/pipeline/crawler/parser.py:7-18` (ParsedDelivery dataclass)

**Implementation:**

**ParsedDelivery dataclass** (lines 7-18):

Rename `qa_status` field to `status`:

```python
@dataclass(frozen=True)
class ParsedDelivery:
    request_id: str
    project: str
    request_type: str
    workplan_id: str
    dp_id: str
    version: str
    status: str
    source_path: str
    scan_root: str
```

**parse_path function** (lines 32-113):

Add `dir_map: dict[str, str]` parameter. Replace the hardcoded `msoc`/`msoc_new` check with a dir_map lookup on the terminal directory name.

Current code (lines 44-54):
```python
if path.endswith("/msoc"):
    qa_status = "passed"
elif path.endswith("/msoc_new"):
    qa_status = "pending"
else:
    return ParseError(...)
```

Replace with:
```python
terminal_dir = parts[-1]  # after splitting the path
if terminal_dir not in dir_map:
    return ParseError(
        raw_path=path,
        scan_root=scan_root,
        reason=f"terminal directory '{terminal_dir}' not in dir_map",
    )
status = dir_map[terminal_dir]
```

The full updated function signature:

```python
def parse_path(
    path: str,
    scan_root: str,
    exclusions: set[str],
    dir_map: dict[str, str],
) -> ParsedDelivery | ParseError | None:
```

Extract `terminal_dir` from the path parts first (it's the last segment after stripping trailing slashes), then look it up in `dir_map`. Remove the `path.endswith("/msoc")` logic entirely. Update the `ParsedDelivery` construction to use `status=status` instead of `qa_status=qa_status`.

**Commit:** `feat: generalize parse_path to use dir_map instead of hardcoded msoc/msoc_new`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update `derive_qa_statuses()` → `derive_statuses()` and update `walk_roots()`

**Verifies:** None (implementation — tested in Task 4)

**Files:**
- Modify: `src/pipeline/crawler/parser.py:126-156` (derive_qa_statuses)
- Modify: `src/pipeline/crawler/main.py:86-93` (walk_roots terminal directory check)

**Implementation:**

**derive_statuses** (replaces `derive_qa_statuses` at lines 126-156):

Rename to `derive_statuses`. Add `lexicon` parameter. When `lexicon.derive_hook` is not None, call it. Otherwise, keep the existing inline QA supersession logic as a fallback (it will be removed in Phase 6 when the hook module is created).

```python
from pipeline.lexicons.models import Lexicon

def derive_statuses(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
    """Apply lexicon derivation hook if defined.

    If lexicon.derive_hook is set, delegates to the hook function.
    If lexicon.derive_hook is None, applies the inline QA supersession
    logic (pending non-highest versions → failed). This inline logic
    will be removed in Phase 6 when the hook module is created.

    Returns a new list — does not mutate the input.
    """
    if lexicon.derive_hook is not None:
        return lexicon.derive_hook(deliveries, lexicon)

    # Inline fallback: QA supersession logic (kept until Phase 6 extracts it)
    if not deliveries:
        return []

    result = []
    sorted_deliveries = sorted(deliveries, key=_group_key)

    for _key, group in groupby(sorted_deliveries, key=_group_key):
        group_list = list(group)
        if len(group_list) == 1:
            result.append(group_list[0])
            continue

        by_version = sorted(group_list, key=_version_sort_key, reverse=True)
        highest_version = by_version[0].version

        for delivery in group_list:
            if delivery.status == "pending" and delivery.version != highest_version:
                result.append(replace(delivery, status="failed"))
            else:
                result.append(delivery)

    return result
```

Keep `_group_key` and `_version_sort_key` helper functions (lines 116-123) — they are still used by the inline fallback. Phase 6 will remove them when extracting the logic to the hook module. Rename references from `qa_status` to `status` and `replace(delivery, qa_status=...)` to `replace(delivery, status=...)`.

**walk_roots** (line 92):

Currently hardcodes `terminal_entry.name in ("msoc", "msoc_new")`. This needs to accept a set of valid terminal directory names derived from all loaded lexicons' dir_maps.

Update `walk_roots` signature to accept valid terminal names:

```python
def walk_roots(
    scan_roots: list,
    valid_terminals: set[str],
    logger=None,
) -> list[tuple[str, str]]:
```

Replace line 92:
```python
# Old:
if terminal_entry.is_dir(follow_symlinks=False) and terminal_entry.name in ("msoc", "msoc_new"):
# New:
if terminal_entry.is_dir(follow_symlinks=False) and terminal_entry.name in valid_terminals:
```

**Update `__init__.py` re-exports** at `src/pipeline/crawler/__init__.py`:

Replace `derive_qa_statuses` with `derive_statuses`:

```python
from pipeline.crawler.parser import (
    parse_path as parse_path,
    derive_statuses as derive_statuses,
    ParsedDelivery as ParsedDelivery,
    ParseError as ParseError,
)
```

**Commit:** `feat: rename derive_qa_statuses to derive_statuses with lexicon hook support`

<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Update `crawl()` and manifest to use lexicon fields

**Verifies:** None (implementation — tested in Task 4)

**Files:**
- Modify: `src/pipeline/crawler/main.py:98-203` (crawl function)
- Modify: `src/pipeline/crawler/main.py:9` (imports)
- Modify: `src/pipeline/crawler/manifest.py:18-29` (CrawlManifest TypedDict)
- Modify: `src/pipeline/crawler/manifest.py:48-76` (build_manifest function)

**Implementation:**

**CrawlManifest** (manifest.py lines 18-29):

Replace `qa_status: str` with `status: str` and add `lexicon_id: str`:

```python
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
```

**build_manifest** (manifest.py lines 48-76):

Add `lexicon_id: str` parameter. Replace `"qa_status": parsed.qa_status` with `"lexicon_id": lexicon_id` and `"status": parsed.status`:

```python
def build_manifest(
    parsed: ParsedDelivery,
    files: list[FileEntry],
    fingerprint: str,
    crawler_version: str,
    crawled_at: str,
    lexicon_id: str,
) -> CrawlManifest:
```

**crawl()** (main.py lines 98-203):

The crawl function needs access to loaded lexicons. It should receive them via config (already loaded at startup) or load them itself. Since `config.lexicons_dir` is now available, load lexicons at the start of `crawl()`:

```python
from pipeline.lexicons import load_all_lexicons

def crawl(config, logger) -> int:
    lexicons = load_all_lexicons(config.lexicons_dir)
```

Build a mapping of scan_root_path → lexicon for quick lookup, and collect all valid terminal directory names:

```python
    root_lexicon_map = {}
    valid_terminals = set()
    for root in config.scan_roots:
        lex = lexicons[root.lexicon]
        root_lexicon_map[root.path] = (root.lexicon, lex)
        valid_terminals.update(lex.dir_map.keys())
```

Pass `valid_terminals` to `walk_roots()`:

```python
    candidates = walk_roots(config.scan_roots, valid_terminals, logger)
```

In Pass 1, pass `dir_map` to `parse_path`:

```python
    for source_path, scan_root in candidates:
        lexicon_id, lexicon = root_lexicon_map[scan_root]
        result = parse_path(source_path, scan_root, exclusions, lexicon.dir_map)
```

In the manifest build, pass `lexicon_id`:

```python
        manifest = build_manifest(
            result, files, fingerprint, config.crawler_version, now, lexicon_id,
        )
```

In Pass 2, group deliveries by lexicon and call `derive_statuses` per group:

```python
    # Group by scan_root to find their lexicon
    from itertools import groupby

    # Build deliveries with their lexicon info
    delivery_lexicons = {}
    for delivery in parsed_deliveries:
        lex_id, lex = root_lexicon_map[delivery.scan_root]
        delivery_lexicons[delivery.source_path] = (lex_id, lex)

    # Group by lexicon_id for derivation
    deliveries_by_lexicon: dict[str, list[ParsedDelivery]] = {}
    for delivery in parsed_deliveries:
        lex_id, _ = delivery_lexicons[delivery.source_path]
        deliveries_by_lexicon.setdefault(lex_id, []).append(delivery)

    # Direct lexicon lookup by ID (built during setup)
    lexicon_by_id = {lid: lex for lid, lex in root_lexicon_map.values()}

    resolved_deliveries = []
    for lex_id, group_deliveries in deliveries_by_lexicon.items():
        lex = lexicon_by_id[lex_id]
        resolved_deliveries.extend(derive_statuses(group_deliveries, lex))
```

In the POST payload, replace `qa_status` with `status` and `lexicon_id`:

```python
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
```

Update the log message to use `status` instead of `qa_status`.

**Commit:** `feat: update crawl() to use lexicon-driven dir_map, derivation, and POST payload`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Update crawler tests and write new AC5 tests

**Verifies:** lexicon-system.AC5.1, lexicon-system.AC5.2, lexicon-system.AC5.3, lexicon-system.AC5.4, lexicon-system.AC5.5, lexicon-system.AC5.6

**Files:**
- Modify: `tests/crawler/test_parser.py` (update all `qa_status` references to `status`, add `dir_map` param to `parse_path` calls)
- Modify: `tests/crawler/conftest.py` (update `delivery_tree` fixture if it references `qa_status`)
- Create or modify: test file for crawler AC5 tests

**Implementation:**

All existing `parse_path` calls need the `dir_map` parameter added. The existing tests use paths ending in `msoc` and `msoc_new`, so pass the standard dir_map: `{"msoc": "passed", "msoc_new": "pending"}`.

Update `ParsedDelivery` field assertions: `result.qa_status` → `result.status`.

Update `derive_qa_statuses` calls → `derive_statuses` with a lexicon parameter.

**Testing:**

Tests must verify each AC listed above:

- **lexicon-system.AC5.1:** Call `parse_path()` with a path ending in a terminal directory that's a key in `dir_map`. Assert returned `ParsedDelivery.status` matches the `dir_map` value. Test with multiple dir_map entries.
- **lexicon-system.AC5.2:** Call `parse_path()` with a path ending in a terminal directory NOT in `dir_map`. Assert `ParseError` returned with reason mentioning "not in dir_map".
- **lexicon-system.AC5.3:** Create a `Lexicon` with `derive_hook` set to a test function. Call `derive_statuses()`. Assert the hook function was called and its return value used.
- **lexicon-system.AC5.4:** Create a `Lexicon` with `derive_hook=None`. Call `derive_statuses()`. Assert deliveries returned unchanged.
- **lexicon-system.AC5.5:** This is tested in Phase 6 (QA hook implementation). Here, verify derive_statuses correctly delegates to the hook — the actual hook logic is tested there.
- **lexicon-system.AC5.6:** This requires integration testing of the full crawl flow. Create a test that builds a directory tree, runs the crawler with a lexicon config, and verifies the POST payload contains `lexicon_id` and `status` (no `qa_status`). Mock `post_delivery` to capture the payload.

For the `delivery_tree` conftest fixture, update the `qa_status` parameter name to `status` and update the directory creation logic to use a `dir_map` parameter (or keep `msoc`/`msoc_new` as the directory names since those are physical directories — just rename the parameter).

**Verification:**

```bash
uv run pytest tests/crawler/ -v
```

Expected: All tests pass.

**Commit:** `test: update crawler tests for lexicon-driven parsing, add AC5.1-AC5.6`

<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->

<!-- START_TASK_5 -->
### Task 5: Run full test suite, verify no regressions

**Verifies:** None (regression check)

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: All tests pass.

**Commit:** No commit if clean.

<!-- END_TASK_5 -->
