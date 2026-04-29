# Issue #26: Adopt test_<function>_<scenario> Naming Convention

## Summary

~112 test methods across five files use inconsistent naming: some embed AC codes
(`test_ac2_3_posts_valid_delivery_payload_to_registry`), some embed implementation
details as the scenario (`test_find_sas_files_mixed_case_extension`), some omit a
scenario entirely (`test_known_exception_classes`), and a minority are already
compliant. The rename is a pure mechanical refactor — no logic, no fixtures, no
imports change. A sed/regex script is the right tool: it avoids transcription
errors on ~112 names and keeps the diff readable.

The only real risk is pytest `-k` expressions in CI scripts or developer notes that
select tests by name. Investigation found no `.github/workflows/` directory and no
`-k` options in `pyproject.toml`. The risk is low but warrants a grep before merge.

## Definition of Done

- All test method names in the five in-scope files satisfy `test_<function>_<scenario>`
- Every test still passes (`uv run pytest` green)
- No other files reference the old names (imports, `-k` flags, comments)

## Acceptance Criteria

### issue-26.AC1: All in-scope method names are compliant

- **issue-26.AC1.1 Success:** Every `def test_*` in the five files matches `test_<function>_<scenario>` (two underscore-separated segments minimum after `test_`)
- **issue-26.AC1.2 Success:** Names that already comply are left unchanged
- **issue-26.AC1.3 Failure:** No method retains an AC-code prefix (`test_ac\d+_\d+_`)
- **issue-26.AC1.4 Failure:** No method is renamed to a single-segment name (`test_foo` with no scenario)

### issue-26.AC2: Test suite passes after rename

- **issue-26.AC2.1 Success:** `uv run pytest` exits 0
- **issue-26.AC2.2 Failure:** No test is silently deselected or skipped due to rename

### issue-26.AC3: No stale name references remain

- **issue-26.AC3.1 Success:** `grep -r "test_ac[0-9]"` returns no matches in `tests/`
- **issue-26.AC3.2 Success:** No documentation, CI script, or comment references an old method name

## Glossary

- **`test_<function>_<scenario>`**: Naming convention where `function` is the
  unit under test (a function, method, or behaviour) and `scenario` is the
  condition or case being verified (e.g. `test_find_sas_files_empty_directory`).
- **AC-code prefix**: Legacy names that embed acceptance-criteria identifiers
  directly in the method name (e.g. `test_ac2_3_posts_valid_delivery_payload`).
  These encode traceability in the name rather than in a comment, making names
  brittle when AC numbering changes.
- **sed script**: A shell one-liner or file of `s/old/new/` substitutions applied
  with `sed -i` for bulk in-place rename across files.

---

## Current Naming Patterns

Three distinct patterns exist across the five files:

**Pattern A — AC-code prefix** (non-compliant, ~25 methods)
The method name starts with `test_ac<N>_<M>_`. The function being tested is
buried or absent.

```
test_ac2_3_posts_valid_delivery_payload_to_registry   # crawler/test_main.py
test_ac5_1_terminal_directory_in_dir_map_maps_to_correct_status  # crawler/test_parser.py
test_ac61_output_is_valid_json                        # test_json_logging.py
```

**Pattern B — Scenario only / descriptive prose** (partially compliant, ~70 methods)
Many names describe the scenario well but omit or mangle the function name.
Some are already `test_<function>_<scenario>` and need no change.

```
test_find_sas_files_single_file          # already compliant
test_skip_when_already_converted_flag_set  # missing function name
test_sub_delivery_created_when_sub_dir_exists  # missing function name
test_token_forwarded_to_post_delivery    # missing function name
```

**Pattern C — No scenario** (non-compliant, ~4 methods in test_classify.py)
```
test_known_exception_classes
test_subclasses_match_parent_class
```

## Rename Strategy

**Use a sed script, not manual edits.** 112 renames by hand invites typos and
missed cases. A script produces a reviewable, repeatable diff.

