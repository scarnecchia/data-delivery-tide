# GH17 — Test Requirements

Maps each acceptance criterion to either an automated verification command or human review. The design's Acceptance Criteria section is `<!-- TO BE GENERATED -->`, so this document treats the **Definition of Done** as the canonical AC list and synthesizes scoped IDs (`GH17.AC1.1` etc.) consistent with the implementation plan.

## Summary

GH17 is a tooling-and-config issue. Verification is dominated by **commands that must exit 0**:

- `uv run ruff format --check src/ tests/` — formatting is idempotent.
- `uv run ruff check src/ tests/` — zero lint violations.
- `uv run mypy src/pipeline/` — zero strict-mode errors.
- `uv run pytest` — no regressions across all phases.

There is **no new test code**: the plan's own verification steps ARE the regression check. Existing tests are the safety net for "tooling gates didn't break runtime semantics." Per the writing-implementation-plans skill: tooling/infrastructure phases are verified operationally, not by inventing unit tests.

The single category requiring human verification is the per-line `# noqa: B008` and `# type: ignore[assignment]` decisions in Phases 3 and 4 — these are judgement calls that mypy/ruff cannot validate.

---

## Coverage Map

### GH17.AC1.1 — `[tool.ruff]` config present with target-version, line-length, select

- **Verification type:** Automated (mechanical introspection)
- **Phase:** 1 (Task 1)
- **Command:**
  ```bash
  python -c "
  import tomllib
  with open('pyproject.toml', 'rb') as f:
      data = tomllib.load(f)
  ruff = data['tool']['ruff']
  assert ruff['target-version'] == 'py311', ruff['target-version']
  assert ruff['line-length'] == 100, ruff['line-length']
  assert data['tool']['ruff']['lint']['select'] == ['E', 'F', 'I', 'UP', 'B', 'SIM', 'TCH'], data['tool']['ruff']['lint']['select']
  print('AC1.1 ok')
  "
  ```
- **Pass condition:** prints `AC1.1 ok` with exit 0.

### GH17.AC1.2 — `[tool.mypy]` config present with python_version and strict

- **Verification type:** Automated (mechanical introspection)
- **Phase:** 1 (Task 1)
- **Command:**
  ```bash
  python -c "
  import tomllib
  with open('pyproject.toml', 'rb') as f:
      data = tomllib.load(f)
  mypy = data['tool']['mypy']
  assert mypy['python_version'] == '3.11', mypy['python_version']
  assert mypy['strict'] is True, mypy['strict']
  print('AC1.2 ok')
  "
  ```
- **Pass condition:** prints `AC1.2 ok`.

### GH17.AC1.3 — `mypy` in dev deps

- **Verification type:** Automated (mechanical)
- **Phase:** 1 (Task 1)
- **Command:**
  ```bash
  grep -E '^\s*"mypy>=' pyproject.toml
  ```
- **Pass condition:** matches one line containing `"mypy>=1.10,<2"` (or compatible floor).

### GH17.AC2.1 — `ruff format` exits 0 with no diffs

- **Verification type:** Automated
- **Phase:** 2 (Task 1)
- **Command:**
  ```bash
  uv run ruff format --check src/ tests/
  ```
- **Pass condition:** exit 0; output reads `N files already formatted`.

### GH17.AC2.2 — `ruff check --fix` clears auto-fixable violations

- **Verification type:** Automated
- **Phase:** 2 (Task 2)
- **Command:**
  ```bash
  uv run ruff check src/ tests/ --select I,F401,F541,UP
  ```
- **Pass condition:** exit 0 (zero violations of these auto-fixable codes).

### GH17.AC2.3, GH17.AC3.2, GH17.AC4.3, GH17.AC5.8, GH17.AC6.3 — `pytest` passes at every phase boundary

- **Verification type:** Automated (regression)
- **Phase:** every phase
- **Command:**
  ```bash
  uv run pytest
  ```
