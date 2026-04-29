# GH17 Phase 6 — Third-party stub gaps

**Goal:** Suppress `[import-untyped]` errors for `pandas`, `pyarrow`, and `pyreadstat` via `[[tool.mypy.overrides]]` in `pyproject.toml`. After this phase, `uv run mypy src/pipeline/` exits 0.

**Architecture:** Configuration-only. No source edits. The override approach is the design's explicit decision: "Do not install third-party stub packages — `pyarrow-stubs` has spotty coverage and `pyreadstat` has no stubs at all. Partial stub coverage creates a false sense of type safety."

**Tech Stack:** mypy 1.10+, `pyproject.toml`.

**Scope:** 6 of 6 phases (final).

**Codebase verified:** 2026-04-29

- ✓ Pre-Phase-6 mypy errors include 4 `[import-untyped]` errors (per planning data: 2× `pyarrow.parquet`, 1× `pyarrow`, 1× `pandas`). After Phases 1-5 land, only `[import-untyped]` errors should remain.
- ✓ `pyreadstat` is also imported (verified at `convert.py:14`) and will produce a similar error once mypy's strict mode is fully active. Include it pre-emptively.
- ✓ Confirmed via planning-time research: `pandas-stubs` exists but covers only DataFrame/Series basics; `pyarrow-stubs` exists as a third-party package with mixed quality; `pyreadstat` has no published stubs. Per design's explicit decision, we override rather than install partial stubs.

---

## Acceptance Criteria Coverage

- **GH17.AC6.1 (import-untyped cleared):** `uv run mypy src/pipeline/ 2>&1 | grep -c "import-untyped"` returns 0.
- **GH17.AC6.2 (Mypy clean):** `uv run mypy src/pipeline/` exits 0.
- **GH17.AC6.3 (Definition of Done met):** all six DoD bullets from the design pass simultaneously.

---

<!-- START_TASK_1 -->
### Task 1: Add `[[tool.mypy.overrides]]` for stub-less third-party libs

**Verifies:** GH17.AC6.1, GH17.AC6.2

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/pyproject.toml`

**Implementation:**

**Step 1: Locate the existing `[tool.mypy]` section** (added in Phase 1, lines roughly 50-53 after Phase 1 inserts):

```toml
[tool.mypy]
python_version = "3.11"
strict = true
files = ["src/pipeline"]
```

**Step 2: Append the override blocks immediately after**

Add these stanzas directly below the `[tool.mypy]` block:

```toml
[[tool.mypy.overrides]]
module = ["pandas", "pandas.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["pyarrow", "pyarrow.*"]
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = ["pyreadstat", "pyreadstat.*"]
ignore_missing_imports = true
```

Notes:

- `module = ["pkg", "pkg.*"]` form covers both the top-level import (`import pyarrow`) and submodules (`import pyarrow.parquet`). Without the wildcard, `pyarrow.parquet` would still error.
- `ignore_missing_imports = true` makes mypy treat the missing-stub case as `Any`-typed, silently. This is the design's chosen trade-off: we lose type checking on calls into these libraries, but we already accept that since they're file-format I/O boundaries, not core domain logic.
- One block per package keeps the diff readable. Mypy supports a single block with a list of modules — both forms work; the per-package form is easier to comment on or remove individually if a library later ships stubs.

**Step 3: Verify mypy exits 0**

```bash
uv run mypy src/pipeline/
```

Expected: `Success: no issues found in N source files`. Exit code 0.

If mypy still reports errors, **do not** broaden the overrides — investigate. Possible causes:

- A residual error from Phases 4 or 5 wasn't actually fixed (the inventory missed something).
- A new third-party import was added between planning and execution (e.g., a logging library).
- A first-party import broke (e.g., `pipeline.config` cannot resolve) — this is a config bug in Phase 1 that needs revisiting.

**Step 4: Verify ruff still passes**

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
```

Expected: both exit 0.

**Step 5: Verify pytest passes**

```bash
uv run pytest
```

Expected: zero failures, zero errors.

**Step 6: Sanity-check the full Definition of Done**

The design's Definition of Done has six bullets. Verify each:

```bash
# DoD bullet 1-3: pyproject.toml has the right config
grep -E '^target-version|^line-length|^select|^python_version|^strict|^mypy>=' pyproject.toml

# DoD bullet 4: ruff format clean
uv run ruff format --check src/ tests/ && echo "✓ format clean"

# DoD bullet 5: ruff check clean
uv run ruff check src/ tests/ && echo "✓ lint clean"

# DoD bullet 6: mypy clean
uv run mypy src/ && echo "✓ mypy clean"

# DoD bullet 7: pytest clean
uv run pytest && echo "✓ tests clean"
```

All six checks should print their `✓` line.

**Commit:**

```bash
git add pyproject.toml
git commit -m "chore: ignore_missing_imports for pandas/pyarrow/pyreadstat (#17)"
```
<!-- END_TASK_1 -->

---

## Phase Done When

- `pyproject.toml` contains three `[[tool.mypy.overrides]]` blocks for pandas, pyarrow, pyreadstat.
- `uv run mypy src/pipeline/` exits 0 with `Success: no issues found`.
- `uv run ruff format --check src/ tests/` exits 0.
- `uv run ruff check src/ tests/` exits 0.
- `uv run pytest` exits 0.
- All six Definition-of-Done bullets from the design pass simultaneously.

## Out of Scope

- Installing `pandas-stubs` or `pyarrow-stubs` packages — explicitly rejected by the design.
- Adding overrides for any first-party module — those should never need `ignore_missing_imports`.
- Wiring ruff/mypy into pre-commit or CI — out of this issue's scope; that's a follow-up.

## Notes for the implementor

- If a future contributor adds a new untyped third-party import, the design's standing instruction is: add a new `[[tool.mypy.overrides]]` block for it, not an inline `# type: ignore`. Inline ignores rot; overrides centralise the boundary decisions.
- `[[tool.mypy.overrides]]` syntax is TOML's "array of tables" — the double brackets are correct. Single brackets (`[tool.mypy.overrides]`) define a single table and would silently fail to apply.
- After Phase 6, the codebase has its first-ever mypy strict gate. New code that violates strict will fail mypy at PR time. This phase deliberately doesn't wire CI — that's a follow-up, but consider mentioning it in the PR description so the team knows the gate is now meaningful.

## Final state after all six phases

By the end of Phase 6, the project has:

1. `pyproject.toml` with full ruff + mypy config and updated dev deps (Phase 1).
2. All source/test files reformatted to 100-col line length (Phase 2).
3. All auto-fixable ruff violations resolved (Phase 2).
4. All manual ruff violations resolved with idiomatic suppressions where appropriate (Phase 3).
5. Zero mypy strict errors after annotation gap-fill (Phase 4) and generic type fixes (Phase 5).
6. Third-party stub gaps suppressed at the package boundary (Phase 6).

The Definition of Done is fully satisfied.
