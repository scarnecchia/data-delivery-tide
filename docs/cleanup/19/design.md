# Issue #19: Add Missing Type Annotations Design

## Summary

This document covers the addition of complete PEP 484 type annotations across all modules in the pipeline codebase. The work is primarily mechanical — reading existing function signatures, inferring types from call sites and docstrings, and writing them down — but several modules require Protocol definitions to correctly annotate dependency-injected callables (test seams). The annotation pass is safe to execute as a standalone effort and can run in parallel with or before issue #17 (mypy strict mode enforcement), since annotations are a prerequisite for mypy to do useful work.

The design is deliberately module-by-module rather than a single bulk commit. Each module group can be reviewed and merged independently, limiting the blast radius of mistakes and making review manageable.

## Definition of Done

- All function signatures across all affected modules have complete parameter and return type annotations.
- No bare `Callable` without parameter/return types remains in any module.
- WebSocket and dependency-injected callable parameters use Protocol types or `Callable[..., T]` with explicit signatures where shape is stable.
- `config.py` `__getattr__` carries correct return annotation.
- `uv run pytest` passes with no regressions after each phase.

## Acceptance Criteria

### type-annotations.AC1: registry_api module annotations complete
- **type-annotations.AC1.1 Success:** All route handler functions in `routes.py` have explicit return type annotations (`DeliveryResponse`, `PaginatedDeliveryResponse`, `list[DeliveryResponse]`, `EventRecord`, `dict[str, str]`).
- **type-annotations.AC1.2 Success:** `db.get_db()` return annotation is `Generator[sqlite3.Connection, None, None]`.
- **type-annotations.AC1.3 Success:** `db.upsert_delivery` return annotation is `dict` (not `None`; the function always returns or raises).
- **type-annotations.AC1.4 Success:** Pydantic validator methods (`check_metadata_size`, `clamp_limit`, `check_offset`) in `models.py` carry full annotations on `cls` and `v` parameters and return types.
- **type-annotations.AC1.5 Success:** `auth.require_role()` return annotation is `Depends` (or more precisely `Any` given FastAPI's opaque return; document the decision).
- **type-annotations.AC1.6 Success:** `auth._check_role()` return annotation is `TokenInfo`.
- **type-annotations.AC1.7 Success:** `main.websocket_events` `token` parameter annotated as `str | None`.
- **type-annotations.AC1.8 Success:** `main.websocket_events` return annotation is `None`.
- **type-annotations.AC1.9 Failure:** A missing annotation on any public function in this module group causes the mypy check (when #17 is enabled) to emit an error.

### type-annotations.AC2: converter module annotations complete
- **type-annotations.AC2.1 Success:** `engine.convert_one` all parameters annotated; return type is `ConversionResult`.
- **type-annotations.AC2.2 Success:** `engine.convert_one` `http_module` and `convert_fn` DI parameters annotated using Protocol types defined in Phase 2.
- **type-annotations.AC2.3 Success:** `cli._iter_unconverted` annotated as `Generator[dict, None, None]`; `http_module` parameter uses Protocol type.
- **type-annotations.AC2.4 Success:** `cli._run` `args` parameter annotated as `argparse.Namespace`; `http_module` and `convert_one_fn` parameters use Protocol types; return is `int`.
- **type-annotations.AC2.5 Success:** `convert.convert_sas_to_parquet` `chunk_iter_factory` parameter annotated using `Callable[[Path, int], Iterator[tuple[pd.DataFrame, object]]]` or equivalent Protocol.
- **type-annotations.AC2.6 Success:** `daemon.DaemonRunner.__init__` all parameters annotated; `consumer_factory` and `convert_one_fn` use Protocol types.

### type-annotations.AC3: crawler module annotations complete
- **type-annotations.AC3.1 Success:** `crawler.main.walk_roots` fully annotated; `scan_roots` typed as `list[ScanRoot]`; return is `list[tuple[str, str]]`.
- **type-annotations.AC3.2 Success:** `crawler.main.crawl` `config` parameter typed as `PipelineConfig`; `logger` typed as `logging.Logger`; return is `int`.
- **type-annotations.AC3.3 Success:** `crawler.main.main` return annotation is `None`.

### type-annotations.AC4: lexicons module annotations complete
- **type-annotations.AC4.1 Success:** `lexicons.models.Lexicon.derive_hook` typed as `Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]] | None`.
- **type-annotations.AC4.2 Success:** `lexicons.loader._import_hook` return annotation is `Callable[..., Any]` or a Protocol matching the derive_hook signature.
- **type-annotations.AC4.3 Failure:** Using bare `Callable` without parameters on `derive_hook` field causes mypy to emit an error under strict mode.

### type-annotations.AC5: config and auth_cli annotations complete
- **type-annotations.AC5.1 Success:** `config.__getattr__` annotated as `(name: str) -> PipelineConfig`.
- **type-annotations.AC5.2 Success:** `auth_cli.main` return annotation is `None`.

### type-annotations.AC6: events consumer annotations complete
- **type-annotations.AC6.1 Success:** `EventConsumer.__init__` `on_event` parameter annotated as `Callable[[dict], Awaitable[None]]`.
- **type-annotations.AC6.2 Success:** `EventConsumer._session` `websocket` parameter annotated as `websockets.asyncio.client.ClientConnection` (or the correct websockets type).
- **type-annotations.AC6.3 Success:** `EventConsumer._buffer_ws` `websocket` parameter has same annotation.
- **type-annotations.AC6.4 Failure:** Bare `websocket` without annotation causes mypy to flag a missing annotation error.

### type-annotations.AC7: Protocol definitions are stable and reusable
- **type-annotations.AC7.1 Success:** A `ConverterProtocols` module (or equivalent location) defines `HttpModuleProtocol` covering `get_delivery`, `patch_delivery`, `emit_event`, `list_unconverted`.
- **type-annotations.AC7.2 Success:** `ConvertOneFnProtocol` covers the `convert_one` signature.
- **type-annotations.AC7.3 Success:** `ConsumerFactoryProtocol` covers the `EventConsumer` constructor signature used in `DaemonRunner`.
- **type-annotations.AC7.4 Success:** Tests that inject fakes for these seams continue to pass (structural subtyping via Protocol means no changes to fake implementations).

### type-annotations.AC8: No regressions
- **type-annotations.AC8.1 Success:** `uv run pytest` passes at every phase boundary.
- **type-annotations.AC8.2 Success:** No existing test is modified to accommodate annotation changes (annotations must fit existing call sites, not the reverse).

## Glossary

- **PEP 484**: The Python specification defining type hints syntax and semantics.
- **Protocol**: A `typing.Protocol` class defining a structural interface; a type satisfies a Protocol if it has the required attributes/methods, without explicit inheritance.
- **DI param / test seam**: A function parameter that defaults to a production implementation but can be overridden in tests (dependency injection light pattern used throughout this codebase).
- **bare `Callable`**: `Callable` used without subscript parameters, e.g., `Callable` instead of `Callable[[int], str]`. Accepted by Python but provides no useful type information.
- **`Generator[Y, S, R]`**: Return type for generator functions (`yield`-based). `Y` = yielded type, `S` = sent type, `R` = return type.
- **`Awaitable`**: Abstract base type for coroutines and objects implementing `__await__`; used for async callback parameters.
- **mypy strict mode**: mypy configuration enabling `--disallow-untyped-defs`, `--disallow-any-generics`, and related flags. Issue #17 adds this; #19 makes it possible.
- **structural subtyping**: Python's Protocol-based duck typing — a class matches a Protocol if it has the right shape, not because it explicitly inherits from it.

---

## Architecture

The change is additive: no runtime behaviour changes, no new modules beyond a single Protocols file. The work is a read-and-annotate pass over existing signatures, guided by call sites, docstrings, and test files to infer correct types.

The one structural decision is where to define Protocol types for DI parameters. The current codebase uses module-level defaults (e.g., `http_module=converter_http`) with no formal interface. Three parameters require Protocol definitions because their signatures are non-trivial and used across multiple files:

- `HttpModuleProtocol` — the `converter.http` module interface, used in `engine.py`, `cli.py`
- `ConvertOneFnProtocol` — the `convert_one` function signature, used in `cli.py` and `daemon.py`
- `ConsumerFactoryProtocol` — the `EventConsumer` constructor, used in `daemon.py`

These Protocols live in `src/pipeline/converter/protocols.py`. They use `typing.Protocol` with `__call__` or method definitions. Placing them in the `converter` package (rather than a top-level `protocols.py`) keeps them close to their primary consumers and avoids circular imports.

The `derive_hook` callable in `lexicons/models.py` is annotated inline using a full `Callable` signature referencing `ParsedDelivery` from `crawler.parser`. Because `lexicons` must not import from `crawler` (boundary invariant), a `TYPE_CHECKING` guard is used:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.crawler.parser import ParsedDelivery
```

**Decision:** Use `TYPE_CHECKING` guards (not `from __future__ import annotations`) for cross-package type references. `TYPE_CHECKING` is surgical — it makes the import boundary explicit. `from __future__ import annotations` changes evaluation semantics for every annotation in the file, which is overkill for targeted forward references.

## Existing Patterns

Investigation found no existing Protocol definitions in the codebase. All DI parameters use bare module references or untyped defaults. This design introduces Protocols as a new pattern, justified by the requirement to annotate the seams without changing runtime behaviour.

`typing.TYPE_CHECKING` guards are introduced by this design for cross-package type references (primarily the `derive_hook` annotation in `lexicons/models.py`).

All other patterns (return type annotations on plain functions, `Generator`, `Awaitable`) are standard Python and require no new conventions.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Protocol Definitions
**Goal:** Define the three Protocol types needed before annotating the modules that depend on them.

**Components:**
- `src/pipeline/converter/protocols.py` — new file with `HttpModuleProtocol`, `ConvertOneFnProtocol`, `ConsumerFactoryProtocol`

**Dependencies:** None (first phase).

**Done when:** Module imports cleanly; `uv run pytest` still passes (no behaviour change).
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: registry_api Annotations
**Goal:** Complete annotations for all five files in `registry_api/`.

**Components:**
- `src/pipeline/registry_api/db.py` — `get_db` return type, `upsert_delivery` return type correction
- `src/pipeline/registry_api/models.py` — Pydantic validator `cls`, `v`, and return annotations
- `src/pipeline/registry_api/auth.py` — `require_role` and `_check_role` return types
- `src/pipeline/registry_api/main.py` — `websocket_events` parameter and return types
- `src/pipeline/registry_api/routes.py` — all route handler return types, `_validate_source_path` return type

**Dependencies:** Phase 1 (Protocols available, though not needed by this module group directly).

**Done when:** All route handlers and db functions annotated; `uv run pytest` passes; AC1.1–AC1.9 satisfied.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: converter Annotations
**Goal:** Complete annotations for all converter module files using the Phase 1 Protocols.

**Components:**
- `src/pipeline/converter/engine.py` — `convert_one` parameters including `http_module: HttpModuleProtocol` and `convert_fn: ConvertOneFnProtocol`
- `src/pipeline/converter/cli.py` — `_iter_unconverted` generator return, `_run` parameters including `http_module: HttpModuleProtocol`, `convert_one_fn: ConvertOneFnProtocol`
- `src/pipeline/converter/daemon.py` — `DaemonRunner.__init__` all parameters including `consumer_factory: ConsumerFactoryProtocol`, `convert_one_fn: ConvertOneFnProtocol`
- `src/pipeline/converter/convert.py` — `chunk_iter_factory` callable parameter with explicit `Callable[[Path, int], Iterator[...]]` signature

**Dependencies:** Phase 1 (Protocols).

**Done when:** `uv run pytest` passes; AC2.1–AC2.6 satisfied; existing test seams continue to work via structural subtyping.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: crawler and lexicons Annotations
**Goal:** Complete annotations for `crawler/main.py` and `lexicons/models.py` + `lexicons/loader.py`.

**Components:**
- `src/pipeline/crawler/main.py` — `walk_roots`, `crawl`, `main`, `inventory_files` parameter and return types; `logger` typed as `logging.Logger`
- `src/pipeline/lexicons/models.py` — `derive_hook` field typed as full `Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]] | None` using `TYPE_CHECKING` guard for the cross-package import
- `src/pipeline/lexicons/loader.py` — `_import_hook` return type

**Dependencies:** Phase 1.

**Done when:** `uv run pytest` passes; AC3.1–AC3.3 and AC4.1–AC4.3 satisfied.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: config, auth_cli, and events Annotations
**Goal:** Complete annotations for the remaining three files.

**Components:**
- `src/pipeline/config.py` — `__getattr__` annotated as `(name: str) -> PipelineConfig`
- `src/pipeline/auth_cli.py` — `main` return annotation
- `src/pipeline/events/consumer.py` — `__init__` `on_event` parameter, `_session` and `_buffer_ws` `websocket` parameter using correct `websockets` type

**Dependencies:** Phases 1–4 (all other modules annotated first to avoid discovering cross-module type errors in the last phase).

**Done when:** `uv run pytest` passes; AC5.1–AC5.2, AC6.1–AC6.4 satisfied; all AC8 criteria satisfied across the full test suite.
<!-- END_PHASE_5 -->

## Additional Considerations

**Relationship to issue #17 (mypy):** This work is a strict prerequisite. mypy in strict mode will reject unannotated functions. Phases 1–5 here must land before #17 enables `--disallow-untyped-defs`. The two issues can be developed in the same branch but should be sequenced: #19 first, #17 adds the mypy config after.

**`derive_hook` cross-package import:** `lexicons/models.py` must not import from `crawler` at runtime (boundary invariant per CLAUDE.md). The `TYPE_CHECKING` guard isolates the import to type-check time only. At runtime, `derive_hook` is `Callable[..., Any]` from Python's perspective; mypy sees the full type.

**Effort estimate:** This is genuinely large. Fifteen files, ~40–60 individual annotation sites. The mechanical work per file is low, but review cycles add up. Estimate: 3–5 hours of focused work across all phases, with the converter phase (Phase 3) being the most judgement-intensive due to the Protocol definitions requiring correctness verification against existing test fakes.

**No behaviour changes:** Annotations are purely additive. No function body changes, no refactoring of defaults, no removal of `# type: ignore` comments that aren't warranted. If a `# type: ignore` is needed to satisfy mypy for a FastAPI-specific pattern (e.g., `require_role` return type), add it with a comment explaining why.
