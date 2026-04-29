# Mark Integration Tests with @pytest.mark.integration — Phase 1

**Goal:** Decorate the five test classes that exercise real pyreadstat/pyarrow on disk with `@pytest.mark.integration` so the marker declared by GH18 actually filters them, and `pytest -m "not integration"` excludes them cleanly.

**Architecture:** Single decorator added at class scope in three test files. No logic changes, no fixture changes, no new imports (`pytest` is already imported in all three target files).

**Tech Stack:** pytest, pytest-asyncio, pyreadstat, pyarrow.

**Scope:** 1 of 1 phase from the original design.

**Codebase verified:** 2026-04-29

Verification findings:
- All three target files exist and already import `pytest`:
  - `tests/converter/test_engine.py` (line 6: `import pytest`)
  - `tests/converter/test_convert.py` (line 7: `import pytest`)
  - `tests/test_end_to_end_converter.py` (line 20: `import pytest`)
- Five classes confirmed at exact line numbers:
  - `tests/converter/test_engine.py:751` — `class TestConvertOneIntegration:`
  - `tests/converter/test_convert.py:61` — `class TestConvertSasToParquetHappyPath:`
  - `tests/converter/test_convert.py:157` — `class TestConvertAtomicWrite:`
  - `tests/converter/test_convert.py:204` — `class TestConvertSchemaStability:`
  - `tests/test_end_to_end_converter.py:189` — `class TestEndToEndConverter:`
- Verified that other `TestConvertOne*` classes in `test_engine.py` (HappyPath, SkipGuards, PartialSuccess, TotalFailure, EmptyDir, Interrupt, Failure, Logging) use `_StubHttp` and do NOT call `sas_fixture_factory`/`sav_chunk_iter_factory`. They are pure unit tests against mocked converter logic; the design correctly excludes them from marking.
- Verified `TestConvertSchemaDrift` (test_convert.py:228) uses hand-rolled `chunk_iter_factory` stubs only, no real I/O — design correctly tells us NOT to mark it.

**Upstream dependency:** This phase depends on GH18 having declared `markers = ["integration: tests that hit the filesystem or network"]` in `[tool.pytest.ini_options]` (see `/Users/scarndp/dev/Sentinel/qa_registry/docs/project/18/phase_01.md`). Without the marker registered, decorators added here would emit `PytestUnknownMarkWarning`. Verify GH18 is merged before executing this plan.

---

## Acceptance Criteria Coverage

The design uses a "Definition of Done" section instead of formally numbered ACs. The criteria below are derived directly from those bullets. This phase implements and tests:

### GH25.AC1: All five integration test classes carry `@pytest.mark.integration`
- **GH25.AC1.1 Success:** `tests/converter/test_engine.py::TestConvertOneIntegration` carries the decorator
- **GH25.AC1.2 Success:** `tests/converter/test_convert.py::TestConvertSasToParquetHappyPath` carries the decorator
- **GH25.AC1.3 Success:** `tests/converter/test_convert.py::TestConvertAtomicWrite` carries the decorator
- **GH25.AC1.4 Success:** `tests/converter/test_convert.py::TestConvertSchemaStability` carries the decorator
- **GH25.AC1.5 Success:** `tests/test_end_to_end_converter.py::TestEndToEndConverter` carries the decorator

### GH25.AC2: `pytest -m "not integration"` cleanly excludes the marked classes
- **GH25.AC2.1 Success:** `uv run pytest -m "not integration"` exits 0 with no `PytestUnknownMarkWarning`
- **GH25.AC2.2 Success:** None of the methods of the five classes appear in collection output of `-m "not integration"`

### GH25.AC3: `pytest -m integration` selects only the marked classes
- **GH25.AC3.1 Success:** `uv run pytest -m integration` collects only methods belonging to the five classes
- **GH25.AC3.2 Success:** All collected integration tests pass

### GH25.AC4: No regressions
- **GH25.AC4.1 Success:** Full `uv run pytest` run passes with the same green status as before the change

### GH25.AC5: `TestConvertSchemaDrift` is NOT marked
- **GH25.AC5.1 Success:** `tests/converter/test_convert.py::TestConvertSchemaDrift` continues to run under `-m "not integration"` (it does not exercise real I/O and must remain a unit test)

---

## Phase classification

This phase is **functionality** (test annotation that changes pytest collection behaviour). The change is mechanical, but the verification is behavioural: pytest's `-m` filter must select/deselect the right classes. Verification leans on running pytest with both filters and inspecting the collection output.

---

