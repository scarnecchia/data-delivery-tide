# Lexicon System Implementation Plan — Phase 1: Lexicon Schema and Loader

**Goal:** Define the lexicon data model and build the loader that reads JSON files, resolves inheritance, imports derivation hooks, and validates schemas — all errors reported in batch.

**Architecture:** Frozen dataclasses for the domain model (`Lexicon`, `MetadataField`), pure-function loader that discovers JSON files in a directory tree, resolves inheritance via topological sort, validates all cross-references, and imports optional Python hook functions. Follows the Functional Core pattern established in `src/pipeline/crawler/parser.py`.

**Tech Stack:** Python 3.10+ stdlib only (json, dataclasses, pathlib, importlib, graphlib)

**Scope:** Phase 1 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### lexicon-system.AC1: Lexicon loading and validation
- **lexicon-system.AC1.1 Success:** Lexicon JSON files load and resolve to frozen Lexicon dataclasses
- **lexicon-system.AC1.2 Success:** Child lexicon inherits all fields from base via `extends`
- **lexicon-system.AC1.3 Success:** Child lexicon overrides specific base fields while keeping the rest
- **lexicon-system.AC1.4 Failure:** Circular `extends` chain detected and reported at load time
- **lexicon-system.AC1.5 Failure:** Status referenced in `transitions` that isn't in `statuses` reported
- **lexicon-system.AC1.6 Failure:** `dir_map` value not in `statuses` reported
- **lexicon-system.AC1.7 Failure:** `set_on` value not in `statuses` reported
- **lexicon-system.AC1.8 Failure:** `derive_hook` string that can't be imported reported
- **lexicon-system.AC1.9 Edge:** Multiple validation errors collected and reported in single batch

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Create lexicon data model (`models.py`)

**Verifies:** None (infrastructure — dataclass definitions only)

**Files:**
- Create: `src/pipeline/lexicons/__init__.py`
- Create: `src/pipeline/lexicons/models.py`

**Implementation:**

Create the `src/pipeline/lexicons/` package with the `Lexicon` and `MetadataField` frozen dataclasses.

Follow the frozen dataclass pattern from `src/pipeline/crawler/parser.py:7-24` (uses `@dataclass(frozen=True)`, modern type hints like `str | None`, tuple for immutable sequences).

`src/pipeline/lexicons/models.py`:

```python
# pattern: Functional Core
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MetadataField:
    type: str
    set_on: str | None = None


@dataclass(frozen=True)
class Lexicon:
    id: str
    statuses: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    dir_map: dict[str, str]
    actionable_statuses: tuple[str, ...]
    metadata_fields: dict[str, MetadataField]
    derive_hook: Callable | None = None
```

`src/pipeline/lexicons/__init__.py` — re-export pattern matching `src/pipeline/crawler/__init__.py` (uses `as` alias for mypy):

```python
from pipeline.lexicons.models import (
    Lexicon as Lexicon,
    MetadataField as MetadataField,
)
```

(Loader exports added in Task 2 after the functions exist.)

**Verification:**

```bash
cd /Users/scarndp/dev/Sentinel/qa_registry
python -c "from pipeline.lexicons import Lexicon, MetadataField; print('OK')"
```

Expected: `OK`

**Commit:** `feat: add Lexicon and MetadataField frozen dataclasses`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create lexicon loader (`loader.py`)

**Verifies:** None (infrastructure — loader functions, tested in Task 3)

**Files:**
- Create: `src/pipeline/lexicons/loader.py`
- Modify: `src/pipeline/lexicons/__init__.py` (add loader re-exports)

**Implementation:**

