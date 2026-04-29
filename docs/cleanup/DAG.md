# Issue Dependency DAG

Last updated: 2026-04-29

## Graph

```
                    ┌──────┐
                    │  #18 │  Bump Python ≥3.11 + integration marker
                    └──┬───┘
                       │
                       ▼
                    ┌──────┐
                    │  #25 │  Mark integration tests
                    └──────┘

    ┌──────┐        ┌──────┐
    │  #28 │───────▶│  #19 │  Type annotations (absorbs #28's change)
    └──────┘        └──┬───┘
                       │
                       ▼
                    ┌──────┐
                    │  #17 │  ruff + mypy config (mypy strict needs annotations)
                    └──┬───┘
                       │
                       ▼
                    ┌──────┐
                    │  #20 │  Frozen dataclasses (benefits from mypy validation)
                    └──────┘

    ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐
    │  #22 │  │  #23 │  │  #24 │  │  #27 │  │  #21 │
    └──────┘  └──────┘  └──────┘  └──────┘  └──────┘
    Lowercase  Swallowed  Structured  Pattern   DI
    errors     exceptions logging     labels    refactor

                    ┌──────┐
                    │  #26 │  Test naming (last — touches every test file)
                    └──────┘
```

## Dependency table

| Issue | Title                          | Hard deps | Soft deps | Conflict surface        |
|-------|--------------------------------|-----------|-----------|-------------------------|
| #18   | Python ≥3.11 + marker          | —         | —         | `pyproject.toml` only   |
| #25   | Mark integration tests         | #18       | —         | 3 test files (decorators only) |
| #28   | collections.abc.Callable       | —         | —         | `models.py` only        |
| #19   | Type annotations               | —         | #28       | 15 source files (signatures only) |
| #17   | ruff + mypy config             | #19       | #18       | `pyproject.toml` + all source files (formatting) |
| #22   | Lowercase error messages       | —         | —         | `auth.py`, `routes.py`, `auth_cli.py` + 2 test files |
| #23   | Log swallowed exceptions       | —         | —         | 6 source files (exception handlers only) |
| #24   | Structured logging extra       | —         | —         | `crawler/main.py` only  |
| #27   | Pattern labels                 | —         | —         | Line 1 of 22 files      |
| #21   | Replace mock with DI           | —         | —         | 7 test files + 4 source files |
| #20   | Frozen dataclasses             | —         | #17       | `db.py`, `engine.py`, `manifest.py`, `routes.py`, `main.py` |
| #26   | Test naming convention         | —         | #21, #25  | All test files (method names) |

## Merge order

Issues are grouped into tiers. Within a tier, issues can be merged in any order
or in parallel branches. Each tier should be fully merged before starting the
next to minimise conflicts.

### Tier 0 — Foundation (no deps, no conflicts with each other)

| Issue | Effort | Rationale |
|-------|--------|-----------|
| **#18** | 10 min | Unblocks #25. Touches only `pyproject.toml`. |
| **#28** | 5 min  | Absorbed by #19 if done together, but trivial standalone. |
| **#22** | 15 min | String changes only. No overlap with #18/#28. |
| **#27** | 20 min | Line-1 comments. No overlap with any other tier-0 issue. |
| **#23** | 2–3 hr | Exception handlers. No file overlap with #22/#27/#28. |
| **#24** | 1–2 hr | `crawler/main.py` log calls. No overlap with #22/#23/#27. |

All six are independent. Merge in any order.

### Tier 1 — Needs tier 0

| Issue | Effort | Rationale |
|-------|--------|-----------|
| **#25** | 15 min | Blocked on #18 for marker declaration. Decorator-only changes in 3 test files. |
| **#19** | 3–5 hr | Largest annotation pass. If #28 is merged first, skip the `models.py` Callable change. If not, include it. Overlaps with #23/#24 on function signatures in the same files — merging tier 0 first avoids conflicts. |

### Tier 2 — Needs tier 1

| Issue | Effort | Rationale |
|-------|--------|-----------|
| **#17** | 3–4 hr | ruff format touches every file — must go after all manual edits in tiers 0–1 are merged, or the formatting diff becomes a rebase nightmare. mypy strict needs #19's annotations. |
| **#21** | 4–6 hr | DI refactor rewrites test files. Going after tier 0 (#27 pattern labels, #23 exception fixes) means those edits are already in the files before test rewrites begin. |

### Tier 3 — Needs tier 2

| Issue | Effort | Rationale |
|-------|--------|-----------|
| **#20** | 4–6 hr | Frozen dataclasses change return types across `db.py`, `engine.py`, `routes.py`, `manifest.py`. Benefits from mypy (#17) catching type errors during the migration. Overlaps heavily with #19 (signatures) and #21 (test assertions) — merging those first keeps the diff clean. |

### Tier 4 — Last

| Issue | Effort | Rationale |
|-------|--------|-----------|
| **#26** | 1.5 hr | Renames ~95 test methods across all test files. Any issue that touches test files (#21, #25, #27) should merge first to avoid rename collisions. This is pure rename — zero logic — and should be the final commit. |

## Conflict hotspots

These files are touched by 4+ issues and are the most likely rebase headaches:

| File | Issues | Risk |
|------|--------|------|
| `src/pipeline/converter/engine.py` | #17, #19, #20, #23 | Signatures (#19), return types (#20), exc_info (#23), formatting (#17) |
| `src/pipeline/registry_api/routes.py` | #17, #19, #20, #22 | Error strings (#22), signatures (#19), return types (#20), formatting (#17) |
| `src/pipeline/crawler/main.py` | #19, #20, #23, #24 | Log calls (#24), exceptions (#23), signatures (#19), return types (#20) |
| `tests/crawler/test_main.py` | #20, #21, #26, #27 | Pattern label (#27), DI rewrite (#21), assertions (#20), rename (#26) |
| `tests/registry_api/test_routes.py` | #21, #22, #27 | Pattern label (#27), error strings (#22), DI rewrite (#21) |

Following the tier order keeps each file's changes sequential rather than concurrent.
