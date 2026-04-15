# Lexicon System Design

## Summary

The lexicon system replaces a set of hardcoded, QA-specific fields (`qa_status`, `qa_passed_at`) with a configuration-driven delivery type system. Rather than encoding assumptions about what statuses exist, what directory names mean, and what metadata to capture directly in Python source, each delivery type is described by a JSON file — a "lexicon" — that declares all of this declaratively. The crawler, registry API, and event stream all read from these definitions at runtime instead of from code.

The implementation is structured as a layered replacement across the full pipeline. At the bottom, a loader reads lexicon JSON files from disk, resolves inheritance between them (child lexicons can extend a base to share common definitions), validates internal consistency, and imports optional Python derivation hooks for cross-delivery logic that can't be expressed declaratively. That loaded configuration is threaded upward into the config system, the SQLite schema, the API validation layer, the crawler's directory parsing, and finally the event payloads. The result is a pipeline where adding a new delivery type requires only a JSON file and a scan root entry — no Python changes needed unless custom derivation logic is required.

## Definition of Done

- Hardcoded `qa_status` and `qa_passed_at` fields replaced by a generic, lexicon-driven status system
- Each delivery type (e.g., `soc.qar`, `soc.qmr`, `soc.dgr`) defined by a JSON lexicon file with statuses, transitions, directory mappings, and metadata field rules
- Lexicon files support inheritance via `extends` for shared definitions across request types
- Crawler derives delivery status from lexicon `dir_map` instead of hardcoded `msoc`/`msoc_new`
- Optional Python derivation hooks for cross-delivery logic (e.g., version supersession)
- Registry API validates statuses and transitions at runtime against loaded lexicon definitions
- Lexicon-specific metadata (e.g., `passed_at` timestamp) stored as JSON, auto-populated on status transitions via `set_on` rules
- Actionable deliveries endpoint driven by per-lexicon `actionable_statuses` configuration
- Scan roots reference a lexicon ID; config validated at startup against loaded lexicons
- All validation errors reported at load time (fail fast, report all at once)
- Fresh database schema — no migration from old `qa_status`/`qa_passed_at` columns
- Event system payloads carry `lexicon_id`, `status`, and `metadata` instead of QA-specific fields
- Existing test coverage replaced with lexicon-aware equivalents; all tests pass

## Acceptance Criteria

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

### lexicon-system.AC2: Config integration
- **lexicon-system.AC2.1 Success:** Scan root with valid `lexicon` reference loads successfully
- **lexicon-system.AC2.2 Failure:** Scan root referencing non-existent lexicon ID fails at startup
- **lexicon-system.AC2.3 Failure:** Missing `lexicons_dir` in config fails at startup

### lexicon-system.AC3: Database schema
- **lexicon-system.AC3.1 Success:** Delivery created with `lexicon_id`, `status`, and `metadata` fields
- **lexicon-system.AC3.2 Success:** `metadata` JSON round-trips correctly through upsert and query
- **lexicon-system.AC3.3 Success:** Actionable query returns deliveries matching per-lexicon `actionable_statuses`
- **lexicon-system.AC3.4 Success:** Actionable query works across multiple lexicons with different actionable statuses
- **lexicon-system.AC3.5 Success:** List/filter deliveries by `lexicon_id` and `status`

### lexicon-system.AC4: API validation
- **lexicon-system.AC4.1 Success:** POST with valid status for lexicon succeeds
- **lexicon-system.AC4.2 Failure:** POST with status not in lexicon's `statuses` returns 422
- **lexicon-system.AC4.3 Success:** PATCH with legal transition succeeds
- **lexicon-system.AC4.4 Failure:** PATCH with illegal transition returns 422
- **lexicon-system.AC4.5 Success:** `set_on` metadata field auto-populated on matching status transition
- **lexicon-system.AC4.6 Edge:** PATCH that doesn't change status produces no event and no metadata auto-population

### lexicon-system.AC5: Crawler generalisation
- **lexicon-system.AC5.1 Success:** Terminal directory in `dir_map` maps to correct status
- **lexicon-system.AC5.2 Failure:** Terminal directory not in `dir_map` produces ParseError
- **lexicon-system.AC5.3 Success:** Derivation hook called when `derive_hook` is set
- **lexicon-system.AC5.4 Success:** No derivation when `derive_hook` is null
- **lexicon-system.AC5.5 Success:** QA hook marks superseded pending as failed (identical to current behaviour)
- **lexicon-system.AC5.6 Success:** Crawler POST payload includes `lexicon_id` and `status`

