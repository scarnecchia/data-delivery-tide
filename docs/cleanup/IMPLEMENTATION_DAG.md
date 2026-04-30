# Implementation Execution DAG

Last updated: 2026-04-29

This DAG governs the **execution order** of implementation plans. It incorporates
dependency tightening and cross-plan coordination constraints discovered during
the cross-plan review (see `cross-plan-review.md` and `cross-plan-re-review.md`).

The design-level DAG (`DAG.md`) remains the source of truth for *why* issues are
ordered this way. This file is the source of truth for *how* to execute them.

## Rules

1. **Complete every issue in a tier before starting the next tier.**
2. For each issue, use `/ed3d-plan-and-execute:execute-implementation-plan`.
3. Within a tier, issues may run in parallel unless noted otherwise.
4. Each issue gets its own branch off `cleanup`.
5. Merge each branch to `cleanup` before starting downstream tiers.
6. After merging a tier, run `uv run pytest` on `cleanup` to confirm green.

## Plan locations

All plans live under `docs/project/<issue_number>/`:

| Issue | Phases | Plan path | test-requirements.md |
|-------|--------|-----------|----------------------|
| GH17  | 6      | `docs/project/17/implementation-plan/phase_01..06.md` | yes |
| GH18  | 1      | `docs/project/18/phase_01.md` | yes |
| GH19  | 5      | `docs/project/19/implementation-plan/phase_01..05.md` | yes |
| GH20  | 5      | `docs/project/20/phase_01..05.md` | yes |
| GH21  | 5      | `docs/project/21/phase_01..05.md` | yes |
| GH22  | 1      | `docs/project/22/phase_01.md` | yes |
| GH23  | 5      | `docs/project/23/phase_01..05.md` | yes |
| GH24  | 1      | `docs/project/24/phase_01.md` | yes |
| GH25  | 1      | `docs/project/25/phase_01.md` | yes |
| GH26  | 1      | `docs/project/26/phase_01.md` | yes |
| GH27  | 1      | `docs/project/27/phase_01.md` | inline in phase_01 |
| GH28  | 1      | `docs/project/28/implementation-plan/phase_01.md` | yes |

## Execution graph

```
                         TIER 0 — all independent, run in parallel
  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐
  │ GH18 │  │ GH28 │  │ GH22 │  │ GH27 │  │ GH23 │  │ GH24 │
  │10 min│  │ 5 min│  │15 min│  │20 min│  │2–3 hr│  │1–2 hr│
  └──┬───┘  └──┬───┘  └──────┘  └──────┘  └──────┘  └──────┘
     │         │
     │  ════════════════ merge all tier 0, run pytest ══════════
     │         │
     │         │       TIER 1
     ▼         ▼
  ┌──────┐  ┌──────┐
  │ GH25 │  │ GH19 │
  │15 min│  │3–5 hr│
  └──────┘  └──┬───┘
               │
     ══════════════════ merge all tier 1, run pytest ══════════
               │
               │       TIER 2
     ┌─────────┤
     ▼         ▼
  ┌──────┐  ┌──────┐
  │ GH17 │  │ GH21 │
  │3–4 hr│  │4–6 hr│
  └──┬───┘  └──┬───┘
     │         │
     ══════════════════ merge all tier 2, run pytest ══════════
     │         │
     │         │       TIER 3
     ▼         │
  ┌──────┐     │
  │ GH20 │◄───┘
  │4–6 hr│
  └──┬───┘
     │
     ══════════════════ merge tier 3, run pytest ══════════════
     │
     │                 TIER 4
     ▼
  ┌──────┐
  │ GH26 │
  │1.5 hr│
  └──────┘
```

## Dependency table