The loader has these responsibilities:
1. **Discovery:** Walk `lexicons_dir` recursively, find all `.json` files, derive IDs from relative path (`soc/qar.json` → `soc.qar`, `soc/_base.json` → `soc._base`)
2. **Inheritance resolution:** Topological sort using `graphlib.TopologicalSorter`. Process bases before children. Deep-merge: child keys override base keys at top level; nested dicts (like `transitions`, `metadata_fields`) are merged key-by-key with child winning.
3. **Hook import:** If `derive_hook` is a string like `"pipeline.lexicons.soc.qa:derive"`, split on `:`, import the module, `getattr` the function.
4. **Validation:** Collect ALL errors before raising. Check:
   - Every status in `transitions` keys and values exists in `statuses`
   - Every `dir_map` value exists in `statuses`
   - Every `actionable_statuses` entry exists in `statuses`
   - Every `metadata_fields[*].set_on` value exists in `statuses`
   - `derive_hook` string resolves to an importable callable
   - No circular `extends` chains (graphlib raises `CycleError`)
   - Inheritance depth ≤ 3

`src/pipeline/lexicons/loader.py`:

```python
# pattern: Functional Core
from __future__ import annotations

import importlib
import json
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from pipeline.lexicons.models import Lexicon, MetadataField

MAX_INHERITANCE_DEPTH = 3


class LexiconLoadError(Exception):
    """Raised when one or more lexicon files fail validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} lexicon error(s):\n" + "\n".join(errors))


def _discover_lexicon_files(lexicons_dir: Path) -> dict[str, Path]:
    """Walk lexicons_dir, return mapping of lexicon_id -> file path."""
    result: dict[str, Path] = {}
    for json_file in sorted(lexicons_dir.rglob("*.json")):
        relative = json_file.relative_to(lexicons_dir)
        lexicon_id = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")
        result[lexicon_id] = json_file
    return result


def _resolve_inheritance_order(
    raw_lexicons: dict[str, dict],
) -> list[str]:
    """Return lexicon IDs in topological order (bases before children).

    Raises LexiconLoadError on circular extends or missing base references.
    """
    errors: list[str] = []
    sorter: TopologicalSorter[str] = TopologicalSorter()

    for lid, data in raw_lexicons.items():
        extends = data.get("extends")
        if extends:
            if extends not in raw_lexicons:
                errors.append(f"{lid}: extends unknown lexicon '{extends}'")
            else:
                sorter.add(lid, extends)
        else:
            sorter.add(lid)

    if errors:
        raise LexiconLoadError(errors)

    try:
        return list(sorter.static_order())
    except CycleError as exc:
        raise LexiconLoadError([f"circular extends chain: {exc.args[1]}"]) from exc


def _check_inheritance_depth(
    raw_lexicons: dict[str, dict],
) -> list[str]:
    """Check that no inheritance chain exceeds MAX_INHERITANCE_DEPTH."""
    errors: list[str] = []
    for lid, data in raw_lexicons.items():
        depth = 0
        current = lid
        while raw_lexicons.get(current, {}).get("extends"):
            depth += 1
            current = raw_lexicons[current]["extends"]
            if depth > MAX_INHERITANCE_DEPTH:
                errors.append(
                    f"{lid}: inheritance depth exceeds {MAX_INHERITANCE_DEPTH}"
                )
                break
    return errors


def _deep_merge(base: dict, child: dict) -> dict:
    """Merge child into base. Child keys win. Nested dicts merged recursively."""
    result = dict(base)
    for key, value in child.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_single(
    lid: str,
    raw_lexicons: dict[str, dict],
    resolved: dict[str, dict],
) -> dict:
    """Resolve a single lexicon, merging with its base if extends is set."""
    data = raw_lexicons[lid]
    extends = data.get("extends")
    if extends and extends in resolved:
        base = resolved[extends]
        merged = _deep_merge(base, data)
        merged["id"] = lid
        merged.pop("extends", None)
        return merged
    data = dict(data)
    data["id"] = lid
    data.pop("extends", None)
    return data


def _import_hook(hook_path: str) -> object:
    """Import a hook from a dotted path like 'pipeline.lexicons.soc.qa:derive'."""
    module_path, _, attr_name = hook_path.rpartition(":")
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def _validate_lexicon(lid: str, data: dict) -> list[str]:
    """Validate a single resolved lexicon dict. Return list of error strings."""
    errors: list[str] = []
    statuses = set(data.get("statuses", []))

    if not statuses:
        errors.append(f"{lid}: 'statuses' is empty or missing")

    for from_status, targets in data.get("transitions", {}).items():
        if from_status not in statuses:
            errors.append(f"{lid}: transitions key '{from_status}' not in statuses")
        for target in targets:
            if target not in statuses:
                errors.append(
                    f"{lid}: transitions['{from_status}'] references "
                    f"unknown status '{target}'"
                )

    for dir_name, status in data.get("dir_map", {}).items():
        if status not in statuses:
            errors.append(
                f"{lid}: dir_map['{dir_name}'] references unknown status '{status}'"
            )

    for action_status in data.get("actionable_statuses", []):
        if action_status not in statuses:
            errors.append(
                f"{lid}: actionable_statuses references unknown status "
                f"'{action_status}'"
            )

    for field_name, field_def in data.get("metadata_fields", {}).items():
        set_on = field_def.get("set_on") if isinstance(field_def, dict) else None
        if set_on and set_on not in statuses:
            errors.append(
                f"{lid}: metadata_fields['{field_name}'].set_on references "
                f"unknown status '{set_on}'"
            )

    return errors


def _build_lexicon(data: dict, hook: object | None) -> Lexicon:
    """Convert a validated dict to a frozen Lexicon dataclass."""
    metadata_fields = {}
    for name, field_def in data.get("metadata_fields", {}).items():
        metadata_fields[name] = MetadataField(
            type=field_def["type"],
            set_on=field_def.get("set_on"),
        )

    return Lexicon(
        id=data["id"],
        statuses=tuple(data.get("statuses", ())),
        transitions={k: tuple(v) for k, v in data.get("transitions", {}).items()},
        dir_map=dict(data.get("dir_map", {})),
        actionable_statuses=tuple(data.get("actionable_statuses", ())),
        metadata_fields=metadata_fields,
        derive_hook=hook,
    )


def load_all_lexicons(lexicons_dir: str | Path) -> dict[str, Lexicon]:
    """Load, resolve, validate, and return all lexicons from a directory.

    Raises LexiconLoadError if any validation errors are found.
    All errors are collected and reported in a single batch.
    """
    lexicons_path = Path(lexicons_dir)
    if not lexicons_path.is_dir():
        raise LexiconLoadError([f"lexicons_dir does not exist: {lexicons_dir}"])

    file_map = _discover_lexicon_files(lexicons_path)
    if not file_map:
        raise LexiconLoadError([f"no lexicon files found in {lexicons_dir}"])

    raw: dict[str, dict] = {}
    parse_errors: list[str] = []
    for lid, path in file_map.items():
        try:
            with open(path) as f:
                raw[lid] = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            parse_errors.append(f"{lid}: failed to read {path}: {exc}")

    if parse_errors:
        raise LexiconLoadError(parse_errors)

    all_errors: list[str] = []

    # Resolve inheritance order first — catches circular extends chains
    # before depth check (so circulars report as cycles, not depth violations)
    order = _resolve_inheritance_order(raw)

    all_errors.extend(_check_inheritance_depth(raw))

    resolved: dict[str, dict] = {}
    for lid in order:
        resolved[lid] = _resolve_single(lid, raw, resolved)

    for lid, data in resolved.items():
        all_errors.extend(_validate_lexicon(lid, data))

    hook_map: dict[str, object | None] = {}
    for lid, data in resolved.items():
        hook_path = data.get("derive_hook")
        if hook_path:
            try:
                hook_map[lid] = _import_hook(hook_path)
            except (ImportError, AttributeError) as exc:
                all_errors.append(f"{lid}: cannot import derive_hook '{hook_path}': {exc}")
        else:
            hook_map[lid] = None

    if all_errors:
        raise LexiconLoadError(all_errors)

    result: dict[str, Lexicon] = {}
    for lid, data in resolved.items():
        result[lid] = _build_lexicon(data, hook_map.get(lid))

    return result


def load_lexicon(lexicon_id: str, lexicons_dir: str | Path) -> Lexicon:
    """Load a single lexicon by ID. Convenience wrapper around load_all_lexicons."""
    all_lexicons = load_all_lexicons(lexicons_dir)
    if lexicon_id not in all_lexicons:
        raise LexiconLoadError([f"lexicon '{lexicon_id}' not found"])
    return all_lexicons[lexicon_id]
```

