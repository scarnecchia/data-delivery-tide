# GH17 Phase 2 — Apply ruff format and auto-fixable lint

**Goal:** Run `ruff format` and `ruff check --fix` against `src/` and `tests/` to eliminate every auto-fixable violation surfaced by the Phase 1 config. Manual fixes are deferred to Phase 3.

**Architecture:** Mechanical apply pass. ruff format is idempotent and well-tested; auto-fixes for I001 (import sorting), F401 (unused imports), F541 (f-string missing placeholders), and UP rules (pyupgrade) are safe. The change set for Phase 2 should produce a single large but reviewable diff per directory tree.

**Tech Stack:** ruff 0.15.6 (declared as dev dep in Phase 1).

**Scope:** 2 of 6 phases.

**Codebase verified:** 2026-04-29

- ✓ Pre-Phase-1 state has 17 violations under default ruff. The exact count after Phase 1's config takes effect cannot be predicted without running it, but the design's "72 E501 + 30 across 6 codes = 102" prediction is stale (codebase has been cleaned up since).
- ✓ Phase 1 set `line-length = 100`. Files currently formatted to 88 will see new line-length flags resolved either by reformatting (the bulk) or by genuine over-length lines that need splitting.
- ✓ Phase 1 enabled `UP` rule set. UP006/UP007/UP035 may auto-fix `Dict` -> `dict`, `Optional[X]` -> `X | None`, `typing.Callable` -> `collections.abc.Callable`, etc. Some of these are already handled by GH28 (lexicons/models.py) and GH19 (broader annotations) — those issues are upstream of GH17 (DAG: GH17 has hard dep on GH19, soft on GH18). By the time Phase 2 runs, those fixes are already in.

---

## Acceptance Criteria Coverage

- **GH17.AC2.1 (Format clean):** `uv run ruff format src/ tests/` exits 0 with no diffs.
- **GH17.AC2.2 (Auto-fixes applied):** `uv run ruff check src/ tests/ --fix` leaves zero auto-fixable violations.
- **GH17.AC2.3 (No regressions):** `uv run pytest` exits 0 after the formatting + auto-fix pass.

---

<!-- START_TASK_1 -->
### Task 1: Apply `ruff format` to src and tests

**Verifies:** GH17.AC2.1

**Files:**
- Modify: every `.py` file under `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/` and `/Users/scarndp/dev/Sentinel/qa_registry/tests/` that ruff format wants to reformat.

**Implementation:**

**Step 1: Inspect the format diff first (don't write it yet)**

```bash
uv run ruff format src/ tests/ --diff 2>&1 | head -200
```

Expected: a unified diff showing reformatting candidates. Read the first 200 lines to confirm the changes look mechanical (whitespace, line-wrapping at 100 cols, trailing comma normalisation). If anything looks non-mechanical (e.g., a function body actually rearranged), STOP and surface to the user.

**Step 2: Apply the format**

```bash
uv run ruff format src/ tests/
```

Expected: prints `N files reformatted, M files left unchanged`. No errors.

**Step 3: Sanity-check via test**

```bash
uv run pytest -x
```

Expected: zero failures, zero errors. (Format never changes semantics; this is paranoia.)

**Step 4: Verify format is now idempotent**

```bash
uv run ruff format --check src/ tests/
```

Expected: `N files already formatted`, exit code 0. If exit is non-zero, the previous step missed files — re-run.

**Step 5: Commit**

```bash
git add src/ tests/
git commit -m "style: apply ruff format to src and tests (#17)"
```

(One commit for the format pass keeps it bisectable separately from the lint-fix commit in Task 2.)
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Apply `ruff check --fix` to src and tests

**Verifies:** GH17.AC2.2, GH17.AC2.3

**Files:**
- Modify: every `.py` file under `src/` and `tests/` that ruff's auto-fixer wants to touch.

**Implementation:**

**Step 1: Inventory auto-fixable violations**

```bash
uv run ruff check src/ tests/ --statistics
```

Expected: prints a table of rule code -> count -> fixable status. Note which rules have `[*]` (auto-fixable) vs none (manual fix in Phase 3).

**Step 2: Inspect the auto-fix diff first**

```bash
uv run ruff check src/ tests/ --fix --diff 2>&1 | head -200
```

Expected: a unified diff showing the auto-fixes ruff would apply. Read it. The common fixes:

- **I001** (import sorting): rearranges import blocks. Mechanical, safe.
- **F401** (unused-import): removes imports. **Inspect each one** — sometimes "unused" means "imported for its side effect" (rare but real); if a `# noqa: F401` annotation is needed, add it manually after the auto-fix and surface to the user.
- **F541** (f-string-missing-placeholders): rewrites `f"..."` with no `{}` to plain `"..."`. Safe.
- **UP rules**: 3.11+ syntax migrations. Safe per design.

If the diff includes anything NOT in the auto-fixable categories above (i.e., something semantic), STOP and surface to the user.

**Step 3: Apply the fixes**

```bash
uv run ruff check src/ tests/ --fix
```

Expected: prints `Fixed N errors`. Exit code is 0 if all violations resolved, non-zero if manual violations remain (Phase 3 will handle those).

**Step 4: Re-check to confirm only manual violations remain**

```bash
uv run ruff check src/ tests/ --statistics
```

Expected: ONLY non-fixable rule codes remain in the output. Fixable codes (I001, F401, F541, UP) should be at zero. The remaining codes are Phase 3's work — note them in the commit message.

**Step 5: Run tests**

```bash
uv run pytest
```

Expected: zero failures. If F401 removed an import that was actually load-bearing, a test will fail here — investigate, restore with `# noqa: F401` and a comment explaining why.

**Step 6: Commit**

```bash
git add src/ tests/
git commit -m "style: apply ruff --fix for I001/F401/F541/UP (#17)"
```
<!-- END_TASK_2 -->

---

## Phase Done When

- `uv run ruff format --check src/ tests/` exits 0.
- `uv run ruff check src/ tests/ --statistics` shows only non-fixable violations remaining (these are Phase 3's work).
- `uv run pytest` exits 0.

## Out of Scope

- Manual ruff fixes (B008 in route handlers, E402 in auth.py, SIM/B905/UP028 if any) — Phase 3.
- Mypy errors — Phases 4-6.
- New violations introduced by future commits — out of scope; ruff is now the gate.

## Notes for the implementor

- If `ruff format` produces a >2000-line diff, that's expected for a codebase that has never been auto-formatted at 100 cols. Don't try to "review every line" — review a sample, trust the tool, and rely on `pytest` as the regression check.
- The two-task split (format then lint-fix) keeps `git bisect` clean. If a regression is introduced, bisecting will land on either Task 1's commit (formatting only — extremely unlikely to break anything) or Task 2's commit (auto-fixes — more likely if F401 yanked a load-bearing import).
- If F401 wants to remove `from pipeline.crawler.parser import ParsedDelivery` from a `TYPE_CHECKING` block, that's WRONG — it's used as a forward-ref string. ruff should not flag imports inside `if TYPE_CHECKING:` as unused, but if it does, suppress with `# noqa: F401` and report to the user as a tooling bug to investigate.
- Tests get `E501` per-file-ignore (set in Phase 1) so long parametrize tuples don't get rewrapped weirdly. This is intentional.
