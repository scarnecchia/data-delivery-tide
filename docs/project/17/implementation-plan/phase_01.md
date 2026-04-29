# GH17 Phase 1 — Tooling Configuration in pyproject.toml

**Goal:** Add `[tool.ruff]`, `[tool.ruff.lint]`, and `[tool.mypy]` sections to `pyproject.toml` and add `mypy` + `ruff` to the `dev` optional-dependencies group.

**Architecture:** Pure config edit. No source code touched in this phase. Establishes the "target state" so subsequent phases (2-6) have something to validate against.

**Tech Stack:** ruff 0.15+, mypy 1.10+, hatchling (build backend, unchanged).

**Scope:** 1 of 6 phases.

**Codebase verified:** 2026-04-29

- ✓ `pyproject.toml` exists at repo root with `[build-system]`, `[project]`, `[project.optional-dependencies]`, `[project.scripts]`, `[tool.pytest.ini_options]`, `[tool.hatch.build.targets.wheel]`. No `[tool.ruff]` or `[tool.mypy]` sections present.
- ✓ `requires-python = ">=3.10"` at line 8 — GH18 (hard dep) bumps this to `">=3.11"` first; this phase assumes that has already landed.
- ✓ `dev` group at lines 24-28 has `pytest`, `pytest-asyncio`, `httpx`. No `ruff` or `mypy` listed (ruff 0.15.6 is available transiently via `uv run` but not declared as a project dep).
- ✓ Python runtime resolves to 3.12.12 via uv (verified: `uv run python -c "import sys; print(sys.version)"`).
- ✓ Current ruff state (without project config): 17 violations under default rule set. Once `select = ["E","F","I","UP","B","SIM","TCH"]` is set with `line-length = 100`, the violation count will change — see Phase 2.
- ✓ Current mypy strict state: **100 errors in 21 files** when run via `uv run --with mypy mypy --strict src/pipeline/`. Categories: 42 type-arg, 31 no-untyped-def variants, ~10 dict-item/assignment/return-type/arg-type, 4 import-untyped (pyarrow, pandas, pyreadstat). After GH19 lands (annotations), the no-untyped-def category drops near-zero — Phase 4 will mop up residuals.

---

## Acceptance Criteria Coverage

The design's "Acceptance Criteria" section is `<!-- TO BE GENERATED -->`, so this phase honours the **Definition of Done** bullets directly:

- **GH17.AC1.1 (Tooling config present):** `pyproject.toml` has `[tool.ruff]` with `target-version = "py311"`, `line-length = 100`, and `select = ["E","F","I","UP","B","SIM","TCH"]`.
- **GH17.AC1.2 (Mypy config present):** `pyproject.toml` has `[tool.mypy]` with `python_version = "3.11"` and `strict = true`.
- **GH17.AC1.3 (Mypy in dev deps):** `mypy` is listed in `[project.optional-dependencies] dev`.

Phase 1 explicitly does NOT verify the rest of the Definition of Done (ruff format passing, ruff check passing, mypy passing, pytest passing) — those are the responsibility of Phases 2-6.

---

<!-- START_TASK_1 -->
### Task 1: Add ruff and mypy config sections + dev deps to pyproject.toml

**Verifies:** GH17.AC1.1, GH17.AC1.2, GH17.AC1.3

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/pyproject.toml`

**Implementation:**

This is a single-file edit. Three config sections appended, plus two entries added to the `dev` group.

**Edit 1 — `pyproject.toml:24-28` (extend `dev` group).** Current:

```toml
dev = [
    "pytest>=8,<9",
    "pytest-asyncio>=0.23,<1",
    "httpx>=0.28,<1",
]
```

Replace with:

```toml
dev = [
    "pytest>=8,<9",
    "pytest-asyncio>=0.23,<1",
    "httpx>=0.28,<1",
    "ruff>=0.15,<1",
    "mypy>=1.10,<2",
]
```

(Both ruff and mypy declared as project deps so contributors don't rely on transient `uv run --with` installs. ruff 0.15.6 is the version verified during planning; mypy 1.10 is the floor that supports `python_version = "3.11"` cleanly.)

**Edit 2 — Append after line 38 (`[tool.pytest.ini_options]` block ends), before `[tool.hatch.build.targets.wheel]` at line 40.** Insert these new sections:

```toml
[tool.ruff]
target-version = "py311"
line-length = 100
extend-exclude = [
    ".worktrees",
    "build",
    "dist",
]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["E501"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["src/pipeline"]
```

Notes for the implementor:

- `target-version = "py311"` matches the design and the post-#18 `requires-python`.
- `line-length = 100` matches the design (default is 88; 100 is a deliberate choice for this project).
- `select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]` matches the design: pycodestyle errors, Pyflakes, isort, pyupgrade, flake8-bugbear, flake8-simplify, flake8-type-checking. Phase 3 details which manual fixes these surface.
- `extend-exclude` covers the `.worktrees/` directory the team may use, plus standard build outputs. Tests aren't excluded — they're linted but with `E501` (line-length) ignored, since long pytest parametrize tuples and string fixtures are common.
- `[tool.mypy] strict = true` enables the canonical strict bundle: `--disallow-untyped-defs`, `--disallow-any-generics`, `--check-untyped-defs`, `--no-implicit-optional`, `--warn-redundant-casts`, `--warn-unused-ignores`, `--warn-return-any`, `--no-implicit-reexport`, `--strict-equality`. Per the design's "Mypy strict is phased for a reason" note.
- `files = ["src/pipeline"]` scopes the strict check to source code only; test files won't be checked under strict mode (they already get coverage from runtime test execution). Phase 6 may add overrides for third-party libraries.
- The third-party `[[tool.mypy.overrides]]` blocks for pandas/pyarrow/pyreadstat are added in **Phase 6**, not here. This phase intentionally surfaces the import-untyped errors so Phase 6 has work to do; suppressing them in Phase 1 would obscure the boundary.

**Step 1: Apply the edits**

Use whatever editor mechanic is preferred (`Edit` tool, manual edit, etc.). The combined diff is:

```diff
@@ -23,9 +23,11 @@
 dev = [
     "pytest>=8,<9",
     "pytest-asyncio>=0.23,<1",
     "httpx>=0.28,<1",
+    "ruff>=0.15,<1",
+    "mypy>=1.10,<2",
 ]

 [project.scripts]
 registry-api = "pipeline.registry_api.main:run"
 registry-auth = "pipeline.auth_cli:main"
 registry-convert = "pipeline.converter.cli:main"
 registry-convert-daemon = "pipeline.converter.daemon:main"

 [tool.pytest.ini_options]
 testpaths = ["tests"]
 asyncio_mode = "auto"

