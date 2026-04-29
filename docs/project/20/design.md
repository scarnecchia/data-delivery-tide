# Replace Bare Dicts and Tuples with Frozen Dataclasses (Issue #20)

## Summary

This design replaces anonymous structural types — bare `dict`, `list[tuple]`, and `TypedDict` — with
`@dataclass(frozen=True)` types across five files in three subsystems: the registry API database
layer, the converter engine, and the crawler (manifest, fingerprint, main). The goal is to surface
field-level errors at definition sites rather than at consumption sites, make internal contracts
inspectable, and comply with Python Programming Standards §4.1.

The migration is layered: crawler Functional Core modules (`fingerprint.py`, `manifest.py`) are
converted first because they have no Pydantic coupling. The converter engine follows because its
tuple/dict accumulation is self-contained. The registry API database layer (`db.py`) goes last
because its return types feed directly into Pydantic models that serialize to JSON — that boundary
requires explicit `model_validate` calls replacing the current implicit dict-to-Pydantic promotion.
`TypedDict` types in crawler code are promoted to frozen dataclasses in place; the `dict()`
constructor calls inside `build_manifest` and `inventory_files` that produce these types are updated
accordingly.

## Definition of Done

- All `TypedDict` types in `crawler/fingerprint.py` and `crawler/manifest.py` are replaced with
  `@dataclass(frozen=True)`.
- `build_error_manifest` returns a named dataclass pair instead of a bare `tuple[str, ErrorManifest]`.
- `walk_roots` in `crawler/main.py` returns `list[WalkResult]` instead of `list[tuple[str, str]]`.
- The `delivery_data` accumulator in `crawler/main.py` uses a frozen dataclass value instead of a
  bare `tuple`.
- `successes` in `converter/engine.py` uses `FileConversionSuccess` dataclass instead of
  `list[tuple[str, int, int]]`.
- `failures` in `converter/engine.py` uses `FileConversionFailure` dataclass instead of bare `dict`
  values.
- `get_delivery`, `list_deliveries`, `get_actionable`, `update_delivery`, `get_token_by_hash`,
  `insert_event`, and `get_events_after` in `registry_api/db.py` return typed dataclasses instead
  of `dict` / `list[dict]`.
- All callers that previously used the `dict` return values of `db.py` functions use
  `dataclasses.asdict()` or attribute access as appropriate.
- All existing tests pass without modification to test assertions.
- No new public API surface (routes, WebSocket payloads, event shapes) changes.

## Acceptance Criteria

### design.AC1: Crawler Functional Core types are dataclasses

- **design.AC1.1 Success:** `FileEntry` in `fingerprint.py` is a frozen dataclass; `compute_fingerprint`
  accepts and returns correctly typed values.
- **design.AC1.2 Success:** `ParsedMetadata`, `CrawlManifest`, `ErrorManifest` in `manifest.py` are
  frozen dataclasses.
- **design.AC1.3 Success:** `build_error_manifest` returns a named `ErrorManifestResult` (or equivalent
  dataclass) rather than `tuple[str, ErrorManifest]`.
- **design.AC1.4 Failure:** Passing a dict where a `FileEntry` is expected raises `TypeError` (no
  implicit coercion).
- **design.AC1.5 Edge:** `build_manifest` constructs `CrawlManifest` using keyword arguments; all
  fields accounted for.

### design.AC2: Crawler Imperative Shell types are dataclasses

- **design.AC2.1 Success:** `walk_roots` returns `list[WalkResult]` with `.source_path` and
  `.scan_root` attributes.
- **design.AC2.2 Success:** `delivery_data` accumulator value is a frozen dataclass with `.files`,
  `.fingerprint`, and `.manifest` fields.
- **design.AC2.3 Success:** All destructuring of `walk_roots` results and `delivery_data` values in
  `crawl()` uses attribute access, not tuple unpacking.
- **design.AC2.4 Failure:** Existing `test_main.py` tests pass without modification.

### design.AC3: Converter engine accumulation types are dataclasses

- **design.AC3.1 Success:** `successes` list holds `FileConversionSuccess` instances with `.filename`,
  `.row_count`, `.bytes_written` fields.
- **design.AC3.2 Success:** `failures` dict values are `FileConversionFailure` instances with
  `.error_class`, `.message`, `.at`, `.converter_version` fields.
- **design.AC3.3 Success:** `total_rows`, `total_bytes`, and `converted_files` aggregations in
  `engine.py` use attribute access on `FileConversionSuccess`.
- **design.AC3.4 Success:** The `patch_body` and `event_payload` dicts built from `failures` serialize
  identically to the current output (use `dataclasses.asdict()`).
- **design.AC3.5 Failure:** Existing `test_engine.py` assertions on patch body shapes pass without
  modification.

