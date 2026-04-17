# SAS-to-Parquet Converter Design

## Summary

The SAS-to-Parquet converter is a new pipeline component that takes registered SAS7BDAT deliveries and converts them to Parquet files, writing output in place on the network share alongside the source data. It sits downstream of the registry: the crawler discovers files on disk and registers them; the converter reads those registrations, performs the format conversion, and writes results back to the registry row (`output_path`, `parquet_converted_at`) via PATCH. The converter does not inspect delivery status, apply lexicon rules, or stack data across deliveries — it is a dumb transformation engine whose only job is "SAS file in, Parquet file out, one delivery at a time."

This design adopts Shape A from the aggregation design notes: per-delivery Parquet files written in-place, with no hive layout and no cross-delivery aggregation. That keeps the converter's contract simple and deferrable — the `parquet/` subdirectory it creates under each delivery's source path is uniform enough that analysts can query it directly, and a future aggregation service can read from it without the converter knowing anything about that consumer. The component exposes two entry points sharing a single engine: a backfill CLI (`registry-convert`) for draining a pre-existing backlog and a long-running event-driven daemon (`registry-convert-daemon`) that subscribes to the registry's WebSocket event stream and converts deliveries as they arrive. Failures are classified into a fixed error taxonomy and written back to the registry row as `metadata.conversion_error`; nothing is retried automatically. A failed delivery stays skipped until an operator clears the error or the crawler re-registers the delivery with a new fingerprint.

## Definition of Done

- `src/pipeline/converter/` implements a SAS-to-Parquet converter split into functional core (`convert.py`, `classify.py`) and imperative shell (`engine.py`, `http.py`, `events.py`, `daemon.py`, `cli.py`).
- `convert.py` exposes a pure `convert_sas_to_parquet(source_path, output_path, ...) -> ConversionMetadata` function that streams chunks via `pyreadstat.read_file_in_chunks` and writes a single Parquet file with zstd compression, embedding SAS column labels, value labels, and encoding in Parquet file-level key-value metadata.
- Writes are atomic: tmp file + `os.replace`, with `finally` cleanup on exception.
- Output path for every delivery is `{source_path}/parquet/{stem}.parquet`, applied uniformly to parent and sub-deliveries.
- `classify.py` maps exceptions to a fixed set of error classes (`source_missing`, `source_permission`, `source_io`, `parse_error`, `encoding_mismatch`, `schema_drift`, `oom`, `arrow_error`, `unknown`).
- `engine.py` orchestrates one delivery: compute output path, call core, on success PATCH `output_path` + `parquet_converted_at` and emit `conversion.completed`; on failure classify, PATCH `metadata.conversion_error`, emit `conversion.failed`. No automatic retry.
- Two entry points wired in `pyproject.toml`: `registry-convert` (one-shot backfill CLI) and `registry-convert-daemon` (event-driven service subscribing to WebSocket with catch-up via `GET /events`).
- Conversion is status-blind: any delivery with null `parquet_converted_at` and no `conversion_error` is eligible.
- Serial processing; one delivery at a time per process.
- Events table CHECK constraint migrated to allow `conversion.completed` and `conversion.failed`.
- New config fields added with defaults: `converter_version`, `converter_chunk_size`, `converter_compression`, `converter_state_path`, `converter_cli_batch_size`, `converter_cli_sleep_empty_secs`.
- Registry HTTP client mirrors `crawler/http.py` (stdlib urllib, exponential backoff on 5xx only).
- Tests mirror crawler layout: `tests/converter/test_convert.py`, `test_classify.py`, `test_engine.py`, `test_cli.py`, `test_daemon.py`.
- Daemon persists `last_seq` after each processed event; resumes from persisted seq on restart.

## Acceptance Criteria

