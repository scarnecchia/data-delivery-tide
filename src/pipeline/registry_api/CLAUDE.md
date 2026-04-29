# Registry API

Last verified: 2026-04-17

## Purpose

Single source of truth for delivery state. Tracks which data partner deliveries have been seen, validated according to lexicon rules, and converted to Parquet. The crawler writes here; the converter reads actionable items from here. Emits lifecycle events via WebSocket broadcast and persists them in SQLite for consumer catch-up.

## Contracts

- **Exposes**: REST API on port 8000 via FastAPI
  - Public (no auth):
    - `GET /health` -- health check
  - Protected (bearer token required, any role):
    - `GET /deliveries` -- list with filters (dp_id, project, status, lexicon_id, version="latest", etc.); supports keyset pagination via `after=` and `limit=`
    - `GET /deliveries/actionable` -- status matches lexicon's actionable_statuses and not yet converted
    - `GET /deliveries/{delivery_id}` -- single delivery by ID
    - `GET /events?after={seq}&limit={n}` -- catch-up endpoint for events after a sequence number (limit default 100, max 1000)
  - Protected (bearer token required, write+ role):
    - `POST /deliveries` -- upsert a delivery (idempotent, keyed on source_path)
    - `PATCH /deliveries/{delivery_id}` -- partial update (status, parquet_converted_at, output_path, metadata); metadata deep-merges with existing
    - `POST /events` -- emit converter-lifecycle events (conversion.completed, conversion.failed); verifies delivery exists, inserts event, broadcasts to WebSocket clients
  - WebSocket:
    - `WS /ws/events` -- one-way broadcast of delivery lifecycle events (auth required)
- **Auth**: Bearer tokens hashed with SHA-256, stored in `tokens` table. Role hierarchy: admin > write > read. Revoked tokens return 401.
- **Event types**: `delivery.created` (new delivery, not re-crawl), `delivery.status_changed` (status transition), `conversion.completed` (converter finished), `conversion.failed` (converter error)
- **Guarantees**: delivery_id is SHA-256 of source_path (deterministic, stable). first_seen_at is never overwritten on upsert. last_updated_at only changes when fingerprint changes. Event seq is monotonically increasing (SQLite INTEGER PRIMARY KEY).
- **Expects**: SQLite database path from config. Callers provide valid Pydantic models and a valid bearer token for protected routes. Lexicons loaded at startup via `load_all_lexicons(settings.lexicons_dir)` and stored on `app.state.lexicons`.

## Dependencies

- **Uses**: `pipeline.config.settings` for db_path and lexicons
- **Used by**: crawler (POSTs deliveries with lexicon_id and derived status -- must supply write-role token), converter (will GET actionable + PATCH after conversion -- must supply write-role token), `pipeline.auth_cli` (manages tokens directly in SQLite), EventConsumer (`pipeline.events.consumer`)
- **Boundary**: no imports from crawler, converter, or events consumer

## Key Decisions

- SQLite over Postgres: target environment has no managed database; single-writer is fine for this scale
- Upsert with fingerprint-based change detection: avoids unnecessary last_updated_at churn on re-crawls
- FastAPI dependency injection for db connections: per-request connections, closed automatically
- WAL mode: enables concurrent reads during writes
- Status validation is runtime (no CHECK constraint) -- queried against lexicon.statuses at request time

## Invariants

- delivery_id = SHA-256 of source_path (never random, never sequential)
- source_path has UNIQUE constraint; one delivery per path
- status values are validated at request time against lexicon.statuses
- lexicon_id must exist in loaded lexicons; unknown lexicons are rejected at POST time
- first_seen_at is immutable after initial insert (COALESCE preserves it on conflict)
- metadata is JSON-serialized dict (nullable, defaults to {}); PATCH deep-merges at the top level (existing keys preserved, new keys added, null values allowed)
- actionable = status matches lexicon.actionable_statuses AND parquet_converted_at IS NULL
- event_type is constrained to four values via CHECK constraint: "delivery.created", "delivery.status_changed", "conversion.completed", "conversion.failed"
- event seq is auto-incrementing INTEGER PRIMARY KEY (monotonic, gap-free under normal operation)
- delivery.created fires only on genuinely new deliveries (not idempotent re-crawls)
- delivery.status_changed fires only when status actually transitions to a different value
- token_hash is SHA-256 of raw bearer token; raw tokens are never stored
- username has UNIQUE constraint in tokens table; one active token per user
- role is CHECK-constrained to "admin", "write", or "read"
- conversion.completed and conversion.failed are emitted via POST /events with converter-computed payloads (not stored as delivery columns)
- PATCH with both status AND metadata merges all three sources: existing metadata, user-supplied metadata, and lexicon-derived set_on fields

## Key Files

- `main.py` -- FastAPI app with lifespan (schema init on startup), includes public_router and protected_router, WebSocket /ws/events endpoint
- `db.py` -- all SQLite operations (init_db, upsert, get, list, actionable, update, insert_event, get_events_after, delivery_exists, get_token_by_hash); tokens table schema
- `models.py` -- Pydantic request/response models (including EventRecord, EventCreate)
- `routes.py` -- public_router (health) and protected_router (delivery endpoints with auth, including GET /events, POST /events)
- `auth.py` -- bearer token validation (require_auth), role enforcement (require_role), TokenInfo model
- `events.py` -- ConnectionManager for WebSocket broadcast; module-level `manager` singleton

## Gotchas

- `DbDep` type alias uses FastAPI's `Depends(get_db)` via `Annotated` -- don't call get_db directly in route handlers
- `AuthDep` type alias wraps `require_auth` via `Annotated[TokenInfo, Depends(require_auth)]`
- `require_role("write")` returns a `Depends()` -- assign it as a default parameter value, not as a type annotation
- version="latest" filter uses a correlated subquery (MAX version per dp_id+workplan_id), not application-level sorting
- The ensure_registry.sh watchdog uses PID files, not systemd -- check the pidfile if the API seems dead but won't restart
- Token management is via the `registry-auth` CLI (`pipeline.auth_cli`), not through the API -- there are no token management endpoints
- WebSocket endpoint is on `app` directly (not `router`) because FastAPI's APIRouter doesn't support `@router.websocket`
- ConnectionManager.broadcast silently removes dead connections -- consumer reconnect loop handles recovery
