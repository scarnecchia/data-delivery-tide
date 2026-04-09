# QA Registry Implementation Plan — Phase 1: Monorepo Scaffolding

**Goal:** Project structure, build configuration, and tooling so that `pip install -e ".[registry,dev]"` works and `pytest` runs with zero tests.

**Architecture:** Single Python package monorepo using `src/pipeline/` layout with hatchling build backend. Optional dependency groups per service (`registry`, `converter`, `dev`). Placeholder subpackages for crawler and converter.

**Tech Stack:** Python 3.12.5, hatchling (build backend), pytest (testing), FastAPI + uvicorn (registry deps), pyreadstat + pyarrow (converter deps)

**Scope:** 6 phases from original design (phase 1 of 6)

**Codebase verified:** 2026-04-09 — greenfield repo, only `spec.md` and `docs/design-plans/2026-04-09-qa-registry.md` exist.

---

## Acceptance Criteria Coverage

This phase is infrastructure scaffolding. No functional acceptance criteria are tested.

**Verifies:** None — verified operationally (install succeeds, pytest runs, import works).

Covers design Definition of Done item 1: "Monorepo scaffolding — single `pyproject.toml` with `src/pipeline/` layout, optional dependency groups per service (`registry`, `converter`, `dev`), `[project.scripts]` entrypoints for each service, pytest configured"

Partially covers:
### qa-registry.AC4: Infrastructure
- **qa-registry.AC4.3 Success:** `pip install -e ".[registry,dev]"` installs all dependencies and `registry-api` entrypoint is available

---

<!-- START_TASK_1 -->
### Task 1: Create pyproject.toml

**Files:**
- Create: `pyproject.toml`

**Step 1: Create the file**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pipeline"
version = "0.1.0"
requires-python = ">=3.12"

[project.optional-dependencies]
registry = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.34,<1",
]
converter = [
    "pyreadstat>=1.2,<2",
    "pyarrow>=18,<19",
]
dev = [
    "pytest>=8,<9",
    "httpx>=0.28,<1",
]

[project.scripts]
registry-api = "pipeline.registry_api.main:run"

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.hatch.build.targets.wheel]
packages = ["src/pipeline"]
```

**Step 2: Verify the file is syntactically correct**

Run: `python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with hatchling build config"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create src/pipeline package structure

**Files:**
- Create: `src/pipeline/__init__.py`
- Create: `src/pipeline/registry_api/__init__.py`
- Create: `src/pipeline/crawler/__init__.py`
- Create: `src/pipeline/converter/__init__.py`

**Step 1: Create the directories and empty init files**

All four files are empty `__init__.py` files. Create the directory structure:

```
src/
  pipeline/
    __init__.py
    registry_api/
      __init__.py
    crawler/
      __init__.py
    converter/
      __init__.py
```

Each `__init__.py` is an empty file (zero bytes).

**Step 2: Verify Python can find the package**

Run: `python -c "import importlib.util; print('src/pipeline exists:', importlib.util.find_spec('pipeline') is not None or 'not installed yet — expected')"`
Expected: Prints confirmation (package not importable yet until installed — expected at this stage)

**Step 3: Commit**

```bash
git add src/
git commit -m "chore: add src/pipeline package structure with subpackage placeholders"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Create tests directory

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/registry_api/__init__.py`

**Step 1: Create the directories and files**

```
tests/
  __init__.py          (empty)
  conftest.py          (empty — fixtures added in Phase 5)
  registry_api/
    __init__.py        (empty)
```

All three files are empty.

**Step 2: Commit**

```bash
git add tests/
git commit -m "chore: add tests directory structure"
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Create .gitignore

**Files:**
- Create: `.gitignore`

**Step 1: Create the file**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
*.egg
.eggs/

# Virtual environments
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Testing
.pytest_cache/
.coverage
htmlcov/

# Project-specific
output/
pipeline/registry.db
pipeline/logs/
```

**Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore for Python project"
```
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Install and verify

**Step 1: Install the package in editable mode with all optional dependencies**

Run: `pip install -e ".[registry,dev]"`
Expected: Installs successfully with all dependencies resolved. Output ends with `Successfully installed ...` (or reports already satisfied).

**Step 2: Verify the package is importable**

Run: `python -c "import pipeline; print('pipeline imported successfully')"`
Expected: `pipeline imported successfully`

**Step 3: Verify pytest runs**

Run: `pytest`
Expected: `no tests ran` or `0 items collected` — exits with code 5 (no tests collected) or 0. No import errors.

**Step 4: Verify the entrypoint is registered**

Run: `which registry-api || pip show pipeline | grep -A5 "Entry points"`
Expected: The `registry-api` entrypoint is available (it will fail to run since `main.py` doesn't exist yet — that's expected).

**Step 5: Commit (if any changes from install)**

No code changes expected from this step. If `.gitignore` needs updates for any generated files, commit those.
<!-- END_TASK_5 -->
