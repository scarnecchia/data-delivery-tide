# Sub-Delivery System — Phase 1: Lexicon Model, Loader, and Schema

**Goal:** Add `sub_dirs` field to the `Lexicon` dataclass, update the loader to parse and validate it, update the JSON Schema, create the `soc.scdm` lexicon, and update `soc.qar`/`soc.qmr` with `sub_dirs` configuration.

**Architecture:** Extends the existing lexicon model with a single new field. Validation follows the batch-error-collection pattern already established in the loader. No new modules — all changes in existing files.

**Tech Stack:** Python 3.10+ stdlib only

**Scope:** Phase 1 of 3 from sub-deliveries design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### sub-deliveries.AC1: Lexicon model extension
- **sub-deliveries.AC1.1 Success:** `Lexicon` dataclass has a `sub_dirs` field of type `dict[str, str]`
- **sub-deliveries.AC1.2 Success:** `sub_dirs` defaults to empty dict when not specified in JSON
- **sub-deliveries.AC1.3 Success:** `sub_dirs` survives inheritance via deep merge

### sub-deliveries.AC2: Loader validation
- **sub-deliveries.AC2.1 Success:** Lexicon with valid `sub_dirs` referencing an existing lexicon ID loads successfully
- **sub-deliveries.AC2.2 Failure:** Lexicon with `sub_dirs` referencing a non-existent lexicon ID fails with `LexiconLoadError`
- **sub-deliveries.AC2.3 Success:** Lexicon with no `sub_dirs` field loads successfully (backward compatible)
- **sub-deliveries.AC2.4 Failure:** `sub_dirs` entry where the referenced lexicon has its own `sub_dirs` is rejected

### sub-deliveries.AC3: JSON Schema
- **sub-deliveries.AC3.1 Success:** `lexicon.schema.json` defines the `sub_dirs` field
- **sub-deliveries.AC3.2 Success:** Existing lexicon files without `sub_dirs` still validate

### sub-deliveries.AC6: Lexicon files
- **sub-deliveries.AC6.1 Success:** `soc/scdm.json` lexicon exists, extends `soc._base`, no derive hook
- **sub-deliveries.AC6.2 Success:** `soc/qar.json` and `soc/qmr.json` include `sub_dirs: {"scdm_snapshot": "soc.scdm"}`

---

<!-- START_TASK_1 -->
### Task 1: Add `sub_dirs` field to `Lexicon` dataclass

**Verifies:** sub-deliveries.AC1.1, sub-deliveries.AC1.2

**Files:**
- Modify: `src/pipeline/lexicons/models.py`

**Implementation:**

Add `sub_dirs: dict[str, str]` to the `Lexicon` frozen dataclass. Use `field(default_factory=dict)` so lexicons without `sub_dirs` get an empty dict.

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Lexicon:
    id: str
    statuses: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    dir_map: dict[str, str]
    actionable_statuses: tuple[str, ...]
    metadata_fields: dict[str, MetadataField]
    derive_hook: Callable | None = None
    sub_dirs: dict[str, str] = field(default_factory=dict)
```

The field maps directory names to lexicon IDs (e.g., `{"scdm_snapshot": "soc.scdm"}`).

**Tests:**
- No new test file — existing loader tests in `tests/lexicons/test_loader.py` will verify loading. Add tests in Task 3.

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update loader to parse and validate `sub_dirs`

**Verifies:** sub-deliveries.AC2.1, sub-deliveries.AC2.2, sub-deliveries.AC2.3, sub-deliveries.AC2.4

**Files:**
- Modify: `src/pipeline/lexicons/loader.py`

**Implementation:**

**In `_build_lexicon`:** Parse `sub_dirs` from the resolved data dict.

```python
def _build_lexicon(data: dict, hook: object | None) -> Lexicon:
    # ... existing code ...
    sub_dirs = dict(data.get("sub_dirs", {}))

    return Lexicon(
        # ... existing fields ...
        sub_dirs=sub_dirs,
    )
```

**In `load_all_lexicons`:** After all lexicons are built, add a validation pass for `sub_dirs` references. This must happen after all lexicons are resolved because `sub_dirs` references other lexicon IDs.

Add a new validation function `_validate_sub_dirs`:

```python
def _validate_sub_dirs(lexicons: dict[str, Lexicon]) -> list[str]:
    """Validate sub_dirs references across all loaded lexicons."""
    errors: list[str] = []
    for lid, lex in lexicons.items():
        for dir_name, sub_lexicon_id in lex.sub_dirs.items():
            if sub_lexicon_id not in lexicons:
                errors.append(
                    f"{lid}: sub_dirs['{dir_name}'] references "
                    f"unknown lexicon '{sub_lexicon_id}'"
                )
            elif lexicons[sub_lexicon_id].sub_dirs:
                errors.append(
                    f"{lid}: sub_dirs['{dir_name}'] references lexicon "
                    f"'{sub_lexicon_id}' which itself has sub_dirs "
                    f"(recursive nesting not allowed)"
                )
    return errors
```

Call this after building all lexicons in `load_all_lexicons`, before returning. If errors found, raise `LexiconLoadError`.

Note: `_validate_sub_dirs` runs on the built `Lexicon` objects (not raw dicts), so it must be called after `_build_lexicon` but before returning from `load_all_lexicons`. Restructure the end of `load_all_lexicons`:

```python
    # ... existing build loop ...
    result: dict[str, Lexicon] = {}
    for lid, data in resolved.items():
        result[lid] = _build_lexicon(data, hook_map.get(lid))

    # Validate sub_dirs references (must happen after all lexicons are built)
    sub_dir_errors = _validate_sub_dirs(result)
    if sub_dir_errors:
        raise LexiconLoadError(sub_dir_errors)

    return result
