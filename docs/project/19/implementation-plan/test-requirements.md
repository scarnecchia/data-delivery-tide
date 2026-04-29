# GH19 — Test Requirements

Maps each acceptance criterion in `docs/project/19/design.md` to either an automated test or documented human verification.

## Summary

GH19 is a pure type-annotation pass. Per the design's "No behaviour changes" guarantee, **no new test code is required** and **no existing test is modified** (AC8.2). Verification falls into three buckets:

1. **Regression** (AC8.1) — `uv run pytest` continues to pass at every phase boundary. Existing tests are the regression suite for "no runtime change".
2. **Mechanical** (AC1.1–AC1.8, AC2.1–AC2.6, AC3.1–AC3.3, AC4.1–AC4.2, AC5.1–AC5.2, AC6.1–AC6.3, AC7.1–AC7.4) — `inspect.signature()` and `grep` confirm that the textual annotations are present and have the expected shape.
3. **Negative under strict mypy** (AC1.9, AC4.3, AC6.4) — these ACs say "missing/bare annotation causes mypy strict to error". They are fully verified once issue #17 lands and runs mypy strict in CI; until then they are human-verifiable by reading the source.

The combination is sufficient because PEP 484 annotations have no runtime semantics on Python 3.10+ for the kinds of types this issue uses (no `Annotated` runtime metadata, no `Pydantic` field validation changes, no `dataclass` field type changes that would alter `__init__`).

---

## Coverage Map

### GH19.AC1.1 — registry_api route handlers carry explicit return types

- **Verification type:** Automated (mechanical introspection)
- **Test approach:** `inspect.signature()` per handler, asserted in Phase 2 Task 5's verification step.
- **Per-handler expected return:**
  - `health` → `dict[str, str]`
  - `create_delivery` → `dict`
  - `list_all_deliveries` → `PaginatedDeliveryResponse`
  - `get_actionable_deliveries` → `list[dict]`
  - `get_single_delivery` → `dict`
  - `update_single_delivery` → `dict`
  - `get_events` → `list[dict]`
  - `emit_event` → `dict`
- **Pass condition:** every handler's return annotation is non-empty and matches the table above.
- **Why this differs from design literal:** handlers return Python dicts; FastAPI's `response_model=` parameter handles conversion to the `DeliveryResponse`/`EventRecord`/`PaginatedDeliveryResponse` wire shapes. Annotating handlers as their `response_model` would mis-type their actual return value. Documented in Phase 2 Task 5.

### GH19.AC1.2 — `db.get_db() -> Generator[sqlite3.Connection, None, None]`

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "from pipeline.registry_api.db import get_db; import inspect; print(inspect.signature(get_db).return_annotation)"
  ```
- **Pass condition:** prints `Generator[sqlite3.Connection, None, None]` (or its repr).

### GH19.AC1.3 — `db.upsert_delivery -> dict`

- **Verification type:** Automated (mechanical)
- **Command:** as above for `upsert_delivery`.
- **Pass condition:** prints `<class 'dict'>`.
- **Note:** the unreachable `return None` at `db.py:333` is silenced with `# type: ignore[return-value]` per Phase 2 Task 1.

### GH19.AC1.4 — Pydantic validators carry full annotations

- **Verification type:** Automated (mechanical) + human acknowledgement
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.registry_api.models import DeliveryCreate, DeliveryUpdate, DeliveryFilters
  import inspect
  for cls, name in [(DeliveryCreate, 'check_metadata_size'), (DeliveryUpdate, 'check_metadata_size'), (DeliveryFilters, 'clamp_limit'), (DeliveryFilters, 'check_offset')]:
      validator = getattr(cls, name)
      sig = inspect.signature(validator)
      print(f'{cls.__name__}.{name}:', sig.return_annotation, sig.parameters['v'].annotation)
  "
  ```
- **Pass condition:** all four validators print their `v` parameter type and return type.
- **Human verification:** confirm that omitting `cls` annotation is acceptable per Phase 2 Task 2's rationale (Pydantic v2 introspection doesn't require it).

### GH19.AC1.5 — `auth.require_role() -> Any`

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "from pipeline.registry_api.auth import require_role; import inspect; print(inspect.signature(require_role).return_annotation)"
  ```