The rename logic per file:

1. **Strip AC-code prefixes**: `s/test_ac[0-9]+_[0-9]+_/test_/` then prepend the
   function name manually for the cases where the remainder still lacks one.
2. **Prepend missing function names**: For names that are scenario-only, prefix
   with the public function under test. The class name usually encodes this
   (e.g. `TestConvertOneSkipGuards` → function is `convert_one`).
3. **Add scenario to bare names**: `test_known_exception_classes` →
   `test_classify_exception_known_classes`.

The sed approach works cleanly for pattern A. Patterns B and C require
mapping class context to function name, which is better done as a curated
rename list than a pure regex.

**Recommended approach:** generate the full rename list from `grep`, review it,
then apply with `sed -i` in one pass per file.

## Sample Before/After by File

### `tests/converter/test_engine.py` (31 methods)

Most names in `TestHelpers` are already compliant. The other classes need the
function name (`convert_one`) prepended where it is absent.

| Before | After |
|--------|-------|
| `test_find_sas_files_single_file` | unchanged (already compliant) |
| `test_build_parquet_dir_parent_delivery` | unchanged |
| `test_multiple_files_all_succeed` | `test_convert_one_multiple_files_all_succeed` |
| `test_skip_when_already_converted_flag_set` | `test_convert_one_skip_when_already_converted` |
| `test_skip_when_dp_id_excluded` | `test_convert_one_skip_when_dp_id_excluded` |
| `test_partial_success_patches_with_converted_files_and_errors` | `test_convert_one_partial_success_with_errors` |
| `test_all_files_fail` | `test_convert_one_all_files_fail` |
| `test_no_sas_files_skips_with_no_side_effects` | `test_convert_one_no_sas_files_skips` |
| `test_keyboard_interrupt_propagates_no_patch_or_event` | `test_convert_one_keyboard_interrupt_propagates` |
| `test_per_file_success_logging` | `test_convert_one_per_file_success_logging` |
| `test_multiple_real_sas_files_to_parquet` | `test_convert_one_multiple_real_sas_files` |

### `tests/crawler/test_main.py` (32 methods)

AC-code prefixes are stripped and the enclosing class (`crawl` or `walk_roots`) is
used as the function segment.

| Before | After |
|--------|-------|
| `test_ac2_1_discovers_msoc_and_msoc_new_directories` | `test_walk_roots_discovers_msoc_and_msoc_new_directories` |
| `test_ac2_3_posts_valid_delivery_payload_to_registry` | `test_crawl_posts_valid_delivery_payload` |
| `test_ac2_7_pending_superseded_by_newer_version_marked_failed` | `test_crawl_pending_superseded_by_newer_version_marked_failed` |
| `test_ac3_4_re_crawling_same_delivery_overwrites_manifest_idempotent` | `test_crawl_re_crawl_overwrites_manifest_idempotent` |
| `test_ac4_4_excluded_dp_ids_no_error_manifest` | `test_crawl_excluded_dp_ids_no_error_manifest` |
| `test_ac5_4_registry_unreachable_exits_nonzero` | `test_crawl_registry_unreachable_exits_nonzero` |
| `test_token_forwarded_to_post_delivery` | `test_crawl_token_forwarded_to_registry` |
| `test_sub_delivery_created_when_sub_dir_exists` | `test_crawl_sub_delivery_created_when_sub_dir_exists` |
| `test_missing_sub_dir_silently_skipped` | `test_crawl_missing_sub_dir_silently_skipped` |

### `tests/crawler/test_parser.py` (29 methods)

Functions under test: `parse_path`, `derive_statuses`, `map_status_from_dir`.

