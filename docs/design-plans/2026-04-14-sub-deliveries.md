# Sub-Delivery System Design

## Summary

Certain delivery types contain subsidiary data directories that travel with the parent delivery but need to be independently addressable downstream. For example, QAR and QMR deliveries contain an `scdm_snapshot/` subdirectory inside their terminal directory (`msoc/` or `msoc_new/`). This snapshot data passes and fails with its parent but consumers need to query, aggregate, and process it separately.

This design extends the lexicon system with a `sub_dirs` field that tells the crawler "after you match a terminal directory, also check for these known subdirectories and register them as separate deliveries with their own lexicon." Sub-deliveries get their own `delivery_id`, fingerprint, file inventory, and conversion tracking, but inherit their status from the parent's `dir_map` resolution. They are correlated to the parent by shared `(request_id, workplan_id, dp_id, version)`.

## Definition of Done

- Lexicon model supports a `sub_dirs` field mapping subdirectory names to lexicon IDs
- JSON Schema updated to define the `sub_dirs` field
- Loader validates `sub_dirs` references (referenced lexicon IDs must exist)
- Crawler discovers sub-directories inside matched terminal directories and registers them as separate deliveries
- Sub-deliveries inherit status from the parent terminal directory's `dir_map` resolution
- Sub-deliveries are independently queryable by `lexicon_id` (e.g., `soc.scdm`)
- Sub-deliveries are correlated to their parent by `(request_id, workplan_id, dp_id, version)`
- No database or API schema changes required — sub-deliveries are just deliveries with a different `lexicon_id`
- `soc.scdm` lexicon created, referenced from `soc.qar` and `soc.qmr` via `sub_dirs`

## Acceptance Criteria

### sub-deliveries.AC1: Lexicon model extension
- **sub-deliveries.AC1.1 Success:** `Lexicon` dataclass has a `sub_dirs` field of type `dict[str, str]` mapping directory name to lexicon ID
- **sub-deliveries.AC1.2 Success:** `sub_dirs` defaults to empty dict when not specified in JSON
- **sub-deliveries.AC1.3 Success:** `sub_dirs` survives inheritance — child inherits parent's `sub_dirs`, can override or extend via deep merge

### sub-deliveries.AC2: Loader validation
- **sub-deliveries.AC2.1 Success:** Lexicon with valid `sub_dirs` referencing an existing lexicon ID loads successfully
- **sub-deliveries.AC2.2 Failure:** Lexicon with `sub_dirs` referencing a non-existent lexicon ID fails with `LexiconLoadError`
- **sub-deliveries.AC2.3 Success:** Lexicon with no `sub_dirs` field loads successfully (backward compatible)
- **sub-deliveries.AC2.4 Failure:** `sub_dirs` entry where the referenced lexicon has its own `sub_dirs` is rejected (no recursive nesting)

### sub-deliveries.AC3: JSON Schema
- **sub-deliveries.AC3.1 Success:** `lexicon.schema.json` defines the `sub_dirs` field with correct structure
- **sub-deliveries.AC3.2 Success:** Existing lexicon files without `sub_dirs` still validate against the schema

### sub-deliveries.AC4: Crawler sub-directory discovery
- **sub-deliveries.AC4.1 Success:** Crawler finds `scdm_snapshot/` inside a matched terminal directory and creates a separate `ParsedDelivery` with `lexicon_id = "soc.scdm"`
- **sub-deliveries.AC4.2 Success:** Sub-delivery `source_path` is the full path including the sub-directory (e.g., `.../msoc/scdm_snapshot`)
- **sub-deliveries.AC4.3 Success:** Sub-delivery inherits `request_id`, `project`, `workplan_id`, `dp_id`, `version` from the parent
- **sub-deliveries.AC4.4 Success:** Sub-delivery inherits status from the parent's `dir_map` resolution (not from its own lexicon's `dir_map`)
- **sub-deliveries.AC4.5 Success:** Sub-delivery gets its own `delivery_id` (SHA-256 of its own `source_path`)
- **sub-deliveries.AC4.6 Success:** Sub-delivery gets its own file inventory and fingerprint
- **sub-deliveries.AC4.7 Edge:** If configured sub-directory doesn't exist on disk, no sub-delivery is created (not an error)
- **sub-deliveries.AC4.8 Success:** Sub-deliveries are included in the derive hook pass grouped by their own lexicon

