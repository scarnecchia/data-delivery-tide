# QA Registry Implementation Plan — Phase 2: Configuration

**Goal:** Shared config loading that all services will use — reads `config.json` from env var or default path, exposes typed config object.

**Architecture:** Single `config.py` module in `src/pipeline/` that exposes a lazy-loaded `settings` object. Config is loaded on first attribute access, not at import time, so that importing the module doesn't require `config.json` to exist (important for test isolation). All services import from `pipeline.config`.

**Tech Stack:** Python stdlib (`json`, `os`, `pathlib`)

**Scope:** 6 phases from original design (phase 2 of 6)

**Codebase verified:** 2026-04-09 — greenfield, Phase 1 creates `src/pipeline/__init__.py` and package structure.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### qa-registry.AC4: Infrastructure
- **qa-registry.AC4.1 Success:** Config loads from `PIPELINE_CONFIG` env var, falls back to `pipeline/config.json`

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->
<!-- START_TASK_1 -->
### Task 1: Create pipeline/config.json

**Files:**
- Create: `pipeline/config.json`

**Step 1: Create the default config file**

```json
{
  "scan_roots": [
    {
      "path": "/requests/qa",
      "label": "QA Package Results"
    },
    {
      "path": "/requests/qm",
      "label": "MIL QA Package Results"
    },
    {
      "path": "/requests/qad",
      "label": "QA Internal DP Data"
    },
    {
      "path": "/requests/qmd",
      "label": "MIL QA Internal DP Data"
    }
  ],
  "registry_api_url": "http://localhost:8000",
  "output_root": "/output",
  "schema_path": "/pipeline/schema.json",
  "overrides_path": "/pipeline/overrides.json",
  "log_dir": "/pipeline/logs",
  "db_path": "pipeline/registry.db"
}
```

Note: `db_path` is added beyond the spec's config — the design specifies `registry.db` lives at `pipeline/registry.db` and the database layer needs to know where to find it.

**Step 2: Commit**

```bash
git add pipeline/config.json
git commit -m "chore: add default pipeline config"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create src/pipeline/config.py

**Verifies:** qa-registry.AC4.1

**Files:**
- Create: `src/pipeline/config.py`

**Implementation:**

The config module should:
1. Define a `PipelineConfig` dataclass with fields matching the JSON structure
2. Define a `ScanRoot` dataclass for the nested scan_roots entries
3. Implement `load_config(path: str | None = None) -> PipelineConfig` that:
   - If `path` is None, reads `PIPELINE_CONFIG` env var
   - If env var is not set, falls back to `pipeline/config.json`
   - Reads the JSON file and returns a `PipelineConfig` instance
   - Raises `FileNotFoundError` if the config file doesn't exist
4. Expose a module-level `settings` object that is **lazy-loaded on first access**, not at import time. Implement using a module-level `__getattr__` function:
   ```python
   _settings = None
   
   def __getattr__(name):
       global _settings
       if name == "settings":
           if _settings is None:
               _settings = load_config()
           return _settings
       raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
   ```
   This ensures `from pipeline.config import settings` works, but config is only loaded when `settings` is actually accessed. This prevents `FileNotFoundError` in tests that import modules transitively depending on config but don't need the actual config values.

Use `dataclasses.dataclass` (stdlib) — no Pydantic needed for config since this is internal-only and the shape is simple.

**Step 1: Create the file with the implementation described above**

**Step 2: Verify it loads**

Run: `python -c "from pipeline.config import settings; print(settings.registry_api_url)"`
Expected: `http://localhost:8000`

**Step 3: Commit**

```bash
git add src/pipeline/config.py
git commit -m "feat: add config module with env var override support"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Config tests

**Verifies:** qa-registry.AC4.1

**Files:**
- Create: `tests/test_config.py`

**Testing:**

Tests must verify:
- **qa-registry.AC4.1:** Config loads from `PIPELINE_CONFIG` env var, falls back to `pipeline/config.json`

Specific test cases:
1. `test_load_config_from_explicit_path` — pass a path to a temp config JSON, verify all fields load correctly including nested `scan_roots`
2. `test_load_config_from_env_var` — set `PIPELINE_CONFIG` env var to a temp config file path, call `load_config()` with no args, verify it reads from the env var path
3. `test_load_config_falls_back_to_default` — with no env var set and a config file at `pipeline/config.json`, verify `load_config()` finds it (run from repo root)
4. `test_load_config_missing_file_raises` — pass a nonexistent path, verify `FileNotFoundError` is raised

Use `tmp_path` pytest fixture for creating temporary config files. Use `monkeypatch` for env var manipulation.

**Verification:**

Run: `pytest tests/test_config.py -v`
Expected: All 4 tests pass

**Commit:** `test: add config loading tests`
<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_A -->
