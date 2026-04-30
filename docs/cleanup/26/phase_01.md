# GH26 Phase 1: Test naming convention rename

**Goal:** Rename ~111 test methods across five test files so each name follows `test_<function>_<scenario>`. Strip AC-code prefixes, prepend missing function names from class context, and add scenario suffixes to bare names.

**Architecture:** Pure mechanical rename — no logic, no fixtures, no imports change. Pre-computed rename map applied with `sed -i` (one pass per file) or by the executor's editor multi-rename. The diff is one-line-per-method touched, all under `tests/`. Production code is not touched. Test count is unchanged.

**Tech Stack:** No new dependencies; relies only on pytest's standard test discovery (any function starting with `test_` is collected).

**Scope:** 1 of 1 phase. Single commit per the design's effort estimate (~1.5 hours total).

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH26.AC1: All in-scope method names are compliant
- **GH26.AC1.1 Success:** Every `def test_*` in the five files matches `test_<function>_<scenario>` (two underscore-separated segments minimum after `test_`)
- **GH26.AC1.2 Success:** Names that already comply are left unchanged
- **GH26.AC1.3 Failure:** No method retains an AC-code prefix (`test_ac\d+_\d+_`)
- **GH26.AC1.4 Failure:** No method is renamed to a single-segment name (`test_foo` with no scenario)

### GH26.AC2: Test suite passes after rename
- **GH26.AC2.1 Success:** `uv run pytest` exits 0
- **GH26.AC2.2 Failure:** No test is silently deselected or skipped due to rename

### GH26.AC3: No stale name references remain
- **GH26.AC3.1 Success:** `grep -r "test_ac[0-9]"` returns no matches in the five in-scope files (see "Out-of-scope" note below for the one file the design intentionally excluded)
- **GH26.AC3.2 Success:** No documentation, CI script, or comment references an old method name

---

## Codebase verification findings

- ✓ Confirmed 5 in-scope files, with the actual method counts: `tests/converter/test_engine.py` (31), `tests/crawler/test_main.py` (32), `tests/crawler/test_parser.py` (28), `tests/converter/test_classify.py` (4), `tests/test_json_logging.py` (16) — total **111 methods** (design said "~112"; the rounding is harmless).
- ✓ `tests/crawler/test_parser.py:402` contains a local `def test_hook(...)` inside a test method's body — this is a hook fixture, not a test method, and must not be renamed. The design called this out (line 202-204) and the verification is that line 402 starts with `        def test_hook(` (eight-space indent, inside a function), not `    def test_hook(` at class scope.
- ✓ No `.github/workflows/` exists. `pyproject.toml` contains no `-k` expressions. No `.sh`/`.yml`/`.toml`/`.cfg` file in the repo references a `-k` flag. Confirmed via `grep -rn '"-k"\| -k "\|" -k\|-k ' . --include="*.sh" --include="*.yml" --include="*.toml" --include="*.cfg"` returning empty.
- ✓ No documentation or comment references any of the AC-prefixed test names except the test files themselves and the design documents under `docs/project/26/` and `docs/project/`. Verified via `grep -rn "test_ac[0-9]" . --include="*.md" --include="*.py"` filtered to non-test paths.
- ⚠ **Out-of-scope discovery:** `tests/registry_api/test_routes.py` contains 11 methods with `test_ac\d+_\d+_` prefixes (e.g. `test_ac4_1_post_with_valid_status`, `test_ac6_1_delivery_created_contains_lexicon_id_status_metadata`). The design explicitly lists only **five** in-scope files; `test_routes.py` is not one of them. Per the design's Definition of Done ("All test method names in the five in-scope files satisfy …"), this phase **does not** rename `test_routes.py`. AC3.1's `grep` will still return matches in `test_routes.py` after this phase ships — that is by design. If reviewer disagrees, expand scope before merge or open a follow-up issue. The most defensible interpretation: this issue's title says "Adopt naming convention" with a curated five-file scope; expanding scope would change the merge plan.
- ✓ Class context (used to fill in missing function names) verified: `TestConvertOne*` (8 classes) → `convert_one`; `TestHelpers` → `find_sas_files`/`build_parquet_dir` (already compliant); `TestWalkRoots` → `walk_roots`; `TestInventoryFiles` → `inventory_files`; `TestCrawl`, `TestCrawlAuth`, `TestLexiconSystemAC5Integration`, `TestSubDeliveryDiscovery`, `TestMain` → `crawl`/`main`; `TestParsePath*` → `parse_path`; `TestDeriveStatuses` → `derive_statuses`; `TestLexiconSystemAC5` → `map_status_from_dir`/`derive_statuses`; `TestClassifyException` → `classify_exception`; `TestJsonFormatter` → `json_formatter`; `TestGetLogger` → `get_logger`.

