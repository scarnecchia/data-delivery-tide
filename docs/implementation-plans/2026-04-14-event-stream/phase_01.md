# Event Stream Implementation Plan — Phase 1: Event Persistence

**Goal:** Add an `events` table and event read/write functions to the database layer, plus an `EventRecord` Pydantic model.

**Architecture:** Extends the existing SQLite schema with a new `events` table created inside `init_db`. Query functions follow the same pattern as delivery queries (accept `sqlite3.Connection`, return dicts). The Pydantic model lives in `models.py` alongside existing models.

**Tech Stack:** Python 3.10+, SQLite (stdlib sqlite3), Pydantic v2, FastAPI, pytest + httpx

**Scope:** 5 phases from original design (phase 1 of 5)

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### event-stream.AC4: Event persistence with monotonic sequence
- **event-stream.AC4.1 Success:** Each persisted event has a seq higher than all previous events
- **event-stream.AC4.2 Success:** Event payload stored as JSON matches the broadcast payload
- **event-stream.AC4.3 Success:** Events persist even if no WS clients are connected

### event-stream.AC5: Catch-up REST endpoint (partial — query functions only)
- **event-stream.AC5.1 Success:** GET /events?after=N returns only events with seq > N, ordered by seq ASC
- **event-stream.AC5.2 Success:** GET /events?after=N&limit=M returns at most M events

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Add EventRecord Pydantic model to models.py

**Verifies:** None (model definition — validated by tests in Task 4)

**Files:**
- Modify: `src/pipeline/registry_api/models.py:70` (append after DeliveryFilters)

**Implementation:**

Add the following model at the end of `models.py`. This follows the existing pattern: `BaseModel` subclass, type hints, docstring, `Literal` for constrained fields.

```python
class EventRecord(BaseModel):
    """Persisted event record for delivery lifecycle changes."""

    seq: int
    event_type: Literal["delivery.created", "delivery.status_changed"]
    delivery_id: str
    payload: dict
    created_at: str
```

Notes:
- `payload` is `dict` rather than `DeliveryResponse` because the event stores a JSON snapshot at event time. The dict is already-serialised `DeliveryResponse.model_dump()` output.
- `seq` is the monotonic SQLite rowid, assigned on insert.
- `created_at` is ISO 8601 UTC string, matching `_get_iso_now()` format used elsewhere.

**Verification:**
Run: `uv run pytest tests/registry_api/test_models.py -v`
Expected: All existing model tests still pass (no regressions).

**Commit:** `feat(registry): add EventRecord pydantic model`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add events table to init_db and event query functions to db.py

**Verifies:** event-stream.AC4.1, event-stream.AC4.2, event-stream.AC4.3, event-stream.AC5.1, event-stream.AC5.2

**Files:**
- Modify: `src/pipeline/registry_api/db.py` — add events table in `init_db` (after deliveries table, before indexes)
- Modify: `src/pipeline/registry_api/db.py` — append new functions at end of file

**Implementation:**

**Step 0: Add `import json` to top-level imports in db.py**

Add `import json` alongside the existing stdlib imports at the top of `db.py` (after `import hashlib`).

**Step 1: Add events table to `init_db`**

Inside the `try` block of `init_db`, after the `CREATE TABLE IF NOT EXISTS deliveries` statement (line 62) and before the index creation statements (line 65), add:

```python
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq         INTEGER PRIMARY KEY,
                event_type  TEXT NOT NULL CHECK (event_type IN ('delivery.created', 'delivery.status_changed')),
                delivery_id TEXT NOT NULL,
                payload     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
            """
        )
```

This uses `INTEGER PRIMARY KEY` which aliases SQLite's rowid — auto-assigned, monotonically increasing, never reused (unless max rowid is deleted, which doesn't happen in this design).

**Step 2: Add `insert_event` function**

Append to the end of `db.py`:

```python
def insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    delivery_id: str,
    payload: dict,
) -> dict:
    """
    Insert an event record and return it with the assigned sequence number.

    Args:
        conn: sqlite3.Connection
        event_type: One of 'delivery.created' or 'delivery.status_changed'
        delivery_id: The delivery ID this event relates to
        payload: Full delivery record as a dict (DeliveryResponse.model_dump() output)

    Returns:
        dict: The inserted event row as a dict, including the auto-assigned seq.
    """
    now = _get_iso_now()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
        (event_type, delivery_id, json.dumps(payload), now),
    )
    conn.commit()

    seq = cursor.lastrowid
    return {
        "seq": seq,
        "event_type": event_type,
        "delivery_id": delivery_id,
        "payload": payload,
        "created_at": now,
    }
```