### sas-to-parquet-converter.AC1: Conversion core produces valid Parquet
- **sas-to-parquet-converter.AC1.1 Success:** `convert_sas_to_parquet` produces a Parquet file readable by `pq.read_table` with the same row count as the source SAS file
- **sas-to-parquet-converter.AC1.2 Success:** Output Parquet uses zstd compression by default (overridable via parameter)
- **sas-to-parquet-converter.AC1.3 Success:** SAS column labels are embedded in Parquet file-level metadata under key `sas_labels` as JSON; readable via `pq.read_metadata(path).metadata[b'sas_labels']`
- **sas-to-parquet-converter.AC1.4 Success:** SAS value labels embedded under key `sas_value_labels`; SAS encoding embedded under key `sas_encoding`; converter version embedded under key `converter_version`
- **sas-to-parquet-converter.AC1.5 Success:** Streaming write uses `pq.ParquetWriter` with one row group per chunk (default 100k rows)
- **sas-to-parquet-converter.AC1.6 Edge:** SAS file with no column labels produces Parquet with empty `sas_labels` dict (not missing key)

### sas-to-parquet-converter.AC2: Atomic writes and cleanup
- **sas-to-parquet-converter.AC2.1 Success:** Converter writes to `{stem}.parquet.tmp-{uuid}` then `os.replace` to final path
- **sas-to-parquet-converter.AC2.2 Failure:** Exception during chunked write unlinks the tmp file before re-raising
- **sas-to-parquet-converter.AC2.3 Failure:** Exception before writer opens does not leave a tmp file
- **sas-to-parquet-converter.AC2.4 Success:** Final Parquet path is exactly `{source_path}/parquet/{stem}.parquet`
- **sas-to-parquet-converter.AC2.5 Success:** Parent `parquet/` directory is created if missing

### sas-to-parquet-converter.AC3: Schema drift detection
- **sas-to-parquet-converter.AC3.1 Success:** Chunk 1 locks the schema; subsequent chunks matching the locked schema write successfully
- **sas-to-parquet-converter.AC3.2 Failure:** Chunk N with a dtype-mismatched column raises `SchemaDriftError` before writing that chunk
- **sas-to-parquet-converter.AC3.3 Failure:** On `SchemaDriftError`, tmp file is cleaned up

### sas-to-parquet-converter.AC4: Exception classification
- **sas-to-parquet-converter.AC4.1 Success:** `FileNotFoundError` classifies to `source_missing`
- **sas-to-parquet-converter.AC4.2 Success:** `PermissionError` classifies to `source_permission`
- **sas-to-parquet-converter.AC4.3 Success:** `OSError` (non-file-not-found, non-permission) classifies to `source_io`
- **sas-to-parquet-converter.AC4.4 Success:** `pyreadstat.ReadstatError` classifies to `parse_error`
- **sas-to-parquet-converter.AC4.5 Success:** `UnicodeDecodeError` classifies to `encoding_mismatch`
- **sas-to-parquet-converter.AC4.6 Success:** `SchemaDriftError` classifies to `schema_drift`
- **sas-to-parquet-converter.AC4.7 Success:** `MemoryError` classifies to `oom`
- **sas-to-parquet-converter.AC4.8 Success:** `pyarrow.ArrowException` classifies to `arrow_error`
- **sas-to-parquet-converter.AC4.9 Edge:** Any other `Exception` subclass classifies to `unknown`

### sas-to-parquet-converter.AC5: Engine orchestration and skip guards
- **sas-to-parquet-converter.AC5.1 Success:** Given a delivery with null `parquet_converted_at` and no `conversion_error`, engine converts and PATCHes `output_path` + `parquet_converted_at`, emits `conversion.completed`
- **sas-to-parquet-converter.AC5.2 Success:** Delivery with non-null `parquet_converted_at` and existing file is skipped (no work, no events)
- **sas-to-parquet-converter.AC5.3 Success:** Delivery with `metadata.conversion_error` set is skipped (no work, no events)
- **sas-to-parquet-converter.AC5.4 Failure:** Classified exception from core results in a PATCH writing `metadata.conversion_error = {class, message, at, converter_version}` and emitting `conversion.failed`
- **sas-to-parquet-converter.AC5.5 Failure:** No automatic retry occurs after a classified exception
- **sas-to-parquet-converter.AC5.6 Success:** Structured log line emitted per conversion attempt (success or failure) via `JsonFormatter`

