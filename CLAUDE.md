# QA Registry Pipeline

Last verified: 2026-04-14
Last context update: 2026-04-14

## Purpose

SAS-to-Parquet data pipeline for healthcare data arriving on a network share. Crawls directory structures that encode metadata (project, workplan, version, QA status), registers deliveries in SQLite, and converts SAS7BDAT files to Parquet.

## Tech Stack

- Python 3.10+ (target environment: RHEL, no Docker, no systemd)
- FastAPI + Uvicorn (registry API)
- SQLite via stdlib sqlite3 (registry backing store, WAL mode)
- pyreadstat + pyarrow (SAS-to-Parquet conversion, not yet implemented)
- websockets (WebSocket event stream)
- pytest + httpx (testing)
- hatchling (build system)

## Commands

- `uv run pytest` -- run all tests
- `uv run registry-api` -- start the registry API on port 8000
- `uv pip install -e ".[registry,dev]"` -- install with registry and dev deps
- `uv pip install -e ".[consumer]"` -- install event consumer deps (websockets, httpx)

## Project Structure

- `src/pipeline/` -- main package
  - `config.py` -- config loading with env var override (`PIPELINE_CONFIG`)
  - `json_logging.py` -- JSON structured logging (JsonFormatter + file/stderr handlers)
  - `registry_api/` -- FastAPI app, SQLite db, Pydantic models, routes, WebSocket event stream
  - `crawler/` -- filesystem crawler (see `src/pipeline/crawler/CLAUDE.md`)
  - `events/` -- reference EventConsumer for WebSocket + REST catch-up consumption
  - `converter/` -- SAS-to-Parquet converter (placeholder)
- `pipeline/` -- runtime config and scripts
  - `config.json` -- default pipeline configuration
  - `scripts/ensure_registry.sh` -- PID-based watchdog for registry API
- `tests/` -- mirrors src structure
- `docs/implementation-plans/` -- phased implementation plans
- `output/` -- pipeline output directory

## Conventions

- Functional Core / Imperative Shell pattern (files annotated with `# pattern:` comment)
- Delivery IDs are deterministic SHA-256 of source_path
- Config loaded lazily via module-level `__getattr__` on `pipeline.config.settings`
- QA status is tri-state: "pending", "passed", or "failed". Directories encode "pending" (msoc_new) and "passed" (msoc); "failed" is derived by the crawler when a newer version supersedes a pending delivery within the same workplan+dp_id
- Crawler uses a two-pass approach: (1) walk/parse/fingerprint/write manifests, (2) derive failed statuses then POST to registry
- Config fields `dp_id_exclusions`, `crawl_manifest_dir`, and `crawler_version` control crawler behaviour
- `ScanRoot` has `path`, `label`, and `target` fields; `target` (default `"packages"`) controls which subdirectory the crawler enters under each dpid during traversal
- Event stream uses WebSocket for real-time broadcast + REST GET /events for catch-up; events are persisted in SQLite with monotonic sequence numbers
- Events are emitted only for genuine state changes: delivery.created on first POST (not re-crawl), delivery.status_changed on qa_status transitions

## Boundaries

- Safe to edit: `src/`, `tests/`, `pipeline/config.json`
- Never touch: `spec.md` (upstream requirements), `uv.lock` (managed by uv)