### lexicon-system.AC6: Event system
- **lexicon-system.AC6.1 Success:** `delivery.created` event payload contains `lexicon_id`, `status`, `metadata`
- **lexicon-system.AC6.2 Success:** `delivery.status_changed` event payload contains updated `status` and `metadata`
- **lexicon-system.AC6.3 Success:** Event payloads do not contain `qa_status` or `qa_passed_at`

### lexicon-system.AC7: Zero hardcoded QA references
- **lexicon-system.AC7.1 Success:** grep for `qa_status`, `qa_passed_at` in `src/` returns zero matches
- **lexicon-system.AC7.2 Success:** Full test suite passes

## Glossary

- **Lexicon**: A JSON configuration file that fully describes a delivery type — its valid statuses, legal transitions between them, directory-to-status mappings, metadata fields, and an optional derivation hook. The term is used throughout this document to mean both the file and the resolved in-memory `Lexicon` dataclass.
- **Delivery type**: A category of data deliveries distinguished by project and request type (e.g., `soc.qar`, `soc.qmr`). Each delivery type has exactly one lexicon.
- **`dir_map`**: A lexicon field mapping filesystem directory names (e.g., `msoc`, `msoc_new`) to status strings (e.g., `passed`, `pending`). The crawler uses this to assign status during directory traversal instead of matching against hardcoded names.
- **`set_on`**: A metadata field rule that triggers automatic population when a delivery transitions to a specified status. For example, `passed_at` is stamped with the current timestamp when status becomes `passed`.
- **`actionable_statuses`**: A per-lexicon list of statuses that indicate a delivery is ready for downstream processing (e.g., Parquet conversion). The API's actionable endpoint is driven entirely by this configuration.
- **Derivation hook**: An optional Python function referenced by dotted import path in a lexicon's `derive_hook` field. Called during the crawler's second pass to mutate delivery statuses based on cross-delivery logic — for example, marking a superseded pending delivery as failed.
- **`extends`**: A lexicon field declaring inheritance from a base lexicon. The loader performs a deep merge: the child's keys override the base's, all others are inherited. Chains are allowed up to depth 3.
- **Topological sort**: An ordering algorithm used by the lexicon loader to resolve inheritance — bases are fully resolved before any child that depends on them. Circular `extends` chains are detected and rejected.
- **Functional Core / Imperative Shell**: An architectural pattern used throughout the codebase. Pure functions (the "functional core") handle logic with no side effects; side-effectful code (the "imperative shell") calls them and handles I/O. The lexicon loader follows this pattern.
- **WAL mode**: SQLite's Write-Ahead Logging mode, used by the registry to allow concurrent reads during writes.
- **Two-pass crawler**: The crawler's design: Pass 1 walks directories, parses paths, fingerprints files, and writes manifests; Pass 2 runs derivation hooks and POSTs to the registry. The lexicon system slots into both passes without changing the structure.
- **Upsert**: A database operation that inserts a record if it doesn't exist or updates it if it does. The registry uses deterministic delivery IDs (SHA-256 of source path) to make upserts idempotent across re-crawls.
- **`dp_id`**: Data package identifier. Part of the directory structure encoded in the path, used alongside `workplan_id` for grouping deliveries during derivation.
- **Pydantic**: A Python data validation library used for the API's request/response models. Status validation currently uses Pydantic `Literal` types; the lexicon system moves this to runtime validation against loaded lexicon definitions.

## Architecture

Config-driven lexicon system that replaces hardcoded QA-specific fields with pluggable delivery type definitions. Each delivery type is defined by a JSON file that declares its statuses, valid transitions, directory-to-status mappings, metadata fields, and optionally a Python derivation hook for cross-delivery logic.

**Namespace convention:** `project.request_type` (e.g., `soc.qar`, `soc.qmr`), derived from the existing directory structure where `project` and `request_type` are already parsed from request IDs. Cross-project safe — identifiers are unique across Sentinel components.

**Lexicon file layout:**
```
pipeline/
  lexicons/
    soc/
      _base.json        # shared statuses, transitions, dir_map
      qar.json          # extends _base, adds metadata_fields
      qmr.json          # extends _base
      dgr.json          # extends _base, custom derive_hook
```

IDs derived from path: `soc/qar.json` → `soc.qar`, `soc/_base.json` → `soc._base`.

**Inheritance:** Child lexicons declare `"extends": "soc._base"`. Loader resolves base-first via topological sort, deep-merges dicts (child overrides base at key level). Chains allowed, capped at depth 3. `id` never inherited.

**Data flow:**

