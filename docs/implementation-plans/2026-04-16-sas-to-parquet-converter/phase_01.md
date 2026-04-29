# SAS-to-Parquet Converter — Phase 1: Registry surface area + events migration

**Goal:** Extend the registry API with the contract the converter depends on — two new event types, metadata deep-merge on PATCH, keyset pagination on `GET /deliveries`, and a minimal `POST /events` endpoint the converter uses to emit lifecycle events with converter-computed payloads.

**Architecture:** Mutate existing files in `src/pipeline/registry_api/` only. Schema change is applied idempotently inside `init_db` via a detect-and-recreate helper (SQLite cannot alter a CHECK constraint in place). No new files in this phase.

**Event-emission split (decided in Phase 1, per design plan):** The registry owns all event emission. Existing PATCH stays focused on delivery state (no new side-effect events on `parquet_converted_at` change). The converter emits `conversion.completed` / `conversion.failed` events by calling a new narrow `POST /events` endpoint that accepts event_type + delivery_id + payload, inserts via `insert_event`, and broadcasts via `ConnectionManager`. Rationale: AC6.2/AC6.3 payloads require converter-computed fields (`row_count`, `bytes_written`) that are not delivery columns — a side-effect-on-PATCH model would force us to either add columns (out of scope per design) or leak converter-computed fields into the `metadata` dict just to re-extract them. A narrow `POST /events` keeps the registry as the single event writer without dragging converter internals into the deliveries schema.

**Tech Stack:** FastAPI, stdlib sqlite3, Pydantic v2, pytest + TestClient.

**Scope:** Phase 1 of 6 from design plan `docs/design-plans/2026-04-16-sas-to-parquet-converter.md`.

**Codebase verified:** 2026-04-16.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### sas-to-parquet-converter.AC6: Events schema migration
- **sas-to-parquet-converter.AC6.1 Success:** Events table CHECK constraint allows insertion of `conversion.completed` and `conversion.failed` event types
- **sas-to-parquet-converter.AC6.4 Success:** Events broadcast via existing `ConnectionManager` to connected WebSocket clients

### sas-to-parquet-converter.AC7: Registry query surface
- **sas-to-parquet-converter.AC7.1 Success:** `GET /deliveries?converted=false&limit=N&after=delivery_id` returns only rows with null `parquet_converted_at`, paginated by `delivery_id`
- **sas-to-parquet-converter.AC7.2 Success:** PATCH with `metadata.conversion_error` deep-merges into existing metadata without clobbering other keys
- **sas-to-parquet-converter.AC7.3 Success:** PATCH with `metadata.conversion_error: null` (or equivalent) clears the error field

Note: AC6.2 (conversion.completed payload shape) and AC6.3 (conversion.failed payload shape) are tested in Phase 3 against the engine, since the engine is what assembles those payloads. Phase 1 verifies only that the `POST /events` endpoint accepts ANY dict-shaped payload for the new event types.

---

## Engineer Briefing

**You have zero context about this project. Read this first.**

- `src/pipeline/registry_api/CLAUDE.md` — contracts, invariants, gotchas for the registry
- `src/pipeline/registry_api/db.py` — all SQLite operations (init_db, upsert, get, list, update, insert_event, get_events_after)
- `src/pipeline/registry_api/routes.py` — FastAPI routes
- `src/pipeline/registry_api/models.py` — Pydantic request/response models
- `tests/registry_api/` — test layout mirrors `src/`

**Testing conventions for this project** (from registry CLAUDE.md and existing tests):
- `test_db.py` uses `:memory:` SQLite connections or `tmp_path` for file DBs; does NOT mock the database
- `test_routes.py` uses FastAPI `TestClient`; does NOT mock the database (uses real tmp_path DB via fixture)
- `test_models.py` unit-tests Pydantic models in isolation
- Follow the existing class-based test structure (`class TestXxx:` with methods)
- **Do NOT mock sqlite3**. The investigator and human operator have flagged that integration tests must hit a real DB; mocked tests have hidden schema bugs in the past.

**Commit conventions:** conventional commits (`feat:`, `fix:`, `test:`, `refactor:`). Commit after each task completes (green tests + any code changes together).

**Run tests:** `uv run pytest` from the repo root. All 324 existing tests must remain passing.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Extend events CHECK constraint via idempotent migration in `init_db`

**Verifies:** sas-to-parquet-converter.AC6.1

**Context:** SQLite does not support `ALTER TABLE ... MODIFY CHECK`. To change the CHECK constraint on the `events` table we must create a new table with the extended constraint, copy rows, drop the old table, and rename. `init_db` is idempotent today (uses `CREATE TABLE IF NOT EXISTS`) and is called from `main.py`'s FastAPI lifespan on every startup — the migration must therefore detect "schema is old" before recreating, so startup is cheap on already-migrated DBs.