| Before | After |
|--------|-------|
| `test_standard_path_with_msoc_status_passed` | `test_parse_path_standard_with_msoc_status_passed` |
| `test_dp_id_too_short_2_chars` | `test_parse_path_dp_id_too_short` |
| `test_excluded_dp_id_returns_none` | `test_parse_path_excluded_dp_id_returns_none` |
| `test_ac2_7_pending_superseded_by_newer_version` | `test_derive_statuses_pending_superseded_by_newer_version` |
| `test_multiple_groups_scoped_per_workplan_dp_id` | `test_derive_statuses_multiple_groups_scoped_per_workplan` |
| `test_empty_list_returns_empty_list` | `test_derive_statuses_empty_list_returns_empty` |
| `test_ac5_1_terminal_directory_in_dir_map_maps_to_correct_status` | `test_map_status_from_dir_terminal_dir_maps_to_correct_status` |
| `test_ac5_3_derivation_hook_called_when_set` | `test_derive_statuses_hook_called_when_set` |
| `test_ac5_5_qa_hook_marks_superseded_pending_as_failed` | `test_derive_statuses_qa_hook_marks_superseded_pending_failed` |

### `tests/converter/test_classify.py` (4 methods)

Function under test: `classify_exception`.

| Before | After |
|--------|-------|
| `test_known_exception_classes` | `test_classify_exception_known_classes` |
| `test_subclasses_match_parent_class` | `test_classify_exception_subclass_matches_parent` |
| `test_filenotfound_preferred_over_oserror` | `test_classify_exception_filenotfound_preferred_over_oserror` |
| `test_permission_preferred_over_oserror` | `test_classify_exception_permission_preferred_over_oserror` |

### `tests/test_json_logging.py` (16 methods)

Functions under test: `JsonFormatter` (format behaviour), `get_logger`.

| Before | After |
|--------|-------|
| `test_ac61_output_is_valid_json` | `test_json_formatter_output_is_valid_json` |
| `test_ac62_required_fields_present` | `test_json_formatter_required_fields_present` |
| `test_ac62_timestamp_format_is_iso` | `test_json_formatter_timestamp_is_iso` |
| `test_ac63_contextual_fields_included_when_provided` | `test_json_formatter_contextual_fields_included` |
| `test_ac63_contextual_fields_absent_when_not_provided` | `test_json_formatter_contextual_fields_absent` |
| `test_ac64_logs_to_stderr` | `test_get_logger_logs_to_stderr` |
| `test_ac64_logs_to_file` | `test_get_logger_logs_to_file` |
| `test_ac64_both_stderr_and_file` | `test_get_logger_logs_to_both_stderr_and_file` |
| `test_level_names_correctly_formatted` | `test_json_formatter_level_names_correctly_formatted` |
| `test_log_dir_created_if_missing` | `test_get_logger_log_dir_created_if_missing` |
| `test_no_duplicate_handlers_on_multiple_calls` | `test_get_logger_no_duplicate_handlers` |

## Risks

**No CI name-based selection foreseen.** `pyproject.toml` contains no `-k`
expressions and there is no `.github/workflows/` directory. Before merging,
run: `grep -r "\-k " . --include="*.sh" --include="*.yml" --include="*.toml"`
to confirm nothing external selects by name.

**Parametrize IDs are unaffected.** The files use `pytest.mark.parametrize`
with explicit `ids` or positional tuples; none derive from method names.

**Inner test helpers.** `test_parser.py` line 402 defines `def test_hook(…)` as
a local function inside a test method. This is not a test method (it has no
`self` and is not at class scope) and must not be renamed.

**Name length.** A few after-names are long
(`test_json_formatter_contextual_fields_absent_when_not_provided`). Truncate
the scenario segment where it reads clearly without full verbosity.

## Effort Estimate

| Task | Estimate |
|------|----------|
| Generate full rename list (grep + review) | 30 min |
| Apply renames via sed / editor multi-rename | 30 min |
| Run `uv run pytest` and fix any breakage | 15 min |
| Grep for stale references, update if any | 10 min |
| **Total** | **~1.5 hours** |

Priority is low. No logic changes. Safe to batch with other housekeeping.