### sub-deliveries.AC5: Integration
- **sub-deliveries.AC5.1 Success:** Sub-deliveries appear in `GET /deliveries?lexicon_id=soc.scdm`
- **sub-deliveries.AC5.2 Success:** Parent and sub-delivery are correlated by `(request_id, workplan_id, dp_id, version)`
- **sub-deliveries.AC5.3 Success:** Sub-deliveries appear in actionable query when their lexicon's `actionable_statuses` match
- **sub-deliveries.AC5.4 Success:** Events emitted for sub-deliveries with correct `lexicon_id`

### sub-deliveries.AC6: Lexicon files
- **sub-deliveries.AC6.1 Success:** `soc/scdm.json` lexicon exists, extends `soc._base`, no derive hook
- **sub-deliveries.AC6.2 Success:** `soc/qar.json` and `soc/qmr.json` include `sub_dirs: {"scdm_snapshot": "soc.scdm"}`

## Glossary

- **Sub-delivery**: A delivery registered from a known subdirectory inside a parent delivery's terminal directory. Has its own `delivery_id`, lexicon, fingerprint, and file inventory, but inherits status and metadata identity from the parent.
- **`sub_dirs`**: A lexicon field mapping subdirectory names to lexicon IDs. Tells the crawler to look inside matched terminal directories for additional deliveries.
- **Terminal directory**: The leaf directory matched by `dir_map` (e.g., `msoc`, `msoc_new`). Sub-directories are one level deeper.

## Architecture

The sub-delivery system is a thin extension of the existing lexicon + crawler architecture. No new database tables, no new API endpoints, no new event types. Sub-deliveries are just deliveries with a different `lexicon_id`.

**Directory structure:**

```
scan_root/<dpid>/packages/<request_id>/<version_dir>/msoc/
                                                     ├── file1.sas7bdat        ← parent delivery files
                                                     ├── file2.sas7bdat
                                                     └── scdm_snapshot/        ← sub-delivery
                                                         ├── snapshot1.sas7bdat
                                                         └── snapshot2.sas7bdat
```

**Lexicon configuration:**

```json
// soc/qar.json
{
  "extends": "soc._base",
  "derive_hook": "pipeline.lexicons.soc.qa:derive",
  "metadata_fields": {
    "passed_at": { "type": "datetime", "set_on": "passed" }
  },
  "sub_dirs": {
    "scdm_snapshot": "soc.scdm"
  }
}

// soc/scdm.json
{
  "extends": "soc._base"
}
```

**Data flow change:**

Current crawler flow for a matched terminal directory:
1. Match terminal dir via `dir_map` → create `ParsedDelivery`
2. Inventory files → fingerprint → write manifest → POST

Extended flow:
1. Match terminal dir via `dir_map` → create `ParsedDelivery` (parent)
2. Check `lexicon.sub_dirs` → for each configured sub-dir that exists on disk:
   - Create additional `ParsedDelivery` with sub-dir's lexicon ID and parent's status
   - Inventory files in sub-dir → fingerprint → write manifest → POST
3. Parent delivery inventories only its own direct files (not sub-dir contents)

**Key constraint: no recursive nesting.** A sub-delivery's lexicon cannot itself declare `sub_dirs`. This is validated at load time. One level of nesting is sufficient for the SCDM snapshot case and prevents complexity explosion.

**Derivation hooks and sub-deliveries:** Sub-deliveries participate in derivation independently of their parents. They are grouped by their own `lexicon_id` and passed to their own lexicon's `derive_hook` (if any). Since `soc.scdm` has no derive hook, SCDM snapshots will not be subject to version supersession logic — their status comes entirely from the parent's `dir_map` resolution. This is correct: the snapshot doesn't have an independent pass/fail lifecycle.

**Parent file inventory:** When a terminal directory has sub-directories configured in `sub_dirs`, the parent's file inventory (`inventory_files`) must exclude files inside those sub-directories. Currently `inventory_files` uses `os.scandir` which only returns direct children — no change needed. Sub-directory files are already excluded from the parent's inventory.

### Lexicon model change

```python
@dataclass(frozen=True)
class Lexicon:
    id: str
    statuses: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    dir_map: dict[str, str]
    actionable_statuses: tuple[str, ...]
    metadata_fields: dict[str, MetadataField]
    derive_hook: Callable | None = None
    sub_dirs: dict[str, str] = field(default_factory=dict)  # dir_name → lexicon_id
```

### Loader validation additions

After resolving and validating all lexicons, the loader adds one more validation pass:
1. For each lexicon with `sub_dirs`, verify every referenced lexicon ID exists in the resolved set
2. For each referenced sub-lexicon, verify it does not itself have `sub_dirs` (no recursive nesting)

### Crawler changes