## External dependency findings

N/A — pytest's collection rules (anything starting with `test_` in a module/class) are the only relevant external behaviour, and the rename preserves that prefix. Pytest version is unaffected.

---

<!-- START_TASK_1 -->
### Task 1: Apply rename map for `tests/converter/test_engine.py`

**Verifies:** GH26.AC1.1, GH26.AC1.2, GH26.AC1.4 (for this file only — full coverage achieved across Tasks 1-5)

**Files:**
- Modify: `tests/converter/test_engine.py` — only test method names; class definitions, fixtures, body content unchanged.

**Implementation:**

The complete rename map for this file. Names already compliant are listed for reference but not renamed:

| Class | Old name | New name |
|-------|----------|----------|
| `TestHelpers` | `test_find_sas_files_single_file` | unchanged |
| `TestHelpers` | `test_find_sas_files_multiple_files_sorted` | unchanged |
| `TestHelpers` | `test_find_sas_files_mixed_case_extension` | unchanged |
| `TestHelpers` | `test_find_sas_files_excludes_non_sas` | unchanged |
| `TestHelpers` | `test_find_sas_files_empty_directory` | unchanged |
| `TestHelpers` | `test_find_sas_files_only_non_sas_files` | unchanged |
| `TestHelpers` | `test_build_parquet_dir_parent_delivery` | unchanged |
| `TestHelpers` | `test_build_parquet_dir_sub_delivery` | unchanged |
| `TestHelpers` | `test_build_parquet_dir_returns_directory_not_file` | unchanged |
| `TestConvertOneHappyPath` | `test_multiple_files_all_succeed` | `test_convert_one_multiple_files_all_succeed` |
| `TestConvertOneHappyPath` | `test_single_file_backward_compat` | `test_convert_one_single_file_backward_compat` |
| `TestConvertOneHappyPath` | `test_mixed_case_extension_discovered_and_converted` | `test_convert_one_mixed_case_extension_discovered` |
| `TestConvertOneHappyPath` | `test_uppercase_sas_extension_found` | `test_convert_one_uppercase_sas_extension_found` |
| `TestConvertOneSkipGuards` | `test_skip_when_already_converted_flag_set` | `test_convert_one_skip_when_already_converted` |
| `TestConvertOneSkipGuards` | `test_skip_when_conversion_error_set` | `test_convert_one_skip_when_conversion_error_set` |
| `TestConvertOneSkipGuards` | `test_skip_when_dp_id_excluded` | `test_convert_one_skip_when_dp_id_excluded` |
| `TestConvertOneSkipGuards` | `test_no_skip_when_dp_id_not_excluded` | `test_convert_one_no_skip_when_dp_id_not_excluded` |
| `TestConvertOneSkipGuards` | `test_null_conversion_error_does_not_skip` | `test_convert_one_null_conversion_error_does_not_skip` |
| `TestConvertOnePartialSuccess` | `test_partial_success_patches_with_converted_files_and_errors` | `test_convert_one_partial_success_with_errors` |
| `TestConvertOneTotalFailure` | `test_all_files_fail` | `test_convert_one_all_files_fail` |
| `TestConvertOneTotalFailure` | `test_skip_guard_blocks_errored_delivery` | `test_convert_one_skip_guard_blocks_errored_delivery` |
| `TestConvertOneEmptyDir` | `test_no_sas_files_skips_with_no_side_effects` | `test_convert_one_no_sas_files_skips` |
| `TestConvertOneEmptyDir` | `test_no_diagnostic_dir_contents_logged` | `test_convert_one_no_diagnostic_dir_contents_logged` |
| `TestConvertOneInterrupt` | `test_keyboard_interrupt_propagates_no_patch_or_event` | `test_convert_one_keyboard_interrupt_propagates` |
| `TestConvertOneInterrupt` | `test_system_exit_propagates_no_patch_or_event` | `test_convert_one_system_exit_propagates` |
| `TestConvertOneFailure` | `test_parse_error_in_single_file_total_failure` | `test_convert_one_parse_error_total_failure` |
| `TestConvertOneFailure` | `test_no_retry_after_failure` | `test_convert_one_no_retry_after_failure` |
| `TestConvertOneFailure` | `test_error_message_truncated_to_500_chars` | `test_convert_one_error_message_truncated` |
| `TestConvertOneLogging` | `test_per_file_success_logging` | `test_convert_one_per_file_success_logging` |
| `TestConvertOneLogging` | `test_summary_delivery_logging` | `test_convert_one_summary_delivery_logging` |
| `TestConvertOneIntegration` | `test_multiple_real_sas_files_to_parquet` | `test_convert_one_multiple_real_sas_files` |

