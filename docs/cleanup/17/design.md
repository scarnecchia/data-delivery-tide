# Ruff and Mypy Configuration Design

## Summary

<!-- TO BE GENERATED after body is written -->

## Definition of Done

- `pyproject.toml` has `[tool.ruff]` with `target-version = "py311"`, `line-length = 100`, and `select = ["E","F","I","UP","B","SIM","TCH"]`
- `pyproject.toml` has `[tool.mypy]` with `python_version = "3.11"` and `strict = true`
- `mypy` is listed in `[project.optional-dependencies] dev`
- `uv run ruff format src/ tests/` exits 0 with no diffs
- `uv run ruff check src/ tests/` exits 0 with no errors
- `uv run mypy src/` exits 0 with no errors (or all remaining errors are suppressed with inline `# type: ignore[...]` comments tracking third-party stub gaps)
- `uv run pytest` continues to pass after all changes

## Acceptance Criteria

<!-- TO BE GENERATED after body is written -->

## Glossary

<!-- TO BE GENERATED after body is written -->

---

## Architecture

This is a tooling-configuration issue, not a structural one. No new modules, no API changes — just three categories of work:

1. **Config**: add `[tool.ruff]` and `[tool.mypy]` to `pyproject.toml`; add `mypy` to dev deps
2. **Format/lint fixes**: apply `ruff format` and `ruff check --fix`, then manually fix remaining lint violations
3. **Type annotation fixes**: add missing return and parameter annotations, tighten generic types, suppress unavoidable third-party stub errors

The three categories are independent and can be implemented sequentially in phases. Ruff changes are purely cosmetic/style and carry near-zero semantic risk. Mypy changes require reasoning about intent and carry small but real risk of surfacing latent bugs — which is the point.

## Existing Patterns

The codebase already uses type annotations in most places:

- `src/pipeline/config.py` — `@dataclass` fields fully annotated, `load_config` return type annotated
- `src/pipeline/lexicons/loader.py` — `from __future__ import annotations`, fully annotated
- `src/pipeline/registry_api/models.py` — Pydantic `BaseModel` subclasses, fully typed
- `src/pipeline/registry_api/db.py` — `Annotated` imports, partial annotations present

The gaps are concentrated in:

- Route handlers in `routes.py` (missing return type annotations on async def)
- CLI entry points (`auth_cli.py`, `converter/cli.py`, `converter/daemon.py`) — missing `-> None`
- Third-party imports: `pandas`, `pyarrow`, `pyreadstat` have no stubs or `py.typed` markers
- Generic `dict` / `list` uses without type arguments (pre-3.9 style in some files)

The project already uses `from __future__ import annotations` in `loader.py`; this pattern should be extended where needed for forward references.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Add tooling configuration to pyproject.toml

**Goal:** Configure ruff and mypy with the required settings and add mypy to dev deps. No source changes yet — just establish what the target state looks like.

**Components:**
- `pyproject.toml` — add `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.mypy]` sections; add `mypy>=1.10,<2` to `dev` optional-deps

**Dependencies:** None

**Done when:** `uv pip install -e ".[dev]"` succeeds with mypy available; `uv run ruff check src/` reports violations using the new rule set; `uv run mypy src/ --strict` runs without config errors (violations expected at this stage)
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Apply ruff format and fix auto-fixable lint violations

**Goal:** Eliminate all ruff format and auto-fixable ruff check violations. This produces the bulk of the diff (72 E501 line-length violations, 9 I001/UP/SIM fixable violations) without requiring semantic reasoning.

**Components:**
- All files under `src/pipeline/` — reformatted to 100-char line length
- All files under `tests/` — reformatted

**Dependencies:** Phase 1 (ruff config must be in place for correct line-length target)

**Done when:** `uv run ruff format src/ tests/` exits 0 with no diffs; `uv run ruff check src/ tests/ --fix` leaves 0 auto-fixable violations remaining; `uv run pytest` passes
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Fix remaining manual ruff lint violations

**Goal:** Resolve the ~20 violations that `--fix` cannot handle automatically. These require judgment: `B008` (function calls in default arguments, specifically FastAPI `Depends()`), `SIM105` (suppressible exceptions), `B007` (unused loop variable), `B905` (zip without strict), `E402` (import order), `UP028` (yield-in-for-loop).

**Components:**
- `src/pipeline/registry_api/routes.py` — `B008` violations are FastAPI-idiomatic (`Depends()` in signatures); these should be suppressed with `# noqa: B008` rather than rewritten
- `src/pipeline/registry_api/auth.py` — `E402` import ordering
- Remaining files with `SIM105`, `B007`, `B905`, `UP028` — fix substantively where safe, suppress with `# noqa` only when the pattern is intentional

**Dependencies:** Phase 2

**Done when:** `uv run ruff check src/ tests/` exits 0; `uv run pytest` passes
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: Add missing return and parameter type annotations

**Goal:** Fix the largest category of mypy strict errors: `no-untyped-def`. Target the entry-point CLIs, route handlers, and daemon functions that are simply missing `-> None` or parameter annotations.

