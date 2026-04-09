# QA Registry Design

## Summary

The QA Registry is a lightweight HTTP API service that acts as a central tracking ledger for data deliveries moving through a quality assurance pipeline. Upstream crawlers register deliveries by POSTing file metadata; the registry records each delivery's QA status, file fingerprint, and conversion state in a local SQLite database, then exposes filtered query endpoints so downstream converter services can discover exactly which deliveries are ready to process. The goal is a single source of truth that decouples crawlers, converters, and any other consumers without requiring them to share a filesystem or a database connection.

The implementation is deliberately thin: FastAPI handles HTTP routing, Python's stdlib `sqlite3` is the backing store (no ORM, no migration framework), and the schema does just enough — deterministic IDs from path hashes, fingerprint-based change detection, and a dedicated `actionable` endpoint — to support the pipeline's workflow without over-engineering for requirements that don't exist yet.

## Definition of Done

1. **Monorepo scaffolding** — single `pyproject.toml` with `src/pipeline/` layout, optional dependency groups per service (`registry`, `converter`, `dev`), `[project.scripts]` entrypoints for each service, pytest configured
2. **Registry API service implemented** — FastAPI + SQLite backing store, all endpoints from the spec (GET/POST/PATCH deliveries, GET /health, GET /deliveries/actionable, query filters on GET /deliveries), data model with the `deliveries` table and indexes
3. **Test coverage** — pytest tests for the registry API covering endpoints, data model, query filters, and upsert logic
4. **Deployment scaffolding** — watchdog script (`ensure_registry.sh`), `config.json` structure

**Out of scope:** Crawler, converter, SAS schema generation, parquet conversion, CI/CD, auth

## Acceptance Criteria

### qa-registry.AC1: API Endpoints

- **qa-registry.AC1.1 Success:** `POST /deliveries` creates a new delivery and returns it with server-computed `delivery_id`
- **qa-registry.AC1.2 Success:** `POST /deliveries` with same `source_path` upserts (updates fields, preserves `first_seen_at`)
- **qa-registry.AC1.3 Success:** `GET /deliveries/{delivery_id}` returns the delivery
- **qa-registry.AC1.4 Failure:** `GET /deliveries/{delivery_id}` returns 404 for nonexistent ID
- **qa-registry.AC1.5 Success:** `PATCH /deliveries/{delivery_id}` updates only provided fields
- **qa-registry.AC1.6 Failure:** `PATCH /deliveries/{delivery_id}` returns 404 for nonexistent ID
- **qa-registry.AC1.7 Success:** `GET /health` returns `{"status": "ok"}`
- **qa-registry.AC1.8 Success:** `GET /deliveries/actionable` returns only deliveries with `qa_status=passed` and `parquet_converted_at IS NULL`

### qa-registry.AC2: Database & Query Logic

- **qa-registry.AC2.1 Success:** Upsert creates delivery with all metadata fields populated
- **qa-registry.AC2.2 Success:** Upsert preserves `first_seen_at` when re-inserting existing delivery
- **qa-registry.AC2.3 Success:** Upsert bumps `last_updated_at` when fingerprint changes
- **qa-registry.AC2.4 Success:** Upsert does NOT bump `last_updated_at` when fingerprint is unchanged
- **qa-registry.AC2.5 Success:** `list_deliveries` filters by each supported query param (`dp_id`, `project`, `request_type`, `workplan_id`, `request_id`, `qa_status`, `converted`, `scan_root`)
- **qa-registry.AC2.6 Success:** `version=latest` returns highest version per `(dp_id, workplan_id)`
- **qa-registry.AC2.7 Edge:** Multiple filters combine with AND semantics
- **qa-registry.AC2.8 Edge:** Empty filter set returns all deliveries

### qa-registry.AC3: Validation & Error Handling

- **qa-registry.AC3.1 Failure:** `POST /deliveries` with missing required fields returns 422
- **qa-registry.AC3.2 Failure:** `POST /deliveries` with invalid `qa_status` value returns 422
- **qa-registry.AC3.3 Failure:** `PATCH /deliveries/{delivery_id}` with empty body is a no-op (not an error)
- **qa-registry.AC3.4 Success:** `delivery_id` is deterministic — same `source_path` always produces same ID

### qa-registry.AC4: Infrastructure

