# Lexicon System Implementation Plan — Phase 2: Config Integration

**Goal:** Wire lexicon loading into the config system. Add `lexicons_dir` config field, `lexicon` field to `ScanRoot`, and cross-validate scan root lexicon references at startup.

**Architecture:** `load_config()` gains a `lexicons_dir` field and calls `load_all_lexicons()` during config load. Each `ScanRoot` gains a `lexicon` field that must reference a loaded lexicon ID. Validation failures are reported at startup (fail-fast).

**Tech Stack:** Python 3.10+ stdlib only

**Scope:** Phase 2 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### lexicon-system.AC2: Config integration
- **lexicon-system.AC2.1 Success:** Scan root with valid `lexicon` reference loads successfully
- **lexicon-system.AC2.2 Failure:** Scan root referencing non-existent lexicon ID fails at startup
- **lexicon-system.AC2.3 Failure:** Missing `lexicons_dir` in config fails at startup

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Add `lexicons_dir` and `lexicon` fields to config

**Verifies:** None (infrastructure — code changes, tested in Task 2)

**Files:**
- Modify: `src/pipeline/config.py:8-62` (ScanRoot dataclass and load_config function)
- Modify: `pipeline/config.json` (add `lexicons_dir`, add `lexicon` to each scan root)

**Implementation:**

Add `lexicon` field to `ScanRoot` dataclass at `src/pipeline/config.py:8-12`:

```python
@dataclass
class ScanRoot:
    path: str
    label: str
    lexicon: str
    target: str = "packages"
```

Note: `lexicon` is required (no default) — every scan root must specify which lexicon it uses.

Add `lexicons_dir` to `PipelineConfig` at `src/pipeline/config.py:15-27`:

```python
@dataclass
class PipelineConfig:
    scan_roots: list[ScanRoot]
    registry_api_url: str
    output_root: str
    schema_path: str
    overrides_path: str
    log_dir: str
    db_path: str
    dp_id_exclusions: list[str]
    crawl_manifest_dir: str
    crawler_version: str
    lexicons_dir: str
```

Update `load_config()` at `src/pipeline/config.py:29-62`:

In the `ScanRoot` construction (lines 42-48), add `lexicon` field:

```python
scan_roots = [
    ScanRoot(
        path=root["path"],
        label=root["label"],
        lexicon=root["lexicon"],
        target=root.get("target", "packages"),
    )
    for root in data["scan_roots"]
]
```

At the end of `load_config()`, before the return statement:
1. Read `lexicons_dir` from config data (required field — raise `KeyError` if missing)
2. Resolve `lexicons_dir` relative to the config file's parent directory
3. Call `load_all_lexicons(lexicons_dir)` to validate all lexicons load
4. Cross-validate: every scan root's `lexicon` must be a key in the loaded lexicons dict
5. Store `lexicons_dir` on the config object

```python
from pipeline.lexicons import load_all_lexicons, LexiconLoadError

# In load_config(), after building scan_roots:
lexicons_dir_raw = data.get("lexicons_dir")
if lexicons_dir_raw is None:
    raise ValueError("config missing required field 'lexicons_dir'")

lexicons_dir = str((config_path.parent / lexicons_dir_raw).resolve())

loaded_lexicons = load_all_lexicons(lexicons_dir)

bad_refs = [
    f"scan root '{root.label}' references unknown lexicon '{root.lexicon}'"
    for root in scan_roots
    if root.lexicon not in loaded_lexicons
]
if bad_refs:
    raise LexiconLoadError(bad_refs)

return PipelineConfig(
    scan_roots=scan_roots,
    registry_api_url=data["registry_api_url"],
    output_root=data["output_root"],
    schema_path=data["schema_path"],
    overrides_path=data["overrides_path"],
    log_dir=data["log_dir"],
    db_path=data["db_path"],
    dp_id_exclusions=data.get("dp_id_exclusions", []),
    crawl_manifest_dir=data.get("crawl_manifest_dir", "pipeline/crawl_manifests"),
    crawler_version=data.get("crawler_version", "1.0.0"),
    lexicons_dir=lexicons_dir,
)
```

Update `pipeline/config.json` — add `lexicons_dir` and `lexicon` to each scan root:

```json
{
  "lexicons_dir": "pipeline/lexicons",
  "scan_roots": [
    {
      "path": "/requests/qa",
      "label": "QA Package Results",
      "lexicon": "soc.qar",
      "target": "packages"
    },
    {
      "path": "/requests/qm",
      "label": "MIL QA Package Results",
      "lexicon": "soc.qar",
      "target": "packages"
    },
    {
      "path": "/requests/qad",
      "label": "QA Internal DP Data",
      "lexicon": "soc.qar",
      "target": "packages"
    },
    {
      "path": "/requests/qmd",
      "label": "MIL QA Internal DP Data",
      "lexicon": "soc.qar",
      "target": "packages"
    }
  ],
  "registry_api_url": "http://localhost:8000",
  "output_root": "/output",
  "schema_path": "/pipeline/schema.json",
  "overrides_path": "/pipeline/overrides.json",
  "log_dir": "/pipeline/logs",
  "db_path": "pipeline/registry.db",
  "dp_id_exclusions": ["nsdp"],
  "crawl_manifest_dir": "pipeline/crawl_manifests",
  "crawler_version": "1.0.0"
}
```

**Verification:**

```bash
python -c "from pipeline.config import ScanRoot; sr = ScanRoot(path='/x', label='X', lexicon='soc.qar'); print(sr.lexicon)"
```

Expected: `soc.qar`

**Commit:** `feat: add lexicons_dir and lexicon fields to config system`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update config tests and write new lexicon config tests

**Verifies:** lexicon-system.AC2.1, lexicon-system.AC2.2, lexicon-system.AC2.3

**Files:**
- Modify: `tests/test_config.py` (update existing tests to include `lexicon` field, add new tests)

**Implementation:**

All existing config tests create config JSON dicts with `scan_roots` entries. These must now include a `"lexicon"` field on each scan root AND a `"lexicons_dir"` field pointing to a directory with valid lexicon files.

For existing tests that use `tmp_path`, create a minimal lexicons directory alongside the config file:

```python
# Helper to create minimal lexicons dir for config tests
def _make_lexicons(tmp_path, lexicon_id="soc.qar"):
    """Create a minimal valid lexicons directory for config tests."""
    parts = lexicon_id.split(".")
    # soc.qar -> soc/qar.json
    lex_dir = tmp_path / "lexicons"
    lex_file = lex_dir / "/".join(parts[:-1]) / f"{parts[-1]}.json"
    lex_file.parent.mkdir(parents=True, exist_ok=True)
    lex_file.write_text(json.dumps({
        "statuses": ["pending", "passed", "failed"],
        "transitions": {"pending": ["passed", "failed"], "passed": [], "failed": []},
        "dir_map": {"msoc": "passed", "msoc_new": "pending"},
        "actionable_statuses": ["passed"],
        "metadata_fields": {},
    }))
    return str(lex_dir)
```

Existing tests need `"lexicon": "soc.qar"` added to each scan root dict and `"lexicons_dir"` pointing to the temp lexicons dir. The `test_load_config_falls_back_to_default` and `test_load_config_default_json_all_targets_packages` tests load the real `pipeline/config.json` which now has `lexicons_dir` and `lexicon` fields — these will work if the real lexicon files exist (created in Phase 1 Task 3). Note: the real `soc/qar.json` references a `derive_hook` that doesn't exist yet (Phase 6), so these fallback tests will fail until Phase 6. The executor should temporarily skip the hook import or mock it. Alternatively, the executor can adjust these two tests to use `tmp_path` with a custom config that doesn't reference a hook.

**Testing:**

New tests must verify:

- **lexicon-system.AC2.1:** Create config with valid `lexicon` reference matching a loaded lexicon ID. Assert `load_config()` succeeds, `ScanRoot.lexicon` field populated correctly.
- **lexicon-system.AC2.2:** Create config where scan root references non-existent lexicon ID (`"soc.nonexistent"`). Assert `LexiconLoadError` raised, error mentions the bad reference.
- **lexicon-system.AC2.3:** Create config JSON with no `lexicons_dir` field. Assert `ValueError` raised with message about missing `lexicons_dir`.

**Verification:**

```bash
uv run pytest tests/test_config.py -v
```

Expected: All tests pass (existing updated + new AC2 tests).

**Commit:** `test: update config tests for lexicon fields, add AC2.1-AC2.3 coverage`

<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_3 -->
### Task 3: Run full test suite, verify no regressions

**Verifies:** None (regression check)

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: All tests pass. The config changes affect existing tests (they now need `lexicon` and `lexicons_dir`) — Task 2 addresses all updates.

If the fallback tests that load real `pipeline/config.json` fail due to the `derive_hook` reference in `soc/qar.json` (hook module doesn't exist until Phase 6), the executor should either:
1. Remove `derive_hook` from `pipeline/lexicons/soc/qar.json` temporarily (re-add in Phase 6), OR
2. Adjust those tests to use `tmp_path` with mock config

**Commit:** No commit if clean. Fix commit if needed: `fix: resolve test regression from config lexicon integration`

<!-- END_TASK_3 -->
