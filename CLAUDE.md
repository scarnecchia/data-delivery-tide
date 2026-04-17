# QA Registry Pipeline

Last verified: 2026-04-16
Last context update: 2026-04-16

## Purpose

SAS-to-Parquet data pipeline for healthcare data arriving on a network share. Crawls directory structures that encode metadata (project, workplan, version, status), registers deliveries in SQLite, and converts SAS7BDAT files to Parquet. Status semantics (valid statuses, transitions, directory mappings, actionable states) are defined by configurable lexicons rather than hardcoded values.

## Tech Stack

- Python 3.10+ (target environment: RHEL, no Docker, no systemd)
- FastAPI + Uvicorn (registry API)
- SQLite via stdlib sqlite3 (registry backing store, WAL mode)
- pyreadstat + pyarrow (SAS-to-Parquet conversion)
- websockets (WebSocket event stream)
- pytest + pytest-asyncio + httpx (testing)
- hatchling (build system)

## Commands

- `uv run pytest` -- run all tests
- `uv run registry-api` -- start the registry API on port 8000
- `uv pip install -e ".[registry,dev]"` -- install with registry and dev deps
- `uv pip install -e ".[consumer]"` -- install event consumer deps (websockets, httpx)
- `uv pip install -e ".[converter]"` -- install SAS-to-Parquet converter deps (pyreadstat, pyarrow)
- `uv run registry-convert` -- drain unconverted deliveries backlog (backfill CLI)
- `uv run registry-convert --limit 10` -- process at most 10 deliveries
- `uv run registry-convert --shard 0/4` -- process shard 0 of 4 (horizontal split)
- `uv run registry-convert --include-failed` -- re-attempt errored deliveries
- `uv run registry-convert-daemon` -- start the event-driven converter daemon
- `pipeline/scripts/ensure_converter.sh` -- PID-based watchdog for the daemon

## Project Structure

- `src/pipeline/` -- main package
  - `config.py` -- config loading with env var override (`PIPELINE_CONFIG`)
  - `json_logging.py` -- JSON structured logging (JsonFormatter + file/stderr handlers)
  - `lexicons/` -- lexicon system: models, loader, domain hooks (see `src/pipeline/lexicons/CLAUDE.md`)
  - `registry_api/` -- FastAPI app, SQLite db, Pydantic models, routes, WebSocket event stream
  - `crawler/` -- filesystem crawler (see `src/pipeline/crawler/CLAUDE.md`)
  - `events/` -- reference EventConsumer for WebSocket + REST catch-up consumption
  - `converter/` -- SAS-to-Parquet converter (see `src/pipeline/converter/CLAUDE.md`)
- `pipeline/` -- runtime config and scripts
  - `config.json` -- default pipeline configuration
  - `lexicons/` -- lexicon JSON definitions (namespace directories, e.g. `soc/`)
  - `scripts/ensure_registry.sh` -- PID-based watchdog for registry API
- `tests/` -- mirrors src structure
- `docs/implementation-plans/` -- phased implementation plans
- `output/` -- pipeline output directory

## Conventions

- Functional Core / Imperative Shell pattern (files annotated with `# pattern:` comment)
- Delivery IDs are deterministic SHA-256 of source_path
- Config loaded lazily via module-level `__getattr__` on `pipeline.config.settings`
- Status semantics are defined by lexicons, not hardcoded. Each lexicon declares valid statuses, allowed transitions, directory-to-status mappings (`dir_map`), actionable statuses, metadata fields, and an optional `derive_hook`. Lexicon JSON files live in `pipeline/lexicons/` and support single-level inheritance via `extends`
- Lexicons can declare `sub_dirs` mapping subdirectory names to lexicon IDs; the crawler discovers these inside terminal directories and registers them as separate deliveries correlated to the parent by shared identity fields
- Crawler uses a two-pass approach: (1) walk/parse/fingerprint/write manifests, (2) derive statuses via lexicon hooks then POST to registry
- Config fields `dp_id_exclusions`, `crawl_manifest_dir`, `crawler_version`, and `lexicons_dir` control crawler behaviour
- `ScanRoot` has `path`, `label`, `lexicon`, and `target` fields; `target` (default `"packages"`) controls which subdirectory the crawler enters under each dpid; `lexicon` references a lexicon ID (e.g. `"soc.qar"`)
- Event stream uses WebSocket for real-time broadcast + REST GET /events for catch-up; events are persisted in SQLite with monotonic sequence numbers
- Events are emitted only for genuine state changes: delivery.created on first POST (not re-crawl), delivery.status_changed on status transitions
- Database stores `lexicon_id`, `status`, and `metadata` (JSON dict) per delivery instead of the former `qa_status`/`qa_passed_at` columns
- Converter writes per-delivery Parquet at `{source_path}/parquet/{stem}.parquet` — Shape A from `docs/design-plans/2026-04-16-aggregation-design-notes.md`. No hive layout, no cross-delivery aggregation.
- Converter event emission flows through `POST /events` (not PATCH side-effects), keeping registry as the single event writer while allowing converter-computed payload fields.

## Boundaries

- Safe to edit: `src/`, `tests/`, `pipeline/config.json`
- Never touch: `spec.md` (upstream requirements), `uv.lock` (managed by uv)