- **qa-registry.AC4.1 Success:** Config loads from `PIPELINE_CONFIG` env var, falls back to `pipeline/config.json`
- **qa-registry.AC4.2 Success:** `ensure_registry.sh` is syntactically valid bash
- **qa-registry.AC4.3 Success:** `pip install -e ".[registry,dev]"` installs all dependencies and `registry-api` entrypoint is available

## Glossary

- **Delivery**: A discrete unit of work in the pipeline — a set of files from a specific data provider, associated with a workplan and request, that must be QA-checked and converted before downstream use.
- **Upsert**: An insert operation that updates an existing row instead of failing if the primary key already exists. Used here via SQLite's `INSERT ... ON CONFLICT ... DO UPDATE` syntax.
- **Fingerprint**: A SHA-256 hash of the sorted `(filename, mtime, size)` tuples for all files in a delivery directory. Used to detect whether the delivery's contents have changed between crawler runs without reading file data.
- **WAL mode**: Write-Ahead Logging — a SQLite journalling mode that allows concurrent reads during writes. Unsafe on network filesystems.
- **FastAPI**: A Python web framework for building HTTP APIs. Uses type annotations for automatic request validation and OpenAPI schema generation.
- **Pydantic**: A Python data validation library used by FastAPI. Schemas defined as `BaseModel` subclasses validate incoming request bodies and serialise outgoing responses.
- **Dependency injection (FastAPI)**: A pattern where FastAPI resolves function arguments automatically at request time — used here to manage SQLite connection lifecycle per request.
- **`src` layout**: A Python project structure where the package lives under `src/` rather than the repo root, preventing accidental imports of the uninstalled source.
- **hatchling**: A modern Python build backend used in `pyproject.toml` to define how the package is built and installed.
- **Optional dependency groups**: Named sets of extras in `pyproject.toml` (`[registry]`, `[converter]`, `[dev]`) that allow installing only the dependencies relevant to a given service.
- **`dp_id`**: Data provider identifier — the source organisation delivering files.
- **`workplan_id`**: Identifies the workplan a delivery belongs to — a planning artefact grouping related requests.
- **TestClient**: A FastAPI/Starlette utility that runs the app in-process for testing without a running server.
- **PID-based watchdog**: A shell script pattern that checks whether a process is still running by examining its PID file, restarting the service if the process is gone.
- **ISO 8601**: An international date/time string format (e.g. `2026-04-09T14:32:00Z`). Used for all timestamp columns.

## Architecture

### Approach: Thin Routes + Query Functions

Single Python package monorepo (`src/pipeline/`) with the registry API as the first implemented service. Internal architecture uses three core files: `routes.py` for endpoint definitions, `db.py` for SQLite connection management and standalone query functions, and `models.py` for Pydantic request/response schemas. Routes call db functions directly — no repository abstraction, no ORM.

FastAPI serves as the HTTP layer. SQLite (stdlib `sqlite3`) is the backing store, running in WAL mode on local disk. Connections are managed per-request via FastAPI dependency injection with `check_same_thread=False`.

### Data Flow

```
Crawler ──POST /deliveries──▶ Registry API ──sqlite3──▶ registry.db
                                    ▲
Converter ─GET /actionable──────────┘
           ─PATCH /deliveries/{id}──┘
                                    ▲
Consumers ─GET /deliveries──────────┘
```

The registry is the single source of truth. No service touches SQLite directly — all access goes through the API. This allows swapping the backing store later without changing any client.

### Data Model

The `deliveries` table extends the spec with two columns for change detection:

```sql
CREATE TABLE deliveries (
    delivery_id          TEXT PRIMARY KEY,  -- sha256 of source_path
    request_id           TEXT NOT NULL,
    project              TEXT NOT NULL,
    request_type         TEXT NOT NULL,
    workplan_id          TEXT NOT NULL,
    dp_id                TEXT NOT NULL,
    version              TEXT NOT NULL,
    scan_root            TEXT NOT NULL,
    qa_status            TEXT NOT NULL CHECK (qa_status IN ('pending', 'passed')),
    first_seen_at        TEXT NOT NULL,     -- ISO 8601
    qa_passed_at         TEXT,
    parquet_converted_at TEXT,
    file_count           INTEGER,
    total_bytes          INTEGER,
    source_path          TEXT NOT NULL UNIQUE,
    output_path          TEXT,
    fingerprint          TEXT,              -- sha256 of sorted (filename, mtime, size) tuples
    last_updated_at      TEXT               -- bumped when fingerprint changes on upsert
);

CREATE INDEX idx_actionable ON deliveries (qa_status, parquet_converted_at);
CREATE INDEX idx_dp_wp ON deliveries (dp_id, workplan_id);
CREATE INDEX idx_request_id ON deliveries (request_id);
```

