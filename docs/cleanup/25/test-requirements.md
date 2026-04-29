# Test Requirements — GH25 (Mark integration tests with @pytest.mark.integration)

Maps each acceptance criterion to either an automated verification or a documented human verification step. The design uses a "Definition of Done" structure rather than numbered ACs; the AC identifiers below are derived in `phase_01.md` and reused here.

---

## Automated tests

### GH25.AC1.1 - GH25.AC1.5: Each of the five target classes carries `@pytest.mark.integration`

- **Test type:** static file inspection (grep) — these are existence checks on the source, not pytest tests
- **Expected location:** verified inline during Tasks 1-3
- **Verification commands (one per AC case):**

  ```bash
  grep -B1 "^class TestConvertOneIntegration:" tests/converter/test_engine.py | grep -q "@pytest.mark.integration"
  grep -B1 "^class TestConvertSasToParquetHappyPath:" tests/converter/test_convert.py | grep -q "@pytest.mark.integration"
  grep -B1 "^class TestConvertAtomicWrite:" tests/converter/test_convert.py | grep -q "@pytest.mark.integration"
  grep -B1 "^class TestConvertSchemaStability:" tests/converter/test_convert.py | grep -q "@pytest.mark.integration"
  grep -B1 "^class TestEndToEndConverter:" tests/test_end_to_end_converter.py | grep -q "@pytest.mark.integration"
  ```

  Each command should exit 0 (decorator present immediately above the class).

### GH25.AC2.1: `pytest -m "not integration"` runs cleanly with no `PytestUnknownMarkWarning`

- **Test type:** integration (pytest invocation)
- **Expected location:** N/A — verified inline during Task 4, Step 1
- **Verification command:**
  ```bash
  uv run pytest -m "not integration" -W error::pytest.PytestUnknownMarkWarning
  ```
  Expected: exit 0, no warnings.

### GH25.AC2.2: None of the marked classes' methods appear under `-m "not integration"`

- **Test type:** integration (pytest collection inspection)
- **Expected location:** N/A — verified inline during Task 4, Step 1
- **Verification command:**
  ```bash
  uv run pytest -m "not integration" --collect-only -q | \
    grep -E "TestConvertOneIntegration::|TestConvertSasToParquetHappyPath::|TestConvertAtomicWrite::|TestConvertSchemaStability::|TestEndToEndConverter::"
  ```
  Expected: zero matches (grep exit 1).

### GH25.AC3.1: `pytest -m integration` selects exactly the five marked classes

- **Test type:** integration (pytest collection inspection)
- **Expected location:** N/A — verified inline during Task 4, Step 3
- **Verification command:**
  ```bash
  uv run pytest -m integration --collect-only -q | grep -oE "Test[A-Za-z]+::" | sort -u
  ```
  Expected output (in some order):
  ```
  TestConvertAtomicWrite::
  TestConvertOneIntegration::
  TestConvertSasToParquetHappyPath::
  TestConvertSchemaStability::
  TestEndToEndConverter::
  ```

### GH25.AC3.2: All collected integration tests pass

- **Test type:** integration (pytest run with `-m integration`)
- **Expected location:** existing test files (no new tests added)
- **Verification command:**
  ```bash
  uv run pytest -m integration
  ```
  Expected: green run, exit 0.

### GH25.AC4.1: Full suite still passes — no regressions

- **Test type:** integration (full pytest run)
- **Expected location:** entire `tests/` tree
- **Verification command:**
  ```bash
  uv run pytest
  ```
  Expected: same green status as before the change.

### GH25.AC5.1: `TestConvertSchemaDrift` is NOT marked and still runs under `-m "not integration"`

- **Test type:** integration (pytest collection inspection) + static check
- **Expected location:** N/A — verified inline during Task 2 Step 4 and Task 4 Step 2
- **Verification commands:**
  ```bash
  # Static: confirm no decorator above TestConvertSchemaDrift
  ! grep -B1 "^class TestConvertSchemaDrift:" tests/converter/test_convert.py | grep -q "@pytest.mark.integration"

  # Behavioural: confirm it IS collected under "not integration"
  uv run pytest -m "not integration" --collect-only -q | grep -q "TestConvertSchemaDrift::"
  ```
  Both expected to exit 0.

---

## Human verification

None. Every AC case is fully automatable.

---

## Coverage summary

| AC | Coverage |
|----|----------|
| GH25.AC1.1 | Automated (grep on source) |
| GH25.AC1.2 | Automated (grep on source) |
| GH25.AC1.3 | Automated (grep on source) |
| GH25.AC1.4 | Automated (grep on source) |
| GH25.AC1.5 | Automated (grep on source) |
| GH25.AC2.1 | Automated (`pytest -m "not integration" -W error`) |
| GH25.AC2.2 | Automated (collection inspection) |
| GH25.AC3.1 | Automated (collection inspection, exact set comparison) |
| GH25.AC3.2 | Automated (`pytest -m integration` run) |
| GH25.AC4.1 | Automated (full `uv run pytest` run) |
| GH25.AC5.1 | Automated (negative grep + positive collection check) |

Every AC mapped, all automated. Zero human-verification items.

---

## Upstream dependency note

This plan assumes GH18 has been merged. If `markers = ["integration: tests that hit the filesystem or network"]` is NOT present in `[tool.pytest.ini_options]` in `pyproject.toml`, GH25.AC2.1 will fail with `PytestUnknownMarkWarning` promoted to an error. The executor should sanity-check by running `uv run pytest --markers | grep integration` before starting; expected output includes a line `@pytest.mark.integration: tests that hit the filesystem or network`.