<!-- START_TASK_1 -->
### Task 1: Decorate `TestConvertOneIntegration` in `tests/converter/test_engine.py`

**Verifies:** GH25.AC1.1

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/tests/converter/test_engine.py:751`

**Step 1: Add decorator above the class**

Locate line 751 (`class TestConvertOneIntegration:`). Insert `@pytest.mark.integration` on the line immediately above the class, with no blank line between decorator and class. Preserve any existing blank line(s) above the decorator.

Before:
```python
class TestConvertOneIntegration:
    def test_multiple_real_sas_files_to_parquet(self, tmp_path, sas_fixture_factory, sav_chunk_iter_factory):
        ...
```

After:
```python
@pytest.mark.integration
class TestConvertOneIntegration:
    def test_multiple_real_sas_files_to_parquet(self, tmp_path, sas_fixture_factory, sav_chunk_iter_factory):
        ...
```

**Step 2: Verify the file still parses**

```bash
python -c "import ast; ast.parse(open('tests/converter/test_engine.py').read())"
```

Expected: exit 0, no output.

**Step 3: Verify pytest can collect the class without warnings**

```bash
uv run pytest tests/converter/test_engine.py::TestConvertOneIntegration --collect-only -W error::pytest.PytestUnknownMarkWarning
```

Expected: collection lists the class's tests, exit 0, no unknown-marker error.

**Step 4: Stage but do not commit yet** (one combined commit at end of phase)

```bash
git add tests/converter/test_engine.py
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Decorate three classes in `tests/converter/test_convert.py`

**Verifies:** GH25.AC1.2, GH25.AC1.3, GH25.AC1.4

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/tests/converter/test_convert.py:61`
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/tests/converter/test_convert.py:157`
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/tests/converter/test_convert.py:204`

**Step 1: Add decorator above each of the three classes**

Add `@pytest.mark.integration` immediately above each of:
- `class TestConvertSasToParquetHappyPath:` (line 61)
- `class TestConvertAtomicWrite:` (line 157)
- `class TestConvertSchemaStability:` (line 204)

**CRITICAL: Do NOT mark `class TestConvertSchemaDrift:` (line 228).** That class uses hand-rolled stubs and is a pure unit test. It must continue to run under `-m "not integration"` (verifies GH25.AC5.1).

After the edits, the structure of the file should look like:

```python
class TestBuildColumnLabels:        # line 18  — UNCHANGED (unit test)
    ...

class TestFileMetadataBytes:        # line 33  — UNCHANGED (unit test)
    ...

@pytest.mark.integration
class TestConvertSasToParquetHappyPath:    # was line 61, now shifted by 1
    ...

@pytest.mark.integration
class TestConvertAtomicWrite:              # was line 157, now shifted by 2
    ...

@pytest.mark.integration
class TestConvertSchemaStability:          # was line 204, now shifted by 3
    ...

class TestConvertSchemaDrift:              # was line 228 — UNCHANGED, NOT marked
    ...
```

**Step 2: Verify the file still parses**

```bash
python -c "import ast; ast.parse(open('tests/converter/test_convert.py').read())"
```

Expected: exit 0, no output.

**Step 3: Verify the four target classes are collected without warnings**

```bash
uv run pytest \
  tests/converter/test_convert.py::TestConvertSasToParquetHappyPath \
  tests/converter/test_convert.py::TestConvertAtomicWrite \
  tests/converter/test_convert.py::TestConvertSchemaStability \
  --collect-only -W error::pytest.PytestUnknownMarkWarning
```

Expected: all three classes' tests listed, exit 0, no unknown-marker error.

**Step 4: Verify `TestConvertSchemaDrift` is NOT decorated**

```bash
grep -B1 "^class TestConvertSchemaDrift:" tests/converter/test_convert.py
```

Expected: the line above `class TestConvertSchemaDrift:` is a blank line (or any existing comment) — NOT `@pytest.mark.integration`. (Verifies GH25.AC5.1.)

**Step 5: Stage**

```bash
git add tests/converter/test_convert.py
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Decorate `TestEndToEndConverter` in `tests/test_end_to_end_converter.py`

**Verifies:** GH25.AC1.5

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/tests/test_end_to_end_converter.py:189`

**Step 1: Add decorator above the class**

Locate line 189 (`class TestEndToEndConverter:`). Insert `@pytest.mark.integration` immediately above it.

Before:
```python
class TestEndToEndConverter:
    ...
```

After:
```python
@pytest.mark.integration
class TestEndToEndConverter:
    ...
