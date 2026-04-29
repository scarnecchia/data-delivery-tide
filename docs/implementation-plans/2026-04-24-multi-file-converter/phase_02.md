# Multi-File Converter Implementation Plan

**Goal:** Rework the converter engine to handle deliveries containing multiple SAS7BDAT files, with partial success support.

**Architecture:** Replace the single-file discovery and output path functions with multi-file versions. Rewrite `convert_one` to iterate over all SAS files, collect per-file results, and issue a single PATCH + event. The core `convert_sas_to_parquet` function is unchanged.

**Tech Stack:** Python 3.10+, pyreadstat, pyarrow, pytest

**Scope:** 2 phases from original design (phases 1-2). This is Phase 2: Cleanup and documentation.

**Codebase verified:** 2026-04-24

---

## Acceptance Criteria Coverage

**Verifies: None** -- This is an infrastructure/documentation phase. No acceptance criteria are tested here.

---

## Phase 2: Cleanup and Documentation

**Files:**
- Modify: `src/pipeline/converter/CLAUDE.md` (49 lines currently)
- Modify: `docs/design-plans/2026-04-24-multi-file-converter.md` (198 lines currently)

---

<!-- START_TASK_1 -->
### Task 1: Update converter CLAUDE.md

**Files:**
- Modify: `src/pipeline/converter/CLAUDE.md`

**Implementation:**

Update the following sections to reflect multi-file behavior:

**Purpose** (line 7): Change "one delivery at a time" phrasing to reflect that each delivery may contain multiple SAS files. The engine still processes one *delivery* at a time, but now iterates over all SAS files within it.

**Contracts - Writes** (line 13): Update to reflect:
- Output: one Parquet file per SAS file at `{source_path}/parquet/{sas_stem}.parquet`
- PATCH on success: `{output_path (directory), parquet_converted_at, metadata: {converted_files}}` and optionally `metadata: {conversion_errors}` on partial success
- PATCH on total failure: `{metadata: {conversion_error (singular), conversion_errors (plural)}}`
- Events: `conversion.completed` payload now includes `file_count`, `total_rows`, `total_bytes`, `failed_count`

**Contracts - Guarantees** (line 14): Add note about partial success: if some files fail, the rest are still converted and the delivery is marked converted.

**Invariants** (line 33): Update the output path invariant from `{source_path}/parquet/{source_path.name}.parquet` to `{source_path}/parquet/{sas_stem}.parquet` for each SAS file. Add invariant: `output_path` stored in registry is the `parquet/` directory, not a single file. Add invariant: "already converted" skip guard trusts `parquet_converted_at` only (no file existence check).

**Gotchas**: Add note that `metadata.conversion_error` (singular) is the skip-guard key checked by the engine; `metadata.conversion_errors` (plural) is informational per-file detail not checked by any guard.

Update `Last verified` date to today.

**Verification:**
Run: `cat src/pipeline/converter/CLAUDE.md` and visually confirm accuracy.

**Commit:** `docs: update converter CLAUDE.md for multi-file behavior`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Finalize design doc

**Files:**
- Modify: `docs/design-plans/2026-04-24-multi-file-converter.md`

No content changes expected -- the design doc is already complete. If implementation introduced any deviations from the design, document them at the bottom of the design doc under an `## Implementation Notes` section. Otherwise, no changes needed.

**Verification:**
Run: `git diff docs/design-plans/2026-04-24-multi-file-converter.md` to confirm minimal or no changes.

**Commit:** `docs: finalize multi-file converter design plan` (only if changes were made)
<!-- END_TASK_2 -->