In `main.py`, after creating a parent `ParsedDelivery` and inventorying its files:
1. Look up the parent's lexicon
2. For each `(sub_dir_name, sub_lexicon_id)` in `lexicon.sub_dirs`:
   - Check if `os.path.join(source_path, sub_dir_name)` exists
   - If yes: create a new `ParsedDelivery` with the sub-dir's source path, the sub-lexicon ID, and the parent's status
   - Inventory files in the sub-directory, fingerprint, write manifest, add to delivery lists

## Existing Patterns

This design follows established codebase patterns:

- **Lexicon model extension**: Adds a field to the existing `Lexicon` frozen dataclass, same pattern as `metadata_fields`
- **Loader validation**: New validation rules follow the existing batch-error-collection pattern in `_validate_lexicon`
- **Crawler delivery creation**: Sub-deliveries follow the exact same `ParsedDelivery` → inventory → fingerprint → manifest → POST flow as parent deliveries
- **No new tables or endpoints**: Sub-deliveries are just deliveries. The existing schema, API, and event system handle them without modification.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Lexicon model, loader, and schema

**Goal:** Add `sub_dirs` field to the `Lexicon` dataclass, update the loader to parse and validate it, update the JSON Schema, create the `soc.scdm` lexicon, and update `soc.qar`/`soc.qmr` with `sub_dirs` configuration.

**Components:**
- `src/pipeline/lexicons/models.py` — add `sub_dirs: dict[str, str]` field
- `src/pipeline/lexicons/loader.py` — parse `sub_dirs` from JSON, validate referenced lexicon IDs exist, reject recursive nesting
- `pipeline/lexicons/lexicon.schema.json` — add `sub_dirs` definition
- `pipeline/lexicons/soc/scdm.json` — new lexicon extending `soc._base`
- `pipeline/lexicons/soc/qar.json` — add `sub_dirs`
- `pipeline/lexicons/soc/qmr.json` — add `sub_dirs`

**Dependencies:** None

**Done when:** `sub_dirs` loads and validates correctly. Bad references caught. Recursive nesting rejected. Schema validates. Tests cover all AC1, AC2, AC3, and AC6 criteria.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Crawler sub-directory discovery

**Goal:** Crawler discovers configured sub-directories inside matched terminal directories and registers them as separate deliveries.

**Components:**
- `src/pipeline/crawler/main.py` — after parent delivery creation, check `sub_dirs` and create additional `ParsedDelivery` entries with their own inventory, fingerprint, manifest, and POST
- `src/pipeline/crawler/parser.py` — no changes (sub-delivery `ParsedDelivery` built in `main.py` using `dataclasses.replace` or direct construction)

**Dependencies:** Phase 1

**Done when:** Sub-deliveries discovered, inventoried, fingerprinted, manifested, and POSTed with correct `lexicon_id` and inherited status. Missing sub-directories skipped silently. Tests cover AC4.1–AC4.8.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Integration validation and documentation

**Goal:** Verify end-to-end integration, update documentation.

**Components:**
- Integration tests verifying sub-deliveries appear in API queries
- `src/pipeline/lexicons/CLAUDE.md` — update for `sub_dirs`
- `src/pipeline/crawler/CLAUDE.md` — update for sub-delivery discovery
- `CLAUDE.md` — update conventions section
- `README.md` — update lexicon documentation

**Dependencies:** Phase 2

**Done when:** Sub-deliveries queryable by `lexicon_id`, correlated to parent by shared metadata fields, events emitted correctly. Documentation updated. All tests pass. Tests cover AC5.1–AC5.4.
<!-- END_PHASE_3 -->

## Additional Considerations

**File inventory boundary:** `inventory_files` uses `os.scandir` which only returns direct children of a directory. This means the parent delivery's file inventory naturally excludes sub-directory contents. No special filtering needed.

**Conversion tracking:** Sub-deliveries have their own `parquet_converted_at` field. They can be converted independently of the parent. The actionable endpoint will surface them based on their own lexicon's `actionable_statuses`.

**Future sub-directory types:** The `sub_dirs` mechanism is generic. If other subsidiary data types emerge (e.g., a `compare/` directory), they can be added to the lexicon's `sub_dirs` without code changes — just a new lexicon file and a `sub_dirs` entry.

**Derive hook interaction:** Sub-deliveries participate in derivation grouped by their own lexicon. If `soc.scdm` later needs derivation logic (e.g., "fail SCDM snapshots when parent fails"), a derive hook can be added to the SCDM lexicon. For now, SCDM status comes purely from the parent's `dir_map` resolution.
