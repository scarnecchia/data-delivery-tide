# QA Registry Pipeline

SAS-to-Parquet data pipeline for healthcare data on a network share. Crawls directory structures that encode metadata (project, workplan, version, QA status), registers deliveries in SQLite, and converts SAS7BDAT files to Parquet.

## Requirements

- Python 3.10+
- Network access to the source data share

## Installation

### With pip

```bash
pip install -e ".[registry,dev]"
```

### With uv

```bash
uv pip install -e ".[registry,dev]"
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
| `scan_roots` | Directories to crawl, each with `path`, `label`, and `target` |
| `registry_api_url` | Where the registry API listens (default `http://localhost:8000`) |
| `output_root` | Where converted Parquet files land |
| `db_path` | SQLite database location |
| `dp_id_exclusions` | Directory names to skip during crawl |

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

## For consumers of the output

The pipeline produces two things downstream systems can use:

### 1. Parquet files

Converted SAS7BDAT data lands under the configured `output_root`. File paths mirror the source directory structure, so you can derive the project, workplan, and version from the path.

### 2. Registry API

The registry API exposes delivery metadata over HTTP. Each delivery has a deterministic ID (SHA-256 of the source path), QA status (`pending`, `passed`, or `failed`), and the metadata parsed from the directory structure.

Query the API at the configured `registry_api_url` (default `http://localhost:8000`). Standard HTTP — use `requests`, `httpx`, `curl`, or whatever your stack prefers.

### 3. Event stream (optional)

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