- **Pass condition:** prints `typing.Any`.

### GH19.AC1.6 — `auth._check_role() -> TokenInfo`

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.registry_api.auth import require_role
  import inspect
  inner = require_role('read').dependency
  print(inspect.signature(inner).return_annotation.__name__)
  "
  ```
- **Pass condition:** prints `TokenInfo`.
- **Note:** `_check_role` is a closure inside `require_role`; this AC was already satisfied in current code.

### GH19.AC1.7, AC1.8 — `websocket_events` `token: str | None`, `-> None`

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.registry_api.main import websocket_events
  import inspect
  sig = inspect.signature(websocket_events)
  print('token:', sig.parameters['token'].annotation)
  print('return:', sig.return_annotation)
  "
  ```
- **Pass condition:** `token: str | None`, `return: None`.

### GH19.AC1.9 — Missing annotation triggers mypy error under strict mode

- **Verification type:** Human + automated (after issue #17 lands)
- **Approach:** Once `mypy --strict` is wired into CI by issue #17, it will error on any unannotated public function in `src/pipeline/registry_api/`. Until then, this is a property of the codebase enforced by code review.
- **Manual check at PR time:** reviewer reads each registry_api source file and confirms every public function has both parameter and return annotations.

### GH19.AC2.1, AC2.2 — `engine.convert_one` annotations

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.converter.engine import convert_one
  import inspect
  sig = inspect.signature(convert_one)
  print('http_module:', sig.parameters['http_module'].annotation.__name__)
  print('convert_fn:', sig.parameters['convert_fn'].annotation.__name__)
  print('return:', sig.return_annotation.__name__)
  "
  ```
- **Pass condition:** prints `HttpModuleProtocol`, `ConvertSasToParquetFnProtocol`, `ConversionResult`.
- **Note on protocol naming:** Phase 3 Task 1 surfaces a discrepancy with the design — `engine.py`'s `convert_fn` parameter actually injects `convert_sas_to_parquet`, not `convert_one`. Plan introduces `ConvertSasToParquetFnProtocol` (as a sibling of `ConvertOneFnProtocol`) to type the engine seam faithfully.

### GH19.AC2.3, AC2.4 — `cli._iter_unconverted` and `_run`

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.converter.cli import _iter_unconverted, _run
  import inspect
  print('_iter_unconverted return:', inspect.signature(_iter_unconverted).return_annotation)
  print('_iter_unconverted http_module:', inspect.signature(_iter_unconverted).parameters['http_module'].annotation.__name__)
  print('_run args:', inspect.signature(_run).parameters['args'].annotation.__name__)
  print('_run http_module:', inspect.signature(_run).parameters['http_module'].annotation.__name__)
  print('_run convert_one_fn:', inspect.signature(_run).parameters['convert_one_fn'].annotation.__name__)
  print('_run return:', inspect.signature(_run).return_annotation.__name__)
  "
  ```
- **Pass condition:** prints the expected `Generator[dict, None, None]`, `HttpModuleProtocol`, `Namespace`, `HttpModuleProtocol`, `ConvertOneFnProtocol`, `int`.

### GH19.AC2.5 — `chunk_iter_factory` parameter annotated

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  grep -n "chunk_iter_factory: Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/convert.py
  ```
- **Pass condition:** matches the line `chunk_iter_factory: Callable[[Path, int], Iterator[tuple[pd.DataFrame, object]]] = _iter_sas_chunks,`.

### GH19.AC2.6 — `DaemonRunner.__init__` parameters annotated

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.converter.daemon import DaemonRunner
  import inspect
  sig = inspect.signature(DaemonRunner.__init__)
  for p in sig.parameters.values():
      if p.name == 'self':
          continue
      print(p.name, p.annotation)
  "
  ```
- **Pass condition:** every parameter (except `self`) has a non-empty annotation; `consumer_factory` shows `ConsumerFactoryProtocol`; `convert_one_fn` shows `ConvertOneFnProtocol`.

### GH19.AC3.1, AC3.2, AC3.3 — crawler annotations

- **Verification type:** Automated (mechanical)
- **Commands:**
  ```bash
  uv run python -c "
  from pipeline.crawler.main import walk_roots, crawl, main, inventory_files
  import inspect
  print('walk_roots scan_roots:', inspect.signature(walk_roots).parameters['scan_roots'].annotation)
  print('crawl config:', inspect.signature(crawl).parameters['config'].annotation.__name__)
  print('crawl logger:', inspect.signature(crawl).parameters['logger'].annotation.__name__)
  print('main return:', inspect.signature(main).return_annotation)
  print('inventory_files return:', inspect.signature(inventory_files).return_annotation)
  "
  ```
- **Pass condition:** matches design AC3.1–AC3.3 literals.

### GH19.AC4.1, AC4.3 — `lexicons.models.derive_hook` parameterised

- **Verification type:** Hybrid — mechanical + human review
- **Mechanical command:**
  ```bash
  grep -n 'derive_hook: Callable\[\[list\["ParsedDelivery"\], "Lexicon"\], list\["ParsedDelivery"\]\] | None = None' /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py
  ```
- **Pass condition:** exactly one match.
- **Human verification:** confirm `TYPE_CHECKING` block imports `ParsedDelivery` from `pipeline.crawler.parser` and that the `lexicons` -> `crawler` boundary is preserved at runtime.
- **Idempotency note:** identical to GH28's edit. If GH28 has already landed, Phase 4 Task 2 is a verified no-op.

### GH19.AC4.2 — `_import_hook` annotated

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "from pipeline.lexicons.loader import _import_hook; import inspect; print(inspect.signature(_import_hook).return_annotation)"
  ```
- **Pass condition:** prints `collections.abc.Callable[..., typing.Any]` or its string form.

### GH19.AC4.4 (deduced — covered by AC4.3)

Bare `Callable` with no parameters is what GH28 fixes; Phase 4 Task 2 confirms.

### GH19.AC5.1, AC5.2 — config, auth_cli

- **Verification type:** Automated (mechanical)
- **Commands:**
  ```bash
  uv run python -c "from pipeline.config import settings; print(type(settings).__name__)"
  uv run python -c "from pipeline.auth_cli import main; import inspect; print(inspect.signature(main).return_annotation)"
  ```
- **Pass condition:** first prints `PipelineConfig`; second prints `<class 'NoneType'>` or `None`.

### GH19.AC6.1 — `EventConsumer.__init__.on_event` annotated

- **Verification type:** Automated (mechanical) — already satisfied
- **Command:**
  ```bash
  uv run python -c "from pipeline.events.consumer import EventConsumer; import inspect; print(inspect.signature(EventConsumer.__init__).parameters['on_event'].annotation)"
  ```
- **Pass condition:** prints `collections.abc.Callable[[dict], collections.abc.Awaitable[None]]` (or its string form).
- **Note:** AC6.1 was already satisfied in the existing code at `consumer.py:31`. Phase 5 Task 3 verifies, no edit needed.

### GH19.AC6.2, AC6.3 — `_session` and `_buffer_ws` `websocket: ClientConnection`

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.events.consumer import EventConsumer
  import inspect
  print('_session:', inspect.signature(EventConsumer._session).parameters['websocket'].annotation.__name__)
  print('_buffer_ws:', inspect.signature(EventConsumer._buffer_ws).parameters['websocket'].annotation.__name__)
  "
  ```
- **Pass condition:** both print `ClientConnection`.

### GH19.AC6.4 — Mypy strict catches bare `websocket`

- **Verification type:** Human + automated (after issue #17 lands)
- **Approach:** same as AC1.9 — strict mypy in CI (#17) is the automated enforcement; human review is the interim check.

### GH19.AC7.1, AC7.2, AC7.3 — Protocol module exists with three Protocols

- **Verification type:** Automated (mechanical)
- **Command:**
  ```bash
  uv run python -c "
  from pipeline.converter.protocols import HttpModuleProtocol, ConvertOneFnProtocol, ConsumerFactoryProtocol, ConvertSasToParquetFnProtocol
  print('HttpModuleProtocol methods:', sorted(set(dir(HttpModuleProtocol)) - set(dir(object)) - {'_is_protocol', '_is_runtime_protocol', '_proto_hook', '_abc_impl'}))
  for proto in [ConvertOneFnProtocol, ConsumerFactoryProtocol, ConvertSasToParquetFnProtocol]:
      print(proto.__name__, 'has __call__:', hasattr(proto, '__call__'))
  "
  ```
- **Pass condition:** `HttpModuleProtocol` lists `get_delivery, patch_delivery, list_unconverted, emit_event`; the three callable protocols all have `__call__`.

### GH19.AC7.4 — Tests with fakes continue to pass via structural subtyping

- **Verification type:** Automated (regression)
- **Command:** `uv run pytest tests/converter/`
- **Pass condition:** all converter tests pass with no test-file edits.
- **Why this works:** Protocols use structural subtyping. Existing test fakes that "look like" `HttpModuleProtocol` (by exposing the four method names with the right signatures) automatically satisfy it without any inheritance change.

### GH19.AC8.1 — `uv run pytest` passes at every phase boundary

- **Verification type:** Automated (regression)
- **Command:** `uv run pytest`
- **Pass condition:** exit 0, no failures, no errors.
- **Performed at:** end of every phase. The implementation plan's per-phase "Verification" sections include narrower test-subset commands for fast feedback during development; the full-suite run is the definitive check before each phase commit.

### GH19.AC8.2 — No test files modified

- **Verification type:** Automated (mechanical)
- **Command:** `git diff --stat ORIGIN_MAIN.. -- tests/`
- **Pass condition:** zero lines changed in `tests/` for this issue's branch.

---

## Human Verification Items (consolidated)

| Item | AC | Justification | Approach |
|---|---|---|---|
| `cls` parameter omitted from validator annotations | AC1.4 | Pydantic v2 idiom; `cls: type["DeliveryCreate"]` would force forward refs everywhere | PR review |
| Handler returns documented as `dict` (not `response_model`) | AC1.1 | FastAPI converts via `response_model`; annotating return as the wire type would lie to mypy | PR review (also documented in Phase 2 Task 5) |
| `# type: ignore[assignment]` on `require_role(...)` defaults | AC1.5 | Consequence of AC1.5's `Any` choice; documented in CLAUDE.md gotcha | PR review |
| `# type: ignore[assignment]` on Protocol-typed module/class defaults (engine, daemon, cli) | AC2.1–AC2.6, AC7.x | mypy doesn't structurally match modules-as-Protocols; runtime is correct | PR review |
| `ConvertSasToParquetFnProtocol` introduced (design conflated two seams) | AC2.2, AC7.2 | Design plan incorrectly named `ConvertOneFnProtocol` for the engine seam; engine actually injects `convert_sas_to_parquet` | PR review against design discrepancy notes |
| Mypy negative tests (AC1.9, AC4.3, AC6.4) | various | These ACs are testable only after issue #17 enables `mypy --strict` in CI | Verified once #17 lands; until then, code review |

---

## Out of Scope for Test Requirements

- mypy strict-mode invocation (issue #17 — listed as the canonical home for AC1.9, AC4.3, AC6.4 enforcement).
- Runtime tests for individual annotations (annotations have no runtime semantics in Python 3.10+ for the types this issue uses).
- Tests of `derive_hook` invocation (existing crawler tests cover this — no new tests needed).
- Tests of FastAPI dependency injection (existing registry_api tests cover this).
- Tests of the new Protocol classes (Protocols are declarative types — they don't execute).