| Issue | Title                          | Hard deps        | Soft deps | Notes |
|-------|--------------------------------|------------------|-----------|-------|
| GH18  | Python >=3.11 + marker         | —                | —         | |
| GH28  | collections.abc.Callable       | —                | —         | Absorbed by GH19 if both land |
| GH22  | Lowercase error messages       | —                | —         | |
| GH27  | Pattern labels                 | —                | —         | |
| GH23  | Log swallowed exceptions       | —                | —         | |
| GH24  | Structured logging extra       | —                | —         | |
| GH25  | Mark integration tests         | GH18             | —         | Needs marker from GH18's pyproject.toml |
| GH19  | Type annotations               | —                | GH28      | Absorbs GH28's models.py change idempotently |
| GH17  | ruff + mypy config             | **GH18**, GH19   | —         | GH18 is HARD (UP rules produce 3.11+ syntax). See review I1. |
| GH21  | Replace mock with DI           | —                | GH22, GH27, GH23 | Must run after tier 0 for string casing (GH22), pattern labels (GH27), exception handlers (GH23) |
| GH20  | Frozen dataclasses             | GH17, GH21       | —         | Needs mypy (GH17) + DI test state (GH21) |
| GH26  | Test naming convention         | —                | GH21, GH25 | Must be last — renames methods across all test files |

## Cross-plan coordination notes for executors

These notes come from the cross-plan review. Each is embedded in the relevant
plan file, but collected here for quick reference.

### GH17 executor notes

- **Phase 1:** GH18 is a hard dependency (not soft as the design DAG states).
  Do not start GH17 until GH18 is merged. UP rule migrations produce 3.11+
  syntax that breaks on Python 3.10.

- **Phase 3, Task 3 (SIM105 in convert.py):** GH23 Phase 1 replaces the
  `try/except: pass` with `try/except: logger.debug(...)`, eliminating this
  SIM105 violation. Run `uv run ruff check --select SIM105 src/pipeline/converter/convert.py`
  first — if clean, skip this fix.

- **Phase 4, Task 3 (require_auth parameters):** Use Option B (`# type: ignore`).
  GH20 and GH21 assume the current parameter order. Reordering risks
  positional-call regressions.

- **Phase 5, Task 4 (list_all_deliveries arg-type):** GH20 Phase 5 will rewrite
  this expression again when deliveries become frozen dataclasses. This edit is
  correct for the post-GH19 state; don't be surprised when GH20 overwrites it.

### GH19 executor notes

- **Phase 4, Task 2 (models.py):** If GH28 has already merged, this is a
  verified no-op. Run the verification grep before committing to confirm
  idempotency.

### GH21 executor notes

- **Phase 2, Task 3 (test_http.py imports):** GH27 (Tier 0) adds
  `# pattern: test file` to line 1 before this task runs. The Edit's
  `old_string` must include the existing label. Do NOT prepend a duplicate.

- **Phase 2, Task 5 (test_http.py error string):** Use lowercase
  `"delivery not found"` — GH22 lowercases this string in Tier 0 before
  GH21 executes.

### GH20 executor notes

- **Phase 3 (engine.py):** GH23 Phase 2 adds `exc_info=True` to two logger
  calls. The structural shape is identical; reapply the dataclass migration
  on top of GH23's edits.

- **Phase 5 (routes.py):** GH17 Phase 5 Task 4 edited `list_all_deliveries`
  for arg-type; this phase rewrites it again with `dataclasses.asdict()`.

### GH26 executor notes

- **Phase 1:** `tests/registry_api/test_routes.py` has 11 additional
  AC-prefixed test names that are out of scope per the design's 5-file
  enumeration. Consider a scope expansion before or after this issue.

## Conflict hotspots

Files touched by 3+ issues. Tier order keeps edits sequential.

| File | Issues | Coordination |
|------|--------|--------------|
| `src/pipeline/converter/engine.py` | #17, #19, #20, #23 | Signatures (#19) -> exc_info (#23) -> formatting (#17) -> return types (#20) |
| `src/pipeline/registry_api/routes.py` | #17, #19, #20, #22 | Error strings (#22) -> signatures (#19) -> formatting + arg-type (#17) -> asdict (#20) |
| `src/pipeline/crawler/main.py` | #19, #20, #23, #24 | Exceptions (#23) -> log calls (#24) -> annotations (#19) -> return types (#20) |
| `tests/crawler/test_main.py` | #20, #21, #26, #27 | Pattern label (#27) -> DI rewrite (#21) -> assertions (#20) -> renames (#26) |
| `tests/registry_api/test_routes.py` | #21, #22, #27 | Pattern label (#27) -> error strings (#22) -> DI rewrite (#21) |
| `tests/converter/test_http.py` | #21, #22, #27 | Pattern label (#27) -> lowercase strings (#22) -> DI rewrite (#21). GH21 must use lowercase "delivery not found" post-GH22. |