### sas-to-parquet-converter.AC6: Events schema migration
- **sas-to-parquet-converter.AC6.1 Success:** Events table CHECK constraint allows insertion of `conversion.completed` and `conversion.failed` event types
- **sas-to-parquet-converter.AC6.2 Success:** `conversion.completed` payload contains `delivery_id`, `output_path`, `row_count`, `bytes_written`, `wrote_at`
- **sas-to-parquet-converter.AC6.3 Success:** `conversion.failed` payload contains `delivery_id`, `error_class`, `error_message`, `at`
- **sas-to-parquet-converter.AC6.4 Success:** Events broadcast via existing `ConnectionManager` to connected WebSocket clients

### sas-to-parquet-converter.AC7: Registry query surface
- **sas-to-parquet-converter.AC7.1 Success:** `GET /deliveries?converted=false&limit=N&after=delivery_id` returns only rows with null `parquet_converted_at`, paginated by `delivery_id`
- **sas-to-parquet-converter.AC7.2 Success:** PATCH with `metadata.conversion_error` deep-merges into existing metadata without clobbering other keys
- **sas-to-parquet-converter.AC7.3 Success:** PATCH with `metadata.conversion_error: null` (or equivalent) clears the error field

### sas-to-parquet-converter.AC8: Backfill CLI
- **sas-to-parquet-converter.AC8.1 Success:** `registry-convert` with empty backlog exits 0 immediately
- **sas-to-parquet-converter.AC8.2 Success:** `registry-convert` with N unconverted deliveries processes all N and exits
- **sas-to-parquet-converter.AC8.3 Success:** `--limit M` processes at most M deliveries and exits
- **sas-to-parquet-converter.AC8.4 Success:** `--shard I/N` only processes deliveries whose `delivery_id` falls into shard `I` of `N`
- **sas-to-parquet-converter.AC8.5 Success:** `--include-failed` re-attempts deliveries with `conversion_error` set (clears it on success)
- **sas-to-parquet-converter.AC8.6 Failure:** Registry unreachable results in non-zero exit code and no partial work

### sas-to-parquet-converter.AC9: Event-driven daemon
- **sas-to-parquet-converter.AC9.1 Success:** Daemon reads `last_seq` from `converter_state_path` on startup (defaults to 0 if missing)
- **sas-to-parquet-converter.AC9.2 Success:** Catch-up phase drains `GET /events?after={last_seq}` until empty before opening WebSocket
- **sas-to-parquet-converter.AC9.3 Success:** Each processed event persists the updated `last_seq` with fsync before the next event begins
- **sas-to-parquet-converter.AC9.4 Success:** Daemon ignores `delivery.status_changed` events (conversion is status-blind; only `delivery.created` triggers work)
- **sas-to-parquet-converter.AC9.5 Success:** WebSocket disconnect triggers reconnect with backoff
- **sas-to-parquet-converter.AC9.6 Success:** `SIGTERM` / `SIGINT` finishes the in-flight conversion, persists `last_seq`, exits cleanly
- **sas-to-parquet-converter.AC9.7 Success:** Daemon restarted mid-stream resumes from persisted `last_seq` without gaps or duplicate processing

### sas-to-parquet-converter.AC10: End-to-end integration
- **sas-to-parquet-converter.AC10.1 Success:** Crawler registers a delivery → daemon receives event → engine converts → registry row shows `parquet_converted_at` + `output_path` → Parquet file exists at expected path
- **sas-to-parquet-converter.AC10.2 Success:** Sub-delivery (e.g., `scdm_snapshot`) is converted independently with its own Parquet file at `{source_path}/parquet/{stem}.parquet`
- **sas-to-parquet-converter.AC10.3 Success:** `uv run pytest` passes with all new tests

## Glossary

