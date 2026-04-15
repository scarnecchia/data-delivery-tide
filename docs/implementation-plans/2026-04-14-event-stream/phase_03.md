# Event Stream Implementation Plan — Phase 3: Route Integration

**Goal:** Wire event emission into the POST and PATCH delivery route handlers so that meaningful changes (new delivery, status transition) persist an event and broadcast it to WebSocket clients.

**Architecture:** The POST handler runs a pre-query (`delivery_exists`) before the upsert to distinguish new deliveries from re-crawls. The PATCH handler reads the current `qa_status` before applying the update to detect transitions. Both use `insert_event` from Phase 1 and `manager.broadcast` from Phase 2. DB write happens first — if broadcast fails, the event is still persisted.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, pytest + TestClient

**Scope:** 5 phases from original design (phase 3 of 5)

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### event-stream.AC1: API emits delivery.created events
- **event-stream.AC1.1 Success:** POST with new delivery_id creates event with type `delivery.created`, correct seq, and full delivery payload
- **event-stream.AC1.2 Success:** Event broadcast received by connected WebSocket client
- **event-stream.AC1.3 Success:** Re-crawl of existing delivery (same delivery_id, same fingerprint) produces no event
- **event-stream.AC1.4 Edge:** First POST after API restart correctly detects new vs existing deliveries

### event-stream.AC2: API emits delivery.status_changed events
- **event-stream.AC2.1 Success:** PATCH changing qa_status from pending to passed creates event with type `delivery.status_changed`
- **event-stream.AC2.2 Success:** PATCH changing qa_status from pending to failed creates event with type `delivery.status_changed`
- **event-stream.AC2.3 Success:** Event payload contains the updated delivery record (new status reflected)
- **event-stream.AC2.4 Success:** PATCH that doesn't change qa_status (e.g., setting parquet_converted_at) produces no event
- **event-stream.AC2.5 Success:** PATCH with same qa_status value as current produces no event

### event-stream.AC7: Backward compatibility
- **event-stream.AC7.1 Success:** Existing delivery POST/PATCH behaviour unchanged (same request/response contract)
- **event-stream.AC7.2 Success:** All existing tests pass without modification

---

<!-- START_TASK_1 -->
### Task 1: Add event emission to POST /deliveries route

**Verifies:** event-stream.AC1.1, event-stream.AC1.3, event-stream.AC1.4, event-stream.AC7.1

**Files:**
- Modify: `src/pipeline/registry_api/routes.py:1-12` (add imports)
- Modify: `src/pipeline/registry_api/routes.py:28-37` (modify `create_delivery` handler)

**Implementation:**

**Step 1: Update imports in routes.py**

Add `delivery_exists`, `insert_event`, `make_delivery_id` to the db imports, and import `manager` from events:

```python
from pipeline.registry_api.db import (
    DbDep,
    delivery_exists,
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
)
from pipeline.registry_api.events import manager
```

**Step 2: Modify the `create_delivery` handler**

Replace the current handler (lines 28-37) with:

```python
@router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(data: DeliveryCreate, db: DbDep):
    """
    Create or upsert a delivery.

    If a delivery with the same source_path already exists, updates its fields
    while preserving first_seen_at. Returns the created or updated delivery.

    Emits a delivery.created event if this is a genuinely new delivery
    (not a re-crawl of an existing one).
    """
    delivery_id = make_delivery_id(data.source_path)
    is_new = not delivery_exists(db, delivery_id)

    result = upsert_delivery(db, data.model_dump())

    if is_new:
        response = DeliveryResponse(**result)
        event = insert_event(db, "delivery.created", delivery_id, response.model_dump())
        await manager.broadcast(event)

    return result
```

Notes:
- The pre-query (`delivery_exists`) runs before the upsert. This is the only way to distinguish new deliveries from re-crawls since the upsert is idempotent.
- `DeliveryResponse(**result)` validates the dict through Pydantic before serialising — ensures the payload matches the API contract.
- DB write (`insert_event`) happens before broadcast — if broadcast fails, the event is still persisted for catch-up.
- The return value and status code are unchanged — backward compatible.

**Verification:**
Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: All existing route tests still pass (backward compatibility).

**Commit:** `feat(registry): emit delivery.created events on POST`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add event emission to PATCH /deliveries/{id} route