Apply these renames using either `sed -i 's/^    def test_OLD/    def test_NEW/g'` per row (one sed invocation per rename — easier to review per-line in diff), or use the editor's multi-rename. Do NOT rename via global string replace; the leading 4-space indentation guards against renaming any string literals or docstrings that happen to mention an old name.

**Recommended sed command per rename:**

```bash
sed -i '' 's|^    def test_multiple_files_all_succeed(|    def test_convert_one_multiple_files_all_succeed(|' tests/converter/test_engine.py
```

The trailing `(` is critical — it ensures only the function definition matches, not any reference to the name elsewhere (none expected, but belt-and-braces).

After applying, run `grep -nE '^    def test_' tests/converter/test_engine.py` and verify the output matches the "After" column for every row.

**Verification:**

```bash
# All non-Helpers test methods now start with the function under test
grep -nE '^    def test_(convert_one_|find_sas_files_|build_parquet_dir_)' tests/converter/test_engine.py | wc -l
```

Expected: 31.

```bash
# No method has a scenario-only name (no longer matches the legacy patterns)
grep -nE '^    def test_(multiple_files|single_file_backward|mixed_case_extension_discovered|skip_when|partial_success_patches|all_files_fail|null_conversion|parse_error_in_single|no_retry_after|error_message_truncated|per_file_success_logging|summary_delivery_logging|multiple_real_sas|keyboard_interrupt|system_exit|no_sas_files_skips|no_diagnostic_dir|skip_guard_blocks)\(' tests/converter/test_engine.py
```

Expected: empty (zero matches).

```bash
uv run pytest tests/converter/test_engine.py -v --collect-only | grep -c "^.*test_"
```

Expected: 31 (same as before rename).

**Commit:** deferred to Task 6.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Apply rename map for `tests/crawler/test_main.py`

**Verifies:** GH26.AC1.1, GH26.AC1.3 for this file (strips AC prefixes); contributes to GH26.AC3.1.

**Files:**
- Modify: `tests/crawler/test_main.py` — 32 method renames.

**Implementation:**