+[tool.ruff]
+target-version = "py311"
+line-length = 100
+extend-exclude = [
+    ".worktrees",
+    "build",
+    "dist",
+]
+
+[tool.ruff.lint]
+select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]
+
+[tool.ruff.lint.per-file-ignores]
+"tests/**/*.py" = ["E501"]
+
+[tool.mypy]
+python_version = "3.11"
+strict = true
+files = ["src/pipeline"]
+
 [tool.hatch.build.targets.wheel]
 packages = ["src/pipeline"]
```

**Step 2: Sync the dev environment**

```bash
uv pip install -e ".[registry,converter,consumer,dev]"
```

Expected: `Successfully installed ... ruff-0.15.x ... mypy-1.10+...` (exact versions floor-pinned). No errors.

**Step 3: Verify ruff is available and uses the new config**

```bash
uv run ruff check src/ tests/ --statistics 2>&1 | head -40
```

Expected: ruff runs against the new rule set. Violation counts will differ from the pre-config 17 — UP/B/SIM/TCH rules will surface new flags, and the line-length change may resolve some E501s. **The exact count is not Phase 1's concern** — Phase 2 inventories and resolves all surfaced violations.

If ruff prints `error: invalid configuration` or similar, the TOML is malformed — re-check the diff above.

**Step 4: Verify mypy is available and uses the new config**

```bash
uv run mypy src/pipeline/ 2>&1 | tail -5
```

Expected: mypy runs against `src/pipeline/` and reports a number of errors (likely ~100 pre-GH19, much fewer post-GH19). The exact count is not Phase 1's concern — it just needs to *run*. If mypy prints `error: Cannot find implementation or library stub for module` for `pipeline.config` or similar **first-party** imports, the `files = ["src/pipeline"]` setting is wrong — re-check.

It's expected and fine if mypy reports many errors; this phase only verifies that **mypy executes against the configured target**. Resolution of those errors is Phases 4-6.

**Step 5: Verify pytest still passes**

```bash
uv run pytest
```

Expected: zero failures. (Phase 1 changes only `pyproject.toml` config; no source or test edits, so test outcomes must be unchanged.)

**Commit:**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: configure ruff and mypy with strict mode (#17)"
```

(`uv.lock` will be regenerated by the `uv pip install -e` step. Commit it so other contributors get the same tool versions.)
<!-- END_TASK_1 -->

---

## Phase Done When

- `pyproject.toml` contains `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.lint.per-file-ignores]`, `[tool.mypy]` sections matching the diff above.
- `dev` optional-deps include `ruff` and `mypy`.
- `uv pip install -e ".[dev]"` succeeds.
- `uv run ruff check src/` and `uv run mypy src/pipeline/` both **execute** (regardless of error count).
- `uv run pytest` exits 0.

## Out of Scope

- Resolving any ruff or mypy violation surfaced by this config (Phases 2-6).
- Adding `[[tool.mypy.overrides]]` for third-party libs (Phase 6).
- `pre-commit`, GitHub Actions, or any CI wiring (not in this issue's scope).
- Changing `requires-python` (handled by GH18, hard dep).

## Notes for the implementor

- If GH18 has not landed by the time this phase is executed, the `target-version = "py311"` setting is *fine to ship* — ruff and mypy honour `target-version`/`python_version` independently of `requires-python`. But the design plan explicitly assumes GH18 is the upstream that bumps `requires-python`. If this phase ships before GH18, surface to the user — the discrepancy is non-fatal but worth recording.

**DAG correction:** GH18 should be a hard dependency of GH17, not soft. GH17 Phase 2's UP rule migrations produce 3.11+ syntax that will fail at runtime if requires-python still allows 3.10. Ensure GH18 has merged before executing GH17.