**Verifies:** event-stream.AC2.1, event-stream.AC2.2, event-stream.AC2.3, event-stream.AC2.4, event-stream.AC2.5, event-stream.AC7.1

**Files:**
- Modify: `src/pipeline/registry_api/routes.py:78-89` (modify `update_single_delivery` handler)

**Implementation:**

Replace the current PATCH handler (lines 78-89) with:

```python
@router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(delivery_id: str, data: DeliveryUpdate, db: DbDep):
    """
    Partially update a delivery.

    Only provided fields are updated. Empty body is a valid no-op.
    Returns 404 if delivery not found.

    Emits a delivery.status_changed event if qa_status transitions
    to a different value.
    """
    old = get_delivery(db, delivery_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    old_status = old["qa_status"]
    result = update_delivery(db, delivery_id, data.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    new_status = result["qa_status"]
    if new_status != old_status:
        response = DeliveryResponse(**result)
        event = insert_event(db, "delivery.status_changed", delivery_id, response.model_dump())
        await manager.broadcast(event)

    return result
```

Notes:
- Reads the current delivery BEFORE applying the update to capture `old_status`.
- Only emits an event when `qa_status` actually changes — no event for same-status PATCHes or non-status field updates.
- The pre-read gives the 404 early exit and captures `old_status`. A defensive null check after `update_delivery` is retained as a safety net.
- Return value and status code are unchanged — backward compatible.

**Verification:**
Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: All existing route tests still pass.

**Commit:** `feat(registry): emit delivery.status_changed events on PATCH`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Add route integration tests for event emission

**Verifies:** event-stream.AC1.1, event-stream.AC1.2, event-stream.AC1.3, event-stream.AC2.1, event-stream.AC2.2, event-stream.AC2.3, event-stream.AC2.4, event-stream.AC2.5, event-stream.AC7.1, event-stream.AC7.2

**Files:**
- Modify: `tests/registry_api/test_routes.py` (append new test classes at end)

**Testing:**

Add test classes to the existing `test_routes.py` file. These tests use the existing `client` and `test_db` fixtures from `tests/conftest.py`. To verify events were persisted, query the events table directly via the `test_db` connection.

**TestDeliveryCreatedEvents:**
- event-stream.AC1.1: POST a new delivery, query `events` table directly via `test_db`, verify one event with `event_type='delivery.created'`, correct `delivery_id`, and `payload` containing full delivery fields
- event-stream.AC1.3: POST same delivery twice (same source_path, same fingerprint), verify only one event in `events` table (re-crawl produces no event)
- event-stream.AC7.1: POST a new delivery, verify response body and status code are unchanged from existing tests

For AC1.2 (WebSocket broadcast received), this can be tested here using threading + `client.websocket_connect("/ws/events")` to listen while POSTing, or deferred to Phase 2's test file if the threading pattern is too complex. The implementor should choose the approach that produces clearer tests.

**TestDeliveryStatusChangedEvents:**
- event-stream.AC2.1: POST a delivery with `qa_status="pending"`, PATCH to `qa_status="passed"`, verify event with `event_type='delivery.status_changed'` in events table
- event-stream.AC2.2: POST a delivery with `qa_status="pending"`, PATCH to `qa_status="failed"`, verify event exists
- event-stream.AC2.3: Verify the event payload contains the updated delivery record (new status reflected, not old)
- event-stream.AC2.4: POST a delivery, PATCH only `parquet_converted_at` (no status change), verify no event in events table
- event-stream.AC2.5: POST a delivery with `qa_status="pending"`, PATCH with `qa_status="pending"` (same value), verify no event

**TestBackwardCompatibility:**
- event-stream.AC7.2: Run the full existing test suite and confirm no modifications were needed (this is verified by the test runner, not a new test — just ensure existing tests in `test_routes.py` still pass)

For querying events directly in tests, use the `test_db` fixture:

```python
import json

def get_events(db):
    """Helper to fetch all events from the test database."""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM events ORDER BY seq ASC")
    rows = cursor.fetchall()
    return [
        {**dict(row), "payload": json.loads(dict(row)["payload"])}
        for row in rows
    ]
```

**Verification:**
Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: All tests pass (existing + new).

Run: `uv run pytest tests/ -v`
Expected: All tests pass (full suite, no regressions — AC7.2).

**Commit:** `test(registry): add route integration tests for event emission`
<!-- END_TASK_3 -->
