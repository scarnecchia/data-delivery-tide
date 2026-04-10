# Crawler Structured Traversal Implementation Plan — Phase 2

**Goal:** Replace unconstrained `os.walk` with level-by-level `os.scandir` descent constrained by the `target` field from each scan root

**Architecture:** Rewrite `walk_roots` to descend exactly 5 levels using `os.scandir` at each level. At level 2 (under dpid), only enter the directory matching `root.target`. Add a `logger` parameter to `walk_roots` so it can warn when a dpid is missing its target subdirectory. Update `crawl()` to pass the logger through. Update all existing test fixtures to include the `target` field.

**Tech Stack:** Python 3.10+, stdlib os, logging

**Scope:** 2 phases from original design (phase 2 of 2)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### crawler-structured-traversal.AC2: Traversal constrained to canonical structure
- **crawler-structured-traversal.AC2.1 Success:** `msoc` directory at canonical depth (`<dpid>/<target>/<request_id>/<version_dir>/msoc`) is discovered
- **crawler-structured-traversal.AC2.2 Success:** `msoc_new` directory at canonical depth is discovered
- **crawler-structured-traversal.AC2.3 Failure:** `msoc` directory inside a sibling of `target` (e.g. `compare/`) is not discovered
- **crawler-structured-traversal.AC2.4 Failure:** `msoc` directory at wrong depth (e.g. directly under dpid) is not discovered
- **crawler-structured-traversal.AC2.5 Failure:** `msoc` directory nested too deep (extra level between version_dir and msoc) is not discovered
- **crawler-structured-traversal.AC2.6 Success:** Multiple dpids under the same scan root are all traversed
- **crawler-structured-traversal.AC2.7 Success:** Multiple version directories under the same request_id are all discovered

### crawler-structured-traversal.AC3: Logging and diagnostics
- **crawler-structured-traversal.AC3.1 Success:** Warning logged when a dpid directory is missing its target subdirectory
- **crawler-structured-traversal.AC3.2 Success:** No warning logged when target subdirectory exists

### crawler-structured-traversal.AC4: Backward compatibility
- **crawler-structured-traversal.AC4.2 Success:** `walk_roots` return type and signature remain compatible with callers

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Rewrite `walk_roots` with structured descent

**Verifies:** crawler-structured-traversal.AC2.1, crawler-structured-traversal.AC2.2, crawler-structured-traversal.AC2.3, crawler-structured-traversal.AC2.4, crawler-structured-traversal.AC2.5, crawler-structured-traversal.AC2.6, crawler-structured-traversal.AC2.7, crawler-structured-traversal.AC3.1, crawler-structured-traversal.AC3.2, crawler-structured-traversal.AC4.2

**Files:**
- Modify: `src/pipeline/crawler/main.py:33-49` (replace `walk_roots` function)
- Modify: `src/pipeline/crawler/main.py:78` (update `walk_roots` call in `crawl()` to pass logger)

**Implementation:**

Replace the `walk_roots` function at lines 33-49 with a structured 5-level `os.scandir` descent. Add `logger` as an optional parameter (defaulting to `None` for backward compatibility with any direct callers).

**Note on AC4.2 (signature compatibility):** The design states "function signature remains `walk_roots(scan_roots)`." Adding `logger=None` is a controlled deviation — it's backward-compatible because the parameter is optional with a default. All existing callers (including `crawl()` before this change, and all tests) continue to work without modification. AC4.2 is satisfied: the return type is unchanged and no caller breaks.

The new `walk_roots`:

```python
def walk_roots(scan_roots: list, logger=None) -> list[tuple[str, str]]:
    """Find all msoc/msoc_new directories under configured scan roots.

    Descends exactly 5 levels following the canonical structure:
    scan_root / <dpid> / <target> / <request_id> / <version_dir> / {msoc|msoc_new}

    Returns list of (source_path, scan_root_path) tuples.
    Skips non-existent scan roots.
    """
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
            continue
        for dpid_entry in dpid_entries:
            if not dpid_entry.is_dir(follow_symlinks=False):
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
                continue
            for request_entry in request_entries:
                if not request_entry.is_dir(follow_symlinks=False):
                    continue

                # Level 4: version directories
                try:
                    version_entries = list(os.scandir(request_entry.path))
                except OSError:
                    continue
                for version_entry in version_entries:
                    if not version_entry.is_dir(follow_symlinks=False):
                        continue

                    # Level 5: check for msoc or msoc_new only
                    try:
                        terminal_entries = list(os.scandir(version_entry.path))
                    except OSError:
                        continue
                    for terminal_entry in terminal_entries:
                        if terminal_entry.is_dir(follow_symlinks=False) and terminal_entry.name in ("msoc", "msoc_new"):
                            results.append((terminal_entry.path, root_path))

    return results
```

**Note on `os.scandir` usage:** Each `os.scandir()` call is immediately consumed into a `list()`, which closes the iterator and releases file descriptors. This avoids the deep nesting that `with` blocks would require while still being resource-safe.

Then update the call site in `crawl()` at line 78:

```python
# Change from:
candidates = walk_roots(config.scan_roots)
# To:
candidates = walk_roots(config.scan_roots, logger)
```

**Verification:**
Run: `uv run pytest tests/crawler/test_main.py -x -q`
Expected: Existing tests pass (they already create the canonical structure via `delivery_tree` fixture)

**Commit:** `feat(crawler): replace os.walk with structured 5-level scandir descent`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add tests for structural traversal constraints

**Verifies:** crawler-structured-traversal.AC2.1, crawler-structured-traversal.AC2.2, crawler-structured-traversal.AC2.3, crawler-structured-traversal.AC2.4, crawler-structured-traversal.AC2.5, crawler-structured-traversal.AC2.6, crawler-structured-traversal.AC2.7, crawler-structured-traversal.AC3.1, crawler-structured-traversal.AC3.2

**Files:**
- Modify: `tests/crawler/test_main.py` (add new test methods to `TestWalkRoots` class)
- Modify: `tests/crawler/conftest.py:67-70` (update `make_crawler_config` to include `target` in `ScanRoot` creation)

**Implementation:**

First, update the `make_crawler_config` fixture in `conftest.py` at lines 67-70 to pass `target` when creating `ScanRoot` objects:

```python
scan_roots_objs = [
    ScanRoot(
        path=sr["path"],
        label=sr.get("label", "default"),
        target=sr.get("target", "packages"),
    )
    for sr in config_dict["scan_roots"]
]
```

**Testing:**

Add new tests to the `TestWalkRoots` class in `tests/crawler/test_main.py`. Tests use `tmp_path` to create directory structures and `ScanRoot` objects directly (same pattern as existing tests).

Tests to write:

- crawler-structured-traversal.AC2.3: Create `<scan_root>/<dpid>/compare/<request_id>/<version_dir>/msoc`. Run `walk_roots` with `target="packages"`. Assert result is empty — the `msoc` inside `compare` is not discovered.

- crawler-structured-traversal.AC2.4: Create `<scan_root>/<dpid>/msoc` (directly under dpid, no target/request/version levels). Run `walk_roots`. Assert result is empty.

- crawler-structured-traversal.AC2.5: Create `<scan_root>/<dpid>/packages/<request_id>/<version_dir>/subdir/msoc` (extra nesting level). Run `walk_roots`. Assert result is empty.

- crawler-structured-traversal.AC2.6: Create two dpid directories under the same scan root, each with a valid `msoc` at canonical depth. Run `walk_roots`. Assert both are discovered.

- crawler-structured-traversal.AC2.7: Create one dpid with one request_id containing two version directories (`v01/msoc` and `v02/msoc_new`). Run `walk_roots`. Assert both are discovered.

- crawler-structured-traversal.AC3.1: Create a dpid directory without a `packages` subdirectory. Run `walk_roots` with a `MagicMock` logger. Assert `logger.warning` was called with a message containing the dpid name and target directory name.

- crawler-structured-traversal.AC3.2: Create a dpid directory WITH a `packages` subdirectory (and a valid delivery inside). Run `walk_roots` with a `MagicMock` logger. Assert `logger.warning` was NOT called.

- Test with custom target: Create `<scan_root>/<dpid>/compare/<request_id>/<version_dir>/msoc` using `tmp_path` directly (not the `delivery_tree` fixture, which hardcodes `"packages"` as the target directory). Run `walk_roots` with a `ScanRoot` that has `target="compare"`. Assert the `msoc` IS discovered. **Note:** The `delivery_tree` fixture in conftest.py hardcodes `"packages"` at line 31. Tests that need a non-default target directory should create the directory tree manually via `tmp_path` and `mkdir(parents=True)`.

Follow the existing test pattern: create dirs with `mkdir(parents=True)`, create `ScanRoot` objects with path/label/target, call `walk_roots([scan_root], logger)`, assert on results. Use `delivery_tree` for default-target tests, `tmp_path` directly for custom-target tests.

**Verification:**
Run: `uv run pytest tests/crawler/test_main.py -x -q`
Expected: All tests pass (existing + new)

Run: `uv run pytest -x -q`
Expected: All tests pass across the full suite

**Commit:** `test(crawler): add structural traversal constraint tests`
<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_3 -->
### Task 3: Update crawler CLAUDE.md

**Files:**
- Modify: `src/pipeline/crawler/CLAUDE.md`

**Implementation:**

Update the Contracts section to document that `walk_roots` now enforces the canonical 5-level structure and uses the `target` field from `ScanRoot`. Update the Invariants section to note that traversal is constrained to `<scan_root>/<dpid>/<target>/<request_id>/<version_dir>/{msoc|msoc_new}`.

Add to the Expects line: `target` (per scan root, defaults to "packages").

Update `Last verified` date to 2026-04-10.

**Verification:**
Run: `uv run pytest -x -q`
Expected: All tests still pass (docs-only change)

**Commit:** `docs(crawler): update CLAUDE.md with structured traversal details`
<!-- END_TASK_3 -->