| Class | Old name | New name |
|-------|----------|----------|
| `TestWalkRoots` | `test_ac2_1_discovers_msoc_and_msoc_new_directories` | `test_walk_roots_discovers_msoc_and_msoc_new_directories` |
| `TestWalkRoots` | `test_ac2_4_processes_multiple_scan_roots` | `test_walk_roots_processes_multiple_scan_roots` |
| `TestWalkRoots` | `test_ac2_5_non_existent_scan_root_skipped` | `test_walk_roots_non_existent_scan_root_skipped` |
| `TestWalkRoots` | `test_ac2_3_msoc_in_sibling_not_discovered` | `test_walk_roots_msoc_in_sibling_not_discovered` |
| `TestWalkRoots` | `test_ac2_4_msoc_at_wrong_depth_not_discovered` | `test_walk_roots_msoc_at_wrong_depth_not_discovered` |
| `TestWalkRoots` | `test_ac2_5_msoc_nested_too_deep_not_discovered` | `test_walk_roots_msoc_nested_too_deep_not_discovered` |
| `TestWalkRoots` | `test_ac2_6_multiple_dpids_discovered` | `test_walk_roots_multiple_dpids_discovered` |
| `TestWalkRoots` | `test_ac2_7_multiple_version_dirs_discovered` | `test_walk_roots_multiple_version_dirs_discovered` |
| `TestWalkRoots` | `test_ac3_1_warning_when_target_missing` | `test_walk_roots_warning_when_target_missing` |
| `TestWalkRoots` | `test_ac3_2_no_warning_when_target_exists` | `test_walk_roots_no_warning_when_target_exists` |
| `TestWalkRoots` | `test_custom_target_directory` | `test_walk_roots_custom_target_directory` |
| `TestWalkRoots` | `test_exclusions_skip_dpid_directories` | `test_walk_roots_exclusions_skip_dpid_directories` |
| `TestInventoryFiles` | `test_ac2_2_inventory_sas_files_with_metadata` | `test_inventory_files_includes_metadata` |
| `TestInventoryFiles` | `test_ac2_6_empty_delivery_directory_inventory_empty` | `test_inventory_files_empty_directory_returns_empty` |
| `TestCrawl` | `test_ac2_3_posts_valid_delivery_payload_to_registry` | `test_crawl_posts_valid_delivery_payload` |
| `TestCrawl` | `test_ac2_7_pending_superseded_by_newer_version_marked_failed` | `test_crawl_pending_superseded_by_newer_version_marked_failed` |
| `TestCrawl` | `test_ac3_4_re_crawling_same_delivery_overwrites_manifest_idempotent` | `test_crawl_re_crawl_overwrites_manifest_idempotent` |
| `TestCrawl` | `test_ac4_4_excluded_dp_ids_no_error_manifest` | `test_crawl_excluded_dp_ids_no_error_manifest` |
| `TestCrawl` | `test_excluded_dpid_folder_blocks_all_deliveries_inside` | `test_crawl_excluded_dpid_folder_blocks_all_deliveries` |
| `TestCrawl` | `test_ac7_1_idempotent_crawl_produces_identical_manifests` | `test_crawl_idempotent_produces_identical_manifests` |
| `TestCrawl` | `test_ac7_2_unchanged_fingerprint_on_re_crawl` | `test_crawl_unchanged_fingerprint_on_re_crawl` |
| `TestLexiconSystemAC5Integration` | `test_ac5_6_crawler_post_payload_includes_lexicon_id_and_status` | `test_crawl_post_payload_includes_lexicon_id_and_status` |
| `TestCrawlAuth` | `test_token_forwarded_to_post_delivery` | `test_crawl_token_forwarded_to_registry` |
| `TestCrawlAuth` | `test_no_token_forwards_none` | `test_crawl_no_token_forwards_none` |
| `TestSubDeliveryDiscovery` | `test_sub_delivery_created_when_sub_dir_exists` | `test_crawl_sub_delivery_created_when_sub_dir_exists` |
| `TestSubDeliveryDiscovery` | `test_sub_delivery_inherits_parent_identity` | `test_crawl_sub_delivery_inherits_parent_identity` |
| `TestSubDeliveryDiscovery` | `test_sub_delivery_inherits_parent_status` | `test_crawl_sub_delivery_inherits_parent_status` |
| `TestSubDeliveryDiscovery` | `test_sub_delivery_has_own_delivery_id` | `test_crawl_sub_delivery_has_own_delivery_id` |
| `TestSubDeliveryDiscovery` | `test_sub_delivery_has_own_file_inventory` | `test_crawl_sub_delivery_has_own_file_inventory` |
| `TestSubDeliveryDiscovery` | `test_missing_sub_dir_silently_skipped` | `test_crawl_missing_sub_dir_silently_skipped` |
| `TestSubDeliveryDiscovery` | `test_sub_deliveries_grouped_by_own_lexicon_for_derivation` | `test_crawl_sub_deliveries_grouped_by_own_lexicon` |
| `TestMain` | `test_ac5_4_registry_unreachable_exits_nonzero` | `test_main_registry_unreachable_exits_nonzero` |

