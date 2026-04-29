# Bump requires-python to >=3.11 and Add Integration Test Marker — Phase 1

**Goal:** Update `pyproject.toml` to declare Python ≥3.11 as the minimum supported interpreter and register the `integration` pytest marker so downstream issues can annotate tests without warnings.

**Architecture:** Two additive edits to a single file (`pyproject.toml`). One line change in `[project]`; one new key in the existing `[tool.pytest.ini_options]` table. No source changes, no lock file changes.

**Tech Stack:** Python 3.11+, pytest, hatchling build backend, uv (local) / pip (RHEL).

**Scope:** 1 of 1 phases from the original design.

**Codebase verified:** 2026-04-29

Verification findings:
- `pyproject.toml` exists at repo root and currently declares `requires-python = ">=3.10"` on line 8.
- `[tool.pytest.ini_options]` table exists on lines 36-38 with keys `testpaths` and `asyncio_mode`. No `markers` key currently set.
- No existing `@pytest.mark.integration` usage in the test suite (forward-looking declaration).
- Repo follows `# pattern:` annotation convention but `pyproject.toml` is config, not Python source — pattern annotations N/A.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### bump-python-311.AC1: requires-python constraint is updated
- **bump-python-311.AC1.1 Success:** `pyproject.toml` `[project]` table declares `requires-python = ">=3.11"`
- **bump-python-311.AC1.2 Success:** `uv pip install -e ".[registry,dev]"` succeeds on Python 3.11+
- **bump-python-311.AC1.3 Failure:** Installation attempt on Python 3.10 produces a clear resolver error citing the version constraint

### bump-python-311.AC2: Integration marker is declared
- **bump-python-311.AC2.1 Success:** `pyproject.toml` `[tool.pytest.ini_options]` contains `markers = ["integration: tests that hit the filesystem or network"]`
- **bump-python-311.AC2.2 Success:** `uv run pytest` produces no `PytestUnknownMarkWarning` for `@pytest.mark.integration`
- **bump-python-311.AC2.3 Success:** `uv run pytest -m integration` selects only tests decorated with `@pytest.mark.integration`
- **bump-python-311.AC2.4 Success:** `uv run pytest -m "not integration"` excludes those tests

### bump-python-311.AC3: Existing test suite unaffected
- **bump-python-311.AC3.1 Success:** Full `uv run pytest` run passes with no regressions after the change

---

## Phase classification

This phase is **infrastructure**: configuration changes verified operationally (file edited correctly, install succeeds, pytest runs cleanly). No new tests are authored in this phase; AC2.3 and AC2.4 are verified by a temporary throwaway test that is removed after verification, since the design explicitly states integration test annotation belongs to a downstream issue (#25).

---

<!-- START_TASK_1 -->
### Task 1: Update `requires-python` and declare `integration` marker

**Verifies:** bump-python-311.AC1.1, bump-python-311.AC2.1

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/pyproject.toml:8` (change `>=3.10` to `>=3.11`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/pyproject.toml:36-38` (add `markers` key to `[tool.pytest.ini_options]`)

**Step 1: Apply the requires-python bump**

Change line 8 from:

```toml
requires-python = ">=3.10"
```

to:

```toml
requires-python = ">=3.11"
```

**Step 2: Add the markers key to `[tool.pytest.ini_options]`**

The current block (lines 36-38) reads:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

Update it to:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: tests that hit the filesystem or network",
]
```

**Step 3: Verify file syntax**

Run from repo root:

```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"
```

Expected: command exits 0 with no output. If `tomllib` is unavailable (Python 3.10), the bump itself prevents the error this command would catch — install with the new constraint first using Step 4 instead.

**Step 4: Verify install still works**

Run from repo root with a Python 3.11+ interpreter active:

```bash
uv pip install -e ".[registry,dev]"
```

Expected: install succeeds. No version-constraint complaints in the resolver output.

**Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: bump requires-python to >=3.11 and declare integration pytest marker"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Verify the marker registration end-to-end

**Verifies:** bump-python-311.AC2.2, bump-python-311.AC2.3, bump-python-311.AC2.4, bump-python-311.AC3.1

**Files:**
- Create (temporary): `/Users/scarndp/dev/Sentinel/qa_registry/tests/_phase_01_marker_check.py`
- Delete (after verification): `/Users/scarndp/dev/Sentinel/qa_registry/tests/_phase_01_marker_check.py`

**Rationale for temporary file:** The design states that no test files exist with `@pytest.mark.integration` today, and that real annotation belongs to issue #25. To verify the marker is wired correctly *now* without pre-empting #25's scope, this task introduces one decorated test, runs the verification commands, then deletes the file. The file is never committed.

**Step 1: Create the temporary verification test**

Write the following to `tests/_phase_01_marker_check.py`:

```python
import pytest