```

Note: there is also a `class _TestClientHttpAdapter:` at line 146 — this is an internal helper (leading underscore), not a test class, and pytest will not collect it. Do NOT decorate it.

**Step 2: Verify the file still parses**

```bash
python -c "import ast; ast.parse(open('tests/test_end_to_end_converter.py').read())"
```

Expected: exit 0, no output.

**Step 3: Verify pytest can collect the class without warnings**

```bash
uv run pytest tests/test_end_to_end_converter.py::TestEndToEndConverter --collect-only -W error::pytest.PytestUnknownMarkWarning
```

Expected: collection lists the class's tests, exit 0, no unknown-marker error.

**Step 4: Stage**

```bash
git add tests/test_end_to_end_converter.py
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Verify filtering behaviour end-to-end and commit

**Verifies:** GH25.AC2.1, GH25.AC2.2, GH25.AC3.1, GH25.AC3.2, GH25.AC4.1, GH25.AC5.1

**Files:**
- No new edits. Verification only.

**Step 1: Confirm `pytest -m "not integration"` cleanly excludes the marked classes**

```bash
uv run pytest -m "not integration" --collect-only -q -W error::pytest.PytestUnknownMarkWarning 2>&1 | tee /tmp/gh25_not_integration.txt
```

Expected: exit 0, no warnings. Then verify none of the marked classes' methods appear:

```bash
grep -E "TestConvertOneIntegration::|TestConvertSasToParquetHappyPath::|TestConvertAtomicWrite::|TestConvertSchemaStability::|TestEndToEndConverter::" /tmp/gh25_not_integration.txt
```

Expected: no matches (exit 1 from grep is the success state for this check). (Verifies GH25.AC2.1, GH25.AC2.2.)

**Step 2: Confirm `TestConvertSchemaDrift` IS still collected under `-m "not integration"`**

```bash
grep "TestConvertSchemaDrift::" /tmp/gh25_not_integration.txt
```

Expected: at least one match (exit 0). Confirms the borderline case is still treated as a unit test. (Verifies GH25.AC5.1.)

**Step 3: Confirm `pytest -m integration` selects only the five marked classes**

```bash
uv run pytest -m integration --collect-only -q 2>&1 | tee /tmp/gh25_integration.txt
```

Expected: exit 0. Then verify only the expected classes appear:

```bash
grep -oE "Test[A-Za-z]+::" /tmp/gh25_integration.txt | sort -u
```

Expected output (exact set, in some order):
```
TestConvertAtomicWrite::
TestConvertOneIntegration::
TestConvertSasToParquetHappyPath::
TestConvertSchemaStability::
TestEndToEndConverter::
```

No other class names. (Verifies GH25.AC3.1.)

**Step 4: Run the integration tests for real and confirm they pass**

```bash
uv run pytest -m integration
```

Expected: all integration tests pass, exit 0. (Verifies GH25.AC3.2.)

**Step 5: Run the full suite and confirm no regressions**

```bash
uv run pytest
```

Expected: same green status as before this change. (Verifies GH25.AC4.1.)

**Step 6: Commit the staged changes from Tasks 1-3 as a single commit**

```bash
git commit -m "test: mark integration tests with @pytest.mark.integration"
```

**Step 7: Clean up temp verification files**

```bash
rm -f /tmp/gh25_not_integration.txt /tmp/gh25_integration.txt
```
<!-- END_TASK_4 -->

---

## Phase exit criteria

When all four tasks complete:

- Five classes are decorated with `@pytest.mark.integration` at the exact lines listed (GH25.AC1.1-1.5).
- `TestConvertSchemaDrift` remains undecorated (GH25.AC5.1).
- `pytest -m "not integration"` excludes the five classes and runs cleanly with no marker warnings (GH25.AC2.1, GH25.AC2.2).
- `pytest -m integration` selects exactly those five classes and they all pass (GH25.AC3.1, GH25.AC3.2).
- Full suite passes (GH25.AC4.1).
- One commit on the working branch with all three test file changes.
- Verification temp files removed.

## Notes for the executor

- **All edits are at class scope, not method scope.** `@pytest.mark.integration` on the class applies the marker to every method via pytest's class-marker inheritance. Don't decorate individual methods — that creates noise and inconsistency.
- **Order of edits doesn't matter** — Tasks 1-3 can run in any order since they touch different files. They're listed sequentially for executor clarity.
- **No new imports needed.** All three files already `import pytest`.
- **Don't refactor while you're in there.** This is a mechanical annotation change. If you spot something else worth fixing, surface it as a separate issue rather than bundling it.
