# GH19 Phase 5 — config, auth_cli, and events Annotations

**Goal:** Complete annotations for the remaining three files: `src/pipeline/config.py` (`__getattr__`), `src/pipeline/auth_cli.py` (`main`), and `src/pipeline/events/consumer.py` (`__init__.on_event`, `_session.websocket`, `_buffer_ws.websocket`).

**Architecture:** Final mechanical pass. Resolves the websockets type for the `websocket` parameter — the `websockets` library exposes `ClientConnection` at `websockets.asyncio.client.ClientConnection` (the same import used at `consumer.py:9` for `connect`).

**Tech Stack:** Python stdlib + `websockets` library.

**Scope:** 5 of 5 phases.

**Codebase verified:** 2026-04-29 — exact lines confirmed.

---

## Acceptance Criteria Coverage

### GH19.AC5: config and auth_cli annotations complete

- **GH19.AC5.1 Success:** `config.__getattr__` annotated as `(name: str) -> PipelineConfig`.
- **GH19.AC5.2 Success:** `auth_cli.main` return annotation is `None`.

### GH19.AC6: events consumer annotations complete

- **GH19.AC6.1 Success:** `EventConsumer.__init__` `on_event` parameter annotated as `Callable[[dict], Awaitable[None]]`.
- **GH19.AC6.2 Success:** `EventConsumer._session` `websocket` parameter annotated as `websockets.asyncio.client.ClientConnection` (or the correct websockets type).
- **GH19.AC6.3 Success:** `EventConsumer._buffer_ws` `websocket` parameter has same annotation.
- **GH19.AC6.4 Failure:** Bare `websocket` without annotation causes mypy to flag a missing annotation error.

### GH19.AC8 (final)

- **GH19.AC8.1 Success:** `uv run pytest` passes at every phase boundary.
- **GH19.AC8.2 Success:** No existing test is modified to accommodate annotation changes.

---

<!-- START_TASK_1 -->
### Task 1: Annotate `config.__getattr__`

**Verifies:** GH19.AC5.1

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/config.py:103-112`

**Implementation:**

**`config.py:103-112`.** Current:

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

Replace with:

```python
_settings: "PipelineConfig | None" = None


def __getattr__(name: str) -> "PipelineConfig":
    global _settings
    if name == "settings":
        if _settings is None:
            _settings = load_config()
        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

The forward-ref string is unnecessary here — `PipelineConfig` is defined at `config.py:19`, before `__getattr__`. Use the bare name:

```python
_settings: PipelineConfig | None = None


def __getattr__(name: str) -> PipelineConfig:
    global _settings
    if name == "settings":
        if _settings is None:
            _settings = load_config()
        return _settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

Note: the design's AC5.1 says the return type is `PipelineConfig`, but `__getattr__` raises `AttributeError` on any other name — semantically the function returns `PipelineConfig` only when `name == "settings"`. mypy's strict mode tolerates this because `AttributeError` is an exception, not an alternative return path. The annotation is faithful.

**Verification:**

```bash
uv run pytest tests/test_config.py 2>/dev/null || uv run pytest tests/ -k config
```

Expected: all config tests pass.

```bash
uv run python -c "from pipeline.config import settings; print(type(settings).__name__)"
```

Expected: prints `PipelineConfig`.

**Commit:**

```bash
git add src/pipeline/config.py
git commit -m "feat(config): annotate module __getattr__ return as PipelineConfig (#19)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Annotate `auth_cli.main`

**Verifies:** GH19.AC5.2

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/auth_cli.py:156`

**Implementation:**

**`auth_cli.py:156`.** Current:

```python
def main():
    """Entry point for the registry-auth CLI."""
```

Replace with:

```python
def main() -> None:
    """Entry point for the registry-auth CLI."""
```

`main()` ends with `sys.exit(args.func(args))` (line 190), which never returns — but `NoReturn` would be more precise. The design's AC5.2 says `None` explicitly; honour that. (`NoReturn` may be revisited in #17 if mypy strict insists.)

**Verification:**

```bash
uv run pytest tests/test_auth_cli.py 2>/dev/null || uv run pytest tests/ -k auth_cli
```

Expected: all auth_cli tests pass.

```bash
uv run python -c "from pipeline.auth_cli import main; import inspect; print(inspect.signature(main).return_annotation)"
```

Expected: prints `<class 'NoneType'>` or `None`.

**Commit:**

```bash
git add src/pipeline/auth_cli.py
git commit -m "feat(auth_cli): annotate main return as None (#19)"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Annotate `events/consumer.py` websocket parameters

