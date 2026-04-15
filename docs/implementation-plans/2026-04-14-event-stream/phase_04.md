# Event Stream Implementation Plan — Phase 4: Catch-up REST Endpoint

**Goal:** Add a `GET /events` REST endpoint so consumers can retrieve missed events by sequence number on reconnect.

**Architecture:** A new route on the existing API router uses `get_events_after()` from Phase 1. Query params `after` (required) and `limit` (optional, default 100, max 1000) control the result set. Returns a JSON array of event records ordered by `seq ASC`.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, pytest + TestClient

**Scope:** 5 phases from original design (phase 4 of 5)

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### event-stream.AC5: Catch-up REST endpoint
- **event-stream.AC5.1 Success:** GET /events?after=N returns only events with seq > N, ordered by seq ASC
- **event-stream.AC5.2 Success:** GET /events?after=N&limit=M returns at most M events
- **event-stream.AC5.3 Success:** GET /events?after=\<latest_seq\> returns empty array
- **event-stream.AC5.4 Failure:** GET /events without after parameter returns 422

---

<!-- START_TASK_1 -->
### Task 1: Add GET /events catch-up endpoint to routes.py

**Verifies:** event-stream.AC5.1, event-stream.AC5.2, event-stream.AC5.3, event-stream.AC5.4

**Files:**
- Modify: `src/pipeline/registry_api/routes.py` (add imports, append new route)

**Implementation:**

**Step 1: Update imports**

Add `get_events_after` to the db imports and `EventRecord` to the model imports:

```python
from pipeline.registry_api.db import (
    DbDep,
    delivery_exists,
    get_events_after,
    insert_event,
    make_delivery_id,
    upsert_delivery,
    get_delivery,
    list_deliveries,
    get_actionable,
    update_delivery,
)
from pipeline.registry_api.models import (
    DeliveryCreate,
    DeliveryUpdate,
    DeliveryResponse,
    DeliveryFilters,
    EventRecord,
)
```

**Step 2: Add the endpoint**

Append after the existing PATCH route:

```python
@router.get("/events", response_model=list[EventRecord])
async def get_events(db: DbDep, after: int, limit: int = 100):
    """
    Retrieve events after a given sequence number for consumer catch-up.

    Args:
        after: Return events with seq strictly greater than this value (required).
        limit: Maximum number of events to return (default 100, max 1000).

    Returns empty array if no events match.
    """
    return get_events_after(db, after, limit)
```

Notes:
- `after: int` without a default makes it required — FastAPI returns 422 if omitted (AC5.4).
- `limit: int = 100` with default makes it optional.
- `get_events_after` already caps limit at 1000 and orders by `seq ASC`.
- The endpoint is on the existing `router` (not on `app`), following the pattern of all other REST endpoints.

**Verification:**
Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: All existing tests pass.

**Commit:** `feat(registry): add GET /events catch-up endpoint`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add catch-up endpoint tests

**Verifies:** event-stream.AC5.1, event-stream.AC5.2, event-stream.AC5.3, event-stream.AC5.4

**Files:**
- Modify: `tests/registry_api/test_routes.py` (append new test class at end)

**Testing:**

Add a `TestCatchUpEndpoint` class to `test_routes.py`. Tests use the `client` and `test_db` fixtures. To set up test data, insert events directly via `insert_event()` on the `test_db` connection (importing from `pipeline.registry_api.db`).

**TestCatchUpEndpoint:**
- event-stream.AC5.1: Insert 3 events, `GET /events?after=1`, verify response contains only events with seq > 1, ordered by seq ASC
- event-stream.AC5.2: Insert 5 events, `GET /events?after=0&limit=2`, verify response contains exactly 2 events
- event-stream.AC5.3: Insert 3 events, `GET /events?after=<seq of last event>`, verify response is empty array `[]`
- event-stream.AC5.4: `GET /events` (no `after` param), verify response status is 422
- Limit capping: `GET /events?after=0&limit=5000`, verify it works (doesn't error) and returns at most 1000 events
- Response shape: Verify each event in response has `seq`, `event_type`, `delivery_id`, `payload` (dict), `created_at` fields

For inserting test events, use `insert_event(test_db, "delivery.created", "test-id", {"key": "value"})` directly.

**Verification:**
Run: `uv run pytest tests/registry_api/test_routes.py::TestCatchUpEndpoint -v`
Expected: All new tests pass.

Run: `uv run pytest tests/ -v`
Expected: Full suite passes.

**Commit:** `test(registry): add catch-up endpoint tests`
<!-- END_TASK_2 -->