- **delivery**: A single registered data package — one row in the registry SQLite database, identified by a deterministic SHA-256 of its `source_path`. Deliveries are discovered by the crawler from directory structures on the network share.
- **parent delivery / sub-delivery**: A terminal directory can contain named subdirectories declared in a lexicon's `sub_dirs` map (e.g., `scdm_snapshot/`). The crawler registers each subdirectory as a separate delivery correlated to the parent by shared identity fields. The converter treats parent and sub-deliveries identically — each gets its own `parquet/` output directory.
- **lexicon**: A JSON configuration file that defines the status semantics, valid transitions, directory-to-status mappings, actionable statuses, metadata fields, and optional derive hook for a family of deliveries. Lexicons are identified by namespaced IDs (e.g., `soc.qar`) and support single-level inheritance. The converter itself is status-blind and does not read lexicons; lexicon concepts appear here because they govern what the registry delivers to the converter.
- **scan root**: A configured entry point for the crawler — a directory path, a label, a lexicon ID, and a `target` subdirectory name. The crawler walks each scan root to discover deliveries.
- **terminal directory**: The deepest directory in a crawled path that the crawler treats as a delivery package boundary. Below a terminal directory, the crawler looks for sub-delivery subdirectories rather than continuing to recurse as a new delivery.
- **FCIS (Functional Core / Imperative Shell)**: An architectural pattern used throughout this codebase. Pure functions that perform computation without I/O form the "functional core" (`convert.py`, `classify.py`); modules that orchestrate I/O, HTTP calls, and side effects form the "imperative shell" (`engine.py`, `http.py`, `daemon.py`, `cli.py`). This separation makes the core fully unit-testable without mocks.
- **SAS7BDAT**: The binary file format used by SAS statistical software to store datasets. The format encodes column names, column labels, value labels, and a declared character encoding alongside the data. These files are the raw inputs the converter reads.
- **pyreadstat**: A Python library that wraps the ReadStat C library to read SAS7BDAT (and other statistical file formats) into pandas DataFrames. The converter uses its `read_file_in_chunks` API to stream large files without loading them fully into memory.
- **pyarrow / ParquetWriter / row group**: pyarrow is the Python interface to Apache Arrow, the in-memory columnar data format. `pq.ParquetWriter` writes Parquet files incrementally; each call to `write_table` appends one _row group_ — a horizontal slice of the file. Streaming one chunk at a time via `read_file_in_chunks` and writing each as a row group is how the converter handles files larger than available RAM.
- **zstd**: Zstandard — the default compression codec applied to Parquet output. It offers a better compression-ratio-to-decompression-speed tradeoff than gzip and is widely supported by Parquet readers. Configurable via `converter_compression`.
- **key-value metadata (Parquet)**: Parquet files carry an arbitrary string-to-bytes metadata map at the file level, separate from column schema. The converter stores SAS column labels (`sas_labels`), value labels (`sas_value_labels`), character encoding (`sas_encoding`), and `converter_version` here, readable via `pyarrow.parquet.read_metadata(path).metadata`.
- **WebSocket event stream / last_seq / catch-up**: The registry broadcasts state-change events (delivery created, status changed, conversion completed/failed) over a WebSocket connection, with each event assigned a monotonically increasing sequence number. The daemon persists `last_seq` after each processed event; on restart it calls `GET /events?after={last_seq}` to drain any events missed while offline before opening the WebSocket — this is the catch-up phase.
- **PATCH / deep-merge**: HTTP PATCH is used to update individual fields on a delivery row without replacing the entire row. The `metadata` field is a JSON dict; a PATCH that writes `metadata.conversion_error` must deep-merge into the existing metadata dict rather than overwriting it, preserving any other keys the crawler or other services have written.
- **CHECK constraint (SQLite)**: A column-level or table-level constraint in SQLite that rejects rows violating a condition. The events table currently has a CHECK constraint limiting the allowed `event_type` values. Adding `conversion.completed` and `conversion.failed` requires a schema migration to extend that constraint.
- **Shape A / Shape B**: Two candidate output layouts from the aggregation design notes. Shape A writes one Parquet file per delivery in-place (`{source_path}/parquet/{stem}.parquet`). Shape B writes directly into a hive-partitioned layout shared across deliveries, collapsing the need for a separate aggregation service. This design adopts Shape A.
- **schema drift**: When successive chunks of the same SAS file produce DataFrames with different column dtypes — typically caused by leading null values that cause pyreadstat to infer a different type for a column in a later chunk. The converter locks the schema after the first chunk and raises `SchemaDriftError` if a subsequent chunk mismatches, rather than silently widening types.
- **scdm_snapshot**: An example sub-delivery type declared in a lexicon's `sub_dirs` map — a subdirectory inside a terminal delivery directory that the crawler registers as a correlated but independent delivery. Referenced in the acceptance criteria as a concrete sub-delivery case for end-to-end testing.