- **Pass condition:** exit 0, zero failures, zero errors.

### GH17.AC3.1 — `ruff check` exits 0 (all manual fixes applied)

- **Verification type:** Automated
- **Phase:** 3 (Tasks 1, 2, 3)
- **Command:**
  ```bash
  uv run ruff check src/ tests/
  ```
- **Pass condition:** exit 0 with `All checks passed!`.

### GH17.AC4.1 — Zero `[no-untyped-def]` errors

- **Verification type:** Automated
- **Phase:** 4 (Task 2)
- **Command:**
  ```bash
  uv run mypy src/pipeline/ 2>&1 | grep -c "no-untyped-def"
  ```
- **Pass condition:** prints `0`.
- **Note:** GH19 (hard upstream) does most of the work; Phase 4 is gap-fill. If grep returns >0 entries when GH19 is supposedly merged, surface to user before annotating — it implies a GH19 regression.

### GH17.AC4.2 — `auth.py:32` `EllipsisType` assignment cleared

- **Verification type:** Hybrid (automated + human review of Option A vs B selection)
- **Phase:** 4 (Task 3)
- **Command:**
  ```bash
  uv run mypy src/pipeline/registry_api/auth.py 2>&1 | grep -c "assignment.*EllipsisType\|EllipsisType.*assignment"
  ```
- **Pass condition:** prints `0`.
- **Human verification:** confirm whether Option A (parameter reorder) or Option B (`# type: ignore[assignment]`) was applied, and whether the chosen option is appropriate for current call sites (verified by `grep -rn "require_auth(" src/ tests/`).

### GH17.AC5.1 — Zero `[type-arg]` errors

- **Verification type:** Automated
- **Phase:** 5 (Task 1)
- **Command:**
  ```bash
  uv run mypy src/pipeline/ 2>&1 | grep -c "type-arg"
  ```
- **Pass condition:** prints `0`.

### GH17.AC5.2 — Zero `[dict-item]` errors

- **Phase:** 5 (Task 2)
- **Command:**
  ```bash
  uv run mypy src/pipeline/ 2>&1 | grep -c "dict-item"
  ```
- **Pass condition:** prints `0`.

### GH17.AC5.3 — Zero `[union-attr]` errors

- **Phase:** 5 (Task 3)
- **Command:**
  ```bash
  uv run mypy src/pipeline/ 2>&1 | grep -c "union-attr"
  ```
- **Pass condition:** prints `0`.
- **Human verification:** the `assert locked_schema is not None` in `convert.py` is a runtime guard; reviewer should confirm the assertion can never fire in practice (i.e., every prior path establishes non-None). If the assert can fire, that's a real bug to investigate.

### GH17.AC5.4 — Zero `[arg-type]` errors

- **Phase:** 5 (Task 4)
- **Command:**
  ```bash
  uv run mypy src/pipeline/ 2>&1 | grep -c "arg-type"
  ```
- **Pass condition:** prints `0`.
- **Human verification:** the `[DeliveryResponse.model_validate(item) for item in items]` change in `routes.py` produces identical wire output but allocates intermediate Pydantic models. Reviewer should confirm acceptable for the common case (likely yes — pagination caps response size).

### GH17.AC5.5, AC5.6, AC5.7 — Zero `[return-value]`, `[no-any-return]`, `[assignment]` errors

- **Phase:** 5 (Task 5)
- **Command:**
  ```bash
  uv run mypy src/pipeline/ 2>&1 | grep -cE "\[(return-value|no-any-return|assignment)\]"
  ```
- **Pass condition:** prints `0`.
- **Human verification:** any new `cast()` calls. A wrong cast silences mypy without fixing the bug — reviewer should validate each cast against the actual runtime type.

### GH17.AC6.1, AC6.2 — Zero `[import-untyped]` errors; mypy clean overall

