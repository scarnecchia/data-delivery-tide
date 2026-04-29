# Test Requirements — GH18 (Bump Python ≥3.11 + integration marker)

Maps each acceptance criterion in `design.md` to either an automated test or a documented human verification step. The test-analyst uses this during execution to validate coverage.

---

## Automated tests

### bump-python-311.AC1.1: `pyproject.toml` declares `requires-python = ">=3.11"`

- **Test type:** static file inspection (no test file required — automatable as a one-line check)
- **Expected location:** N/A (verified inline during Task 1, Step 1)
- **Verification command:**
  ```bash
  grep -E '^requires-python = ">=3\.11"$' pyproject.toml
  ```
  Expected: line matched, exit 0.

### bump-python-311.AC1.2: install succeeds on Python 3.11+

- **Test type:** integration (operational verification, not pytest)
- **Expected location:** N/A (verified inline during Task 1, Step 4)
- **Verification command:**
  ```bash
  uv pip install -e ".[registry,dev]"
  ```
  Expected: exit 0, no resolver errors. Run on a Python 3.11+ interpreter.

### bump-python-311.AC2.1: `markers = ["integration: ..."]` declared in `[tool.pytest.ini_options]`

- **Test type:** static file inspection
- **Expected location:** N/A (verified inline during Task 1)
- **Verification command:**
  ```bash
  python -c "import tomllib; cfg = tomllib.load(open('pyproject.toml','rb')); assert any('integration' in m for m in cfg['tool']['pytest']['ini_options']['markers'])"
  ```
  Expected: exit 0.

### bump-python-311.AC2.2: no `PytestUnknownMarkWarning` for `@pytest.mark.integration`

- **Test type:** integration (pytest invocation against temp file)
- **Expected location:** `tests/_phase_01_marker_check.py` (temporary; created and deleted within Task 2)
- **Verification command:**
  ```bash
  uv run pytest tests/_phase_01_marker_check.py -W error::pytest.PytestUnknownMarkWarning
  ```
  Expected: 2 passed, 0 warnings, exit 0.

### bump-python-311.AC2.3: `-m integration` selects only marked tests

- **Test type:** integration (pytest collection)
- **Expected location:** `tests/_phase_01_marker_check.py` (temporary)
- **Verification command:**
  ```bash
  uv run pytest tests/_phase_01_marker_check.py -m integration -v
  ```
  Expected: exactly `test_marker_registered_integration` selected; the unmarked test deselected.

### bump-python-311.AC2.4: `-m "not integration"` excludes marked tests

- **Test type:** integration (pytest collection)
- **Expected location:** `tests/_phase_01_marker_check.py` (temporary)
- **Verification command:**
  ```bash
  uv run pytest tests/_phase_01_marker_check.py -m "not integration" -v
  ```
  Expected: exactly `test_marker_registered_unmarked` selected; the marked test deselected.

### bump-python-311.AC3.1: full suite passes with no regressions

- **Test type:** integration (full pytest run)
- **Expected location:** entire `tests/` tree
- **Verification command:**
  ```bash
  uv run pytest
  ```
  Expected: green run matching pre-change status. Run twice within Task 2 — once with the temp file present, once after deletion.

---

## Human verification

### bump-python-311.AC1.3: install on Python 3.10 produces a clear resolver error

- **Why human:** Requires a Python 3.10 interpreter that may not be available on every developer machine or in CI. Provisioning one purely to confirm a resolver error is wasteful, and PEP 440 constraint behaviour is well-defined — the constraint text itself in `pyproject.toml` is sufficient evidence.
- **Verification approach:** If a 3.10 interpreter is locally available, run `uv pip install -e ".[registry,dev]" --python python3.10` (or `python3.10 -m pip install -e ".[registry,dev]"`) and confirm the resolver output cites the `>=3.11` constraint. If no 3.10 interpreter is available, document the verification as not-locally-performed in the PR description.
- **Documented in:** `phase_01.md` Task 3.

---

## Coverage summary

| AC | Coverage |
|----|----------|
| bump-python-311.AC1.1 | Automated (file inspection) |
| bump-python-311.AC1.2 | Automated (install command) |
| bump-python-311.AC1.3 | Human (3.10 interpreter not always available) |
| bump-python-311.AC2.1 | Automated (file inspection via tomllib) |
| bump-python-311.AC2.2 | Automated (pytest with `-W error`) |
| bump-python-311.AC2.3 | Automated (pytest collection with `-m`) |
| bump-python-311.AC2.4 | Automated (pytest collection with `-m "not"`) |
| bump-python-311.AC3.1 | Automated (full pytest run) |

Every AC is mapped. 7 of 8 are fully automated; AC1.3 is the only human-verification item, with documented justification.