`delivery_id` is a deterministic SHA-256 hex digest of `source_path`, making upserts idempotent. `fingerprint` is a SHA-256 hex digest of the sorted list of `(filename, mtime, size)` tuples for all files in the delivery directory — computed by the crawler and sent in the POST body. `last_updated_at` is bumped only when `fingerprint` changes, giving consumers a cheap "has anything changed" check.

Upsert uses `INSERT ... ON CONFLICT(delivery_id) DO UPDATE` with a CASE expression: `last_updated_at` updates only when `excluded.fingerprint != deliveries.fingerprint`. `first_seen_at` is preserved via `COALESCE(deliveries.first_seen_at, excluded.first_seen_at)`.

### API Contract

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness check. Returns `{"status": "ok"}`. No db hit. |
| `GET` | `/deliveries` | List deliveries with query filters. |
| `GET` | `/deliveries/actionable` | Convenience: `qa_status=passed AND parquet_converted_at IS NULL`. |
| `GET` | `/deliveries/{delivery_id}` | Single delivery by ID. 404 if not found. |
| `POST` | `/deliveries` | Upsert delivery (crawler calls this). Returns 200. |
| `PATCH` | `/deliveries/{delivery_id}` | Partial update (converter calls this). 404 if not found. |

**Query filters on `GET /deliveries`:** `dp_id`, `project`, `request_type`, `workplan_id`, `request_id` (exact match), `qa_status`, `converted` (boolean), `version` (exact or `latest`), `scan_root`. All optional. `version=latest` returns the highest version per `(dp_id, workplan_id)` group via SQL subquery.

**Request/response schemas (Pydantic):**

- `DeliveryCreate` — POST body: all parsed metadata fields + `source_path`, `qa_status`, `file_count`, `total_bytes`, `fingerprint`. `delivery_id` computed server-side.
- `DeliveryUpdate` — PATCH body: optional fields `parquet_converted_at`, `output_path`, `qa_status`, `qa_passed_at`.
- `DeliveryResponse` — full delivery record for all GET responses.
- `DeliveryFilters` — query params model with all filter fields optional.

### Configuration

`pipeline.config` module reads `config.json` from path specified by `PIPELINE_CONFIG` env var (default: `pipeline/config.json`). Parsed once at import, exposed as a module-level object. All services import from `pipeline.config`.

### Monorepo Structure

```
qa_registry/
├── pyproject.toml
├── spec.md
├── docs/
│   └── design-plans/
├── src/
│   └── pipeline/
│       ├── __init__.py
│       ├── config.py
│       ├── registry_api/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   ├── routes.py
│       │   ├── db.py
│       │   └── models.py
│       ├── crawler/
│       │   └── __init__.py
│       └── converter/
│           └── __init__.py
├── tests/
│   ├── conftest.py
│   └── registry_api/
│       ├── test_routes.py
│       └── test_db.py
├── pipeline/
│   ├── config.json
│   └── scripts/
│       └── ensure_registry.sh
└── output/
```

`src/pipeline/` is the Python package. `pipeline/` at root is runtime config and scripts — same name intentionally to match the spec's filesystem layout.

## Existing Patterns

Greenfield repository — no existing code patterns to follow. Design introduces:

- **src layout** with hatchling build backend — current Python packaging standard
- **FastAPI dependency injection** for database connection lifecycle
- **Standalone query functions** over repository classes — simplest pattern for a small API
- **Pydantic models** for request/response validation at the API boundary

These patterns are standard FastAPI idioms per current documentation and community practice.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Monorepo Scaffolding

**Goal:** Project structure, build configuration, and tooling so that `pip install -e ".[registry,dev]"` works and `pytest` runs (with zero tests).

