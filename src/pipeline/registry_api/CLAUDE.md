# Registry API

Last verified: 2026-04-10

## Purpose

Single source of truth for delivery state. Tracks which data partner deliveries have been seen, passed QA, and converted to Parquet. The crawler writes here; the converter reads actionable items from here.

## Contracts

- **Exposes**: REST API on port 8000 via FastAPI
  - Public (no auth):
    - `GET /health` -- health check
  - Protected (bearer token required, any role):
    - `GET /deliveries` -- list with filters (dp_id, project, qa_status, version="latest", etc.)
    - `GET /deliveries/actionable` -- passed QA but not yet converted
    - `GET /deliveries/{delivery_id}` -- single delivery by ID
  - Protected (bearer token required, write+ role):
    - `POST /deliveries` -- upsert a delivery (idempotent, keyed on source_path)
    - `PATCH /deliveries/{delivery_id}` -- partial update (parquet_converted_at, output_path, qa_status, qa_passed_at only)
- **Auth**: Bearer tokens hashed with SHA-256, stored in `tokens` table. Role hierarchy: admin > write > read. Revoked tokens return 401.
- **Guarantees**: delivery_id is SHA-256 of source_path (deterministic, stable). first_seen_at is never overwritten on upsert. last_updated_at only changes when fingerprint changes.
- **Expects**: SQLite database path from config. Callers provide valid Pydantic models and a valid bearer token for protected routes.

## Dependencies

- **Uses**: `pipeline.config.settings` for db_path
- **Used by**: crawler (POSTs deliveries with derived qa_status -- must supply write-role token), converter (will GET actionable + PATCH after conversion -- must supply write-role token), `pipeline.auth_cli` (manages tokens directly in SQLite)
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
- token_hash is SHA-256 of raw bearer token; raw tokens are never stored
- username has UNIQUE constraint in tokens table; one active token per user
- role is CHECK-constrained to "admin", "write", or "read"

## Key Files

- `main.py` -- FastAPI app with lifespan (schema init on startup), includes public_router and protected_router
- `db.py` -- all SQLite operations (init_db, upsert, get, list, actionable, update, get_token_by_hash); tokens table schema
- `models.py` -- Pydantic request/response models
- `routes.py` -- public_router (health) and protected_router (delivery endpoints with auth)
- `auth.py` -- bearer token validation (require_auth), role enforcement (require_role), TokenInfo model

## Gotchas

- `DbDep` type alias uses FastAPI's `Depends(get_db)` via `Annotated` -- don't call get_db directly in route handlers
- `AuthDep` type alias wraps `require_auth` via `Annotated[TokenInfo, Depends(require_auth)]`
- `require_role("write")` returns a `Depends()` -- assign it as a default parameter value, not as a type annotation
- version="latest" filter uses a correlated subquery (MAX version per dp_id+workplan_id), not application-level sorting
- The ensure_registry.sh watchdog uses PID files, not systemd -- check the pidfile if the API seems dead but won't restart
- Token management is via the `registry-auth` CLI (`pipeline.auth_cli`), not through the API -- there are no token management endpoints
