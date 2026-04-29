# Loading Dock

Data delivery tracking and conversion pipeline for file-based deliveries arriving on a network share. Crawls directory structures that encode metadata (project, workplan, version, status), registers deliveries in a SQLite-backed registry API, streams lifecycle events over WebSocket, and converts SAS7BDAT files to Parquet.

The pipeline is delivery-type agnostic. Status semantics — valid statuses, transitions, directory mappings, metadata fields, and derivation logic — are defined by configurable **lexicons** (JSON files under `pipeline/lexicons/`), not hardcoded. The current configuration targets QA deliveries via the `soc.qar` lexicon. Adding a new delivery type means adding a new lexicon file — the core infrastructure doesn't change.

## How it works

```
Network Share                 Crawler                    Registry API
┌──────────────┐         ┌──────────────┐          ┌──────────────────┐
│ /project/    │         │              │  POST    │                  │
│   /workplan/ │ crawl   │  Walk dirs,  │─────────▶│  SQLite registry │
│     /dp_id/  │────────▶│  parse meta, │ lexicon_ │  (deliveries +   │
│       /v1/   │         │  fingerprint,│ id +     │   events tables) │
│         *.sas│         │  derive hook │ status   │                  │
└──────────────┘         └──────┬───────┘          └────────┬─────────┘
                               │                            │
                        ┌──────┴───────┐       ┌────────────┼────────────┐
                        │   Lexicons   │       │            │            │
                        │  (JSON cfg)  │  REST API     WebSocket     GET /events
                        │  dir_map,    │  (query)      /ws/events    (catch-up)
                        │  transitions,│       │       (live)            │
                        │  hooks       │       ▼            ▼            ▼
                        └──────────────┘  ┌─────────────────────────────────┐
                                          │     Downstream consumers       │
                                          └─────────────────────────────────┘
```

The crawler walks configured `scan_roots`, parses project/workplan/version/status from the directory structure using the lexicon's `dir_map`, and POSTs each delivery (with `lexicon_id` and `status`) to the registry API. The API validates statuses and transitions against the lexicon, auto-populates metadata fields on status transitions, and emits lifecycle events (`delivery.created`, `delivery.status_changed`) to connected WebSocket clients. Consumers can listen in real time or catch up on missed events via REST.

## Requirements

- Python 3.11+
- Network access to the source data share
- C compiler and Python dev headers for native extensions (see [Setup Guide](docs/setup-guide.md))

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[registry,converter,consumer]"
```

For a complete walkthrough — including first-time Python setup, authentication, and running in production — see the **[Setup Guide](docs/setup-guide.md)**.

## Installation

### With pip

```bash
pip install -e ".[registry,converter,consumer]"
```

| Extra       | What It Provides                                              |
|-------------|---------------------------------------------------------------|
| `registry`  | FastAPI + Uvicorn (the registry API server)                   |
| `converter` | pyreadstat + pyarrow + pandas (SAS-to-Parquet conversion)     |
| `consumer`  | websockets + httpx (event stream client, used by the daemon)  |
| `dev`       | pytest, httpx, ruff, mypy (testing and linting)               |

## Configuration

Copy and edit the default config:

```bash
cp pipeline/config.json pipeline/config.local.json
```

Override the config path with the `PIPELINE_CONFIG` environment variable:

```bash
export PIPELINE_CONFIG=pipeline/config.local.json
```

Key fields in `config.json`:

| Field | Purpose |
|-------|---------|
| `lexicons_dir` | Path to lexicon JSON definitions (relative to config file, default `lexicons`) |
| `scan_roots` | Directories to crawl, each with `path`, `label`, `lexicon`, and `target` |
| `registry_api_url` | Where the registry API listens (default `http://localhost:8000`) |
| `output_root` | Where converted Parquet files land |
| `db_path` | SQLite database location |
| `dp_id_exclusions` | Directory names to skip during crawl |

Each scan root's `lexicon` field references a lexicon ID (e.g., `"soc.qar"`) that must match a JSON file under `lexicons_dir`.