### design.AC4: Registry API db layer returns typed dataclasses

- **design.AC4.1 Success:** `DeliveryRecord`, `TokenRecord`, `EventRecord` frozen dataclasses defined
  in `db.py` (or a new `registry_api/records.py`).
- **design.AC4.2 Success:** `get_delivery` returns `DeliveryRecord | None`; `list_deliveries` returns
  `tuple[list[DeliveryRecord], int]`.
- **design.AC4.3 Success:** `get_token_by_hash` returns `TokenRecord | None`.
- **design.AC4.4 Success:** `insert_event` and `get_events_after` return `EventRecord` /
  `list[EventRecord]`.
- **design.AC4.5 Success:** Routes in `routes.py` call `DeliveryResponse.model_validate(dataclasses.asdict(record))`
  (or equivalent) instead of passing the raw dict to the Pydantic constructor.
- **design.AC4.6 Success:** `auth.py` uses `TokenRecord` attribute access instead of dict key access.
- **design.AC4.7 Failure:** Existing `test_db.py` and `test_routes.py` tests pass without modification.
- **design.AC4.8 Edge:** `upsert_delivery` still accepts a plain `dict` input (its call sites pass
  dicts built from Pydantic `.model_dump()`); return type becomes `DeliveryRecord | None`.

### design.AC5: Cross-cutting — no serialization regression

- **design.AC5.1 Success:** JSON responses from all GET endpoints are byte-for-byte equivalent before
  and after the migration (verified by existing route tests).
- **design.AC5.2 Success:** WebSocket broadcast payloads are unchanged.
- **design.AC5.3 Success:** Crawl manifest JSON files written to disk are unchanged.
- **design.AC5.4 Failure:** Any dataclass field access on a missing key fails loudly at construction
  time, not silently returning `None` as dicts do.

## Glossary

- **Frozen dataclass:** A Python `@dataclass(frozen=True)` instance that is immutable after
  construction; fields are accessed as attributes, not subscript keys. Equality and hashing are
  automatically derived.
- **TypedDict:** A `typing.TypedDict` subclass that annotates a plain `dict` with field types.
  Runtime behaviour is identical to a regular dict; type information exists only for static
  analysis. Being replaced by dataclasses here.
- **Functional Core:** Modules annotated `# pattern: Functional Core` — pure functions with no
  side effects. `fingerprint.py`, `manifest.py`, `classify.py`, `convert.py`.
- **Imperative Shell:** Modules annotated `# pattern: Imperative Shell` — orchestration that
  coordinates I/O and side effects. `main.py`, `engine.py`, `db.py`, `routes.py`.
- **FCIS:** Functional Core / Imperative Shell — the architectural pattern used throughout this
  codebase to separate pure logic from side-effecting orchestration.
- **`dataclasses.asdict()`:** Standard library function that recursively converts a dataclass
  instance to a plain `dict`. Used here to bridge dataclass return values from `db.py` into
  Pydantic `model_validate()` calls.
- **`model_validate()`:** Pydantic v2 classmethod (replaces v1 `parse_obj`) that constructs a
  `BaseModel` instance from a plain dict, running validators.
- **`sqlite3.Row`:** The row factory used by `db.py` connections. Acts like a tuple but supports
  dict-style key access. Currently converted to `dict` before returning; will be converted to
  typed dataclasses instead.
- **Delivery record:** The canonical unit of state in the registry — one row per `source_path` in
  the `deliveries` SQLite table.
- **`WalkResult`:** Proposed dataclass replacing the `tuple[str, str]` returned by `walk_roots`
  in `crawler/main.py`, carrying `.source_path` and `.scan_root`.

---

## Architecture

The migration is a type-layer substitution. No new modules are strictly required; the new
dataclass types can live in their respective source files. One optional new file
(`registry_api/records.py`) is foreseen to keep `db.py` focused on SQL operations rather than
type definitions — this is the preferred placement given the number of types and their use by
`routes.py` and `auth.py`.

Data flow is unchanged: `sqlite3.Row` → `dict(row)` → Pydantic model. The middle step changes
from an anonymous `dict` to a typed frozen dataclass: `sqlite3.Row` → `DeliveryRecord` →
`DeliveryResponse.model_validate(dataclasses.asdict(record))`.

Crawler data flow: `os.scandir()` → `FileEntry` dataclass (was TypedDict) →
`compute_fingerprint(files)` → `CrawlManifest` dataclass → `json.dump(dataclasses.asdict(manifest))`.
The manifest JSON on disk is derived from `dataclasses.asdict()`, so its shape is unchanged.

Converter data flow: per-file results accumulated as `FileConversionSuccess` / `FileConversionFailure`
dataclasses → aggregation via attribute access → `patch_body` and `event_payload` built with
`dataclasses.asdict()` for the failure records, or direct attribute access for success aggregation.