## Architecture

The converter turns registered SAS7BDAT files into Parquet files, one delivery at a time, writing output in place on the network share. It is the dumb transformation engine in Shape A of the aggregation design notes: no hive layout, no cross-delivery stacking, no lexicon semantics. Status-blind by design.

**Package layout** (mirrors `src/pipeline/crawler/` FCIS split):

```
src/pipeline/converter/
  __init__.py
  convert.py        # functional core: SAS path + output path -> ConversionMetadata
  classify.py       # functional core: Exception -> ErrorClass
  engine.py         # imperative shell: convert_one(delivery) orchestration
  http.py           # registry client (GET unconverted, PATCH row)
  events.py         # WebSocket subscriber + catch-up via GET /events
  daemon.py         # entry point: event-driven loop
  cli.py            # entry point: backfill walker
```

**Entry points.** One engine, two callers. `registry-convert` walks unconverted deliveries and exits. `registry-convert-daemon` subscribes to the registry's event stream, catches up any events missed since last shutdown, then streams forever. Both funnel into `engine.convert_one(delivery)`.

**Output layout.** For every delivery (parent or sub-delivery), the converter writes to `{delivery.source_path}/parquet/{stem}.parquet`. Analysts scanning the source tree can ignore `parquet/` subdirectories; their `*.sas7bdat` globs keep working. Sub-deliveries like `scdm_snapshot/` land their parquet files inside their own `parquet/` subdir nested under the parent's terminal directory.

**Conversion core contract.**

```python
def convert_sas_to_parquet(
    source_path: Path,
    output_path: Path,
    *,
    chunk_size: int = 100_000,
    compression: str = "zstd",
) -> ConversionMetadata: ...


@dataclass(frozen=True)
class ConversionMetadata:
    row_count: int
    column_count: int
    column_labels: dict[str, str]
    value_labels: dict[str, dict]
    sas_encoding: str
    bytes_written: int
    wrote_at: datetime
```

The core streams chunks from `pyreadstat.read_file_in_chunks` into `pa.Table.from_pandas`, appends each as a row group via `pq.ParquetWriter.write_table`, and embeds SAS labels / encoding in file-level key-value metadata before `writer.close()`. Atomic write: `{stem}.parquet.tmp-{uuid}` then `os.replace`. Schema locked after chunk 1; mismatches raise `SchemaDriftError`.

**Error classification core contract.**

```python
def classify_exception(exc: BaseException) -> ErrorClass: ...

ErrorClass = Literal[
    "source_missing", "source_permission", "source_io",
    "parse_error", "encoding_mismatch", "schema_drift",
    "oom", "arrow_error", "unknown",
]
```

Fallthrough to `unknown` ensures every failure produces a classified event and metadata entry.

**Engine orchestration.** Given a delivery dict from the registry:

1. Skip if `parquet_converted_at` is set and file exists, or if `metadata.conversion_error` is set.
2. Compute output path from `source_path`.
3. Call `convert_sas_to_parquet` in a try/except.
4. On success: PATCH `{output_path, parquet_converted_at}`, emit `conversion.completed`.
5. On failure: `classify_exception`, PATCH `{metadata.conversion_error: {class, message, at, converter_version}}`, emit `conversion.failed`. No retry.

**Failure re-queue semantics.** A delivery with `conversion_error` is skipped. The error clears either by an operator PATCH or by the crawler updating the delivery (new fingerprint on redelivery → existing PATCH logic clears the field). The next daemon cycle or CLI pass then picks it up.

