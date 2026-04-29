# GH17 Phase 3 — Manual ruff lint fixes

**Goal:** Resolve every remaining ruff violation that `--fix` cannot handle automatically. After Phase 2, the residual violations are concentrated in: B008 (FastAPI `Depends()` in defaults — suppress idiomatically), E402 (daemon.py late imports — restructure), F841 (unused local — remove or `# noqa`), E701 (multi-statement line — split), SIM105 (try/except/pass — use `contextlib.suppress`), B905 (`zip` without `strict=`), UP028 (`for ... yield` -> `yield from`).

**Architecture:** Each violation handled with the smallest correct fix. B008 is suppressed; the others are real refactors with semantic content. None of these change observable behaviour.

**Tech Stack:** ruff 0.15.6.

**Scope:** 3 of 6 phases.

**Codebase verified:** 2026-04-29 — concrete violations identified by `uv run ruff check src/ tests/` against the Phase-1 rule set:

- ✓ **E402** (4 occurrences) — `src/pipeline/converter/daemon.py:58-61`. Imports below `load_last_seq`/`persist_last_seq` function defs (deferred imports, intentional but unstandard). Need to restructure: move the function defs below the imports.
- ✓ **B008** — once `B` is enabled, FastAPI `Depends()` defaults in route handlers will be flagged. Verified pattern at `routes.py:120` (`filters: DeliveryFilters = Depends()`) and `auth.py:31` (`credentials: ... = Depends(_bearer_scheme)`). Idiomatic FastAPI — suppress with `# noqa: B008`.
- ✓ **F841** (2 occurrences) — unused local variables (`ws`, `pre_restart_delivery`). Verify each is genuinely unused; remove or rename to `_var`.
- ✓ **E701** (1 occurrence) — multi-statement line. Split.
- ✓ **SIM105** (2 occurrences) — `convert.py:179` and `convert.py:184`. The current code uses nested `try/except/pass` to swallow secondary errors during cleanup. Replace with `contextlib.suppress(...)`.
- ✓ **B905** — `convert.py:43` uses `zip(column_names, column_labels)` without `strict=`. The two lists are guaranteed equal length (pyreadstat invariant), but `strict=False` makes that explicit.
- ✓ **UP028** — `cli.py:83-86` has `for delivery in page: yield delivery` — replace with `yield from page`.
- ✓ **F401** — should be zero after Phase 2's auto-fix. If any survive (e.g., load-bearing `# noqa: F401` cases), they're already suppressed.

---

## Acceptance Criteria Coverage

- **GH17.AC3.1 (Manual fixes applied):** `uv run ruff check src/ tests/` exits 0 (zero violations).
- **GH17.AC3.2 (No regressions):** `uv run pytest` exits 0.

---

<!-- START_TASK_1 -->
### Task 1: Suppress B008 on FastAPI `Depends()` defaults

**Verifies:** GH17.AC3.1

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/auth.py:31` — `credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme)`
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:120` — `filters: DeliveryFilters = Depends()`
- Possibly: any other route signature with `Depends()` in defaults that ruff flags.

**Implementation:**

For each B008 violation, append `# noqa: B008` to the line:

**Step 1: List exact B008 hits**

```bash
uv run ruff check src/ tests/ --select B008 --output-format=concise
```

Expected: a list of `path:line:col: B008 ...` entries.

**Step 2: For each line, append `# noqa: B008`**

For example, `auth.py:31`. Current:

```python
def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: DbDep = ...,
) -> TokenInfo:
```

Replace with:

```python
def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
    db: DbDep = ...,
) -> TokenInfo:
```

**Do NOT use a blanket `# ruff: noqa: B008` at file scope.** Per the design, "Do not suppress globally — only on the specific lines where `Depends()` appears in a function signature default." Keeps B008 alive for any non-FastAPI accidental misuse.

**Step 3: Verify**

```bash
uv run ruff check src/ --select B008
```

Expected: zero violations.