@pytest.mark.integration
def test_marker_registered_integration():
    assert True


def test_marker_registered_unmarked():
    assert True
```

**Step 2: Confirm no `PytestUnknownMarkWarning` is emitted**

Run from repo root:

```bash
uv run pytest tests/_phase_01_marker_check.py -W error::pytest.PytestUnknownMarkWarning
```

Expected: 2 passed, 0 warnings, exit 0. The `-W error::pytest.PytestUnknownMarkWarning` flag promotes any unknown-marker warning to a hard error, so a clean run proves the marker is registered (verifies bump-python-311.AC2.2).

**Step 3: Confirm `-m integration` selects only the marked test**

Run:

```bash
uv run pytest tests/_phase_01_marker_check.py -m integration -v
```

Expected: exactly 1 test selected — `test_marker_registered_integration`. The unmarked test is deselected (verifies bump-python-311.AC2.3).

**Step 4: Confirm `-m "not integration"` excludes the marked test**

Run:

```bash
uv run pytest tests/_phase_01_marker_check.py -m "not integration" -v
```

Expected: exactly 1 test selected — `test_marker_registered_unmarked`. The marked test is deselected (verifies bump-python-311.AC2.4).

**Step 5: Run the full suite to confirm no regressions**

Run:

```bash
uv run pytest
```

Expected: full suite passes with the same green status as before this change. Includes the two temp tests (verifies bump-python-311.AC3.1).

**Step 6: Delete the temporary verification test**

```bash
rm /Users/scarndp/dev/Sentinel/qa_registry/tests/_phase_01_marker_check.py
```

**Step 7: Confirm the suite still passes after deletion**

```bash
uv run pytest
```

Expected: full suite passes. Confirms removal didn't break anything.

**Step 8: Commit (no changes expected)**

The temp file was never staged. Confirm a clean tree:

```bash
git status
```

Expected: working tree clean (the only commit from this phase is the one made in Task 1).
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Manual verification of the failure mode (bump-python-311.AC1.3)

**Verifies:** bump-python-311.AC1.3

**Why manual:** This AC requires running `pip`/`uv` against a Python 3.10 interpreter to confirm the resolver rejects the install. CI may or may not have a 3.10 interpreter available, and provisioning one purely to confirm a resolver error is wasteful. This is documented as a manual verification step rather than an automated one.

**Step 1: Identify a Python 3.10 interpreter**

Locally, this is typically:

```bash
which python3.10 || ls /usr/bin/python3.10 /opt/homebrew/bin/python3.10 2>/dev/null
```

If no 3.10 interpreter is available, skip to Step 4 and document that the failure mode was not verified locally. The constraint text itself in `pyproject.toml` is sufficient evidence; resolver behavior on the constraint is well-defined PEP 440 behavior.

**Step 2: Attempt install with Python 3.10**

```bash
uv pip install -e ".[registry,dev]" --python python3.10
```

Or with stock pip:

```bash
python3.10 -m pip install -e ".[registry,dev]"
```

**Step 3: Confirm the failure message**

Expected: a clear resolver error citing the Python version constraint. With uv, this looks roughly like:

```
× No solution found when resolving dependencies:
  ╰─▶ Because the current Python version (3.10.X) does not satisfy
      Python>=3.11 and pipeline depends on Python>=3.11, we can conclude
      that pipeline cannot be used.
```

With pip:

```
ERROR: Package 'pipeline' requires a different Python: 3.10.X not in '>=3.11'
```

**Step 4: Record the verification outcome**

Note the result (verified locally / verified in CI / documented gap) in the PR description for tracking.
<!-- END_TASK_3 -->

---

## Phase exit criteria

When all three tasks complete:

- `pyproject.toml` declares `requires-python = ">=3.11"` (AC1.1).
- `pyproject.toml` declares the `integration` marker in `[tool.pytest.ini_options]` (AC2.1).
- `uv pip install -e ".[registry,dev]"` succeeds on Python 3.11+ (AC1.2).
- `uv run pytest` is clean of `PytestUnknownMarkWarning` (AC2.2).
- `-m integration` and `-m "not integration"` filter as expected (AC2.3, AC2.4).
- Full suite passes (AC3.1).
- Failure mode on Python 3.10 verified manually or documented as not-locally-verified (AC1.3).
- Working tree clean except for the single commit on `pyproject.toml`.