**Components:**
- `pyproject.toml` — hatchling build backend, project metadata, optional dep groups (`registry`, `converter`, `dev`), `[project.scripts]` entrypoints, pytest config
- `src/pipeline/__init__.py` — package root
- `src/pipeline/registry_api/__init__.py` — registry subpackage
- `src/pipeline/crawler/__init__.py` — placeholder
- `src/pipeline/converter/__init__.py` — placeholder
- `tests/conftest.py` — empty initially
- `.gitignore` — standard Python ignores + `output/`, `pipeline/registry.db`, `*.egg-info`

**Dependencies:** None (first phase)

**Done when:** `pip install -e ".[registry,dev]"` succeeds, `pytest` runs and reports 0 tests collected, `python -c "import pipeline"` succeeds
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Configuration

**Goal:** Shared config loading that all services will use.

**Components:**
- `src/pipeline/config.py` — loads `config.json`, exposes typed config object
- `pipeline/config.json` — default config with placeholder paths

**Dependencies:** Phase 1

**Covers:** `qa-registry.AC4.1`

**Done when:** `from pipeline.config import settings` loads config, tests verify config loading and env var override
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Database Layer

**Goal:** SQLite schema initialisation, connection management, and all query functions.

**Components:**
- `src/pipeline/registry_api/db.py` — `init_db()`, `get_connection()` dependency, `upsert_delivery()`, `get_delivery()`, `list_deliveries()`, `get_actionable()`, `update_delivery()`
- `tests/registry_api/test_db.py` — unit tests against in-memory SQLite

**Dependencies:** Phase 2 (config for db path)

**Covers:** `qa-registry.AC2.1` through `qa-registry.AC2.8`

**Done when:** All query functions work correctly — upsert creates and updates, fingerprint change detection bumps `last_updated_at`, `first_seen_at` preserved, filters work, `version=latest` returns correct results, actionable query returns only passed+unconverted
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: Pydantic Models

**Goal:** Request/response schemas for the API boundary.

**Components:**
- `src/pipeline/registry_api/models.py` — `DeliveryCreate`, `DeliveryUpdate`, `DeliveryResponse`, `DeliveryFilters`

**Dependencies:** Phase 3 (needs to know db field shapes)

**Done when:** Models validate correct input, reject malformed input, serialise to/from JSON correctly
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: API Routes

**Goal:** All HTTP endpoints wired up and functional.

**Components:**
- `src/pipeline/registry_api/routes.py` — all 6 endpoints
- `src/pipeline/registry_api/main.py` — FastAPI app, lifespan handler for `init_db()`, `run()` entrypoint
- `tests/registry_api/test_routes.py` — integration tests via FastAPI TestClient
- `tests/conftest.py` — shared fixtures (`test_db`, `test_client`)

**Dependencies:** Phase 3, Phase 4

**Covers:** `qa-registry.AC1.1` through `qa-registry.AC1.6`, `qa-registry.AC3.1` through `qa-registry.AC3.4`

**Done when:** All endpoints return correct responses, error cases return appropriate status codes, TestClient integration tests pass
<!-- END_PHASE_5 -->

<!-- START_PHASE_6 -->
### Phase 6: Deployment Scaffolding

**Goal:** Watchdog script and runtime config ready for RHEL deployment.

**Components:**
- `pipeline/scripts/ensure_registry.sh` — PID-based watchdog script from spec, with configurable paths
- `pipeline/config.json` — updated with documentation comments for deployment

**Dependencies:** Phase 5

**Covers:** `qa-registry.AC4.2`

**Done when:** Watchdog script is syntactically valid (`bash -n`), config.json matches spec structure
<!-- END_PHASE_6 -->

## Additional Considerations

**SQLite WAL mode:** Enabled at `init_db()` time. Safe on local disk. Must not be used if `registry.db` is ever moved to NFS/CIFS — WAL requires shared memory that network filesystems cannot reliably provide.

**Fingerprint computation:** Not implemented in the registry — the crawler computes it and sends it in the POST body. The registry only stores, compares, and timestamps changes. This keeps fingerprint logic in the service that actually reads the filesystem.

**`version=latest` semantics:** Returns the highest version per `(dp_id, workplan_id)` group. Implemented as a SQL subquery with `MAX(version)` — relies on version format `v\d+` sorting correctly as text (works for `v01`-`v99`, would need casting for `v100+`).
