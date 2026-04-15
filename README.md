# Data Registry Pipeline

Data delivery tracking and event pipeline for file-based deliveries on a network share. Crawls directory structures that encode metadata (project, workplan, version, status), registers deliveries in a SQLite-backed registry API, streams lifecycle events over WebSocket, and converts SAS7BDAT files to Parquet.

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

- Python 3.10+
- Network access to the source data share

## Installation

### With pip

```bash
pip install -e ".[registry,consumer,dev]"
```

### With uv

```bash
uv pip install -e ".[registry,consumer,dev]"
```

The `registry` extra installs FastAPI and Uvicorn. The `converter` extra installs pyreadstat and pyarrow for SAS-to-Parquet conversion. The `consumer` extra installs websockets and httpx for event stream consumption. The `dev` extra adds pytest and httpx.

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

## Running

Start the registry API:

```bash
registry-api
```

This launches a FastAPI server on port 8000. The SQLite database is created automatically on first request.

Run tests:

```bash
pytest
# or
uv run pytest
```

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

### Creating a lexicon

**1. Define your status vocabulary.** What states can a delivery be in, and what transitions between them are valid?

**2. Create the JSON file.** Place it under `pipeline/lexicons/` in a namespace directory. For example, a query package lexicon at `pipeline/lexicons/requests/query_pkg.json` gets the ID `requests.query_pkg`:

```json
{
  "$schema": "../lexicon.schema.json",
  "statuses": ["run", "distributed", "inputfiles_updated"],
  "transitions": {
    "run": ["distributed"],
    "distributed": ["inputfiles_updated"],
    "inputfiles_updated": []
  },
  "dir_map": {
    "run": "run",
    "distributed": "distributed",
    "inputfiles_updated": "inputfiles_updated"
  },
  "actionable_statuses": ["distributed"]
}
```

**3. Wire it to a scan root** in `pipeline/config.json`:

```json
{
  "scan_roots": [
    {
      "path": "/data/requests/mplr",
      "label": "MPLR Requests",
      "lexicon": "requests.query_pkg",
      "target": "packages"
    }
  ]
}
```

That's it for a basic lexicon. The crawler will use `dir_map` to derive statuses from directories, and the registry API will enforce `transitions` on any PATCH.

### Inheriting from a base lexicon

If multiple delivery types share the same status model, define a base lexicon with a `_` prefix (convention, not enforced) and extend it:

```json
{
  "$schema": "../lexicon.schema.json",
  "extends": "soc._base",
  "metadata_fields": {
    "passed_at": {
      "type": "datetime",
      "set_on": "passed"
    }
  }
}
```

The child inherits `statuses`, `transitions`, `dir_map`, and `actionable_statuses` from the parent. Any field declared in the child overrides the parent; nested objects (like `transitions`) merge recursively.

### Metadata fields

Metadata fields are auto-populated when a delivery transitions to a specific status. They live in the delivery's `metadata` JSON dict (separate from the top-level `status` field).

Each metadata field specifies a `type` and a `set_on` status:

```json
"metadata_fields": {
  "passed_at": { "type": "datetime", "set_on": "passed" },
  "reviewed":  { "type": "boolean",  "set_on": "passed" },
  "outcome":   { "type": "string",   "set_on": "distributed" }
}
```

| Type | Value set on transition |
|------|------------------------|
| `datetime` | UTC ISO 8601 timestamp |
| `boolean` | `true` |
| `string` | The new status value |

Metadata is only populated via the registry API's PATCH endpoint when a status transition occurs. It is not set on initial delivery creation.

### Derivation hooks

A derive hook is a Python function that runs during the crawler's second pass, after directories are parsed but before POSTing to the registry. It can modify statuses based on cross-delivery logic (e.g., marking older versions as failed).

The function signature is:

```python
def derive(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
```

It receives all deliveries for a given lexicon and must return a new list (no mutation). Reference the hook in your lexicon as `"module.path:function"`:

```json
{
  "derive_hook": "pipeline.lexicons.soc.qa:derive"
}
```

### Sub-directories

Lexicons can declare `sub_dirs` to register subsidiary data (e.g., SCDM snapshots inside QAR deliveries) as separate deliveries with their own lexicon:

```json
{
  "sub_dirs": {
    "scdm_snapshot": "soc.scdm"
  }
}
```

The crawler checks for these directories inside matched terminal directories and registers them as independent deliveries correlated to the parent. Sub-deliveries get their own file inventory and conversion tracking.

Constraint: the target lexicon of a `sub_dirs` entry cannot itself declare `sub_dirs` (no recursive nesting).

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