Notes:
- `json.dumps(payload)` serialises the dict for TEXT storage. The returned dict contains the original `payload` dict (not the JSON string) so callers can broadcast it directly.
- `cursor.lastrowid` gives the auto-assigned `INTEGER PRIMARY KEY` value.
- Follows existing patterns: accepts `sqlite3.Connection`, returns dict, uses `_get_iso_now()`, uses positional `?` params.

**Step 3: Add `get_events_after` function**

Append to the end of `db.py`:

```python
def get_events_after(
    conn: sqlite3.Connection,
    after_seq: int,
    limit: int = 100,
) -> list[dict]:
    """
    Retrieve events with seq greater than after_seq, ordered by seq ascending.

    Args:
        conn: sqlite3.Connection
        after_seq: Return events with seq strictly greater than this value
        limit: Maximum number of events to return (default 100, max 1000)

    Returns:
        list[dict]: List of event dicts with payload deserialised from JSON.
    """
    capped_limit = min(limit, 1000)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?",
        (after_seq, capped_limit),
    )
    rows = cursor.fetchall()

    result = []
    for row in rows:
        event = dict(row)
        event["payload"] = json.loads(event["payload"])
        result.append(event)
    return result
```

**Step 4: Add `delivery_exists` function**

This is needed by Phase 3 (route integration) for the pre-query check, but adding it now keeps all db functions together and avoids modifying db.py in two phases.

Append to the end of `db.py`:

```python
def delivery_exists(conn: sqlite3.Connection, delivery_id: str) -> bool:
    """
    Check if a delivery exists by ID.

    Args:
        conn: sqlite3.Connection
        delivery_id: The delivery ID to check

    Returns:
        bool: True if the delivery exists, False otherwise.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM deliveries WHERE delivery_id = ? LIMIT 1", (delivery_id,))
    return cursor.fetchone() is not None
```

**Verification:**
Run: `uv run pytest tests/registry_api/test_db.py -v`
Expected: All existing db tests still pass (no regressions from schema change).

**Commit:** `feat(registry): add events table and event query functions`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Add EventRecord model tests

**Verifies:** None (model validation — verifies the Pydantic model from Task 1 works correctly)

**Files:**
- Modify: `tests/registry_api/test_models.py` (append new test class at end)

**Testing:**

Add a `TestEventRecord` class following the existing pattern in `test_models.py` (e.g., `TestDeliveryCreate`, `TestDeliveryResponse`). Tests should verify:

- Valid construction with all required fields succeeds
- `event_type` rejects values outside `Literal["delivery.created", "delivery.status_changed"]` (raises `ValidationError`)
- `event_type` accepts both valid values
- `payload` accepts a dict
- `seq` must be an int

Follow the existing test style: class-based, direct Pydantic instantiation, `pytest.raises(ValidationError)` for invalid inputs, AC references in docstrings where applicable.

**Verification:**
Run: `uv run pytest tests/registry_api/test_models.py -v`
Expected: All tests pass including new EventRecord tests.

**Commit:** `test(registry): add EventRecord model tests`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Add event persistence tests (insert_event, get_events_after, delivery_exists)

**Verifies:** event-stream.AC4.1, event-stream.AC4.2, event-stream.AC5.1, event-stream.AC5.2

**Files:**
- Modify: `tests/registry_api/test_db.py` (append new test classes at end)

**Testing:**

Add test classes following the existing pattern in `test_db.py`. Each test class gets its own `memory_db` fixture (in-memory SQLite with `init_db` called). Tests should verify:

**TestInsertEvent:**
- event-stream.AC4.1: Insert two events sequentially, verify second has higher `seq` than first
- event-stream.AC4.2: Inserted event contains correct `event_type`, `delivery_id`, `payload` dict, and `created_at` string
- Insert with `event_type="delivery.created"` succeeds
- Insert with `event_type="delivery.status_changed"` succeeds
- Insert with invalid `event_type` raises `sqlite3.IntegrityError` (CHECK constraint)

**TestGetEventsAfter:**
- event-stream.AC5.1: Insert 3 events, `get_events_after(seq=1)` returns only events with seq > 1, ordered by seq ASC
- event-stream.AC5.2: Insert 5 events, `get_events_after(seq=0, limit=2)` returns exactly 2 events
- Limit is capped at 1000: `get_events_after(seq=0, limit=2000)` behaves same as `limit=1000`
- Empty result: `get_events_after(seq=999)` returns empty list when no events have seq > 999
- Payload is deserialised: returned event `payload` is a dict, not a JSON string

**TestDeliveryExists:**
- Returns `True` for a delivery that has been upserted
- Returns `False` for a delivery_id that does not exist

Use real `upsert_delivery` calls (not mocks) to set up delivery records for `delivery_exists` tests, following the existing pattern in `test_db.py`.

**Verification:**
Run: `uv run pytest tests/registry_api/test_db.py -v`
Expected: All tests pass including new event tests.

**Commit:** `test(registry): add event persistence and query tests`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->