**Concurrency note:** The recreate runs inside a transaction under SQLite's DDL write-lock. Concurrent readers are unaffected; a concurrent writer would be blocked for the migration's duration. The single-registry-per-host invariant (enforced by `pipeline/scripts/ensure_registry.sh`'s PID file check) already precludes concurrent writers, so this is safe in practice. Do not run this migration against a DB actively being written by multiple processes — it will either serialise cleanly or deadlock on the lock ordering.

**Files:**
- Modify: `src/pipeline/registry_api/db.py:66-77` (update the `CREATE TABLE events` statement to list all four allowed event types so fresh DBs get the right constraint)
- Modify: `src/pipeline/registry_api/db.py:21-100` (add a migration call inside `init_db`)
- Modify: `src/pipeline/registry_api/db.py` (new private helper `_migrate_events_check_constraint(conn)`)

**Implementation:**

The investigator confirmed the current CHECK constraint at `src/pipeline/registry_api/db.py:71`:

```
event_type  TEXT NOT NULL CHECK (event_type IN ('delivery.created', 'delivery.status_changed')),
```

Change this constant to the four-value list and add a migration helper.

Step 1 — Update the CREATE TABLE in `init_db` so fresh databases include all four event types. Change the `CHECK(...)` clause to include `'conversion.completed'` and `'conversion.failed'`.

Step 2 — Add `_migrate_events_check_constraint(conn: sqlite3.Connection) -> None` as a module-level helper. It should:

1. Read the current `events` CREATE statement from `sqlite_master` (`SELECT sql FROM sqlite_master WHERE type='table' AND name='events'`). If the row is None (fresh DB with no events table yet), return early.
2. If the SQL already contains `'conversion.completed'` (simple substring check), return — migration already applied.
3. Otherwise, inside a transaction:
   - `CREATE TABLE events_new (...)` with the four-value CHECK
   - `INSERT INTO events_new (seq, event_type, delivery_id, payload, created_at) SELECT seq, event_type, delivery_id, payload, created_at FROM events`
   - `DROP TABLE events`
   - `ALTER TABLE events_new RENAME TO events`
4. Commit the transaction before returning.

Step 3 — Call `_migrate_events_check_constraint(conn)` from `init_db` *after* the `CREATE TABLE IF NOT EXISTS events` and *before* the `conn.commit()` that ends the block. (Running after the create ensures the table exists on fresh DBs; the substring check then short-circuits.)

**Testing:**

Tests must verify each AC listed above. Add a class `TestMigrateEventsCheckConstraint` to `tests/registry_api/test_db.py` with:

- AC6.1 — given a fresh `:memory:` DB initialised with `init_db`, `INSERT INTO events` with `event_type='conversion.completed'` succeeds and `event_type='conversion.failed'` succeeds (cover both types in one test or two).
- AC6.1 edge — simulate an "old-schema" DB: open a `:memory:` connection, manually execute the old 2-value `CREATE TABLE events` statement (copy the pre-migration SQL verbatim as a test constant), `INSERT` a `delivery.created` row, then call `init_db(conn)`. Verify: old rows survive (`SELECT` returns the `delivery.created` row), and a subsequent `INSERT` of `conversion.completed` succeeds.
- AC6.1 idempotency — running `init_db` twice on the same connection must not lose data and must leave the events table in the four-value state.
- Rejection: `INSERT INTO events` with `event_type='nonsense'` must raise `sqlite3.IntegrityError`.

**Verification:**

Run: `uv run pytest tests/registry_api/test_db.py -v`
Expected: New `TestMigrateEventsCheckConstraint` tests pass; all existing `TestInitDb` tests pass.

Run: `uv run pytest`
Expected: 324 existing tests remain passing; new tests pass.

**Commit:** `feat(registry): extend events CHECK constraint for conversion events`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Extend `EventRecord.event_type` Literal to cover conversion events

**Verifies:** sas-to-parquet-converter.AC6.1 (model side)

**Context:** `src/pipeline/registry_api/models.py:79` currently constrains `EventRecord.event_type` to two literal values. If we leave this unchanged, any attempt to broadcast or serialize a `conversion.*` event via the Pydantic model will fail validation.

**Files:**
- Modify: `src/pipeline/registry_api/models.py:75-82`

**Implementation:**

Change the `event_type` annotation from:

```python
event_type: Literal["delivery.created", "delivery.status_changed"]
```

to include the two new literals:

```python
event_type: Literal[
    "delivery.created",
    "delivery.status_changed",
    "conversion.completed",
    "conversion.failed",
]
```

No other changes to the model.

**Testing:**

Extend `tests/registry_api/test_models.py` class `TestEventRecord` with:

- Construct `EventRecord(seq=1, event_type="conversion.completed", delivery_id="abc", payload={}, created_at="2026-04-16T00:00:00Z")` — must succeed.
- Same for `event_type="conversion.failed"`.
- `EventRecord(..., event_type="nonsense", ...)` must raise `pydantic.ValidationError`.

**Verification:**

Run: `uv run pytest tests/registry_api/test_models.py -v`
Expected: New assertions pass; existing model tests pass.

**Commit:** `feat(registry): accept conversion events in EventRecord model`
<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->

<!-- START_TASK_3 -->
### Task 3: Deep-merge `metadata` on PATCH instead of overwriting

**Verifies:** sas-to-parquet-converter.AC7.2, sas-to-parquet-converter.AC7.3

**Context:** The investigator confirmed `src/pipeline/registry_api/routes.py:197-198` currently overwrites metadata with the entire new dict:

```python
elif "metadata" in updates:
    updates["metadata"] = json.dumps(updates["metadata"])
```

The converter will PATCH `{"metadata": {"conversion_error": {...}}}` and expects any metadata keys the crawler wrote (e.g. lexicon-derived `set_on` fields) to be preserved. A shallow dict-update (top-level merge) is sufficient — `conversion_error` is a single top-level key; we do not need recursive merging of arbitrary nesting.

Also supports AC7.3: the PATCH client can clear `conversion_error` by sending `{"metadata": {"conversion_error": null}}`. After merge, that key holds `None` — the converter skip-guard (Phase 3) treats `None` as "no error" and resumes processing. We do not delete the key on `null`; merging a `null` value is the documented clear semantic.

**Files:**
- Modify: `src/pipeline/registry_api/routes.py:197-198`

**Implementation:**

The status-transition branch above (lines 183-195) already does a shallow merge when auto-populating `set_on` metadata fields; use the same pattern in the no-status-change branch.

Replace lines 197-198 with:

```python
elif "metadata" in updates:
    metadata_val = old.get("metadata", {})
    existing_metadata = (
        metadata_val if isinstance(metadata_val, dict) else json.loads(metadata_val or "{}")
    )
    merged = {**existing_metadata, **updates["metadata"]}
    updates["metadata"] = json.dumps(merged)
```

The `{**existing, **new}` pattern shallow-merges at the top level: new keys win, missing keys are preserved, and `null` values in `new` overwrite existing values to `None`.

**Testing:**

Extend `tests/registry_api/test_routes.py` class `TestUpdateDelivery` (or add `TestPatchMetadataMerge`) with:

- AC7.2 happy path — create a delivery with `metadata={"qa_passed_at": "2026-04-15T00:00:00Z", "other": "keep"}`. PATCH `{"metadata": {"conversion_error": {"class": "parse_error", "message": "bad", "at": "2026-04-16T00:00:00Z", "converter_version": "0.1.0"}}}`. GET the row; assert all three top-level keys are present (`qa_passed_at`, `other`, `conversion_error`) and `conversion_error` matches the posted dict.
- AC7.3 clear — starting from the state above, PATCH `{"metadata": {"conversion_error": null}}`. Assert `qa_passed_at` and `other` still present and `conversion_error` is `None` in the returned row.
- Regression — creating a delivery with `metadata={}` and PATCHing `{"metadata": {"k": "v"}}` produces `{"k": "v"}` (existing test expectation must still hold; confirm it does not break by running the full `TestUpdateDelivery` class).
- Status + metadata combined — PATCHing both `status` (that triggers a lexicon `set_on` write) AND top-level `metadata` fields must result in the union of all three sources (lexicon-derived field, existing keys, new keys). Use the existing `soc.qar` test lexicon.

**Verification:**

Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: New assertions pass; existing PATCH tests pass without modification.

**Commit:** `fix(registry): deep-merge metadata on PATCH instead of overwriting`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Keyset pagination on `GET /deliveries` (`after=&limit=`)

**Verifies:** sas-to-parquet-converter.AC7.1

**Context:** The investigator confirmed `GET /deliveries?converted=false` already returns unconverted rows. What's missing is cursor pagination. The backfill CLI (Phase 4) and the `--shard I/N` flag depend on `after=delivery_id` being a stable keyset cursor.

Keyset (not offset) because `delivery_id` is a deterministic SHA-256 — it's already the natural sort key, is indexed as PRIMARY KEY, and survives concurrent inserts without skipping or duplicating rows.

**Files:**
- Modify: `src/pipeline/registry_api/models.py:60-72` (add `after: str | None` and `limit: int | None` to `DeliveryFilters`)
- Modify: `src/pipeline/registry_api/db.py:285-339` (`list_deliveries` — add `after` and `limit` handling, plus stable `ORDER BY delivery_id`)

**Implementation:**

Step 1 — Add two fields to `DeliveryFilters`:

```python
after: str | None = None
limit: int | None = None
```

Step 2 — In `list_deliveries`, extend the filter handling after the existing blocks:

```python
if "after" in filters and filters["after"] is not None:
    where_clauses.append("delivery_id > ?")
    params.append(filters["after"])
```

Step 3 — Always append `ORDER BY delivery_id` to the query (after the WHERE clause, before any LIMIT). This makes pagination deterministic whether or not `after` is supplied.

Step 4 — Apply LIMIT when provided, capped at 1000 (matching the existing `get_events_after` cap):

```python
if "limit" in filters and filters["limit"] is not None:
    capped = min(int(filters["limit"]), 1000)
    query += f" LIMIT {capped}"
```

**Note:** `limit` can be safely interpolated because it's an int after the cap; do not parameterise SQL LIMIT (SQLite accepts `LIMIT ?` but interpolation is easier and equally safe with an int cast).

**Testing:**

Extend `tests/registry_api/test_db.py` with a `TestListDeliveriesPagination` class and `tests/registry_api/test_routes.py` with pagination assertions in `TestListDeliveries`:

- AC7.1 ordering — insert 5 deliveries with known source_paths; call `list_deliveries(conn, {})`; assert the returned rows are sorted by `delivery_id` ascending.
- AC7.1 after — call `list_deliveries(conn, {"after": results[1]["delivery_id"]})`; assert exactly rows 2, 3, 4 returned (3 rows, all strictly greater than the cursor).
- AC7.1 limit — call `list_deliveries(conn, {"limit": 2})`; assert exactly 2 rows returned and they are the two smallest `delivery_id` rows.
- AC7.1 combined — `GET /deliveries?converted=false&after={some_id}&limit=2` with a fixture that has a mix of converted and unconverted rows returns at most 2 unconverted rows strictly past the cursor.
- Cap — call `list_deliveries(conn, {"limit": 5000})` with fewer than 1000 rows seeded; assert no error and all rows returned (exercises the cap branch without needing to seed 1000+ rows).

**Verification:**

Run: `uv run pytest tests/registry_api/ -v`
Expected: New pagination tests pass; all existing `TestListDeliveries` tests pass without modification.

Run: `uv run pytest`
Expected: Full suite green (324 + new tests).

**Commit:** `feat(registry): add after/limit keyset pagination to GET /deliveries`
<!-- END_TASK_4 -->

<!-- END_SUBCOMPONENT_B -->

<!-- START_SUBCOMPONENT_C (tasks 5-6) -->

<!-- START_TASK_5 -->
### Task 5: Narrow `POST /events` endpoint for external emitters

**Verifies:** sas-to-parquet-converter.AC6.4

**Context:** The converter needs a way to emit `conversion.completed` / `conversion.failed` events whose payload carries converter-computed fields (`row_count`, `bytes_written`, `error_class`, etc.) that are not columns on the delivery row. The existing pattern — events emitted as a side-effect of POST/PATCH — cannot cleanly express this without widening the deliveries schema or leaking converter fields into `metadata`. A narrow `POST /events` endpoint is the minimum-viable alternative.

**Security/access posture:** The whole registry API is unauthenticated on a private network today (see `docs/design-plans/2026-04-10-registry-auth.md` — deferred). Do not add auth here; matches the existing POST /deliveries posture.

**Files:**
- Modify: `src/pipeline/registry_api/models.py` (add `EventCreate` request model)
- Modify: `src/pipeline/registry_api/routes.py` (add the `POST /events` handler)

**Implementation:**

Step 1 — Add `EventCreate` to `models.py`:

```python
class EventCreate(BaseModel):
    """POST body for emitting a lifecycle event from outside the registry."""

    event_type: Literal["conversion.completed", "conversion.failed"]
    delivery_id: str
    payload: dict
```

Deliberately restricts `event_type` to the two converter events. `delivery.created` and `delivery.status_changed` remain registry-internal — the crawler has no business calling this endpoint to fabricate those.

Step 2 — Add `POST /events` to `routes.py` (near the existing `GET /events` at line 215). The handler:

1. Verifies the delivery exists (`get_delivery(db, delivery_id)`); returns 404 if not.
2. Calls `insert_event(db, data.event_type, data.delivery_id, data.payload)`.
3. `await manager.broadcast(event)`.
4. Returns the inserted event as an `EventRecord`.

```python
@router.post("/events", response_model=EventRecord, status_code=201)
async def emit_event(data: EventCreate, db: DbDep):
    """
    Emit a converter lifecycle event.

    Verifies the delivery exists, persists the event via insert_event,
    and broadcasts to connected WebSocket clients.

    Returns 404 if the delivery does not exist.
    """
    if get_delivery(db, data.delivery_id) is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    event = insert_event(db, data.event_type, data.delivery_id, data.payload)
    await manager.broadcast(event)
    return event
```

Add `EventCreate` to the existing `from pipeline.registry_api.models import ...` line at the top of `routes.py`.

**Testing:**

Add `TestEmitEvent` class to `tests/registry_api/test_routes.py`:

- AC6.4 happy path (conversion.completed) — create a delivery; POST `/events` with `{"event_type": "conversion.completed", "delivery_id": "<id>", "payload": {"delivery_id": "<id>", "output_path": "/x/parquet/y.parquet", "row_count": 42, "bytes_written": 1024, "wrote_at": "2026-04-16T00:00:00Z"}}`. Assert 201, returned `EventRecord` matches, and `GET /events?after=0` includes the new event.
- AC6.4 happy path (conversion.failed) — same shape with `error_class`/`error_message`/`at`. Assert 201.
- Unknown delivery — POST with `delivery_id` that doesn't exist returns 404.
- Invalid event_type — POST `event_type="delivery.created"` (the endpoint is restricted to conversion events). Assert 422 (Pydantic rejects the Literal).
- WebSocket broadcast — use `TestClient.websocket_connect("/ws/events")` (check test_events.py for the existing pattern); connect first, then POST /events; assert the event is received on the socket.

**Verification:**

Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: New `TestEmitEvent` tests pass; no existing route tests break.

Run: `uv run pytest`
Expected: Full suite green.

**Commit:** `feat(registry): add POST /events endpoint for converter emission`
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Add `EventCreate` to `models.py` public exports + test in `test_models.py`

**Verifies:** Model validation boundary for AC6.4.

**Context:** Keep model tests isolated — Task 5 tests the route; this task tests the model itself so failure isolation is clean.

**Files:**
- Modify: `tests/registry_api/test_models.py` (add `TestEventCreate` class)

**Implementation:**

```python
class TestEventCreate:
    def test_accepts_conversion_completed(self):
        e = EventCreate(
            event_type="conversion.completed",
            delivery_id="abc",
            payload={"k": "v"},
        )
        assert e.event_type == "conversion.completed"

    def test_accepts_conversion_failed(self):
        e = EventCreate(event_type="conversion.failed", delivery_id="abc", payload={})
        assert e.event_type == "conversion.failed"

    def test_rejects_registry_internal_types(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EventCreate(event_type="delivery.created", delivery_id="abc", payload={})
        with pytest.raises(ValidationError):
            EventCreate(event_type="delivery.status_changed", delivery_id="abc", payload={})

    def test_rejects_arbitrary_strings(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EventCreate(event_type="nonsense", delivery_id="abc", payload={})

    def test_payload_must_be_dict(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            EventCreate(event_type="conversion.completed", delivery_id="abc", payload="not a dict")
```

Add `EventCreate` to the imports at the top of `test_models.py`.

**Verification:**

Run: `uv run pytest tests/registry_api/test_models.py::TestEventCreate -v`
Expected: All tests pass.

**Commit:** `test(registry): cover EventCreate model validation`
<!-- END_TASK_6 -->

<!-- END_SUBCOMPONENT_C -->

---

## Phase completion checklist

Before considering Phase 1 done:

- [ ] All six tasks committed separately with conventional commit messages.
- [ ] `uv run pytest` — entire suite passes.
- [ ] `uv run registry-api` — process starts without error against a fresh DB and against a pre-existing DB created from the prior schema.
- [ ] Manually verified: `sqlite3 /path/to/test.db "SELECT sql FROM sqlite_master WHERE name='events'"` returns a CHECK clause listing all four event types.
- [ ] `curl -X POST http://localhost:8000/events -H 'Content-Type: application/json' -d '{"event_type":"conversion.completed","delivery_id":"<existing-id>","payload":{}}'` returns 201; unknown delivery returns 404; `event_type: "delivery.created"` returns 422.
- [ ] Phase 2 can begin — the converter core has no registry dependencies, but Phase 3 (engine) will consume the PATCH semantics, event types, AND `POST /events` endpoint established here.