Update `src/pipeline/lexicons/__init__.py` to add loader re-exports:

```python
from pipeline.lexicons.models import (
    Lexicon as Lexicon,
    MetadataField as MetadataField,
)
from pipeline.lexicons.loader import (
    load_all_lexicons as load_all_lexicons,
    load_lexicon as load_lexicon,
    LexiconLoadError as LexiconLoadError,
)
```

**Verification:**

```bash
cd /Users/scarndp/dev/Sentinel/qa_registry
python -c "from pipeline.lexicons import load_all_lexicons, LexiconLoadError; print('OK')"
```

Expected: `OK`

**Commit:** `feat: add lexicon loader with inheritance resolution and batch validation`

<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Create QA base lexicon and QAR lexicon JSON files

**Verifies:** None (infrastructure — lexicon JSON data files)

**Files:**
- Create: `pipeline/lexicons/soc/_base.json`
- Create: `pipeline/lexicons/soc/qar.json`

**Implementation:**

These files encode the current hardcoded QA behaviour as configuration. The values come from:
- Statuses: `"pending"`, `"passed"`, `"failed"` (from `src/pipeline/crawler/parser.py:45-48` and `derive_qa_statuses`)
- Directory map: `msoc` → `passed`, `msoc_new` → `pending` (from `src/pipeline/crawler/parser.py:45-48`)
- Transitions: pending can become passed or failed, terminal states have no outgoing transitions
- Actionable: `passed` deliveries are ready for Parquet conversion