**Registry interaction.**

CLI work discovery:
```
GET /deliveries?converted=false&limit={N}&after={delivery_id}
```

Daemon work discovery:
```
GET /events?after={last_seq}&limit=1000   # catch-up on startup
WebSocket                                  # steady state
```

Success PATCH:
```
PATCH /deliveries/{delivery_id}
{"output_path": "...", "parquet_converted_at": "<ISO8601>"}
```

Failure PATCH:
```
PATCH /deliveries/{delivery_id}
{"metadata": {"conversion_error": {"class": "...", "message": "...", "at": "...", "converter_version": "..."}}}
```

**Event contracts.** Two new event types require CHECK constraint migration in `src/pipeline/registry_api/db.py`:

```
conversion.completed   payload: {delivery_id, output_path, row_count, bytes_written, wrote_at}
conversion.failed      payload: {delivery_id, error_class, error_message, at}
```

Events written via the existing `insert_event()` and broadcast via the existing `ConnectionManager`. The converter emits events via its own `events.py` client that calls a registry endpoint or uses the shared module — exact split decided in Phase 1 of implementation based on what's already callable.

**Concurrency.** Serial. One delivery per process. Memory footprint of a multi-GB SAS file conversion makes parallel workers risky on a RHEL server without cgroups. Horizontal scale via `--shard I/N` on the CLI or multiple daemon instances keyed on delivery_id prefix if backlog grows.

**Daemon lifecycle.** Persisted `last_seq` in `pipeline/.converter_state.json` (path configurable). On startup, drain `GET /events?after={last_seq}` until empty, then open WebSocket. On `SIGTERM`/`SIGINT`, finish current conversion, persist `last_seq`, exit. Watchdog via `pipeline/scripts/ensure_converter.sh` analogous to `ensure_registry.sh`.

## Existing Patterns

This design follows established codebase patterns identified by investigation:

- **Functional Core / Imperative Shell split.** `src/pipeline/crawler/` annotates files with `# pattern:` comments separating pure functions (`parser.py`, `fingerprint.py`, `manifest.py`) from I/O and orchestration (`main.py`, `http.py`). The converter mirrors this split exactly.
- **Stdlib HTTP client with backoff.** `src/pipeline/crawler/http.py` uses `urllib` directly (no `requests` dep), raises `RegistryUnreachableError` / `RegistryClientError`, retries on 5xx with exponential backoff (2/4/8s, 3 attempts). `converter/http.py` mirrors this shape.
- **Pydantic models at the registry boundary.** Crawler POSTs `DeliveryCreate` models. Converter PATCHes using the same model types (or equivalently shaped dicts) exported from `src/pipeline/registry_api/models.py`.
- **Lazy config loading.** `pipeline.config.settings` is accessed via module-level `__getattr__` (see `src/pipeline/config.py:90-96`). New converter config fields follow the same pattern — added to the config schema, loaded on first access.
- **JSON structured logging.** `src/pipeline/json_logging.py` provides `JsonFormatter` with file + stderr handlers configured against `log_dir`. Converter emits one structured line per conversion (success or failure).
- **Test layout.** `tests/` mirrors `src/pipeline/`. Functional core tested with pure-function tests (no fixtures beyond `tmp_path`). Shell tested with `TestClient` or mocked HTTP. `pytest-asyncio` for async route tests.
- **Events persisted via `insert_event` + broadcast via `ConnectionManager`.** Existing pattern in `src/pipeline/registry_api/routes.py`. Converter events reuse this machinery; only the CHECK constraint changes.
- **Existing registry schema already fits.** `parquet_converted_at` and `output_path` columns exist on the delivery row. An `idx_actionable` index already covers `(lexicon_id, status, parquet_converted_at)` — usable for "find unconverted deliveries" queries. No new tables or columns needed beyond the events CHECK-constraint migration.

No divergence from existing patterns. The converter is a new service that looks structurally identical to the existing crawler, differing only in what it does inside the core.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Registry surface area + events migration

**Goal:** Establish the registry-side contract the converter depends on before building the converter itself.

