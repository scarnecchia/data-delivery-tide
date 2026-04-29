# GH26 Test Requirements

This document maps each GH26 acceptance criterion to its automated verification. GH26 is a pure rename refactor: there are no new tests to write, only existing tests to keep passing under new names. Every AC is verified by a single command — `pytest`, a `grep`, or a `wc -l` cross-check.

## Coverage matrix

| AC | Spec (verbatim, scoped to GH26) | Verification | Phase 1 task |
|----|----------------------------------|--------------|--------------|
| GH26.AC1.1 | Every `def test_*` in the five files matches `test_<function>_<scenario>` (two underscore-separated segments minimum after `test_`) | `grep -nE '^    def test_[a-z_]+\(' tests/converter/test_engine.py tests/crawler/test_main.py tests/crawler/test_parser.py tests/converter/test_classify.py tests/test_json_logging.py \| awk -F'def test_' '{print $2}' \| awk -F'(' '{print $1}' \| awk -F_ 'NF<2' ` returns empty | Task 6 step 5 |
| GH26.AC1.2 | Names that already comply are left unchanged | `git log -p tests/converter/test_engine.py` shows no rename for `TestHelpers`'s `test_find_sas_files_*` and `test_build_parquet_dir_*` methods | Task 1 (rename map explicitly marks "unchanged") |
| GH26.AC1.3 | No method retains an AC-code prefix (`test_ac\d+_\d+_`) | `grep -nE '^    def test_ac[0-9]' tests/converter/test_engine.py tests/crawler/test_main.py tests/crawler/test_parser.py tests/converter/test_classify.py tests/test_json_logging.py` returns empty | Task 6 step 3 |
| GH26.AC1.4 | No method is renamed to a single-segment name (`test_foo` with no scenario) | Same command as AC1.1 — the `awk -F_ 'NF<2'` filter matches single-segment names | Task 6 step 5 |
| GH26.AC2.1 | `uv run pytest` exits 0 | `uv run pytest` | Task 6 step 1 |
| GH26.AC2.2 | No test is silently deselected or skipped due to rename | Test count cross-check: `grep -cE '^    def test_'` over the five files equals 111; `uv run pytest --collect-only` shows the same count as before this phase | Task 6 step 2 |
| GH26.AC3.1 | `grep -r "test_ac[0-9]"` returns no matches in `tests/` | Task 6 step 3 (scoped to the five in-scope files; see "Out-of-scope note" below) | Task 6 step 3 |
| GH26.AC3.2 | No documentation, CI script, or comment references an old method name | `grep -rn "test_ac6[1-4]\|test_ac2_[1-7]\|..." docs/ --include="*.md" --include="*.py" \| grep -v "^docs/project/26/"` returns empty | Task 6 step 4 |

## Per-file rename count (verified during planning)

| File | Methods | Renames | Already compliant |
|------|---------|---------|---------------------|
| `tests/converter/test_engine.py` | 31 | 22 | 9 (`TestHelpers` block) |
| `tests/crawler/test_main.py` | 32 | 32 | 0 |
| `tests/crawler/test_parser.py` | 28 | 28 | 0 (all needed `parse_path_`/`derive_statuses_`/`map_status_from_dir_` prefix) |
| `tests/converter/test_classify.py` | 4 | 4 | 0 |
| `tests/test_json_logging.py` | 16 | 16 | 0 |
| **Total** | **111** | **102** | **9** |

The "already compliant" 9 in `test_engine.py` are the `TestHelpers` class methods (`test_find_sas_files_*` × 6, `test_build_parquet_dir_*` × 3), where the function under test (`find_sas_files`, `build_parquet_dir`) already serves as the prefix — these are AC1.2 examples and stay untouched per Task 1's "unchanged" rows.

## Out-of-scope verification

`tests/registry_api/test_routes.py` contains 11 `test_ac\d+_\d+_*` methods. These are **deliberately not** in this phase's scope per the design's "Definition of Done" listing only five files (`test_engine.py`, `test_main.py`, `test_parser.py`, `test_classify.py`, `test_json_logging.py`).

After GH26 ships, a global `grep -rn "test_ac[0-9]" tests/` will still return matches in `test_routes.py` — this is not an AC failure, because AC3.1's "tests/" wording is bounded by the Definition of Done's five-file enumeration. Any reviewer who wants stricter enforcement should expand scope before merge or open a follow-up issue covering `test_routes.py`'s 11 methods.

The verification commands in `phase_01.md` Task 6 step 3 are scoped explicitly to the five in-scope files to make this scope-boundary unambiguous in the merge diff.

## Pre-rename baseline

Before applying renames, the executor must capture the baseline test count so AC2.2 can be cross-checked:

```bash
uv run pytest --collect-only -q 2>&1 | tail -1
```

Save the count (e.g. "271 tests collected") and re-run after Task 6 — the number must match exactly. Any drift indicates a rename collision (two tests landing on the same name) or a silently dropped test (typo causing the rename to break method signature).

## Human verification: none required

Every criterion is verifiable via shell command + pytest. There is no UI, no behavioural change, no external system observable from the rename — only test method names change. Reviewer can run the verification block at the bottom of `phase_01.md` Task 6 in five minutes and have evidence of every AC.