`pipeline/lexicons/soc/_base.json`:

```json
{
  "statuses": ["pending", "passed", "failed"],
  "transitions": {
    "pending": ["passed", "failed"],
    "passed": [],
    "failed": []
  },
  "dir_map": {
    "msoc": "passed",
    "msoc_new": "pending"
  },
  "actionable_statuses": ["passed"]
}
```

`pipeline/lexicons/soc/qar.json`:

```json
{
  "extends": "soc._base",
  "metadata_fields": {
    "passed_at": {
      "type": "datetime",
      "set_on": "passed"
    }
  }
}
```

Note: `derive_hook` is intentionally omitted here. Phase 6 will add `"derive_hook": "pipeline.lexicons.soc.qa:derive"` to this file after the hook module is created. This avoids import failures during Phases 2-5 when the hook module doesn't exist yet.

**Verification:**

```bash
python -c "import json; json.load(open('pipeline/lexicons/soc/_base.json')); json.load(open('pipeline/lexicons/soc/qar.json')); print('Valid JSON')"
```

Expected: `Valid JSON`

**Commit:** `feat: add QA base and QAR lexicon JSON definitions`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Create test fixtures directory for lexicon tests

**Verifies:** None (infrastructure — test fixtures)

**Files:**
- Create: `tests/lexicons/__init__.py`
- Create: `tests/lexicons/conftest.py`

**Implementation:**

Create the test directory and conftest with factory fixtures. Tests use `make_lexicon_file` with inline dicts to build whatever lexicon layout they need — no separate fixture JSON files needed.

`tests/lexicons/__init__.py`: empty file

`tests/lexicons/conftest.py`:

```python
import json
import shutil
from pathlib import Path

import pytest

@pytest.fixture
def lexicons_dir(tmp_path):
    """Create a temp lexicons directory and return its path.

    Tests copy fixture files into subdirectories of this path to
    build whatever lexicon layout they need.
    """
    return tmp_path / "lexicons"


@pytest.fixture
def make_lexicon_file(lexicons_dir):
    """Factory fixture: write a lexicon JSON file into the temp lexicons dir.

    Usage:
        make_lexicon_file("soc/_base.json", {"statuses": ["pending", "passed"]})
    """
    def _make(relative_path: str, data: dict) -> Path:
        file_path = lexicons_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(data, f)
        return file_path
    return _make
```

**Verification:**

```bash
python -c "from tests.lexicons.conftest import *; print('conftest imports OK')" 2>/dev/null || echo "verify manually"
```

**Commit:** `test: add lexicon test directory and conftest with factory fixtures`

<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->

