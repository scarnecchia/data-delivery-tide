# Bump requires-python to >=3.11 and Add Integration Test Marker Design

## Summary

This change raises the minimum Python version constraint from 3.10 to 3.11 and declares an `integration` pytest marker in `pyproject.toml`. The version bump unlocks stdlib additions that landed in 3.11 — notably `tomllib`, `ExceptionGroup`, and `TaskGroup` — and aligns the declared constraint with what downstream issues (starting with #25) assume is available. The marker declaration resolves the pytest unknown-mark warning that appears when integration tests use `@pytest.mark.integration` without a registered definition.

Both changes are confined to `pyproject.toml`. No source code changes are required for the bump itself; the marker declaration enables downstream issues to start annotating tests without further pyproject edits.

## Definition of Done

- `pyproject.toml` declares `requires-python = ">=3.11"`
- `[tool.pytest.ini_options]` includes `markers = ["integration: tests that hit the filesystem or network"]`
- `uv run pytest` passes with no unknown-mark warnings
- RHEL target environment confirmed capable of satisfying >=3.11

## Acceptance Criteria

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

## Glossary

- **requires-python:** PEP 440 specifier in `pyproject.toml` that pip/uv use to reject installation on incompatible interpreters.
- **tomllib:** Python 3.11 stdlib module for parsing TOML files (previously required the third-party `tomli` package).
- **ExceptionGroup:** Python 3.11 builtin for grouping multiple exceptions; used by `asyncio.TaskGroup` and pytest-asyncio internals.
- **TaskGroup:** Python 3.11 `asyncio` construct for structured concurrency; supersedes manual `gather` + cancellation patterns.
- **pytest marker:** A decorator (`@pytest.mark.<name>`) that categorises tests for selective execution via `-m`; must be declared in `pyproject.toml` to suppress unknown-mark warnings.
- **asyncio_mode = "auto":** pytest-asyncio setting that treats all `async def` test functions as asyncio tests without requiring an explicit `@pytest.mark.asyncio` decorator.
- **RHEL:** Red Hat Enterprise Linux — the production target environment; ships Python from SCL or AppStream, which has provided 3.11 since RHEL 9.2 (2023).

---

## Architecture

Two additive edits to `pyproject.toml`:

1. Raise `requires-python` from `">=3.10"` to `">=3.11"` in `[project]`.
2. Add `markers` list to the existing `[tool.pytest.ini_options]` table.

No changes to source files, test files, or lock files. The lock file (`uv.lock`) is managed by uv and must not be manually edited; uv will regenerate it if dependency resolution changes, but this change does not alter any dependency bounds so lock regeneration is not expected.

## Existing Patterns

`pyproject.toml` already has a `[tool.pytest.ini_options]` table with `testpaths` and `asyncio_mode`. The `markers` key is a standard extension of the same table. This follows the pytest documentation pattern and requires no new section.

No existing `@pytest.mark.integration` usage is present in the test suite today. The marker declaration is forward-looking: it makes the marker valid so that issue #25 and others can begin annotating tests immediately without a separate pyproject change.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Update pyproject.toml
**Goal:** Apply the two edits and verify the test suite still passes.

**Components:**
- `pyproject.toml` — change `requires-python = ">=3.10"` to `">=3.11"` and add `markers` entry to `[tool.pytest.ini_options]`

**Dependencies:** None.

**Done when:** `uv run pytest` passes with zero warnings about unknown markers (bump-python-311.AC2.2, bump-python-311.AC3.1). Manual check that `pyproject.toml` reflects both changes (bump-python-311.AC1.1, bump-python-311.AC2.1).
<!-- END_PHASE_1 -->

## Additional Considerations

**RHEL compatibility:** RHEL 9 (GA May 2022) ships Python 3.9 as the default in BaseOS, but Python 3.11 has been available in AppStream since RHEL 9.2 (May 2023). The project already targets RHEL and uses `pip` rather than `uv` on that machine (per environment notes). Python 3.11 is a reasonable minimum; teams still on RHEL 9.0/9.1 would need to install the AppStream 3.11 package, which is a one-time operation and not a blocker.

**Downstream dependency:** Issue #25 depends on the `integration` marker being declared. This issue must be merged before #25 can annotate tests without triggering `PytestUnknownMarkWarning`.

**No source changes needed now:** The version bump does not require adopting `tomllib`, `ExceptionGroup`, or `TaskGroup` immediately. It merely makes them available. Future issues may introduce them; the constraint bump prevents a future import from silently failing on a Python 3.10 installation.
