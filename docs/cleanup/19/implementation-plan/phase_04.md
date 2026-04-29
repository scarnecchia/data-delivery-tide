# GH19 Phase 4 — crawler and lexicons Annotations

**Goal:** Complete annotations for `crawler/main.py` (the `walk_roots`, `crawl`, `main`, `inventory_files` signatures) and the lexicons `models.py` + `loader.py`.

**Architecture:** Mechanical annotation pass. Adds `TYPE_CHECKING` guard in `lexicons/models.py` for `ParsedDelivery` cross-package reference (issue #28's identical change is absorbed here per the DAG soft dep).

**Tech Stack:** Python stdlib (`logging`, `typing`, `collections.abc`).

**Scope:** 4 of 5 phases.

**Codebase verified:** 2026-04-29 — exact lines confirmed, including current state of `lexicons/models.py:3` (`from typing import Callable`) and `walk_roots` signature.

---

## Acceptance Criteria Coverage

### GH19.AC3: crawler module annotations complete

- **GH19.AC3.1 Success:** `crawler.main.walk_roots` fully annotated; `scan_roots` typed as `list[ScanRoot]`; return is `list[tuple[str, str]]`.
- **GH19.AC3.2 Success:** `crawler.main.crawl` `config` parameter typed as `PipelineConfig`; `logger` typed as `logging.Logger`; return is `int`.
- **GH19.AC3.3 Success:** `crawler.main.main` return annotation is `None`.

### GH19.AC4: lexicons module annotations complete

- **GH19.AC4.1 Success:** `lexicons.models.Lexicon.derive_hook` typed as `Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]] | None`.
- **GH19.AC4.2 Success:** `lexicons.loader._import_hook` return annotation is `Callable[..., Any]` or a Protocol matching the derive_hook signature.
- **GH19.AC4.3 Failure:** Using bare `Callable` without parameters on `derive_hook` field causes mypy to emit an error under strict mode.

### GH19.AC8 (running)

---

<!-- START_TASK_1 -->
### Task 1: Annotate `crawler/main.py`

**Verifies:** GH19.AC3.1, GH19.AC3.2, GH19.AC3.3

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/crawler/main.py:1-13` (imports)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/crawler/main.py:34-39` (`walk_roots`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/crawler/main.py:111` (`crawl`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/crawler/main.py:291` (`main`)

**Implementation:**

**Edit 1 — `crawler/main.py:1-13`.** Current:

```python
# pattern: Imperative Shell
import json
import logging
import os
import sys
from datetime import datetime, timezone

from pipeline.config import settings
from pipeline.json_logging import get_logger
from pipeline.crawler.parser import parse_path, derive_statuses, ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import compute_fingerprint, FileEntry
from pipeline.crawler.manifest import build_manifest, build_error_manifest
from pipeline.crawler.http import post_delivery, RegistryUnreachableError, RegistryClientError
from pipeline.lexicons import load_all_lexicons
```

Wait — re-check the actual top of the file. The actual file (per Read output earlier) is:

```python
# pattern: Imperative Shell
import json
import os
import sys
from datetime import datetime, timezone

from pipeline.config import settings
from pipeline.json_logging import get_logger
from pipeline.crawler.parser import parse_path, derive_statuses, ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import compute_fingerprint, FileEntry
from pipeline.crawler.manifest import build_manifest, build_error_manifest
from pipeline.crawler.http import post_delivery, RegistryUnreachableError, RegistryClientError
from pipeline.lexicons import load_all_lexicons
```

Add `import logging` and `from pipeline.config import PipelineConfig, ScanRoot` so we can annotate `crawl`'s `config: PipelineConfig` and `walk_roots`'s `scan_roots: list[ScanRoot]`. Replace with:

```python
# pattern: Imperative Shell
import json
import logging
import os
import sys
from datetime import datetime, timezone

from pipeline.config import PipelineConfig, ScanRoot, settings
from pipeline.json_logging import get_logger
from pipeline.crawler.parser import parse_path, derive_statuses, ParsedDelivery, ParseError
from pipeline.crawler.fingerprint import compute_fingerprint, FileEntry
from pipeline.crawler.manifest import build_manifest, build_error_manifest
from pipeline.crawler.http import post_delivery, RegistryUnreachableError, RegistryClientError
from pipeline.lexicons import load_all_lexicons
```

(Verified at `config.py:11` and `config.py:19` that `ScanRoot` and `PipelineConfig` are top-level dataclasses, importable.)

**Edit 2 — `crawler/main.py:34-39`.** Current:

```python
def walk_roots(
    scan_roots: list,
    valid_terminals: set[str],
    exclusions: set[str] | None = None,
    logger=None,
) -> list[tuple[str, str]]:
```

Replace with:

```python
def walk_roots(
    scan_roots: list[ScanRoot],
    valid_terminals: set[str],
    exclusions: set[str] | None = None,
    logger: logging.Logger | None = None,
) -> list[tuple[str, str]]:
```

**Edit 3 — `crawler/main.py:111`.** Current:

```python
def crawl(config, logger, token: str | None = None) -> int:
```

Replace with:

```python
def crawl(config: PipelineConfig, logger: logging.Logger, token: str | None = None) -> int:
```

**Edit 4 — `crawler/main.py:291`.** Current:

```python
def main():
```

Replace with:

```python
def main() -> None:
```

**Edit 5 — `crawler/main.py:16` (`inventory_files`).** Current already has `def inventory_files(source_path: str) -> list[FileEntry]:` — verified, no change needed.

**Verification:**

```bash
uv run pytest tests/crawler/
```

Expected: all crawler tests pass.

```bash
uv run python -c "from pipeline.crawler.main import walk_roots, crawl, main; import inspect; print(inspect.signature(walk_roots).parameters['scan_roots'].annotation); print(inspect.signature(crawl).parameters['config'].annotation); print(inspect.signature(main).return_annotation)"
```

Expected: prints `list[pipeline.config.ScanRoot]`, `<class 'pipeline.config.PipelineConfig'>`, `<class 'NoneType'>` (or `None`).

**Commit:**

```bash
git add src/pipeline/crawler/main.py
git commit -m "feat(crawler): annotate walk_roots, crawl, and main signatures (#19)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Annotate `lexicons/models.py` derive_hook field (absorbs issue #28)

**Verifies:** GH19.AC4.1, GH19.AC4.3

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py` (entire file, 22 lines)

**Implementation:**

This task is identical to GH28's Phase 1. **If issue #28 has already been merged**, verify and skip this edit (re-run pytest only). Otherwise apply the change. Verification command at the end of this task confirms which path applies.

Verify current state first:

```bash
grep -n "from typing import Callable\|from collections.abc import Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py
```

If output shows `from typing import Callable`, GH28 has not landed and this task must apply the edit. If it shows `from collections.abc import Callable`, GH28 has landed and the import-line edit can be skipped — but the parameterised annotation on `derive_hook` field still needs verification.

**Full replacement of `src/pipeline/lexicons/models.py`:**

```python
# pattern: Functional Core
from collections.abc import Callable
from dataclasses import dataclass, field
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

This is the identical content to GH28's plan (`docs/project/28/implementation-plan/phase_01.md`). If GH28 was merged first, the file should already match — in that case this task is a no-op.

**Verification:**

```bash
uv run pytest
```

Expected: all tests pass.

```bash
grep -n "from collections.abc import Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py
grep -c "from typing import Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py
```

Expected: first command returns one match; second returns `0`.

**Commit (only if changes were applied):**

If GH28 had already landed and the file matched: skip this commit.
Otherwise:

```bash
git add src/pipeline/lexicons/models.py
git commit -m "feat(lexicons): use collections.abc.Callable and parameterise derive_hook (#19, absorbs #28)"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Annotate `lexicons/loader._import_hook`

**Verifies:** GH19.AC4.2

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/loader.py:1-10` (imports)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/loader.py:113-117` (`_import_hook`)

**Implementation:**

**Edit 1 — `loader.py:1-9`.** Current:

```python
# pattern: Functional Core
from __future__ import annotations

import importlib
import json
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from pipeline.lexicons.models import Lexicon, MetadataField
```

Replace with:

```python
# pattern: Functional Core
from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

from pipeline.lexicons.models import Lexicon, MetadataField
```

**Edit 2 — `loader.py:113-117`.** Current:

```python
def _import_hook(hook_path: str) -> object:
    """Import a hook from a dotted path like 'pipeline.lexicons.soc.qa:derive'."""
    module_path, _, attr_name = hook_path.rpartition(":")
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)
```

Replace with:

```python
def _import_hook(hook_path: str) -> Callable[..., Any]:
    """Import a hook from a dotted path like 'pipeline.lexicons.soc.qa:derive'.

    Returns a callable matching the `derive_hook` shape:
    `(list[ParsedDelivery], Lexicon) -> list[ParsedDelivery]`. We type as
    `Callable[..., Any]` here (per design #19 AC4.2) because we cannot import
    `ParsedDelivery` at runtime in this module without violating the
    `lexicons` -> `crawler` boundary, and `getattr` returns `Any` from
    mypy's perspective. The actual hook signature is enforced by `Lexicon.derive_hook`
    when the hook is stored on the dataclass.
    """
    module_path, _, attr_name = hook_path.rpartition(":")
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)
```

`Callable[..., Any]` is the design's preferred type. A more precise Protocol matching `(list[ParsedDelivery], Lexicon) -> list[ParsedDelivery]` would require importing `ParsedDelivery` (boundary violation) or another `TYPE_CHECKING` block. The latter is acceptable but adds complexity for marginal benefit — the dataclass annotation in `models.py` already captures the precise shape.

**Note on `_build_lexicon`:** Verified at `loader.py:181`, signature is `def _build_lexicon(data: dict, hook: object | None) -> Lexicon:`. The `hook` parameter type should also be tightened to `Callable[..., Any] | None` for consistency, since this is what `_import_hook` returns. Apply this edit too:

**Edit 3 — `loader.py:181`.** Current:

```python
def _build_lexicon(data: dict, hook: object | None) -> Lexicon:
```

Replace with:

```python
def _build_lexicon(data: dict, hook: Callable[..., Any] | None) -> Lexicon:
```

**Verification:**

```bash
uv run pytest tests/lexicons/
```

Expected: all lexicon tests pass.

```bash
uv run python -c "from pipeline.lexicons.loader import _import_hook; import inspect; print(inspect.signature(_import_hook).return_annotation)"
```

Expected: prints `collections.abc.Callable[..., typing.Any]` or its string form.

**Commit:**

```bash
git add src/pipeline/lexicons/loader.py
git commit -m "feat(lexicons): annotate _import_hook and _build_lexicon hook parameter (#19)"
```
<!-- END_TASK_3 -->

---

## Phase Done When

- `src/pipeline/crawler/main.py` has full annotations on `walk_roots`, `crawl`, `main`, `inventory_files`.
- `src/pipeline/lexicons/models.py` uses `collections.abc.Callable` with the parameterised `derive_hook` annotation under a `TYPE_CHECKING` guard for `ParsedDelivery`.
- `src/pipeline/lexicons/loader.py` has `_import_hook` and `_build_lexicon` annotated.
- `uv run pytest` exits 0.

## Out of Scope

- config, auth_cli, events files (Phase 5).
- mypy strict-mode invocation (issue #17).