Note for the executor: GH21 phase 3 also rewrites `TestMain.test_ac5_4_registry_unreachable_exits_nonzero`'s body. If GH21 lands first, the body is different but the method name still matches — rename to `test_main_registry_unreachable_exits_nonzero`. If GH26 lands first, GH21 will rewrite the method whose new name is `test_main_registry_unreachable_exits_nonzero`. Either ordering composes; the merge conflict (if any) is on body content, not name.

**Verification:**

```bash
grep -cE '^    def test_(walk_roots_|inventory_files_|crawl_|main_)' tests/crawler/test_main.py
```

Expected: 32.

```bash
grep -nE '^    def test_ac[0-9]' tests/crawler/test_main.py
```

Expected: empty.

**Commit:** deferred to Task 6.
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Apply rename map for `tests/crawler/test_parser.py`

**Verifies:** GH26.AC1.1, GH26.AC1.3 for this file.

**Files:**
- Modify: `tests/crawler/test_parser.py` — 28 method renames.

**Implementation:**

| Class | Old name | New name |
|-------|----------|----------|
| `TestParsePathSuccess` | `test_standard_path_with_msoc_status_passed` | `test_parse_path_standard_with_msoc_status_passed` |
| `TestParsePathSuccess` | `test_path_with_msoc_new_status_pending` | `test_parse_path_msoc_new_status_pending` |
| `TestParsePathSuccess` | `test_dp_id_at_minimum_boundary_3_chars` | `test_parse_path_dp_id_at_minimum_boundary` |
| `TestParsePathSuccess` | `test_dp_id_at_maximum_boundary_8_chars` | `test_parse_path_dp_id_at_maximum_boundary` |
| `TestParsePathSuccess` | `test_version_v01_format` | `test_parse_path_version_v01_format` |
| `TestParsePathSuccess` | `test_version_v1_format` | `test_parse_path_version_v1_format` |
| `TestParsePathSuccess` | `test_version_v10_format` | `test_parse_path_version_v10_format` |
| `TestParsePathSuccess` | `test_different_scan_root_one` | `test_parse_path_different_scan_root_one` |
| `TestParsePathSuccess` | `test_different_scan_root_two` | `test_parse_path_different_scan_root_two` |
| `TestParsePathSuccess` | `test_request_id_with_more_than_3_segments` | `test_parse_path_request_id_with_more_than_3_segments` |
| `TestParsePathFailure` | `test_dp_id_too_short_2_chars` | `test_parse_path_dp_id_too_short` |
| `TestParsePathFailure` | `test_dp_id_too_long_9_chars` | `test_parse_path_dp_id_too_long` |
| `TestParsePathFailure` | `test_missing_version_segment` | `test_parse_path_missing_version_segment` |
| `TestParsePathFailure` | `test_path_ending_in_neither_msoc_nor_msoc_new` | `test_parse_path_ending_neither_msoc_nor_msoc_new` |
| `TestParsePathFailure` | `test_path_too_short_missing_version_dir` | `test_parse_path_too_short_missing_version_dir` |
| `TestParsePathEdgeCases` | `test_excluded_dp_id_returns_none` | `test_parse_path_excluded_dp_id_returns_none` |
| `TestParsePathEdgeCases` | `test_excluded_dp_id_among_multiple_exclusions` | `test_parse_path_excluded_dp_id_among_multiple_exclusions` |
| `TestParsePathEdgeCases` | `test_non_excluded_dp_id_with_exclusions_set` | `test_parse_path_non_excluded_dp_id_with_exclusions` |
| `TestDeriveStatuses` | `test_ac2_7_pending_superseded_by_newer_version` | `test_derive_statuses_pending_superseded_by_newer_version` |
| `TestDeriveStatuses` | `test_ac2_8_pending_without_newer_version_stays_pending` | `test_derive_statuses_pending_without_newer_version` |
| `TestDeriveStatuses` | `test_ac2_9_passed_delivery_never_changed` | `test_derive_statuses_passed_delivery_never_changed` |
| `TestDeriveStatuses` | `test_multiple_groups_scoped_per_workplan_dp_id` | `test_derive_statuses_multiple_groups_scoped_per_workplan` |
| `TestDeriveStatuses` | `test_empty_list_returns_empty_list` | `test_derive_statuses_empty_list_returns_empty` |
| `TestLexiconSystemAC5` | `test_ac5_1_terminal_directory_in_dir_map_maps_to_correct_status` | `test_map_status_from_dir_terminal_dir_maps_to_correct_status` |
| `TestLexiconSystemAC5` | `test_ac5_2_terminal_directory_not_in_dir_map_produces_parse_error` | `test_map_status_from_dir_terminal_dir_not_in_map_produces_parse_error` |
| `TestLexiconSystemAC5` | `test_ac5_3_derivation_hook_called_when_set` | `test_derive_statuses_hook_called_when_set` |
| `TestLexiconSystemAC5` | `test_ac5_4_no_derivation_when_derive_hook_is_null` | `test_derive_statuses_no_derivation_when_hook_is_null` |
| `TestLexiconSystemAC5` | `test_ac5_5_qa_hook_marks_superseded_pending_as_failed` | `test_derive_statuses_qa_hook_marks_superseded_pending_failed` |