**Verifies:** GH19.AC6.1, GH19.AC6.2, GH19.AC6.3

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/events/consumer.py:1-12` (imports)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/events/consumer.py:56` (`_session`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/events/consumer.py:97` (`_buffer_ws`)

**Implementation:**

**Edit 1 — `consumer.py:1-12`.** Current:

```python
# pattern: Imperative Shell

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)
```

Replace with:

```python
# pattern: Imperative Shell

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)
```

(Verified: `websockets.asyncio.client` exposes both `connect` and `ClientConnection`. The `connect()` async-iterator pattern at line 48 yields `ClientConnection` instances — confirmed by the websockets library's public API.)

**Edit 2 — `consumer.py:28-32`.** **Already correctly annotated** at lines 28-32:

```python
    def __init__(
        self,
        api_url: str,
        on_event: Callable[[dict], Awaitable[None]],
    ) -> None:
```

AC6.1 is **already satisfied**. No edit needed for `__init__`.

**Edit 3 — `consumer.py:56`.** Current:

```python
    async def _session(self, websocket) -> None:
```

Replace with:

```python
    async def _session(self, websocket: ClientConnection) -> None:
```

**Edit 4 — `consumer.py:97`.** Current:

```python
    async def _buffer_ws(self, websocket) -> None:
```

Replace with:

```python
    async def _buffer_ws(self, websocket: ClientConnection) -> None:
```

**Verification:**

```bash
uv run pytest tests/events/ 2>/dev/null || uv run pytest tests/ -k consumer
```

Expected: all consumer tests pass.

```bash
uv run python -c "from pipeline.events.consumer import EventConsumer; import inspect; print(inspect.signature(EventConsumer._session).parameters['websocket'].annotation); print(inspect.signature(EventConsumer._buffer_ws).parameters['websocket'].annotation)"
```

Expected: both print `<class 'websockets.asyncio.client.ClientConnection'>`.

**Commit:**

```bash
git add src/pipeline/events/consumer.py
git commit -m "feat(events): annotate consumer websocket parameters as ClientConnection (#19)"
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Final regression check across the full codebase

**Verifies:** GH19.AC8.1, GH19.AC8.2

**Files:**
- (no edits — verification only)

**Implementation:**

After Phases 1-5 are all merged (or in the same branch), run the full test suite and confirm no test files have been modified in this issue's branch.

**Verification:**

```bash
uv run pytest
```

Expected: all tests pass with zero failures, zero errors.

```bash
git diff --stat HEAD~$(git rev-list --count HEAD ^origin/main) -- tests/
```

Expected: zero lines changed in `tests/`. (AC8.2 — annotations must fit existing call sites, not the reverse.)

```bash
git diff --stat HEAD~$(git rev-list --count HEAD ^origin/main) -- src/
```

Expected: changes confined to the 15 files in Phases 1-5 plus the new `src/pipeline/converter/protocols.py`.

**Commit (no commit — this task is verification only):**

If everything passes, no commit is created here. The Phases 1-5 commits are the final state.

If any test fails, file a regression task and fix the underlying annotation that broke runtime behaviour. Per the design's "No behaviour changes" guarantee, no annotation should change runtime semantics; if a test fails, the fix is in the annotation, not the test.
<!-- END_TASK_4 -->

---

## Phase Done When

- `src/pipeline/config.py` has `__getattr__` annotated.
- `src/pipeline/auth_cli.py` has `main` annotated.
- `src/pipeline/events/consumer.py` has both `_session` and `_buffer_ws` `websocket` parameters annotated.
- `uv run pytest` exits 0 across the full suite.
- `git diff --stat tests/` shows zero changes for this issue's branch.

## Out of Scope

- mypy invocation/configuration (issue #17 — strictly downstream of this issue per the DAG).
- Any test changes (AC8.2 forbids them).
- Frozen dataclass migration (issue #20 — strictly downstream).
