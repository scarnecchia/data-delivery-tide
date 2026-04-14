# Lexicon System Implementation Plan — Phase 8: Cleanup and End-to-End Validation

**Goal:** Remove all remaining QA-specific hardcoding from `src/`, update subdomain CLAUDE.md documentation, run full test suite, and validate the end-to-end flow.

**Architecture:** This is a sweep-and-verify phase. Grep for old field names, remove any stragglers, update documentation to reflect the lexicon-driven model, and confirm the full pipeline works.

**Tech Stack:** Python 3.10+

**Scope:** Phase 8 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### lexicon-system.AC7: Zero hardcoded QA references
- **lexicon-system.AC7.1 Success:** grep for `qa_status`, `qa_passed_at` in `src/` returns zero matches
- **lexicon-system.AC7.2 Success:** Full test suite passes

---

<!-- START_TASK_1 -->
### Task 1: Grep and remove remaining QA-specific references

**Verifies:** lexicon-system.AC7.1

**Files:**
- Scan: all files in `src/pipeline/` for `qa_status`, `qa_passed_at`, and hardcoded `"msoc"`, `"msoc_new"` outside of lexicon JSON files

**Implementation:**

Run these greps to find remaining hardcoded references:

```bash
grep -rn "qa_status" src/pipeline/
grep -rn "qa_passed_at" src/pipeline/
grep -rn '"msoc"' src/pipeline/
grep -rn '"msoc_new"' src/pipeline/
```

Expected at this point: most should be gone from Phases 3-6. Possible stragglers:
- Docstrings or comments mentioning old field names
- Log messages referencing `qa_status`
- CLAUDE.md files under `src/pipeline/` subdirectories

For each match:
- If it's code: update to use `status`, `lexicon_id`, `metadata`
- If it's a comment or docstring: update the language
- If it's a CLAUDE.md: update in Task 2

Do NOT modify:
- `pipeline/lexicons/soc/_base.json` (dir_map keys `msoc`/`msoc_new` are intentional — they're the physical directory names)
- `tests/` — test files may reference these as test data values (physical directory names, not hardcoded logic)

**Verification:**

```bash
grep -rn "qa_status" src/pipeline/ | grep -v "CLAUDE.md"
grep -rn "qa_passed_at" src/pipeline/ | grep -v "CLAUDE.md"
```

Expected: Zero matches (excluding CLAUDE.md files which are updated in Task 2).

**Commit:** `refactor: remove remaining qa_status/qa_passed_at references from src/`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update subdomain CLAUDE.md documentation

**Verifies:** None (documentation)

**Files:**
- Modify: `src/pipeline/crawler/CLAUDE.md`
- Modify: `src/pipeline/registry_api/CLAUDE.md`
- Modify: `src/pipeline/events/CLAUDE.md` (if it exists — check at execution time)

**Implementation:**

Update these CLAUDE.md files to reflect the lexicon-driven model:

**`src/pipeline/crawler/CLAUDE.md`:**
- Update "Contracts" section: scan_roots now include `lexicon` field, crawler uses `lexicon.dir_map` for terminal directory matching
- Update "Contracts" section: POSTs include `lexicon_id` and `status` instead of `qa_status`
- Update "Invariants": `walk_roots` uses lexicon dir_map keys instead of hardcoded `msoc`/`msoc_new`; `derive_qa_statuses` → `derive_statuses` with lexicon hook
- Update "Key Files": `parser.py` — path parsing uses dir_map, derivation delegates to lexicon hooks
- Update "Gotchas" if any mention QA-specific behaviour

**`src/pipeline/registry_api/CLAUDE.md`:**
- Update "Contracts": deliveries have `lexicon_id`, `status`, `metadata` instead of `qa_status`, `qa_passed_at`
- Update "Invariants": status validation is runtime against lexicon (no CHECK constraint); actionable query uses per-lexicon `actionable_statuses`
- Update event payload descriptions

**`src/pipeline/events/CLAUDE.md`:**
- Update event payload field descriptions if they mention `qa_status`/`qa_passed_at`

Also update the `Last verified` date on each file.

**Verification:**

```bash
grep -rn "qa_status" src/pipeline/**/CLAUDE.md
grep -rn "qa_passed_at" src/pipeline/**/CLAUDE.md
```

Expected: Zero matches.

**Commit:** `docs: update subdomain CLAUDE.md files for lexicon system`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Run full test suite — final validation

**Verifies:** lexicon-system.AC7.2

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: ALL tests pass. Zero failures.

Then run the final grep check:

```bash
grep -rn "qa_status\|qa_passed_at" src/pipeline/
```

Expected: Zero matches anywhere in `src/pipeline/`.

**Commit:** No commit if clean. This is the final verification that the lexicon system is complete.

<!-- END_TASK_3 -->