- **Phase:** 6 (Task 1)
- **Command:**
  ```bash
  uv run mypy src/pipeline/
  ```
- **Pass condition:** exit 0, output reads `Success: no issues found in N source files`.

### GH17.AC6.3 (Composite Definition of Done)

- **Verification type:** Automated (composite)
- **Phase:** 6 (Task 1, Step 6)
- **Command:** the six-line script in Phase 6 Task 1 Step 6.
- **Pass condition:** all six `✓` lines print.

---

## Human Verification Items (consolidated)

| Item | AC | Justification | Approach |
|---|---|---|---|
| `# noqa: B008` correctness on FastAPI `Depends()` defaults | AC3.1 | B008 is suppressed; reviewer confirms each suppression is on a genuine FastAPI signature and not a bare misuse | PR review, `grep "noqa: B008" src/` |
| `auth.py:32` Option A vs B selection | AC4.2 | Either is correct; selection depends on whether `require_auth` is ever called positionally outside `Depends()` | `grep -rn "require_auth(" src/ tests/` at execution time |
| `assert locked_schema is not None` in `convert.py` | AC5.3 | Runtime assertion; reviewer confirms unreachability via prior control flow | PR review of the before/after diff in convert.py |
| `cast()` correctness in Task 5 | AC5.5, AC5.6 | Wrong casts silently mask bugs | PR review of each cast |
| Override decision (no `pandas-stubs`/`pyarrow-stubs`) | AC6.1 | Design's policy decision — reviewer confirms current state hasn't changed (e.g., pyarrow stubs haven't shipped officially) | PR description should state the decision is preserved from design |
| `daemon.py` import reorder (Phase 3 Task 2) | AC3.1 | Promotes deferred imports to top — startup-time impact confirmed acceptable | PR review |

---

## Out of Scope for Test Requirements

- New unit tests for the `pyproject.toml` config — TOML correctness is verified by ruff/mypy actually running.
- Integration tests for ruff/mypy in CI — out of GH17 scope; follow-up issue.
- Tests for the `# noqa: B008` and `# type: ignore[...]` comments themselves — they're suppressions, not behaviour.
- Performance regression tests — Phase 5's `DeliveryResponse.model_validate(item) for item in items` adds Pydantic instantiation cost on every list response; if this becomes a hot-path concern, that's a separate optimisation issue.

---

## Phase-by-Phase Verification Sequence

For an implementor executing the plan, the verification commands run in this order:

```bash
# After Phase 1
uv pip install -e ".[dev]"
uv run ruff check src/ --statistics  # baseline; non-zero is fine
uv run mypy src/pipeline/  # baseline; non-zero is fine
uv run pytest  # MUST exit 0

# After Phase 2
uv run ruff format --check src/ tests/  # MUST exit 0
uv run ruff check src/ tests/ --select I,F401,F541,UP  # MUST exit 0
uv run pytest  # MUST exit 0

# After Phase 3
uv run ruff check src/ tests/  # MUST exit 0 (all violations cleared)
uv run pytest  # MUST exit 0

# After Phase 4
uv run mypy src/pipeline/ 2>&1 | grep -c "no-untyped-def"  # MUST be 0
uv run mypy src/pipeline/ 2>&1 | grep -c "EllipsisType"  # MUST be 0
uv run pytest  # MUST exit 0

# After Phase 5
uv run mypy src/pipeline/ 2>&1 | grep -cE "\[(type-arg|dict-item|union-attr|arg-type|return-value|no-any-return|assignment)\]"  # MUST be 0
uv run pytest  # MUST exit 0

# After Phase 6 (final)
uv run mypy src/pipeline/  # MUST exit 0 with "Success: no issues found"
uv run ruff format --check src/ tests/  # MUST exit 0
uv run ruff check src/ tests/  # MUST exit 0
uv run pytest  # MUST exit 0
```

Each command is the gate for "phase complete". If any command fails, do not advance to the next phase.
