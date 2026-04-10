# Crawler Structured Traversal Implementation Plan — Phase 1

**Goal:** Add `target` field to `ScanRoot` and config loading

**Architecture:** Extend the existing `ScanRoot` dataclass with an optional `target` field that defaults to `"packages"`. Update `load_config` to parse it from JSON using the same `data.get()` pattern used for other optional fields. Update the config JSON to include `target` on existing entries.

**Tech Stack:** Python 3.10+, stdlib dataclasses, JSON config

**Scope:** 2 phases from original design (phase 1 of 2)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### crawler-structured-traversal.AC1: Config supports target field
- **crawler-structured-traversal.AC1.1 Success:** `ScanRoot` with explicit `"target": "packages"` loads correctly
- **crawler-structured-traversal.AC1.2 Success:** `ScanRoot` without `target` field defaults to `"packages"`
- **crawler-structured-traversal.AC1.3 Success:** `ScanRoot` with non-default target (e.g. `"compare"`) loads correctly
- **crawler-structured-traversal.AC1.4 Edge:** Existing config JSON without any `target` fields loads without error

### crawler-structured-traversal.AC4: Backward compatibility
- **crawler-structured-traversal.AC4.1 Success:** Existing config JSON without `target` field produces identical crawl results to current behaviour for canonical paths

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: Add `target` field to `ScanRoot` dataclass

**Verifies:** crawler-structured-traversal.AC1.1, crawler-structured-traversal.AC1.2

**Files:**
- Modify: `src/pipeline/config.py:8-11` (ScanRoot dataclass)

**Implementation:**

Add `target: str = "packages"` as a third field on the `ScanRoot` dataclass:

```python
@dataclass
class ScanRoot:
    path: str
    label: str
    target: str = "packages"
```

This follows the existing dataclass pattern. The default ensures backward compatibility — any code creating `ScanRoot(path=..., label=...)` without specifying `target` gets `"packages"`.

**Verification:**
Run: `uv run pytest tests/test_config.py -x -q`
Expected: All 6 existing tests pass (no breakage from adding a defaulted field)

**Commit:** `feat(config): add target field to ScanRoot dataclass`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update `load_config` to parse `target` from JSON

**Verifies:** crawler-structured-traversal.AC1.1, crawler-structured-traversal.AC1.3

**Files:**
- Modify: `src/pipeline/config.py:~42` (scan_roots list comprehension in load_config — line shifts by 1 after Task 1 adds the target field)

**Implementation:**

Update the list comprehension that creates `ScanRoot` instances to include `target`:

```python
scan_roots = [
    ScanRoot(
        path=root["path"],
        label=root["label"],
        target=root.get("target", "packages"),
    )
    for root in data["scan_roots"]
]
```

This follows the same `data.get("field", default)` pattern used for `dp_id_exclusions` (line 51), `crawl_manifest_dir` (line 52), and `crawler_version` (line 53).

**Verification:**
Run: `uv run pytest tests/test_config.py -x -q`
Expected: All 6 existing tests pass

**Commit:** `feat(config): parse target field from scan root JSON entries`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Add tests for `target` field

**Verifies:** crawler-structured-traversal.AC1.1, crawler-structured-traversal.AC1.2, crawler-structured-traversal.AC1.3, crawler-structured-traversal.AC1.4

**Files:**
- Modify: `tests/test_config.py` (add new test methods to `TestLoadConfig` class)

**Testing:**

Add these tests to the existing `TestLoadConfig` class, following the same `tmp_path` + JSON config pattern used by the existing tests:

- crawler-structured-traversal.AC1.1: Test that a scan root entry with explicit `"target": "packages"` results in `scan_root.target == "packages"`
- crawler-structured-traversal.AC1.2: Test that a scan root entry WITHOUT a `target` field results in `scan_root.target == "packages"` (default)
- crawler-structured-traversal.AC1.3: Test that a scan root entry with `"target": "compare"` results in `scan_root.target == "compare"`
- crawler-structured-traversal.AC1.4: Test that loading the real `pipeline/config.json` (via default fallback) succeeds and all scan roots have `target == "packages"`

Follow the existing test pattern: create a `config_data` dict, write to `tmp_path / "config.json"`, call `load_config(str(config_file))`, assert on the result.

**Verification:**
Run: `uv run pytest tests/test_config.py -x -q`
Expected: All tests pass (6 existing + new tests)

**Commit:** `test(config): add target field loading and default tests`
<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_4 -->
### Task 4: Add `target` to config JSON

**Verifies:** crawler-structured-traversal.AC4.1

**Files:**
- Modify: `pipeline/config.json` (add `target` to each scan root entry)

**Implementation:**

Add `"target": "packages"` to each of the 4 existing scan root entries in `pipeline/config.json`. Example for the first entry:

```json
{
  "path": "/requests/qa",
  "label": "QA Package Results",
  "target": "packages"
}
```

Repeat for all 4 entries (`qa`, `qm`, `qad`, `qmd`).

**Verification:**
Run: `uv run pytest tests/test_config.py -x -q`
Expected: All tests pass, including the fallback test that loads the real config

Run: `python -c "from pipeline.config import load_config; c = load_config(); print([(r.path, r.target) for r in c.scan_roots])"`
Expected: All scan roots show `target='packages'`

**Commit:** `feat(config): add target field to scan root entries in config.json`
<!-- END_TASK_4 -->