## Authentication

The registry API uses bearer token authentication. Manage tokens with the `registry-auth` CLI:

```bash
# Create a token (prints raw token to stdout — save it)
registry-auth add-user crawler --role write
registry-auth add-user dashboard --role read

# List users
registry-auth list-users

# Revoke or rotate
registry-auth revoke-user crawler
registry-auth rotate-token crawler
```

Roles: `admin` > `write` > `read`. The crawler needs `write`; read-only consumers need `read`.

### Crawler authentication

The crawler reads its token from the `REGISTRY_TOKEN` environment variable:

```bash
export REGISTRY_TOKEN=<token-from-add-user>
python -m pipeline.crawler.main
```

Without `REGISTRY_TOKEN`, the crawler will fail with a clear error message on the first POST attempt.

### API consumers

Pass the token as a bearer header:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/deliveries
```

The `/health` endpoint requires no authentication.

## Running

Start the registry API:

```bash
registry-api
```

This launches a FastAPI server on port 8000. The SQLite database is created automatically on first request.

Run tests:

```bash
pytest
```

## Converter (`registry-convert`, `registry-convert-daemon`)

Converts registered SAS7BDAT deliveries to Parquet files, writing output
in place under each delivery's `source_path/parquet/` directory. The
converter is status-blind: any delivery with null `parquet_converted_at`
and no `metadata.conversion_error` is eligible.

Requires the `converter` extra (and `consumer` for daemon mode):

```bash
pip install -e ".[converter,consumer]"
```

### Backfill CLI

Drain the unconverted backlog and exit:

```bash
registry-convert
```

Flags:

- `--limit N` — process at most N deliveries.
- `--shard I/N` — process only deliveries whose `delivery_id` hashes to shard `I` of `N`. Use for horizontal scale across multiple CLI invocations.
- `--include-failed` — re-attempt deliveries with `metadata.conversion_error` set (clears the field first).

Exits 0 on drain, 1 on registry unreachable, 130 on SIGINT.

### Daemon

Long-running event-driven service. Catches up on missed events via
`GET /events` on startup, then opens a WebSocket for steady-state
consumption. Persists `last_seq` after each processed event to
`converter_state_path`.

```bash
registry-convert-daemon
```

Use the watchdog script from cron to keep it running:

```bash
* * * * * cd /path/to/loading-dock && ./pipeline/scripts/ensure_converter.sh
```

Stop with `SIGTERM` or `SIGINT`: the daemon finishes the in-flight
conversion, persists state, and exits cleanly.

### Output layout

Every delivery — parent or sub — gets:

```
{source_path}/parquet/{source_path.name}.parquet
```

Each Parquet file carries the SAS column labels, value labels, and
declared encoding as file-level key-value metadata:

```python
import json
import pyarrow.parquet as pq
meta = pq.read_metadata("/path/to/parquet/x.parquet").metadata
column_labels = json.loads(meta[b"sas_labels"])
encoding      = meta[b"sas_encoding"].decode()
```

### Failure semantics

Classified failures are written to `metadata.conversion_error` on the
delivery row and broadcast as `conversion.failed` events. The converter
does not retry automatically. Operators clear the error by PATCHing
`{"metadata": {"conversion_error": null}}` on the delivery, or by
re-crawling (a new fingerprint clears the field via crawler upsert).

Error classes: `source_missing`, `source_permission`, `source_io`,
`parse_error`, `encoding_mismatch`, `schema_drift`, `oom`,
`arrow_error`, `unknown`.

### Configuration

New config fields (with defaults; all settable via `pipeline/config.json`):

| Field | Default | Purpose |
|-------|---------|---------|
| `converter_version` | `"0.1.0"` | Embedded in Parquet file metadata |
| `converter_chunk_size` | `100000` | Rows per pyreadstat chunk / Parquet row group |
| `converter_compression` | `"zstd"` | Parquet codec |
| `converter_state_path` | `"pipeline/.converter_state.json"` | Daemon `last_seq` persistence |
| `converter_cli_batch_size` | `200` | Page size for `GET /deliveries?converted=false` |
| `converter_cli_sleep_empty_secs` | `0` | (reserved for future poll-loop mode) |


## Lexicons

Lexicons define the status vocabulary for a delivery type. Different delivery types have different lifecycles — a QA package moves through `pending → passed / failed`, while a query package might move through `run → distributed → inputfiles_updated`. Lexicons make these differences configurable without changing the pipeline code.

Each lexicon is a JSON file under `pipeline/lexicons/`. The file's path determines its ID: `soc/qar.json` becomes `soc.qar`.

### Lexicon fields

| Field | Required | Purpose |
|-------|----------|---------|
| `statuses` | yes* | Valid status values (e.g., `["pending", "passed", "failed"]`) |
| `transitions` | yes* | Allowed status transitions — keys are source statuses, values are arrays of valid targets. Empty array = terminal state |
| `dir_map` | yes* | Maps terminal directory names to statuses (e.g., `"msoc"` → `"passed"`) |
| `actionable_statuses` | yes* | Which statuses mean a delivery is ready for downstream processing |
| `extends` | no | Inherit from another lexicon ID. Child keys override; nested dicts merge recursively. Max depth: 3 |
| `metadata_fields` | no | Fields auto-populated on status transitions (see below) |
| `derive_hook` | no | Python function for status derivation logic, as `"module.path:function"` |
| `sub_dirs` | no | Maps subdirectory names to lexicon IDs for sub-delivery registration |

*Required unless the lexicon uses `extends` to inherit these from a parent.

The format is defined by a JSON Schema at `pipeline/lexicons/lexicon.schema.json`. Include a `$schema` reference in your lexicon files for editor validation (autocompletion and inline errors in VS Code).

For a full guide on creating lexicons — including inheritance, metadata fields, derivation hooks, and sub-directories — see **[Creating Lexicons](docs/creating-lexicons.md)**.

### Shipped lexicons

- **`soc._base`** — base lexicon defining the tri-state QA model (pending/passed/failed), directory mappings, and transitions
- **`soc.qar`** — extends `soc._base`, adds `passed_at` metadata and a derivation hook that marks pending deliveries as failed when superseded by a newer version
- **`soc.qmr`** — extends `soc._base`, same additions as `soc.qar` for QMR deliveries
- **`soc.scdm`** — extends `soc._base`, minimal lexicon for SCDM snapshot sub-deliveries

## For consumers

The pipeline exposes three integration points:

### 1. Registry API

The registry API exposes delivery metadata over HTTP. Each delivery has a deterministic ID (SHA-256 of the source path), a `lexicon_id` identifying which lexicon governs it, a `status` validated against that lexicon, and `metadata` (a JSON dict that can be auto-populated by lexicon rules on status transitions).

Query the API at the configured `registry_api_url` (default `http://localhost:8000`). Standard HTTP — use `requests`, `httpx`, `curl`, or whatever your stack prefers.

### 2. Event stream

Instead of polling the registry API, you can subscribe to real-time delivery lifecycle events via WebSocket. The API broadcasts `delivery.created` and `delivery.status_changed` events to all connected clients at `/ws/events`. A REST catch-up endpoint (`GET /events?after=<seq>`) lets you retrieve any events missed during a disconnection.

A reference consumer is included at `src/pipeline/events/consumer.py`. It handles WebSocket streaming, REST catch-up, sequence-based deduplication, and automatic reconnection with backoff. To use it:

```bash
pip install -e ".[consumer]"
```

```python
from pipeline.events.consumer import EventConsumer

async def handle_event(event: dict) -> None:
    print(f"{event['event_type']}: {event['delivery_id']}")

consumer = EventConsumer("http://localhost:8000", on_event=handle_event)
await consumer.run()
```

### 3. Parquet files

Converted SAS7BDAT data lands under the configured `output_root`. File paths mirror the source directory structure, so you can derive the project, workplan, and version from the path.