**Components:**
- `src/pipeline/registry_api/db.py` — migrate `events` table CHECK constraint to allow `conversion.completed` and `conversion.failed`
- `src/pipeline/registry_api/models.py` — event payload models for conversion events; PATCH model supports `output_path`, `parquet_converted_at`, and deep-merge of `metadata` (verify or extend existing behaviour)
- `src/pipeline/registry_api/routes.py` — `GET /deliveries?converted=false&after=&limit=` query support for backfill CLI
- `tests/registry_api/test_db.py`, `test_routes.py`, `test_models.py` — coverage for new event types, converted=false filter, metadata deep-merge

**Dependencies:** None.

**Done when:** Events CHECK migration applied cleanly on a fresh DB. `GET /deliveries?converted=false` returns only rows with null `parquet_converted_at`. Metadata PATCH deep-merges `conversion_error` without clobbering other metadata fields. Tests cover the ACs covered by this phase (sas-to-parquet-converter.AC6.1, AC6.2, AC7.1, AC7.2).
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Conversion core

**Goal:** Pure functions for SAS-to-Parquet conversion and exception classification, fully unit-testable without the registry.

**Components:**
- `src/pipeline/converter/__init__.py` — empty package marker
- `src/pipeline/converter/convert.py` — `convert_sas_to_parquet`, `ConversionMetadata`, `SchemaDriftError`. Chunked read via `pyreadstat.read_file_in_chunks`, streaming write via `pq.ParquetWriter`, atomic tmp-then-rename, embedded SAS labels in file-level metadata, zstd compression
- `src/pipeline/converter/classify.py` — `classify_exception`, `ErrorClass` literal type
- `tests/converter/__init__.py`, `conftest.py` — test fixtures (small generated SAS files via `pyreadstat.write_sas7bdat` or a tiny checked-in fixture dir)
- `tests/converter/test_convert.py` — happy path, chunked path, schema drift, embedded metadata round-trip, atomic cleanup on failure
- `tests/converter/test_classify.py` — exception-to-class mapping table

**Dependencies:** None (independent of Phase 1 — these are pure functions).

**Done when:** `convert_sas_to_parquet` produces a valid Parquet file with SAS labels readable via `pq.read_metadata(path).metadata`. Tmp file is cleaned up on any exception path. Schema drift across chunks raises `SchemaDriftError`. `classify_exception` maps every exception type in the DoD list and falls through to `unknown`. Tests cover sas-to-parquet-converter.AC1, AC2, AC3.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Engine + registry client

**Goal:** Imperative shell orchestrating one conversion end-to-end against the registry.

**Components:**
- `src/pipeline/converter/http.py` — urllib-based registry client with 2/4/8s backoff on 5xx; `PATCH /deliveries/{id}` for success and failure writes; mirrors `crawler/http.py`
- `src/pipeline/converter/engine.py` — `convert_one(delivery_id, http_client) -> ConversionResult`. Fetch delivery, skip guards, call core, PATCH, emit event. Structured logging on success and failure
- Config fields in `src/pipeline/config.py`: `converter_version`, `converter_chunk_size`, `converter_compression`, `converter_state_path`, `converter_cli_batch_size`, `converter_cli_sleep_empty_secs`
- `tests/converter/test_http.py` — retry ladder, error raising
- `tests/converter/test_engine.py` — happy path, skip guards (already converted, already errored), failure path writes classified error and emits `conversion.failed`, success path PATCHes and emits `conversion.completed`

**Dependencies:** Phase 1 (registry contract), Phase 2 (core).

**Done when:** Engine runs one delivery against a test registry, produces a Parquet file, PATCHes the row correctly, emits the right event. Failure injection produces classified errors on the delivery row without retry. Tests cover sas-to-parquet-converter.AC4, AC5.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: Backfill CLI

**Goal:** One-shot walker that drains the unconverted backlog and exits.