**Components:**
- `src/pipeline/registry_api/routes.py` — add return type annotations to all async route handlers (e.g. `-> DeliveryResponse`, `-> PaginatedDeliveryResponse`, `-> None`)
- `src/pipeline/registry_api/main.py` — annotate lifespan, `run`, and startup functions
- `src/pipeline/registry_api/auth.py` — annotate `require_auth` and related helpers
- `src/pipeline/auth_cli.py` — add `-> None` to CLI command functions
- `src/pipeline/converter/cli.py` — annotate `main` and argument-parsing helpers
- `src/pipeline/converter/daemon.py` — annotate async handlers and `main`
- `src/pipeline/converter/engine.py` — annotate `_process_delivery` and helpers

**Dependencies:** Phase 3 (format stable before annotation changes)

**Done when:** `no-untyped-def` errors eliminated from mypy output; `uv run pytest` passes
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Fix generic type arguments and type-narrowing errors

**Goal:** Resolve `type-arg` errors (bare `dict`, bare `list`) and the handful of `dict-item` / `union-attr` / `arg-type` errors surfaced by strict mode. These are genuine type gaps that may mask bugs.

**Components:**
- `src/pipeline/registry_api/db.py` — replace bare `dict` with `dict[str, Any]` or more specific types at lines flagged by mypy (lines ~425, 463, 528, 545, 547, 591)
- `src/pipeline/converter/convert.py` — replace bare `dict` with `dict[str, Any]`; investigate `union-attr` errors on pyreadstat result at lines 192 and 206 (likely requires a cast or a guard)
- `src/pipeline/converter/engine.py` — fix `dict-item` type mismatches at lines 228–232; these indicate a dict with mixed value types (`str | int | None`) that should be typed as `dict[str, str | int | None]`
- `src/pipeline/registry_api/routes.py` — fix `arg-type` at line 136 (`list[dict[Any, Any]]` vs `list[DeliveryResponse]`); likely requires explicit construction

**Dependencies:** Phase 4

**Done when:** `type-arg`, `dict-item`, `union-attr`, `arg-type` error categories cleared; `uv run pytest` passes
<!-- END_PHASE_5 -->

<!-- START_PHASE_6 -->
### Phase 6: Handle third-party stub gaps

**Goal:** Suppress unavoidable `import-untyped` errors for `pandas`, `pyarrow`, and `pyreadstat`, which have no bundled stubs or `py.typed` markers.

**Decision:** Use `[[tool.mypy.overrides]]` with `ignore_missing_imports = true` scoped to `pandas`, `pyarrow`, and `pyreadstat`. Do not install third-party stub packages — `pyarrow-stubs` has spotty coverage and `pyreadstat` has no stubs at all. Partial stub coverage creates a false sense of type safety. The override approach is honest about the boundary and costs zero maintenance. If stubs improve later, flipping the override off is a one-line change.

**Components:**
- `pyproject.toml` — add `[[tool.mypy.overrides]]` sections for `pandas`, `pyarrow`, and `pyreadstat` with `ignore_missing_imports = true`
- No inline `# type: ignore` comments needed — the overrides handle it globally

**Dependencies:** Phase 5

**Done when:** `uv run mypy src/` exits 0; no unresolved `import-untyped` errors; `uv run pytest` passes
<!-- END_PHASE_6 -->

## Additional Considerations

**FastAPI `Depends()` in default arguments (`B008`):** This pattern is idiomatic FastAPI and ruff knows it. The correct fix is `# noqa: B008` on those lines, not refactoring the route signatures. Do not suppress globally — only on the specific lines where `Depends()` appears in a function signature default.

**Target version bump (`py311` vs `py310`):** `pyproject.toml` currently declares `requires-python = ">=3.10"`. The ruff `target-version = "py311"` and mypy `python_version = "3.11"` reflect the actual runtime (uv resolves to 3.12.12 per investigation). Update `requires-python` to `">=3.11"` in the same PR to avoid the mismatch. The UP rules will flag some 3.10-compatible constructs as upgradeable once py311 is the target.

**Incremental vs. all-at-once ruff:** Given 102 violations with 72 being E501 and 30 being distributed across 6 rule codes, all-at-once is appropriate. The violations are not interleaved across sensitive logic — line-length changes are cosmetic and the fixable violations are mechanical. A single formatted commit is cleaner than a series of partial-fix commits.

**Mypy strict is phased for a reason:** Phases 4–6 separate concerns that have different risk profiles. Annotation gaps (Phase 4) are low risk. Generic type arguments (Phase 5) may surface real bugs. Third-party stubs (Phase 6) are a policy decision. Keeping them separate makes review easier and allows stopping at Phase 4 or 5 if time is constrained.

**`assignment` error in `auth.py:32`:** `Incompatible default for parameter "db" (default has type "EllipsisType")` — this is a FastAPI `...` sentinel pattern. It should be handled with a `# type: ignore[assignment]` or restructured to use `Optional` with `None` default. Investigate before suppressing.
