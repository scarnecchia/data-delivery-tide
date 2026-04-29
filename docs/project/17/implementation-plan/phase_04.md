# GH17 Phase 4 — Residual annotation gaps after GH19

**Goal:** Eliminate any remaining `no-untyped-def` errors that survive after GH19's annotation pass. This is a gap-fill phase — most of GH17's design Phase 4 work is done by GH19 (hard upstream dep).

**Architecture:** Run mypy strict, list any `no-untyped-def` errors, annotate. The DAG explicitly states GH17 hard-deps on GH19, so by Phase 4 execution GH19's annotations are merged. The residual gaps will be limited to: (a) helpers GH19 didn't enumerate, (b) test code (mypy doesn't check it under our config but lint pass-through may surface issues), (c) the FastAPI `auth.py:32` `db: DbDep = ...` pattern which mypy flags as an `assignment` error and design Phase 4 calls out specifically.

**Tech Stack:** mypy 1.10+ (declared in Phase 1).

**Scope:** 4 of 6 phases.

**Codebase verified:** 2026-04-29

- ✓ Pre-GH19 state: 31 `no-untyped-def` errors across 9 source files. Per `tail -40` of `uv run --with mypy mypy --strict src/pipeline/` at planning time, the bulk are concentrated in `routes.py` (8), `main.py` (3), `auth.py` (2), `cli.py` (3), `daemon.py` (2), `convert.py` (1), `engine.py` (1), `auth_cli.py` (1).
- ✓ GH19's plan covers ALL of these via Phases 2-5. Cross-reference:
  - `routes.py` ✓ GH19 Phase 2 Task 5 (all 8 handlers)
  - `main.py` ✓ GH19 Phase 2 Task 4 (websocket_events, lifespan, run)
  - `auth.py` ✓ GH19 Phase 2 Task 3 (`require_role -> Any`); `_check_role` was already annotated
  - `cli.py` ✓ GH19 Phase 3 Task 2 (`_iter_unconverted`, `_run`)
  - `daemon.py` ✓ GH19 Phase 3 Task 3 (`DaemonRunner.__init__`)
  - `convert.py` ✓ GH19 Phase 3 Task 4 (`convert_sas_to_parquet.chunk_iter_factory`)
  - `engine.py` ✓ GH19 Phase 3 Task 1 (`convert_one`)
  - `auth_cli.py` ✓ GH19 Phase 5 Task 2 (`main`)
- ✓ The design-flagged `assignment` error at `auth.py:32` (the `db: DbDep = ...` ellipsis sentinel) is **NOT** addressed by GH19 — that issue is annotation gaps, not assignment fixes. Phase 4 of GH17 owns it.
- ✓ Two errors in `crawler/main.py` per planning-time mypy run:
  - `Need type annotation for "valid_terminals" (hint ...)` — local var needs `set[str]` type. GH19 doesn't touch local vars.
  - `Returning Any from function declared to return "list[ParsedDelivery]"` and `Returning Any from function declared to return "dict[Any, Any]"` — these come from `getattr(meta, "column_labels", None)` patterns and similar `Any`-returning calls. May need `cast()` or local var annotation.
- ✓ Three errors in `manifest.py`/`crawler` related to `CrawlManifest` / `ErrorManifest` shape mismatches (see planning data: "Incompatible types in assignment" / "Incompatible return value type"). These are Phase 5 territory (genuine type bugs surfaced by strict mode), not Phase 4 (annotation gaps).
- ✓ One error: `Missing type arguments for generic type "Callable"` — GH19 Phase 4 Task 3 (`lexicons/loader._import_hook -> Callable[..., Any]`) addresses this.

**Net for Phase 4 after GH19:** likely 1-3 residual `no-untyped-def` errors (helpers GH19 didn't list explicitly) plus the `auth.py:32` assignment error.

---

## Acceptance Criteria Coverage

- **GH17.AC4.1 (No annotation gaps):** `uv run mypy src/pipeline/ 2>&1 | grep -c "no-untyped-def"` returns 0.
- **GH17.AC4.2 (Auth.py assignment fixed):** `uv run mypy src/pipeline/registry_api/auth.py` reports zero `assignment` errors related to the `EllipsisType` default.
- **GH17.AC4.3 (No regressions):** `uv run pytest` exits 0.

---

<!-- START_TASK_1 -->
### Task 1: Inventory residual mypy errors after GH19

**Verifies:** GH17.AC4.1 (preparation)

**Files:** None modified — diagnostic only.

**Implementation:**

**Step 1: Run mypy strict and capture all errors by category**

```bash
uv run mypy src/pipeline/ 2>&1 | tee /tmp/gh17-mypy-phase4-baseline.txt
```

**Step 2: Print categorised counts**

```bash
grep -oE '\[[a-z-]+\]' /tmp/gh17-mypy-phase4-baseline.txt | sort | uniq -c | sort -rn
```

Expected (after GH19): a much smaller list than the 100-error baseline. The remaining categories are likely:

- `[type-arg]` — bare `dict`/`list` (Phase 5 work)
- `[no-untyped-def]` — residual annotation gaps (this Phase, Task 2)
- `[assignment]` — `auth.py:32` and possibly others (this Phase, Task 3)
- `[union-attr]`, `[arg-type]`, `[dict-item]`, `[return-value]` — Phase 5 work
- `[import-untyped]` — pandas/pyarrow/pyreadstat (Phase 6 work)
- `[no-any-return]` — Phase 5 work

**Step 3: Filter to just `no-untyped-def`**

```bash
grep "no-untyped-def" /tmp/gh17-mypy-phase4-baseline.txt
```

Expected: a list of every residual `no-untyped-def` line, with file path and line number. **Save this list — it is the work for Task 2.** If the list is empty, mark Task 2 as N/A and proceed directly to Task 3.

**Step 4: Filter to just `assignment`**

```bash
grep "assignment" /tmp/gh17-mypy-phase4-baseline.txt
```

Expected: `auth.py:32` should appear (the `EllipsisType` sentinel for `db: DbDep = ...`). Any others are work for Task 3.

**No commit for this task** — it's a diagnostic pass that informs Tasks 2-3.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Annotate residual `no-untyped-def` errors

**Verifies:** GH17.AC4.1

**Files:**
- Modify: every file listed in Task 1 Step 3's grep output.

**Implementation:**

For each `no-untyped-def` line in Task 1 Step 3:

1. Read the file at the reported line.
2. Identify the function or method.
3. Add the missing annotation(s):
   - **Missing return type:** add `-> ReturnType` (use `-> None` if mypy's hint says so).
   - **Missing parameter type:** annotate every un-annotated parameter.
4. The annotation should be the most precise type the call sites support. Use `Any` only as a last resort, and document why.

**Example pattern (hypothetical residual):**

If mypy reports `src/pipeline/converter/engine.py:21: error: Function is missing a type annotation [no-untyped-def]`, read line 21 and inspect the function. Most likely it's a private helper GH19 didn't enumerate. Add the appropriate signature.

**Step 1: Iterate through the list**

For each entry, edit the file and add the annotation.

**Step 2: Re-run mypy after each edit (or at the end)**

```bash
uv run mypy src/pipeline/ 2>&1 | grep -c "no-untyped-def"
```

Expected: 0.

**Step 3: Tests**

```bash
uv run pytest
```

Expected: zero failures.

**Commit:**

```bash
git add src/pipeline/
git commit -m "feat: annotate residual untyped functions (#17)"
```

**If Task 1's grep returned an empty list,** skip Task 2 entirely — the commit message would be hollow.
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Fix `auth.py:32` `EllipsisType` assignment error

**Verifies:** GH17.AC4.2

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/auth.py:30-33`

**Implementation:**

Current:

```python
def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008 (added in Phase 3)
    db: DbDep = ...,
) -> TokenInfo:
```

The `db: DbDep = ...` is a FastAPI sentinel — `...` (Ellipsis) means "no default; FastAPI must inject this". Mypy strict reads `DbDep = Annotated[sqlite3.Connection, Depends(get_db)]` and sees the default `...` as `EllipsisType`, which is not a `Connection`. Hence the assignment error.

**Two options:**

**Option A (preferred):** Drop the `= ...` default. `Annotated` with `Depends` is sufficient for FastAPI to inject; the ellipsis was redundant.

Replace with:

```python
def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
    db: DbDep,
) -> TokenInfo:
```

**Wait** — Python forbids non-default parameters AFTER default parameters. `credentials` has a default, so `db` cannot be undefaulted in the same signature. We must reorder OR provide a default that mypy accepts.

**Option A revised:** Reorder parameters. Put `db` first.

```python
def require_auth(
    db: DbDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
) -> TokenInfo:
```

This is clean Python and FastAPI accepts it. **Caveat:** changing parameter order is observable IF anyone calls `require_auth` positionally in tests or elsewhere. Verify before reordering:

```bash
grep -rn "require_auth(" /Users/scarndp/dev/Sentinel/qa_registry/src/ /Users/scarndp/dev/Sentinel/qa_registry/tests/
```

If `require_auth` is only ever used as a FastAPI dependency (i.e., `Depends(require_auth)` or via the `AuthDep = Annotated[TokenInfo, Depends(require_auth)]` alias), reordering is safe.

**Option B (fallback):** Keep the `= ...` and suppress the mypy error inline:

```python
def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
    db: DbDep = ...,  # type: ignore[assignment]
) -> TokenInfo:
```

This documents the FastAPI sentinel pattern and silences mypy without semantic change. The design plan's "Investigate before suppressing" guidance applies — Option A is preferred when call sites are FastAPI-only, Option B is the mechanical fallback.

**Recommended:** Use Option B. Multiple downstream plans (GH20, GH21) assume require_auth's current parameter order. Reordering risks positional-call regressions across concurrent branches.

**Step 1: Run the grep above to verify call sites**

If `require_auth` is only invoked via `Depends()` or via the `AuthDep` annotation, choose Option A (reorder).

**Step 2: Apply the chosen edit**

For Option A: reorder `auth.py:30-33`.
For Option B: append `# type: ignore[assignment]` to the `db: DbDep = ...` line.