**Critical:** the local helper function `def test_hook(...)` at line 402 (inside the body of `test_ac5_3_derivation_hook_called_when_set`/`test_derive_statuses_hook_called_when_set`) must NOT be renamed. It is a fixture-style nested function with eight-space indentation, not a class-level test method. The sed pattern `^    def test_` (four-space indent only) avoids it; verify with `grep -n '^    def test_hook' tests/crawler/test_parser.py` returning empty (the inner `test_hook` has eight-space indent and won't match the four-space anchor).

**Verification:**

```bash
grep -cE '^    def test_(parse_path_|derive_statuses_|map_status_from_dir_)' tests/crawler/test_parser.py
```

Expected: 28.

```bash
grep -nE '^    def test_ac[0-9]' tests/crawler/test_parser.py
```

Expected: empty.

```bash
grep -n 'def test_hook' tests/crawler/test_parser.py
```

Expected: a single match at line 402 with eight-space indent (the local helper, intentionally untouched).

**Commit:** deferred to Task 6.
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Apply rename map for `tests/converter/test_classify.py`

**Verifies:** GH26.AC1.1, GH26.AC1.4 (no more bare names).

**Files:**
- Modify: `tests/converter/test_classify.py` — 4 method renames.

**Implementation:**

| Class | Old name | New name |
|-------|----------|----------|
| `TestClassifyException` | `test_known_exception_classes` | `test_classify_exception_known_classes` |
| `TestClassifyException` | `test_subclasses_match_parent_class` | `test_classify_exception_subclass_matches_parent` |
| `TestClassifyException` | `test_filenotfound_preferred_over_oserror` | `test_classify_exception_filenotfound_preferred_over_oserror` |
| `TestClassifyException` | `test_permission_preferred_over_oserror` | `test_classify_exception_permission_preferred_over_oserror` |

**Verification:**

```bash
grep -cE '^    def test_classify_exception_' tests/converter/test_classify.py
```

Expected: 4.

```bash
grep -nE '^    def test_(known_exception|subclasses_match|filenotfound_preferred|permission_preferred)\(' tests/converter/test_classify.py
```

Expected: empty.

**Commit:** deferred to Task 6.
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Apply rename map for `tests/test_json_logging.py`

**Verifies:** GH26.AC1.1, GH26.AC1.3.

**Files:**
- Modify: `tests/test_json_logging.py` — 16 method renames.

**Implementation:**

| Class | Old name | New name |
|-------|----------|----------|
| `TestJsonFormatter` | `test_ac61_output_is_valid_json` | `test_json_formatter_output_is_valid_json` |
| `TestJsonFormatter` | `test_ac62_required_fields_present` | `test_json_formatter_required_fields_present` |
| `TestJsonFormatter` | `test_ac62_timestamp_format_is_iso` | `test_json_formatter_timestamp_is_iso` |
| `TestJsonFormatter` | `test_ac63_contextual_fields_included_when_provided` | `test_json_formatter_contextual_fields_included` |
| `TestJsonFormatter` | `test_ac63_contextual_fields_absent_when_not_provided` | `test_json_formatter_contextual_fields_absent` |
| `TestJsonFormatter` | `test_ac63_partial_contextual_fields` | `test_json_formatter_partial_contextual_fields` |
| `TestJsonFormatter` | `test_level_names_correctly_formatted` | `test_json_formatter_level_names_correctly_formatted` |
| `TestGetLogger` | `test_ac64_logs_to_stderr` | `test_get_logger_logs_to_stderr` |
| `TestGetLogger` | `test_ac64_logs_to_file` | `test_get_logger_logs_to_file` |
| `TestGetLogger` | `test_ac64_both_stderr_and_file` | `test_get_logger_logs_to_both_stderr_and_file` |
| `TestGetLogger` | `test_log_dir_created_if_missing` | `test_get_logger_log_dir_created_if_missing` |
| `TestGetLogger` | `test_custom_log_filename` | `test_get_logger_custom_log_filename` |
| `TestGetLogger` | `test_no_file_handler_when_log_dir_none` | `test_get_logger_no_file_handler_when_log_dir_none` |
| `TestGetLogger` | `test_logger_level_respected` | `test_get_logger_level_respected` |
| `TestGetLogger` | `test_no_duplicate_handlers_on_multiple_calls` | `test_get_logger_no_duplicate_handlers` |
| `TestGetLogger` | `test_contextual_fields_via_extra_kwarg` | `test_get_logger_contextual_fields_via_extra_kwarg` |

**Verification:**

```bash
grep -cE '^    def test_(json_formatter_|get_logger_)' tests/test_json_logging.py
```

Expected: 16.

```bash
grep -nE '^    def test_ac[0-9]' tests/test_json_logging.py
```

Expected: empty.

**Commit:** deferred to Task 6.
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Run full suite, grep for stale references, commit

**Verifies:** GH26.AC2.1, GH26.AC2.2, GH26.AC3.1, GH26.AC3.2

**Files:** none modified in this task — verification and commit only.

**Implementation:**

1. **Full suite:**

```bash
uv run pytest
```

Expected: same total test count as before this phase, all passing. The exact pre-rename count will vary by branch state (other in-flight issues may have added or removed tests); take the count from the baseline of the executor's branch before applying renames.

2. **Test count cross-check** to catch any silent rename collision (e.g. two tests landing on the same name within a class):

```bash
# Count test methods in the five in-scope files. Should equal 111 (pre-rename count).
grep -cE '^    def test_' tests/converter/test_engine.py tests/crawler/test_main.py tests/crawler/test_parser.py tests/converter/test_classify.py tests/test_json_logging.py | awk -F: '{sum += $2} END {print sum}'
```

Expected: 111.

3. **AC3.1 grep** (scoped to the five in-scope files only — see "Out-of-scope" note above for the intentional exclusion of `test_routes.py`):

```bash
grep -nE 'def test_ac[0-9]' \
    tests/converter/test_engine.py \
    tests/crawler/test_main.py \
    tests/crawler/test_parser.py \
    tests/converter/test_classify.py \
    tests/test_json_logging.py
```

Expected: empty.

4. **AC3.2 grep** for stale references in non-test artefacts:

```bash
grep -rn "test_ac6[1-4]\|test_ac2_[1-7]\|test_ac3_[1-4]\|test_ac4_[1-6]\|test_ac5_[1-6]\|test_ac7_[1-2]\|test_known_exception_classes\|test_subclasses_match_parent_class\|test_skip_when_already_converted_flag_set\|test_no_sas_files_skips_with_no_side_effects\|test_keyboard_interrupt_propagates_no_patch_or_event\|test_per_file_success_logging\|test_multiple_real_sas_files_to_parquet" \
    docs/ \
    --include="*.md" \
    --include="*.py" 2>/dev/null \
    | grep -v "^docs/project/26/"
```

Expected: zero matches outside `docs/project/26/` (the design and this implementation plan are the only documents that mention old names; both are in the excluded path).

5. **Belt-and-braces** — confirm no in-scope test method ended up with a single segment name (AC1.4):

```bash
grep -nE '^    def test_[a-z_]+\(' tests/converter/test_engine.py tests/crawler/test_main.py tests/crawler/test_parser.py tests/converter/test_classify.py tests/test_json_logging.py | awk -F'def test_' '{print $2}' | awk -F'(' '{print $1}' | awk -F_ 'NF<2 {print "FAIL: single-segment name " $0}'
```

Expected: empty (every name has at least two underscore-separated segments after `test_`).

6. **Commit:**

```bash
git add tests/converter/test_engine.py \
        tests/crawler/test_main.py \
        tests/crawler/test_parser.py \
        tests/converter/test_classify.py \
        tests/test_json_logging.py

git commit -m "refactor(tests): adopt test_<function>_<scenario> naming convention (GH26)"
```

7. **Final sanity check:**

```bash
git show --stat HEAD | head -10
```

Expected: 5 files changed, 111 insertions, 111 deletions (one line changed per renamed method, plus zero net for already-compliant ones — exact insertion/deletion counts depend on multi-line `def test_xxx(self, ...)` formatting and may differ by a small constant; the right shape is "renames only, no body changes").
<!-- END_TASK_6 -->

---

## Phase 1 Done When

- All 111 test methods in the five in-scope files satisfy `test_<function>_<scenario>`.
- Names already compliant (the `TestHelpers` group in `test_engine.py` plus the existing compliant names in `test_parser.py:TestParsePathSuccess`) are unchanged.
- `grep -nE 'def test_ac[0-9]'` over the five in-scope files returns empty.
- No test was silently dropped — pre/post test counts match exactly per file.
- `uv run pytest` exits 0.
- Single commit covering all five files.

## Notes for executor

- **Phase ordering:** GH26 is the last issue (Tier 4). All test-touching issues should land first to avoid rename collisions.
- **Conflict surface:** the design (line 13) and DAG analysis flag five files as conflict hotspots. With GH21 and GH27 already shipped, the body changes in test files are stable; this rename only touches `def test_xxx(self, ...)` lines, which are not edited by GH21/GH27/GH22/GH23 etc. Mid-phase merge conflicts are unlikely.
- **Out-of-scope file:** `tests/registry_api/test_routes.py` contains 11 AC-prefixed test names. The design lists only the five in-scope files; renaming `test_routes.py` is a follow-up issue, not part of GH26. The AC3.1 grep is therefore scoped to the five in-scope files explicitly. If reviewer wants `test_routes.py` included, surface it before merge — extending scope by 11 names is a 5-minute addition.
- **Risk mitigation:** running each task's verification grep before moving to the next prevents per-file collision (e.g. a typo producing `test_walk_roots_walk_roots_x`). The full pytest run in Task 6 catches collection-time regressions.
- **Local `def test_hook` at `test_parser.py:402`:** explicitly preserved. The class-level rename pattern `^    def test_` (four-space indent) does not match the eight-space inner function. This is also a regression test for the rename script: if the inner `test_hook` is accidentally pytest-collected, the suite count after rename would jump by one — verify count is exactly 111.
- **Sed dialect:** the verification commands use `sed -i ''` syntax (BSD/macOS); on Linux use `sed -i` without the empty argument. Either dialect is fine; the executor should pick the one matching the development host.