1. Startup: load config → load all lexicons from `lexicons_dir` → resolve inheritance → validate schemas → cross-validate scan root references
2. Crawl: walker reads terminal directory names → looks up in `lexicon.dir_map` → assigns status → optional `derive_hook` for cross-delivery logic → POST to registry with `lexicon_id` + `status`
3. Registry: validates status against lexicon on POST/PATCH → enforces transition rules on PATCH → auto-populates metadata via `set_on` rules → emits events with `lexicon_id`/`status`/`metadata`

### Lexicon definition contract

```python
@dataclass(frozen=True)
class MetadataField:
    type: str              # "datetime", "string", "boolean"
    set_on: str | None     # status that triggers auto-set, or None for manual

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

### Lexicon JSON schema (fully resolved example)

```json
{
  "id": "soc.qar",
  "extends": "soc._base",
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
  "actionable_statuses": ["passed"],
  "derive_hook": "pipeline.lexicons.soc.qa:derive",
  "metadata_fields": {
    "passed_at": {"type": "datetime", "set_on": "passed"}
  }
}
```

### Derivation hook contract

```python
def derive(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
    """Mutate statuses based on cross-delivery logic within a
    (workplan_id, dp_id) group. Return modified list."""
```

Hooks are optional. If `derive_hook` is `null`, statuses stay as parsed from directories. Hook output validated against `lexicon.statuses` after return.

### Database schema

**Deliveries table (replaces current):**

| Column | Type | Change |
|--------|------|--------|
| `delivery_id` | TEXT PRIMARY KEY | unchanged |
| `request_id` | TEXT NOT NULL | unchanged |
| `project` | TEXT NOT NULL | unchanged |
| `request_type` | TEXT NOT NULL | unchanged |
| `workplan_id` | TEXT NOT NULL | unchanged |
| `dp_id` | TEXT NOT NULL | unchanged |
| `version` | TEXT NOT NULL | unchanged |
| `scan_root` | TEXT NOT NULL | unchanged |
| `lexicon_id` | TEXT NOT NULL | **new** — references loaded lexicon |
| `status` | TEXT NOT NULL | **renamed** from `qa_status`, no CHECK constraint (validated at app layer) |
| `metadata` | TEXT DEFAULT '{}' | **new** — JSON blob replacing `qa_passed_at` |
| `first_seen_at` | TEXT NOT NULL | unchanged |
| `parquet_converted_at` | TEXT | unchanged |
| `file_count` | INTEGER | unchanged |
| `total_bytes` | INTEGER | unchanged |
| `source_path` | TEXT NOT NULL UNIQUE | unchanged |
| `output_path` | TEXT | unchanged |
| `fingerprint` | TEXT | unchanged |
| `last_updated_at` | TEXT | unchanged |

`qa_passed_at` column removed — lives inside `metadata` JSON as `{"passed_at": "2026-04-14T..."}`.

**Index changes:**
- `idx_actionable` → `(lexicon_id, status, parquet_converted_at)` — actionable queries scoped by lexicon
- `idx_dp_wp` stays: `(dp_id, workplan_id)` — derivation grouping
- New `idx_lexicon`: `(lexicon_id)` — filtering by delivery type

**Events table:** No schema change. Payloads carry updated field names (`lexicon_id`, `status`, `metadata` instead of `qa_status`, `qa_passed_at`).

### Config changes

```json
{
  "lexicons_dir": "pipeline/lexicons",
  "scan_roots": [
    {
      "path": "/requests/qa",
      "label": "QA Package Results",
      "lexicon": "soc.qar",
      "target": "packages"
    }
  ]
}
```

`ScanRoot` gains `lexicon: str` field. Validated at startup: every scan root's `lexicon` must resolve to a loaded lexicon.

### Loader contract

```python
def load_lexicon(lexicon_id: str, lexicons_dir: str) -> Lexicon
def load_all_lexicons(lexicons_dir: str) -> dict[str, Lexicon]
```

Responsibilities: discovery, inheritance resolution, hook import, schema validation. All validation errors collected and reported at once (not fail-on-first).

### API validation changes

- POST: load lexicon by `lexicon_id`, validate `status` ∈ `lexicon.statuses`
- PATCH: load lexicon from existing delivery's `lexicon_id`, validate transition is in `lexicon.transitions[old_status]`
- Metadata `set_on` rules applied automatically on status transitions
- GET actionable: builds WHERE clause dynamically from all loaded lexicons' `actionable_statuses`
- Pydantic models: `qa_status` → `status`, `qa_passed_at` removed, `lexicon_id` and `metadata` added

## Existing Patterns

This design follows established codebase patterns:

- **Config loading via `pipeline.config`**: `lexicons_dir` added as a new config field, loaded alongside existing fields. Lazy `__getattr__` pattern on `pipeline.config.settings` unchanged.
- **Dataclass models**: `Lexicon` and `MetadataField` follow the same frozen dataclass pattern as `ScanRoot` in `config.py`.
- **SQLite schema in `init_db`**: Schema changes follow the same `CREATE TABLE IF NOT EXISTS` pattern in `db.py`.
- **Pydantic models for API**: Updated models follow conventions in `models.py` (Literal types replaced with runtime validation).
- **Two-pass crawler**: Pass 1 (walk/parse/fingerprint) and Pass 2 (derive/POST) structure preserved. Derivation hooks slot into Pass 2 where `derive_qa_statuses` currently lives.
- **Event emission**: Same `delivery.created` / `delivery.status_changed` pattern. Only payload shape changes.

New patterns introduced:

- **Lexicon loader** (`src/pipeline/lexicons/loader.py`): New module for JSON file discovery, inheritance resolution, and schema validation. No existing equivalent, but follows the functional core pattern (pure functions, no side effects beyond file reads).
- **Runtime validation against config**: Currently status validation is compile-time via `Literal` types. Moves to runtime validation against loaded lexicon definitions. This is a deliberate trade-off: flexibility over static checking.
- **JSON metadata column**: Replaces fixed columns (`qa_passed_at`) with a generic JSON blob. Trades query simplicity for extensibility.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Lexicon schema and loader

**Goal:** Define the lexicon data model and build the loader that reads JSON files, resolves inheritance, imports hooks, and validates schemas.

**Components:**
- `src/pipeline/lexicons/__init__.py` — new subpackage
- `src/pipeline/lexicons/loader.py` — `load_lexicon()`, `load_all_lexicons()`, inheritance resolution, schema validation, hook import
- `src/pipeline/lexicons/models.py` — `Lexicon` and `MetadataField` frozen dataclasses
- `pipeline/lexicons/soc/_base.json` — QA base lexicon (current behaviour encoded as config)
- `pipeline/lexicons/soc/qar.json` — extends base, adds `passed_at` metadata field and derive hook

**Dependencies:** None (first phase)

**Done when:** Lexicon files load, inheritance resolves correctly, validation catches invalid schemas (bad status references, circular extends, missing hooks), and all errors reported in batch. Tests cover: valid load, inheritance merge, circular detection, invalid status references in transitions/dir_map/actionable_statuses/set_on, hook import success and failure.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Config integration

**Goal:** Wire lexicon loading into the config system and add `lexicon` field to `ScanRoot`.

**Components:**
- `src/pipeline/config.py` — add `lexicons_dir` config field, `lexicon` field on `ScanRoot`, cross-validation at load time
- `pipeline/config.json` — add `lexicons_dir`, update scan roots with `lexicon` references

**Dependencies:** Phase 1 (lexicon loader)

**Done when:** Config loads lexicons at startup, scan roots validated against loaded lexicons, missing/invalid lexicon references fail fast with clear errors. Tests cover: valid config with lexicons, missing lexicon reference, missing lexicons_dir.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Database schema update

**Goal:** Replace `qa_status`/`qa_passed_at` columns with generic `status`/`lexicon_id`/`metadata` columns.

**Components:**
- `src/pipeline/registry_api/db.py` — updated schema DDL, updated `upsert_delivery()`, `update_delivery()`, `list_deliveries()`, `get_actionable()` query functions
- `src/pipeline/registry_api/models.py` — updated Pydantic models (`DeliveryCreate`, `DeliveryUpdate`, `DeliveryResponse`, `DeliveryFilters`)

**Dependencies:** Phase 1 (lexicon models for type references)

**Done when:** Fresh DB creates with new schema. Upsert, update, list, and actionable queries work with `lexicon_id`/`status`/`metadata`. Pydantic models validate correctly. Tests cover: schema creation, CRUD operations with new fields, metadata JSON round-trip, actionable query with multiple lexicons.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: API route updates

**Goal:** Registry API validates statuses and transitions against loaded lexicon definitions at runtime.

**Components:**
- `src/pipeline/registry_api/routes.py` — POST validates `status` ∈ `lexicon.statuses`, PATCH validates transition legality, `set_on` metadata auto-population on status change
- `src/pipeline/registry_api/main.py` — lexicon loading at app startup, lexicons available to route handlers

**Dependencies:** Phase 2 (config with lexicons), Phase 3 (DB schema)

**Done when:** POST rejects invalid status for a lexicon, PATCH rejects illegal transitions, metadata auto-populated on `set_on` triggers, actionable endpoint queries across all lexicons. Tests cover: valid POST, invalid status rejection (422), valid transition, invalid transition rejection (422), `set_on` auto-population, actionable query with mixed lexicons.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Crawler generalisation

**Goal:** Crawler uses lexicon `dir_map` and derivation hooks instead of hardcoded QA logic.

**Components:**
- `src/pipeline/crawler/parser.py` — `parse_path()` receives lexicon, looks up terminal dir in `dir_map`; `derive_qa_statuses()` renamed to `derive_statuses()`, calls `lexicon.derive_hook` when present
- `src/pipeline/crawler/main.py` — `walk_roots()` collects terminal dirs matching lexicon `dir_map` keys; `crawl()` passes `lexicon_id` and `status` in POST payload
- `src/pipeline/crawler/manifest.py` — `CrawlManifest` updated: `qa_status` → `status`, adds `lexicon_id`
- `src/pipeline/crawler/__init__.py` — updated exports

**Dependencies:** Phase 2 (config with lexicons), Phase 4 (API accepts new fields)

**Done when:** Crawler parses directories using lexicon dir_map, calls derive hooks when defined, skips derivation when no hook, POSTs with `lexicon_id`/`status`. Tests cover: parsing with different dir_maps, derivation hook invocation, no-hook passthrough, unknown terminal dir produces ParseError, manifest shape.
<!-- END_PHASE_5 -->

<!-- START_PHASE_6 -->
### Phase 6: QA derivation hook

**Goal:** Implement the QA-specific "superseded pending → failed" derivation as a hook function.

**Components:**
- `src/pipeline/lexicons/soc/__init__.py` — new subpackage for soc-specific hooks
- `src/pipeline/lexicons/soc/qa.py` — `derive()` function implementing version supersession logic (extracted from current `derive_qa_statuses`)

**Dependencies:** Phase 5 (crawler calls hooks)

**Done when:** QA derivation hook produces identical results to current `derive_qa_statuses` for all test cases. Tests cover: superseded pending → failed, highest version stays pending, passed deliveries unaffected, single delivery (no supersession), hook validates output statuses.
<!-- END_PHASE_6 -->

<!-- START_PHASE_7 -->
### Phase 7: Event system alignment

**Goal:** Event payloads carry `lexicon_id`, `status`, and `metadata` instead of `qa_status`/`qa_passed_at`.

**Components:**
- `src/pipeline/registry_api/routes.py` — event emission uses updated delivery record shape
- `src/pipeline/events/consumer.py` — reference consumer handles updated payload shape

**Dependencies:** Phase 4 (routes emit with new fields)

**Done when:** Event payloads include `lexicon_id`, `status`, `metadata` and omit `qa_status`, `qa_passed_at`. Consumer processes updated payloads. Tests cover: `delivery.created` payload shape, `delivery.status_changed` payload shape, consumer handles new fields.
<!-- END_PHASE_7 -->

<!-- START_PHASE_8 -->
### Phase 8: Cleanup and end-to-end validation

**Goal:** Remove all remaining QA-specific hardcoding, run full test suite, validate end-to-end flow.

**Components:**
- All files in `src/pipeline/` — grep for `qa_status`, `qa_passed_at`, `msoc`, `msoc_new` — remove any remaining hardcoded references
- `tests/` — full test suite passes with lexicon-driven behaviour
- `src/pipeline/crawler/CLAUDE.md`, `src/pipeline/registry_api/CLAUDE.md` — update subdomain documentation

**Dependencies:** All prior phases

**Done when:** Zero hardcoded QA references remain in `src/`. Full test suite passes. End-to-end flow works: config loads → lexicons validated → crawler parses with dir_map → derivation hook runs → registry validates and stores → events emitted with correct shape.
<!-- END_PHASE_8 -->

## Additional Considerations

**Adding a new delivery type (workflow):** Create a JSON file in `pipeline/lexicons/<project>/`, optionally extending a base. Add a scan root with the `lexicon` reference. If custom derivation needed, write a hook function and reference it via `derive_hook`. No other code changes required.

**Metadata querying:** The `metadata` JSON column trades direct SQL filterability for flexibility. If querying by metadata fields (e.g., `passed_at`) becomes a performance concern, SQLite's `json_extract()` function can be used in WHERE clauses, or a generated column could be added for frequently-queried fields. Not needed at current scale.

**Validation strictness:** Moving from compile-time `Literal` types to runtime validation against lexicon config means type checkers won't catch invalid status strings. This is an acceptable trade-off for a system with 5-10+ delivery types — the alternative is code generation or dynamic type creation, both of which add more complexity than runtime validation.
