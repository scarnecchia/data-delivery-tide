# GH28 — collections.abc.Callable Implementation Plan

**Goal:** Replace `typing.Callable` with `collections.abc.Callable` in `src/pipeline/lexicons/models.py` and parameterise `derive_hook` with the full type signature.

**Architecture:** Single-file edit to a frozen dataclass module. The `derive_hook` field's signature is upgraded from bare `Callable` to `Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]]`. `ParsedDelivery` is imported behind a `TYPE_CHECKING` guard to preserve the `lexicons` -> `crawler` package boundary (the `lexicons` package must not import from `crawler` at runtime).

**Tech Stack:** Python stdlib (`collections.abc`, `typing.TYPE_CHECKING`).

**Scope:** 1 phase. The entire change in the design plan fits within a single phase.

**Codebase verified:** 2026-04-29

- ✓ `src/pipeline/lexicons/models.py` exists, line 3 reads `from typing import Callable`, line 20 reads `derive_hook: Callable | None = None`.
- ✓ `typing.Callable` is imported in NO other file under `src/` or `tests/` (verified via grep).
- ✓ `ParsedDelivery` is defined at `src/pipeline/crawler/parser.py:9`.
- ✓ `Lexicon` is defined in the same file as the field — no guard needed for the self-reference.
- ✓ The lexicons package boundary doc (`src/pipeline/lexicons/CLAUDE.md`) explicitly states "no imports from registry_api, crawler, or events" — confirms the `TYPE_CHECKING` guard requirement.
- ✓ Hook signature `(deliveries: list[ParsedDelivery], lexicon: Lexicon) -> list[ParsedDelivery]` is documented as an invariant in `src/pipeline/lexicons/CLAUDE.md` — matches design.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH28.AC1: Import migration

- **GH28.AC1.1 Removed:** `from typing import Callable` is removed from `models.py`
- **GH28.AC1.2 Added:** `from collections.abc import Callable` is present in `models.py`

### GH28.AC2: Parameterised signature

- **GH28.AC2.1 Annotation:** `derive_hook` is typed as `Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]] | None = None`

### GH28.AC3: No regression

- **GH28.AC3.1 Tests pass:** `uv run pytest` passes without modification to any other file.

---

<!-- START_TASK_1 -->
### Task 1: Replace typing.Callable with collections.abc.Callable and parameterise derive_hook

**Verifies:** GH28.AC1.1, GH28.AC1.2, GH28.AC2.1, GH28.AC3.1

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py:1-22` (entire file)

**Implementation:**

Replace the contents of `src/pipeline/lexicons/models.py` with:

```python
# pattern: Functional Core
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.crawler.parser import ParsedDelivery


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
    derive_hook: Callable[[list["ParsedDelivery"], "Lexicon"], list["ParsedDelivery"]] | None = None
    sub_dirs: dict[str, str] = field(default_factory=dict)
```

Notes for the implementor:

- `ParsedDelivery` is referenced as a forward-ref string (`"ParsedDelivery"`) because it is only imported under `TYPE_CHECKING`. At runtime, the dataclass annotation is stored as a string and never evaluated, so the `crawler` package is not imported. This preserves the `lexicons` -> `crawler` boundary documented in `src/pipeline/lexicons/CLAUDE.md`.
- `Lexicon` is defined in the same module, but it appears in the annotation *before* its class statement is fully defined (annotations are evaluated at class-body time for non-frozen access; for frozen dataclass field defaults the annotation is a string anyway when forward-quoted). Quoting `"Lexicon"` is the safe, idiomatic choice and consistent with the `ParsedDelivery` quoting.
- Do NOT add `from __future__ import annotations`. The design plan explicitly rejects it: "too broad for a single field".
- Do NOT use `Callable[..., Any]`. The design plan explicitly rejects it: "defeats the purpose of parameterising the signature".
- `collections.abc.Callable` and `typing.Callable` are runtime-identical on Python 3.10+. There is no behavioural change — only a static-typing improvement.

**Verification:**

Run from the repo root:

```bash
uv run pytest
```

Expected: all existing tests pass with no failures, no errors, no new warnings related to `models.py`.

Additionally, sanity-check the import surface:

```bash
grep -rn "from typing import.*Callable\|typing\.Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/
```

Expected: zero matches.

```bash
grep -n "from collections.abc import Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py
```

Expected: one match on line 3.

**Commit:**

```bash
git add src/pipeline/lexicons/models.py
git commit -m "refactor(lexicons): use collections.abc.Callable and parameterise derive_hook (#28)"
```
<!-- END_TASK_1 -->

---

## Phase Done When

- All four acceptance criteria pass: import removed, import added, annotation parameterised, full test suite green.
- `uv run pytest` exits 0.
- No other source file under `src/` or `tests/` is touched.
- `grep` checks above produce the expected counts.

## Out of Scope

- Type-annotation passes anywhere else in the codebase (see issue #19, which is the broader annotation effort and treats #28 as a soft prerequisite per `docs/project/DAG.md`).
- Mypy configuration (issue #17).
- Any change to `derive_hook` runtime behaviour, the lexicon loader, or the QA hook in `soc/qa.py`.