**Step 4: Tests**

```bash
uv run pytest tests/registry_api/
```

Expected: zero failures.

**Commit:**

```bash
git add src/pipeline/registry_api/
git commit -m "style: suppress B008 on FastAPI Depends() defaults (#17)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Fix E402 in daemon.py — reorder imports

**Verifies:** GH17.AC3.1

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/daemon.py:1-62`

**Implementation:**

Current `daemon.py` has function definitions (`load_last_seq`, `persist_last_seq`) at lines 11-55, **before** the imports at lines 58-61:

```python
# pattern: Imperative Shell

import asyncio
import json
import os
import signal
import uuid
from pathlib import Path


def load_last_seq(state_path: Path) -> int:
    ...

def persist_last_seq(state_path: Path, seq: int) -> None:
    ...


from pipeline.config import settings
from pipeline.converter.engine import convert_one
from pipeline.events.consumer import EventConsumer
from pipeline.json_logging import get_logger


class DaemonRunner:
    ...
```

This pattern is unusual but intentional: `load_last_seq`/`persist_last_seq` only depend on stdlib, while the rest of the file pulls in heavy first-party imports (config triggers lexicon loading at module init; `EventConsumer` pulls websockets/httpx). The deferred imports keep the helpers lightweight — but ruff E402 flags it as wrong.

**Two options:**

**Option A (preferred):** Move all imports to the top. The "lightweight helpers" justification is real but weak — Python's import system is lazy enough that the cost is paid once per process. Modern Python style strongly prefers top-of-file imports.

**Option B:** Add a per-line `# noqa: E402` to each of the four offending lines. Honest about the deferred-import intent but ugly.

**Pick Option A.** Move the four imports to the top:

```python
# pattern: Imperative Shell

import asyncio
import json
import os
import signal
import uuid
from pathlib import Path

from pipeline.config import settings
from pipeline.converter.engine import convert_one
from pipeline.events.consumer import EventConsumer
from pipeline.json_logging import get_logger


def load_last_seq(state_path: Path) -> int:
    ...


def persist_last_seq(state_path: Path, seq: int) -> None:
    ...


class DaemonRunner:
    ...
```

(Read `daemon.py:1-62` first — preserve the exact function bodies, only move them.)

**Step 1: Make the edit**

Use the `Edit` tool with the `daemon.py` content as `old_string` and the rearranged version as `new_string`.

**Step 2: Verify**

```bash
uv run ruff check src/pipeline/converter/daemon.py
```

Expected: zero E402 violations.

**Step 3: Tests**

```bash
uv run pytest tests/converter/test_daemon.py 2>/dev/null || uv run pytest tests/converter/
```

Expected: zero failures.

**Commit:**

```bash
git add src/pipeline/converter/daemon.py
git commit -m "style: reorder daemon.py imports to top of file (#17)"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Fix SIM105, B905, UP028, E701, F841 substantively

**Verifies:** GH17.AC3.1

**GH23 coordination:** GH23 Phase 1 replaces the `try/except: pass` block with `try/except: logger.debug(...)`, eliminating this SIM105 violation before GH17 executes. Run `uv run ruff check --select SIM105 src/pipeline/converter/convert.py` first — if clean, skip this fix.

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/convert.py:43` (B905)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/convert.py:179-187` (SIM105 ×2)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/cli.py:83-86` (UP028)
- Modify: any line flagged E701 (location identified by `ruff check --select E701`)
- Modify: any line flagged F841 (locations: `ws` and `pre_restart_delivery` — `ruff check --select F841` to confirm files)

**Implementation:**

**Sub-step 3a: B905 in convert.py:43**

Current:

```python
return {name: (label or "") for name, label in zip(column_names, column_labels)}
```

Replace with:

```python
return {name: (label or "") for name, label in zip(column_names, column_labels, strict=False)}
```

`strict=False` is the explicit acknowledgement that the lists are pre-validated as equal length by pyreadstat's API.