<!-- START_SUBCOMPONENT_C (tasks 5-6) -->
<!-- START_TASK_5 -->
### Task 5: Write lexicon loader tests

**Verifies:** lexicon-system.AC1.1, lexicon-system.AC1.2, lexicon-system.AC1.3, lexicon-system.AC1.4, lexicon-system.AC1.5, lexicon-system.AC1.6, lexicon-system.AC1.7, lexicon-system.AC1.8, lexicon-system.AC1.9

**Files:**
- Create: `tests/lexicons/test_loader.py`

**Implementation:**

Tests should follow the class-based structure from `tests/crawler/test_parser.py` — classes grouped by AC, docstrings referencing `lexicon-system.AC1.N`, plain pytest assertions.

Use the `make_lexicon_file` factory fixture from `tests/lexicons/conftest.py` to build lexicon layouts in `tmp_path` for each test. This avoids coupling to the real `pipeline/lexicons/` files (which reference a hook module that doesn't exist yet).

**Testing:**

Tests must verify each AC listed above:

- **lexicon-system.AC1.1:** Load a single valid lexicon (no extends). Assert result is a `Lexicon` instance, is frozen (try `setattr` raises `FrozenInstanceError`), all fields populated correctly from JSON, tuples for `statuses`/`transitions` values/`actionable_statuses`.
- **lexicon-system.AC1.2:** Create base + child lexicons where child has `extends` pointing to base. Assert child inherits all base fields (statuses, transitions, dir_map, actionable_statuses).
- **lexicon-system.AC1.3:** Create base + child where child overrides `actionable_statuses` and adds a `metadata_fields` entry. Assert child has overridden field AND still has base's `statuses`, `transitions`, `dir_map`.
- **lexicon-system.AC1.4:** Create two lexicons with circular extends (A extends B, B extends A). Assert `LexiconLoadError` raised, error message mentions circular/cycle.
- **lexicon-system.AC1.5:** Create lexicon with transition referencing non-existent status. Assert `LexiconLoadError`, error message mentions the bad status.
- **lexicon-system.AC1.6:** Create lexicon with dir_map value not in statuses. Assert `LexiconLoadError`, error message mentions the bad dir_map reference.
- **lexicon-system.AC1.7:** Create lexicon with metadata_fields set_on value not in statuses. Assert `LexiconLoadError`, error message mentions the bad set_on reference.
- **lexicon-system.AC1.8:** Create lexicon with derive_hook pointing to non-importable module. Assert `LexiconLoadError`, error message mentions the bad hook path.
- **lexicon-system.AC1.9:** Create lexicon with MULTIPLE errors (bad transition ref + bad dir_map ref + bad actionable ref + bad set_on ref). Assert `LexiconLoadError` with `len(exc.errors) >= 4` — all errors collected in one batch.

Additionally, test the `load_lexicon()` convenience function:
- **load_lexicon success:** Create a valid lexicon, call `load_lexicon("soc._base", lexicons_dir)`. Assert returns the correct `Lexicon` instance.
- **load_lexicon not found:** Call `load_lexicon("nonexistent", lexicons_dir)` with a valid lexicons dir. Assert raises `LexiconLoadError` with message mentioning "not found".

Follow project testing patterns: use `make_lexicon_file` fixture to create JSON in `tmp_path`, call `load_all_lexicons(lexicons_dir)`, assert results or catch `LexiconLoadError`. No mocking needed — these are pure function tests against real temp files.

**Verification:**

```bash
uv run pytest tests/lexicons/test_loader.py -v
```

Expected: All tests pass.

**Commit:** `test: add lexicon loader tests covering AC1.1-AC1.9`

<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Run full test suite, verify no regressions

**Verifies:** None (regression check)

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: All existing tests pass. New lexicon tests pass. Zero failures.

If any existing tests fail, investigate — Phase 1 should not affect existing code. The new `src/pipeline/lexicons/` package is additive only.

**Commit:** No commit needed if all tests pass. If fixes were required, commit with message: `fix: resolve test regression from lexicon package addition`

<!-- END_TASK_6 -->
<!-- END_SUBCOMPONENT_C -->
