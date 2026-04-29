# GH19 Phase 1 — Protocol Definitions

**Goal:** Define `HttpModuleProtocol`, `ConvertOneFnProtocol`, and `ConsumerFactoryProtocol` in a new module so later phases can annotate dependency-injected callable parameters.

**Architecture:** A single new file `src/pipeline/converter/protocols.py` (Functional Core — types only, no behaviour). Protocols use structural subtyping (`typing.Protocol`) so existing test fakes and the production module references continue to satisfy them without inheritance changes.

**Tech Stack:** Python stdlib (`typing.Protocol`, `typing.TYPE_CHECKING`).

**Scope:** 1 of 5 phases (#1 of design phases 1-5).

**Codebase verified:** 2026-04-29

- ✓ `src/pipeline/converter/http.py` exposes `get_delivery(api_url: str, delivery_id: str) -> dict`, `patch_delivery(api_url: str, delivery_id: str, updates: dict) -> dict`, `list_unconverted(api_url: str, after: str = "", limit: int = 200) -> list[dict]`, `emit_event(api_url: str, event_type: str, delivery_id: str, payload: dict) -> dict`, plus exception classes `RegistryUnreachableError` and `RegistryClientError`.
- ✓ `src/pipeline/converter/engine.py:32-43` defines `convert_one(delivery_id, api_url, *, converter_version, chunk_size, compression, dp_id_exclusions=None, log_dir=None, http_module=converter_http, convert_fn=convert_sas_to_parquet) -> ConversionResult`.
- ✓ `src/pipeline/events/consumer.py:28-32` defines `EventConsumer.__init__(self, api_url: str, on_event: Callable[[dict], Awaitable[None]]) -> None`.
- ✓ `ConversionResult` is a frozen dataclass at `src/pipeline/converter/engine.py:14-18` — already importable for return annotations.
- ✓ `src/pipeline/converter/CLAUDE.md` documents the test-seam contract: "The engine accepts `chunk_iter_factory` and `convert_fn` parameters as test seams — production callers never pass them."
- ✓ The `converter` package currently has no `protocols.py`. Verified via `ls src/pipeline/converter/`.
- ✓ Boundary: the `converter` package may import from `pipeline.events.consumer` (daemon already does at `daemon.py:60`). Therefore `ConsumerFactoryProtocol` can directly reference `EventConsumer` from `pipeline.events.consumer` at type-check time.

---

## Acceptance Criteria Coverage

This phase implements:

### GH19.AC7: Protocol definitions are stable and reusable

- **GH19.AC7.1 Success:** A `ConverterProtocols` module (or equivalent location) defines `HttpModuleProtocol` covering `get_delivery`, `patch_delivery`, `emit_event`, `list_unconverted`.
- **GH19.AC7.2 Success:** `ConvertOneFnProtocol` covers the `convert_one` signature.
- **GH19.AC7.3 Success:** `ConsumerFactoryProtocol` covers the `EventConsumer` constructor signature used in `DaemonRunner`.
- **GH19.AC7.4 Success:** Tests that inject fakes for these seams continue to pass (structural subtyping via Protocol means no changes to fake implementations).

### GH19.AC8 (partial — covered by every phase)

- **GH19.AC8.1 Success:** `uv run pytest` passes at every phase boundary.
- **GH19.AC8.2 Success:** No existing test is modified to accommodate annotation changes.

---

<!-- START_TASK_1 -->
### Task 1: Create `protocols.py` with the three Protocol types

**Verifies:** GH19.AC7.1, GH19.AC7.2, GH19.AC7.3

**Files:**
- Create: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/protocols.py`

**Implementation:**

Create the file with the following exact contents. The protocols match real signatures verified above.

```python
# pattern: Functional Core
"""Structural Protocol types for converter dependency-injected callables.

These define the shape of test seams (`http_module`, `convert_one_fn`,
`consumer_factory`) used by the engine, CLI, and daemon. Production code
satisfies them implicitly via duck typing; tests can inject fakes that match
the shape without inheriting from any concrete class.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pipeline.converter.engine import ConversionResult
    from pipeline.events.consumer import EventConsumer


class HttpModuleProtocol(Protocol):
    """Shape of `pipeline.converter.http` as consumed by engine + cli."""

    def get_delivery(self, api_url: str, delivery_id: str) -> dict: ...

    def patch_delivery(
        self, api_url: str, delivery_id: str, updates: dict
    ) -> dict: ...

    def list_unconverted(
        self, api_url: str, after: str = "", limit: int = 200
    ) -> list[dict]: ...

    def emit_event(
        self, api_url: str, event_type: str, delivery_id: str, payload: dict
    ) -> dict: ...


class ConvertOneFnProtocol(Protocol):
    """Shape of `engine.convert_one` for callers that inject it."""

    def __call__(
        self,
        delivery_id: str,
        api_url: str,
        *,
        converter_version: str,
        chunk_size: int,
        compression: str,
        dp_id_exclusions: set[str] | None = ...,
        log_dir: str | None = ...,
    ) -> ConversionResult: ...


class ConsumerFactoryProtocol(Protocol):
    """Shape of `EventConsumer.__init__` for daemon dependency injection."""

    def __call__(
        self,
        api_url: str,
        on_event: object,
    ) -> EventConsumer: ...
```

Notes for the implementor:

- `from __future__ import annotations` is used here (and only here) because this file's job is to declare type aliases — every annotation is evaluated at type-check time only. This is the one file in the codebase where the broad form is appropriate.
- `EventConsumer` and `ConversionResult` are imported under `TYPE_CHECKING` because importing them at module load time would create import cycles: `engine.py` will import `protocols.py` (Phase 3), and `engine.py` defines `ConversionResult`.
- `on_event` in `ConsumerFactoryProtocol.__call__` is typed as `object` (not `Callable[[dict], Awaitable[None]]`) because Protocol-style structural matching with parameterised callable annotations triggers stricter mypy checks than the daemon's actual usage requires. The daemon constructs `EventConsumer(api_url, self._on_event)` directly — `on_event`'s real signature is enforced by `EventConsumer.__init__` itself in Phase 5. Using `object` here documents "any callable shaped value passes" at the Protocol boundary and keeps mypy happy.
- The Protocols use `__call__` for `ConvertOneFnProtocol` and `ConsumerFactoryProtocol` because they are typed as callables (functions/classes), not modules. `HttpModuleProtocol` uses method definitions because `pipeline.converter.http` is a module — modules have attributes accessed by name, which structural typing matches via method protocols. The `self` parameter in `HttpModuleProtocol` methods is ignored by structural matching against a module (modules don't have `self`); this is the standard idiom for typing module-shaped objects in Python.

**Verification:**

Run from the repo root:

```bash
uv run python -c "from pipeline.converter.protocols import HttpModuleProtocol, ConvertOneFnProtocol, ConsumerFactoryProtocol; print('ok')"
```

Expected: prints `ok` with no traceback.

```bash
uv run pytest
```

Expected: all existing tests pass with no failures, no errors. (Phase 1 adds no behaviour, only types.)

**Commit:**

```bash
git add src/pipeline/converter/protocols.py
git commit -m "feat(converter): add Protocol types for DI seams (#19)"
```
<!-- END_TASK_1 -->

---

## Phase Done When

- `src/pipeline/converter/protocols.py` exists and contains the three Protocols.
- The verification import succeeds.
- `uv run pytest` exits 0.
- No other file in the repo is modified by this phase.

## Out of Scope

- Wiring the Protocols into `engine.py`, `cli.py`, or `daemon.py` annotations — that happens in Phase 3.
- Any registry_api, crawler, or lexicons changes — those are Phases 2, 4.
- Any mypy config (issue #17).