**Sub-step 3b: SIM105 in convert.py:179-187**

Current (cleanup block in the `except BaseException:` handler):

```python
    except BaseException:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
```

Replace with:

```python
    except BaseException:
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        raise
```

Add `import contextlib` to the top of the file (verify current imports — `contextlib` is not imported in `convert.py` per Read inspection). Insert after the existing stdlib import block:

Current `convert.py:3-8`:

```python
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
```

Replace with:

```python
import contextlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
```

(ruff's I001 will rearrange to alphabetical anyway; just add the line.)

**Sub-step 3c: UP028 in cli.py:83-86**

Current:

```python
        page = http_module.list_unconverted(api_url, after=cursor, limit=page_size)
        if not page:
            return
        for delivery in page:
            yield delivery
        cursor = page[-1]["delivery_id"]
```

Replace with:

```python
        page = http_module.list_unconverted(api_url, after=cursor, limit=page_size)
        if not page:
            return
        yield from page
        cursor = page[-1]["delivery_id"]
```

Semantically identical. `yield from page` delegates to `iter(page)`; `page` is a `list[dict]`, so iteration order is preserved.

**Sub-step 3d: E701 (multi-statement line)**

Run `uv run ruff check src/ tests/ --select E701 --output-format=concise` to identify the exact location. The fix is mechanical: split the line at the `:`. For example, `if x: y = 1` becomes:

```python
if x:
    y = 1
```

**Sub-step 3e: F841 (unused locals — `ws`, `pre_restart_delivery`)**

Run `uv run ruff check src/ tests/ --select F841 --output-format=concise` to identify the lines.

For each unused local:

1. **If it's a test file**, the variable might be there for documentation/intent (e.g., capturing a fixture's return for clarity). Rename to `_ws` (leading underscore tells linters it's intentionally unused).
2. **If it's source code**, the assignment is dead — remove the assignment entirely.

Surface to the user if either case looks ambiguous. Don't `# noqa: F841` blindly.

**Step 1: Apply each sub-step in order (3a, 3b, 3c, 3d, 3e)**

Each is a small, targeted edit.

**Step 2: Verify all violations cleared**

```bash
uv run ruff check src/ tests/
```

Expected: zero violations of any code. Print should be `All checks passed!`.

**Step 3: Verify tests**

```bash
uv run pytest
```

Expected: zero failures, zero errors.

**Commit:**

```bash
git add src/
git commit -m "style: fix SIM105/B905/UP028/E701/F841 manually (#17)"
```
<!-- END_TASK_3 -->

---

## Phase Done When

- `uv run ruff check src/ tests/` exits 0 with `All checks passed!` (zero violations).
- `uv run ruff format --check src/ tests/` exits 0 (Phase 2 invariant preserved).
- `uv run pytest` exits 0.

## Out of Scope

- Mypy errors — Phases 4-6.
- New violations introduced by future code — out of scope; ruff is the gate going forward.
- Refactoring beyond what each rule code requires (e.g., the daemon.py import reorganisation is the smallest fix that satisfies E402; restructuring the daemon's lazy-import strategy further is not Phase 3's job).

## Notes for the implementor

- The design plan lists `B007` (unused loop variable) but the current codebase has no B007 hits per planning-time `ruff check`. Skipping B007 in this plan as a result. If a B007 surfaces during execution, treat it the same as F841: rename the loop var to `_var`.
- The SIM105 fix in `convert.py` uses `contextlib.suppress(...)` rather than the design-suggested "fix substantively where safe". The substantive fix IS `contextlib.suppress` — the existing `try/except/pass` was already idiomatic, ruff just prefers the new form. No behavioural change.
- `daemon.py` import reorder (Task 2) is the most invasive change. The deferred-import pattern was used to keep the module light; promoting all imports to top costs a one-time import on module load (already happens once `DaemonRunner` is instantiated anyway). Surface to the user if anyone objects on startup-time grounds.
