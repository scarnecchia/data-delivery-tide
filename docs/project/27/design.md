# Issue #27: Add `# pattern:` Labels to Files Missing Them

## Summary

Mechanical housekeeping issue. Twenty-five files are missing `# pattern:` labels; two test files have the wrong label. All changes are one-line additions or corrections. No logic is touched.

## Definition of Done

- Every non-empty Python file under `src/` carries a `# pattern:` label on line 1.
- Every Python file under `tests/` carries `# pattern: test file` on line 1.
- Empty `__init__.py` files (no imports, no code) are exempt — they are namespace anchors with no architectural classification.
- No file retains an inaccurate label.

## Decision: Test File Convention

**Add `# pattern: test file` to all test files.** Do not remove it from `test_end_to_end_converter.py`.

Rationale: the label communicates that the file sits outside the FCIS boundary. Removing the only correctly-labelled test file is a regression. The two mislabelled lexicon test files (`test_loader.py`, `test_qa_hook.py`) have `# pattern: Functional Core` — that is inaccurate because test files exercise the core but are not part of it.

## Scope

### Source files — missing labels

| File | Correct label |
|------|---------------|
| `src/pipeline/lexicons/__init__.py` | `# pattern: Functional Core` |
| `src/pipeline/crawler/__init__.py` | `# pattern: Functional Core` |

The remaining `__init__.py` files (`src/pipeline/__init__.py`, `src/pipeline/converter/__init__.py`, `src/pipeline/events/__init__.py`, `src/pipeline/registry_api/__init__.py`, `src/pipeline/lexicons/soc/__init__.py`) are **empty**. No label needed.

### Test files — missing or wrong labels

All files below get `# pattern: test file` on line 1.

| File | Action |
|------|--------|
| `tests/conftest.py` | add |
| `tests/crawler/conftest.py` | add |
| `tests/crawler/test_fingerprint.py` | add |
| `tests/crawler/test_http.py` | add |
| `tests/crawler/test_main.py` | add |
| `tests/crawler/test_manifest.py` | add |
| `tests/crawler/test_parser.py` | add |
| `tests/events/test_consumer.py` | add |
| `tests/lexicons/conftest.py` | add |
| `tests/lexicons/test_loader.py` | **replace** `# pattern: Functional Core` |
| `tests/lexicons/test_qa_hook.py` | **replace** `# pattern: Functional Core` |
| `tests/registry_api/test_auth.py` | add |
| `tests/registry_api/test_db.py` | add |
| `tests/registry_api/test_events.py` | add |
| `tests/registry_api/test_models.py` | add |
| `tests/registry_api/test_routes.py` | add |
| `tests/test_auth_cli.py` | add |
| `tests/test_config.py` | add |
| `tests/test_json_logging.py` | add |
| `tests/test_no_hardcoded_qa.py` | add |

`tests/__init__.py`, `tests/converter/__init__.py`, `tests/crawler/__init__.py`, `tests/events/__init__.py`, `tests/lexicons/__init__.py`, `tests/registry_api/__init__.py` are empty — exempt.

### Already correct — no change

All files in `src/` that already carry a label (`auth_cli.py`, `config.py`, `json_logging.py`, all converter files, all crawler non-init files, all registry_api files, `events/consumer.py`, `lexicons/loader.py`, `lexicons/models.py`, `lexicons/soc/qa.py`) are untouched.

`tests/test_end_to_end_converter.py` and all converter test files and conftest already carry `# pattern: test file` — untouched.

## Effort Estimate

Small and mechanical. 22 files, one-line edit each. No logic changes, no test changes required, no review risk. Can be done in a single commit.