## Existing Patterns

The codebase already uses `@dataclass(frozen=True)` in two places:

- `ConversionResult` in `converter/engine.py` — frozen dataclass for per-delivery outcome.
- `ParsedDelivery` and `ParseError` in `crawler/parser.py` — frozen dataclasses for path parsing
  results.

The `TypedDict` usage in `fingerprint.py` and `manifest.py` predates these frozen dataclass
introductions. This design unifies all structured internal data under the same pattern.

`inventory_files` in `crawler/main.py` currently constructs `FileEntry` using the TypedDict
constructor syntax (`FileEntry(filename=..., ...)`). After conversion to dataclass, the call site
is identical — no change needed there.

`build_manifest` currently returns a dict literal. After conversion it will construct and return
a `CrawlManifest` dataclass; the `json.dump(manifest, ...)` call site in `crawl()` changes to
`json.dump(dataclasses.asdict(manifest), ...)`.

The `dict(f) for f in files` comprehension inside `build_manifest` (used to serialize `FileEntry`
instances into the manifest's `files` field) changes to `dataclasses.asdict(f) for f in files`.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Crawler Functional Core — fingerprint and manifest types

**Goal:** Replace `FileEntry`, `ParsedMetadata`, `CrawlManifest`, and `ErrorManifest` TypedDicts
with frozen dataclasses. Replace the bare tuple returned by `build_error_manifest` with a named
dataclass.

**Components:**
- `FileEntry` in `src/pipeline/crawler/fingerprint.py` — promote from TypedDict to
  `@dataclass(frozen=True)`.
- `ParsedMetadata`, `CrawlManifest`, `ErrorManifest` in `src/pipeline/crawler/manifest.py` —
  promote from TypedDict to `@dataclass(frozen=True)`.
- `ErrorManifestResult` (new) in `manifest.py` — frozen dataclass with `.filename: str` and
  `.manifest: ErrorManifest` fields, replacing the bare `tuple[str, ErrorManifest]` return type of
  `build_error_manifest`.
- `build_manifest` and `build_error_manifest` function bodies updated to construct dataclass
  instances; `dict(f) for f in files` updated to `dataclasses.asdict(f) for f in files`.

**Dependencies:** None (Functional Core, no external callers outside tests).

**Done when:** `tests/crawler/test_fingerprint.py` and `tests/crawler/test_manifest.py` pass; AC1.1
through AC1.5 covered.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Crawler Imperative Shell — walk_roots and delivery_data

**Goal:** Replace `list[tuple[str, str]]` return type of `walk_roots` and the bare tuple value in
`delivery_data` with frozen dataclasses. Update all call sites in `crawl()`.

**Components:**
- `WalkResult` (new) in `src/pipeline/crawler/main.py` — frozen dataclass with `.source_path: str`
  and `.scan_root: str`.
- `DeliveryAccumulator` (new) in `src/pipeline/crawler/main.py` — frozen dataclass with
  `.files: list[FileEntry]`, `.fingerprint: str`, `.manifest: CrawlManifest`.
- `walk_roots` return type updated to `list[WalkResult]`; tuple construction `(terminal_entry.path, root_path)` replaced with `WalkResult(...)`.
- `crawl()` destructuring of `walk_roots` results and `delivery_data` values updated to attribute access.
- `json.dump(manifest, ...)` call in `crawl()` updated to `json.dump(dataclasses.asdict(manifest), ...)`.
- `inventory_files` return type annotation updated from `list[FileEntry]` (TypedDict) to
  `list[FileEntry]` (dataclass) — call site already uses keyword-argument construction, no change.

**Dependencies:** Phase 1 (FileEntry and CrawlManifest must be dataclasses first).

**Done when:** `tests/crawler/test_main.py` passes; AC2.1 through AC2.4 covered.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Converter engine accumulation types

**Goal:** Replace `list[tuple[str, int, int]]` and `dict[str, dict]` accumulators in
`converter/engine.py` with typed frozen dataclasses.

**Components:**
- `FileConversionSuccess` (new) in `src/pipeline/converter/engine.py` — frozen dataclass with
  `.filename: str`, `.row_count: int`, `.bytes_written: int`.
- `FileConversionFailure` (new) in `src/pipeline/converter/engine.py` — frozen dataclass with
  `.error_class: str`, `.message: str`, `.at: str`, `.converter_version: str`.
- `successes: list[FileConversionSuccess]` — list accumulator updated; tuple construction at
  `successes.append(...)` replaced with dataclass instantiation.
- `failures: dict[str, FileConversionFailure]` — dict value type updated; dict literal construction
  in the except block replaced with dataclass instantiation.
- All aggregations (`total_rows`, `total_bytes`, `converted_files`) updated to use attribute access.
- `patch_body` and `event_payload` construction updated: `dataclasses.asdict(f)` for failure
  values, attribute access for success aggregation.

**Dependencies:** None (engine.py has no import-time dependency on Phase 1 or 2 changes).

**Done when:** `tests/converter/test_engine.py` passes; AC3.1 through AC3.5 covered.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: Registry API — db layer return types

**Goal:** Define `DeliveryRecord`, `TokenRecord`, and `EventRecord` frozen dataclasses and update
all `db.py` query functions to return them instead of `dict` / `list[dict]`.

**Components:**
- `src/pipeline/registry_api/records.py` (new file) — defines `DeliveryRecord`, `TokenRecord`,
  `EventRecord` frozen dataclasses matching the SQLite column shapes. `DeliveryRecord.metadata` is
  typed `dict` (already deserialized from JSON by `_deserialize_metadata`).
- `get_delivery` — return type `DeliveryRecord | None`.
- `list_deliveries` — return type `tuple[list[DeliveryRecord], int]`.
- `get_actionable` — return type `list[DeliveryRecord]`.
- `update_delivery` — return type `DeliveryRecord | None`.
- `upsert_delivery` — return type `DeliveryRecord | None` (input remains `dict`).
- `get_token_by_hash` — return type `TokenRecord | None`.
- `insert_event` — return type `EventRecord`.
- `get_events_after` — return type `list[EventRecord]`.
- `delivery_exists` — unchanged (returns `bool`, no dict involved).
- Internal helper `_deserialize_metadata` refactored to take a `dict` and return a `DeliveryRecord`
  rather than mutating in-place; or removed and inlined into each query function.

**Dependencies:** None (db.py has no import from Phase 1–3 modules).

**Done when:** `tests/registry_api/test_db.py` passes; AC4.1, AC4.2, AC4.3, AC4.4, AC4.8 covered.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Registry API — callers of db layer updated

**Goal:** Update `routes.py` and `auth.py` to consume `DeliveryRecord`, `TokenRecord`, and
`EventRecord` dataclasses via attribute access and explicit `model_validate` calls.

**Components:**
- `src/pipeline/registry_api/routes.py` — all sites that pass a db-layer return value to a Pydantic
  constructor change to `DeliveryResponse.model_validate(dataclasses.asdict(record))` (or the
  equivalent `EventRecord` / list paths). Pagination responses (`PaginatedDeliveryResponse`) built
  from lists of `DeliveryRecord` similarly.
- `src/pipeline/registry_api/auth.py` — `get_token_by_hash` result consumed via attribute access
  (`.username`, `.role`, `.revoked_at`) instead of dict subscript.
- `src/pipeline/registry_api/models.py` — `EventRecord` Pydantic model in `models.py` currently
  shares a name with the new db-layer dataclass; the db-layer type is renamed `EventRow` (in
  `records.py`) to avoid shadowing the Pydantic model on import.

**Dependencies:** Phase 4 (records.py and updated db.py return types must exist first).

**Done when:** `tests/registry_api/test_routes.py`, `tests/registry_api/test_auth.py`,
`tests/registry_api/test_events.py` pass; AC4.5, AC4.6, AC4.7, AC5.1, AC5.2 covered.
<!-- END_PHASE_5 -->

## Additional Considerations

**Name collision — `EventRecord`:** `pipeline.registry_api.models` already defines a Pydantic
`EventRecord`. The new db-layer dataclass for the events table should be named `EventRow` in
`records.py` to avoid shadowing it on import in `routes.py`.

**`_deserialize_metadata` mutation pattern:** The current helper mutates a dict in-place. When the
return type becomes a dataclass (frozen, immutable), the helper must change to construct and return
a new `DeliveryRecord` from the mutated intermediate dict rather than modifying it. This is a
small internal refactor with no external visibility.

**`upsert_delivery` input type:** The function's callers (`routes.py` via `data.model_dump()`,
crawler via a plain dict) both pass plain dicts. Changing the input type to a dataclass would
require updating all callers; the issue scope explicitly targets return types, not input types.
Input type remains `dict`.

**Test surface:** No test assertions depend on the concrete type of db return values (tests access
fields by key on the current dicts; after migration they will access by attribute). In practice,
`dict`-style subscript access on a dataclass raises `TypeError`, so any test using `result["field"]`
rather than `result.field` will fail. A quick grep for subscript access in test files should be
run before starting Phase 4 to identify any such cases.

**Serialization invariant for manifests:** `build_manifest` currently embeds `dict(f) for f in files`
to serialize `FileEntry` TypedDicts. After Phase 1 converts `FileEntry` to a dataclass,
`dict(f)` will raise `TypeError`. The correct replacement is `dataclasses.asdict(f)`. This is a
required change in Phase 1 — it is not deferred.
