# Phase 5: crawler/main.py OSError logging (Category D)

**Goal:** Log a WARNING with the relevant path and `exc_info=True` at each of the four silent `except OSError: continue` sites in `walk_roots`. Continue semantics preserved.

**Architecture:** Four mechanical edits to `walk_roots`. The function already accepts an optional `logger` parameter and already uses it for the existing missing-target-directory warning at lines 73–78. Each new log call must follow that style: structured `extra={"path": ...}` plus `exc_info=True`. Because `logger` may be `None`, all four calls are guarded by `if logger:`, mirroring the existing pattern at line 74.

**Tech Stack:** stdlib `os`, project's `pipeline.json_logging.get_logger`.

**Scope:** 5 of 5 phases (issue #23, slug `GH23`).

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH23.AC5: crawler/main.py logs before continuing
- **GH23.AC5.1 Success:** Each of the four `except OSError: continue` sites logs a warning with the relevant path before continuing.
- **GH23.AC5.2 Success:** Each warning includes `exc_info=True` so the specific OS error is visible.
- **GH23.AC5.3 Edge:** Crawl continues processing remaining directories after logging (continue semantics preserved).

### GH23.AC6 (partial): Test coverage for logged exceptions
- **GH23.AC6.5 Success:** Tests for crawler walk_roots verify warning logged with path when scandir raises OSError.

---

## Codebase verification findings

- ✓ `src/pipeline/crawler/main.py` `walk_roots` signature already takes `logger=None`.
- ✓ Four `except OSError` sites confirmed:
  - Line 61–64: `dpid_entries = list(os.scandir(root_path))` — root-level dpid scan.
  - Line 82–85: `request_entries = list(os.scandir(target_path))` — request_id scan.
  - Line 91–94: `version_entries = list(os.scandir(request_entry.path))` — version scan.
  - Line 100–103: `terminal_entries = list(os.scandir(version_entry.path))` — terminal scan.
- ✓ Existing pattern at lines 74–78 uses `if logger:` guard plus `extra={...}` — mirrored exactly below.
- ✓ Test file `tests/crawler/test_main.py` exists.

**No external dependency research needed.**

---

<!-- START_TASK_1 -->
### Task 1: Add WARNING logs before each OSError continue in walk_roots

**Verifies:** GH23.AC5.1, GH23.AC5.2, GH23.AC5.3, GH23.AC6.5

**Files:**
- Modify: `src/pipeline/crawler/main.py` (lines 61–64, 82–85, 91–94, 100–103)
- Test: `tests/crawler/test_main.py` (add OSError-logging tests)

**Implementation:**

Apply four parallel edits. Each replaces an `except OSError: continue` with a guarded warning followed by `continue`. Use the path most relevant to the failing scan.

1. Site 1 — dpid-level scan (lines 61–64). Current:

```python
        # Level 1: dpid directories
        try:
            dpid_entries = list(os.scandir(root_path))
        except OSError:
            continue
```

Replace with:

```python
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
```

2. Site 2 — request-level scan (lines 82–85). Current:

```python
            # Level 3: request_id directories
            try:
                request_entries = list(os.scandir(target_path))
            except OSError:
                continue
```

Replace with:

```python
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
```

3. Site 3 — version-level scan (lines 91–94). Current:

```python
                # Level 4: version directories
                try:
                    version_entries = list(os.scandir(request_entry.path))
                except OSError:
                    continue
```

Replace with:

```python
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
```

4. Site 4 — terminal-level scan (lines 100–103). Current:

```python
                    # Level 5: check for terminal directories
                    try:
                        terminal_entries = list(os.scandir(version_entry.path))
                    except OSError:
                        continue
```

Replace with:

```python
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
```

**Testing:**

Add tests in `tests/crawler/test_main.py`. Use `caplog.set_level(logging.WARNING, logger="pipeline.crawler.main")` (or whatever module logger is supplied to `walk_roots` in the existing tests — mirror what those tests already do).

For each of the four sites:

- **GH23.AC5.1, AC5.2:** Set up a real on-disk directory tree just deep enough to reach the level under test, then `monkeypatch.setattr(os, "scandir", ...)` with a wrapper that raises `OSError("simulated")` only when called for the target path, otherwise delegates to the original `os.scandir`. Call `walk_roots(scan_roots, valid_terminals, logger=test_logger)`. Assert exactly one captured WARNING record with message `"scandir failed, skipping"`, `record.path == <target path>` (via `record.path` if `extra` is unpacked onto the LogRecord), and `record.exc_info[0] is OSError`.
- **GH23.AC5.3:** In each site test, the on-disk fixture should also include a *sibling* directory at the same level whose scandir succeeds and which leads to a discoverable terminal. Assert the returned `results` list contains the terminal from the sibling — i.e., the loop continued past the failing sibling.
- **GH23.AC5.1 (logger=None branch):** Repeat one site without supplying a logger; assert no exception is raised and no records are captured. This pins the `if logger:` guard.

The existing `walk_roots` tests in `test_main.py` already construct on-disk fixtures with `tmp_path`; reuse those helpers.

**Verification:**

Run: `uv run pytest tests/crawler/test_main.py -v`
Expected: all tests pass.

**Commit:** `feat(crawler): log scandir OSError sites in walk_roots before continuing`
<!-- END_TASK_1 -->

---

## Done when

- Task 1 committed.
- `uv run pytest` passes (full test suite, no regressions in crawler or downstream).
- AC5.1, AC5.2, AC5.3, AC6.5 verified across all four sites.