```

**Tests:** See Task 3.

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Tests for `sub_dirs` loading and validation

**Verifies:** sub-deliveries.AC1.1, sub-deliveries.AC1.2, sub-deliveries.AC1.3, sub-deliveries.AC2.1, sub-deliveries.AC2.2, sub-deliveries.AC2.3, sub-deliveries.AC2.4

**Files:**
- Modify: `tests/lexicons/test_loader.py`

**Implementation:**

Add a new test class `TestSubDirs` with the following tests:

1. **`test_lexicon_without_sub_dirs_has_empty_dict`** (AC1.2, AC2.3): Load a lexicon with no `sub_dirs` field. Assert `lexicon.sub_dirs == {}`.

2. **`test_lexicon_with_valid_sub_dirs_loads`** (AC1.1, AC2.1): Create a base lexicon and a sub-lexicon. Create a parent lexicon with `"sub_dirs": {"scdm_snapshot": "<sub_lexicon_id>"}`. Assert `lexicon.sub_dirs == {"scdm_snapshot": "<sub_lexicon_id>"}`.

3. **`test_sub_dirs_reference_to_unknown_lexicon_fails`** (AC2.2): Create a lexicon with `sub_dirs` referencing a non-existent lexicon ID. Assert `LexiconLoadError` with message mentioning "unknown lexicon".

4. **`test_sub_dirs_recursive_nesting_rejected`** (AC2.4): Create lexicon A with `sub_dirs` pointing to lexicon B. Lexicon B also has `sub_dirs`. Assert `LexiconLoadError` with message mentioning "recursive nesting".

5. **`test_sub_dirs_inherited_via_extends`** (AC1.3): Create a base lexicon with `sub_dirs`. Create a child that extends it without overriding `sub_dirs`. Assert child inherits the `sub_dirs` from base.

6. **`test_sub_dirs_overridden_via_extends`** (AC1.3): Create a base lexicon with `sub_dirs: {"a": "lex_a"}`. Create a child that extends it with `sub_dirs: {"b": "lex_b"}`. Assert child's `sub_dirs` contains both `a` and `b` (deep merge behaviour).

Each test uses the existing `make_lexicon_file` and `lexicons_dir` fixtures. Sub-lexicons need their own valid statuses/transitions/dir_map/actionable_statuses.

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Update JSON Schema for `sub_dirs`

**Verifies:** sub-deliveries.AC3.1, sub-deliveries.AC3.2

**Files:**
- Modify: `pipeline/lexicons/lexicon.schema.json`

**Implementation:**

Add `sub_dirs` to the schema's `properties`:

```json
"sub_dirs": {
  "type": "object",
  "additionalProperties": { "type": "string" },
  "description": "Maps subdirectory names to lexicon IDs. The crawler checks for these directories inside matched terminal directories and registers them as separate deliveries with the referenced lexicon."
}
```

This goes in the `properties` block alongside the existing fields. No `required` constraint — `sub_dirs` is optional.

**Tests:** No automated test — schema validation is editor-side. Existing lexicon files without `sub_dirs` continue to validate (AC3.2) because the field is not required.

<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Create `soc.scdm` lexicon and update `soc.qar`/`soc.qmr`

**Verifies:** sub-deliveries.AC6.1, sub-deliveries.AC6.2

**Files:**
- Create: `pipeline/lexicons/soc/scdm.json`
- Modify: `pipeline/lexicons/soc/qar.json`
- Modify: `pipeline/lexicons/soc/qmr.json`

**Implementation:**

Create `pipeline/lexicons/soc/scdm.json`:

```json
{
  "$schema": "../lexicon.schema.json",
  "extends": "soc._base"
}
```

The SCDM lexicon inherits statuses, transitions, dir_map, and actionable_statuses from `soc._base`. No derive hook (status inherited from parent), no metadata fields, no `sub_dirs`.

Update `pipeline/lexicons/soc/qar.json` — add `sub_dirs`:

```json
{
  "$schema": "../lexicon.schema.json",
  "extends": "soc._base",
  "derive_hook": "pipeline.lexicons.soc.qa:derive",
  "metadata_fields": {
    "passed_at": { "type": "datetime", "set_on": "passed" }
  },
  "sub_dirs": {
    "scdm_snapshot": "soc.scdm"
  }
}
```

Update `pipeline/lexicons/soc/qmr.json` — identical change:

```json
{
  "$schema": "../lexicon.schema.json",
  "extends": "soc._base",
  "derive_hook": "pipeline.lexicons.soc.qa:derive",
  "metadata_fields": {
    "passed_at": { "type": "datetime", "set_on": "passed" }
  },
  "sub_dirs": {
    "scdm_snapshot": "soc.scdm"
  }
}
```

**Tests:**
- Add a test `test_real_lexicons_load_with_sub_dirs` that loads from the actual `pipeline/lexicons/` directory and asserts:
  - `soc.scdm` exists, extends `soc._base`, has empty `sub_dirs` and no derive hook
  - `soc.qar` has `sub_dirs == {"scdm_snapshot": "soc.scdm"}`
  - `soc.qmr` has `sub_dirs == {"scdm_snapshot": "soc.scdm"}`

This test goes in `tests/lexicons/test_loader.py` under the `TestSubDirs` class.

<!-- END_TASK_5 -->