**Step 3: Verify**

```bash
uv run mypy src/pipeline/registry_api/auth.py 2>&1 | grep "assignment"
```

Expected: no output (zero assignment errors).

**Step 4: Tests**

```bash
uv run pytest tests/registry_api/
```

Expected: zero failures. (If Option A was chosen and an inadvertent positional call existed, this is where it fails.)

**Commit:**

```bash
git add src/pipeline/registry_api/auth.py
git commit -m "fix: resolve mypy assignment error on require_auth db parameter (#17)"
```
<!-- END_TASK_3 -->

---

## Phase Done When

- `uv run mypy src/pipeline/ 2>&1 | grep -c "no-untyped-def"` returns 0.
- `uv run mypy src/pipeline/ 2>&1 | grep -c "assignment.*EllipsisType"` returns 0.
- `uv run pytest` exits 0.
- `uv run ruff check src/ tests/` still exits 0 (Phase 3 invariant).

## Out of Scope

- `[type-arg]`, `[union-attr]`, `[dict-item]`, `[arg-type]`, `[return-value]`, `[no-any-return]`, `[assignment]` (non-EllipsisType) — Phase 5.
- `[import-untyped]` for third-party libs — Phase 6.

## Notes for the implementor

- Phase 4 may turn out to be a nearly-no-op if GH19 was thorough. That's fine. The Task 1 inventory is fast; if it shows zero `no-untyped-def`, mark Task 2 as N/A and proceed straight to Task 3.
- If Task 1 shows surprisingly many `no-untyped-def` errors (say, more than 5), surface to the user — it implies GH19 didn't land or didn't fully apply, and GH17 should not proceed until GH19 is verified merged.
- The design plan's "design Phase 4" enumerates files that overlap heavily with GH19's plan. This implementation Phase 4 deliberately does NOT redo GH19's work — GH19 is the single source of annotation truth, GH17 just confirms the gate is green.
