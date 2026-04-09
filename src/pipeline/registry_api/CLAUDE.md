# Registry API

Last verified: 2026-04-09

## Purpose

Single source of truth for delivery state. Tracks which data partner deliveries have been seen, passed QA, and converted to Parquet. The crawler writes here; the converter reads actionable items from here.

## Contracts

- **Exposes**: REST API on port 8000 via FastAPI
  - `POST /deliveries` -- upsert a delivery (idempotent, keyed on source_path)
  - `GET /deliveries` -- list with filters (dp_id, project, qa_status, version="latest", etc.)
  - `GET /deliveries/actionable` -- passed QA but not yet converted
  - `GET /deliveries/{delivery_id}` -- single delivery by ID
  - `PATCH /deliveries/{delivery_id}` -- partial update (parquet_converted_at, output_path, qa_status, qa_passed_at only)
  - `GET /health` -- health check
- **Guarantees**: delivery_id is SHA-256 of source_path (deterministic, stable). first_seen_at is never overwritten on upsert. last_updated_at only changes when fingerprint changes.
- **Expects**: SQLite database path from config. Callers provide valid Pydantic models.

## Dependencies

- **Uses**: `pipeline.config.settings` for db_path
- **Used by**: crawler (will POST deliveries), converter (will GET actionable + PATCH after conversion)
- **Boundary**: no imports from crawler or converter

## Key Decisions

- SQLite over Postgres: target environment has no managed database; single-writer is fine for this scale
- Upsert with fingerprint-based change detection: avoids unnecessary last_updated_at churn on re-crawls
- FastAPI dependency injection for db connections: per-request connections, closed automatically
- WAL mode: enables concurrent reads during writes

## Invariants

- delivery_id = SHA-256 of source_path (never random, never sequential)
- source_path has UNIQUE constraint; one delivery per path
- qa_status is always "pending", "passed", or "failed" (CHECK constraint)
- first_seen_at is immutable after initial insert (COALESCE preserves it on conflict)
- actionable = qa_status "passed" AND parquet_converted_at IS NULL

## Key Files

- `main.py` -- FastAPI app with lifespan (schema init on startup)
- `db.py` -- all SQLite operations (init_db, upsert, get, list, actionable, update)
- `models.py` -- Pydantic request/response models
- `routes.py` -- API route definitions

## Gotchas

- `DbDep` type alias uses FastAPI's `Depends(get_db)` via `Annotated` -- don't call get_db directly in route handlers
- version="latest" filter uses a correlated subquery (MAX version per dp_id+workplan_id), not application-level sorting
- The ensure_registry.sh watchdog uses PID files, not systemd -- check the pidfile if the API seems dead but won't restart