**Components:**
- `src/pipeline/converter/cli.py` — `main()` entry point. Options: `--limit`, `--shard I/N`, `--include-failed`. Pages through `GET /deliveries?converted=false` and calls `engine.convert_one` in order. Respects `converter_cli_sleep_empty_secs` for optional poll-loop mode
- `pyproject.toml` — register `registry-convert = "pipeline.converter.cli:main"`
- `tests/converter/test_cli.py` — backlog walk, empty-backlog exit, shard filtering, `--include-failed` override

**Dependencies:** Phase 3 (engine).

**Done when:** `uv run registry-convert` drains the backlog against a test registry. `--shard` correctly partitions deliveries by `delivery_id` prefix. `--include-failed` re-attempts errored deliveries. Tests cover sas-to-parquet-converter.AC8.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Event-driven daemon

**Goal:** Long-running service that converts as deliveries arrive.

**Components:**
- `src/pipeline/converter/events.py` — WebSocket subscriber + `GET /events?after=` catch-up client; yields events to the daemon loop
- `src/pipeline/converter/daemon.py` — `main()` entry point. Load `last_seq`, drain catch-up, open WebSocket, process events one at a time, persist `last_seq` after each. `SIGTERM`/`SIGINT` drains the in-flight delivery then exits
- `pyproject.toml` — register `registry-convert-daemon = "pipeline.converter.daemon:main"`
- `pipeline/scripts/ensure_converter.sh` — PID-based watchdog analogous to `ensure_registry.sh`
- `tests/converter/test_events.py`, `test_daemon.py` — catch-up drain, WebSocket event handling, `last_seq` persistence and resume, graceful shutdown

**Dependencies:** Phase 3 (engine), Phase 4 optional (CLI can be tested standalone).

**Done when:** Daemon connects to a test registry, processes a simulated event burst, persists seq, survives a restart mid-stream and resumes without gaps or duplicates. Graceful shutdown completes the in-flight conversion. Tests cover sas-to-parquet-converter.AC9.
<!-- END_PHASE_5 -->

<!-- START_PHASE_6 -->
### Phase 6: Integration + documentation

**Goal:** End-to-end validation and documentation updates.

**Components:**
- Integration test covering crawler → registry → converter (daemon) → PATCH flow end-to-end against a real SAS fixture
- `src/pipeline/converter/CLAUDE.md` — package conventions, patterns, config fields
- Root `CLAUDE.md` — note converter in Project Structure and Commands
- `README.md` — converter usage, CLI flags, config fields
- `pipeline/config.json` — document new fields inline or in a schema doc

**Dependencies:** Phases 1–5.

**Done when:** End-to-end integration test passes. All new config fields documented. `uv run pytest` passes cleanly. Tests cover sas-to-parquet-converter.AC10.
<!-- END_PHASE_6 -->

## Additional Considerations

**Shape decision.** This design adopts Shape A from `docs/design-plans/2026-04-16-aggregation-design-notes.md`: converter is local and dumb, no aggregation service, no hive layout. The aggregation notes file remains as a record of the exploration that led here; it is not a design plan and does not need to be preserved long-term.

**QA review use case.** The aggregation notes surfaced a human-in-the-loop QA review case that wants to query pending data. With status-blind conversion, any delivery with a Parquet file is queryable by reviewers pointing tools at the network share — the `parquet/` subdirectories are a discoverable, uniform layout. No separate "pending" path is needed.

**Cross-workplan supersession rule.** Shape A does not solve the `wp002 supersedes wp001` rule that surfaced in the aggregation notes. That rule remains unresolved and will need a follow-up design — likely as a registry query endpoint or a new derive hook at `(proj, wp_type, dp_id)` scope. Out of scope for this converter design.

**Schema drift frequency.** Real healthcare SAS deliveries can have chunk-to-chunk dtype differences in rare cases (nullable numerics with leading nulls). If `schema_drift` becomes a common classified error, Phase 2's schema-lock policy can be relaxed to promote types (e.g., int → float on null-introduction). Not worth engineering preemptively.

**Windows path semantics.** `os.replace` is atomic on POSIX and Windows 3.3+. The pipeline targets RHEL only, so cross-filesystem rename edge cases are not a concern — temp file is in the same directory as the final.
