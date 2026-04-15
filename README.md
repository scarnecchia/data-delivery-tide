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

Lexicons define the status vocabulary for a delivery type. Each lexicon is a JSON file under `pipeline/lexicons/` that declares:

| Field | Purpose |
|-------|---------|
| `statuses` | Valid status values (e.g., `["pending", "passed", "failed"]`) |
| `transitions` | Allowed status transitions (e.g., `pending` can become `passed` or `failed`) |
| `dir_map` | Maps terminal directory names to statuses (e.g., `"msoc"` → `"passed"`) |
| `actionable_statuses` | Which statuses mean a delivery is ready for downstream processing |
| `metadata_fields` | Per-status metadata (e.g., `passed_at` auto-populated when status becomes `"passed"`) |
| `derive_hook` | Optional Python function for status derivation logic (e.g., marking superseded versions as failed) |
| `extends` | Inherit from another lexicon (child keys override, nested dicts merge) |

The current configuration ships with two lexicons:

- **`soc._base`** (`pipeline/lexicons/soc/_base.json`) — base lexicon defining the tri-state QA model (pending/passed/failed), directory mappings, and transitions
- **`soc.qar`** (`pipeline/lexicons/soc/qar.json`) — extends `soc._base`, adds `passed_at` metadata field and a derivation hook that marks pending deliveries as failed when superseded by a newer version

To add a new delivery type, create a new lexicon JSON file under `pipeline/lexicons/`, reference it in the scan root config, and optionally implement a derivation hook.

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
