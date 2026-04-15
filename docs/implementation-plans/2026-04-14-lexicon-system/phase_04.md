# Lexicon System Implementation Plan — Phase 4: API Route Updates

**Goal:** Registry API validates statuses and transitions against loaded lexicon definitions at runtime. POST validates `status ∈ lexicon.statuses`, PATCH validates transition legality and auto-populates `set_on` metadata. Actionable endpoint queries across all lexicons.

**Architecture:** Lexicons loaded at app startup in `main.py` lifespan and stored as app state. Route handlers look up lexicon by `lexicon_id` from the request, validate status/transitions against it, and apply metadata `set_on` rules on status transitions.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, sqlite3

**Scope:** Phase 4 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### lexicon-system.AC4: API validation
- **lexicon-system.AC4.1 Success:** POST with valid status for lexicon succeeds
- **lexicon-system.AC4.2 Failure:** POST with status not in lexicon's `statuses` returns 422
- **lexicon-system.AC4.3 Success:** PATCH with legal transition succeeds
- **lexicon-system.AC4.4 Failure:** PATCH with illegal transition returns 422
- **lexicon-system.AC4.5 Success:** `set_on` metadata field auto-populated on matching status transition
- **lexicon-system.AC4.6 Edge:** PATCH that doesn't change status produces no event and no metadata auto-population

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Load lexicons at app startup and make available to routes

**Verifies:** None (infrastructure — wiring)

**Files:**
- Modify: `src/pipeline/registry_api/main.py:12-21` (lifespan function)

**Implementation:**

In the `lifespan` function at `src/pipeline/registry_api/main.py:12-21`, after `init_db()`, load all lexicons and store them on `app.state`:

```python
from pipeline.lexicons import load_all_lexicons

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.db_path)
    app.state.lexicons = load_all_lexicons(settings.lexicons_dir)
    yield
```

This makes lexicons available in route handlers via `request.app.state.lexicons`.

**Verification:**

```bash
python -c "from pipeline.registry_api.main import app; print('OK')"
```

Expected: `OK` (import succeeds, no runtime errors)

**Commit:** `feat: load lexicons at app startup and store on app.state`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add lexicon validation to POST and PATCH routes

**Verifies:** None (implementation — tested in Task 3)

**Files:**
- Modify: `src/pipeline/registry_api/routes.py:34-55` (create_delivery POST)
- Modify: `src/pipeline/registry_api/routes.py:96-122` (update_single_delivery PATCH)
- Modify: `src/pipeline/registry_api/routes.py:72-80` (get_actionable_deliveries)

**Implementation:**

Routes need access to the loaded lexicons. Add `Request` import and pass `request` to route handlers that need lexicon access.

**POST /deliveries** (lines 34-55):

Add `request: Request` parameter. Before upserting, validate:
1. Look up `data.lexicon_id` in `request.app.state.lexicons`
2. If not found, raise `HTTPException(422, detail=f"unknown lexicon_id: {data.lexicon_id}")`
3. Validate `data.status` is in `lexicon.statuses`
4. If not, raise `HTTPException(422, detail=f"status '{data.status}' not valid for lexicon '{data.lexicon_id}'")`
5. If metadata provided in request, serialize to JSON string for DB storage. If not, set `metadata` to `"{}"`.

```python
from fastapi import APIRouter, HTTPException, Depends, Request
from datetime import datetime, timezone

@router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(data: DeliveryCreate, db: DbDep, request: Request):
    lexicons = request.app.state.lexicons
    lexicon = lexicons.get(data.lexicon_id)
    if lexicon is None:
        raise HTTPException(status_code=422, detail=f"unknown lexicon_id: {data.lexicon_id}")

    if data.status not in lexicon.statuses:
        raise HTTPException(
            status_code=422,
            detail=f"status '{data.status}' not valid for lexicon '{data.lexicon_id}'",
        )

    delivery_id = make_delivery_id(data.source_path)
    is_new = not delivery_exists(db, delivery_id)

    db_data = data.model_dump()
    # Serialize metadata dict to JSON string for SQLite storage
    db_data["metadata"] = json.dumps(db_data.get("metadata") or {})

    result = upsert_delivery(db, db_data)

    # Deserialize metadata back to dict for response
    if result and isinstance(result.get("metadata"), str):
        result["metadata"] = json.loads(result["metadata"])

    if is_new:
        response = DeliveryResponse(**result)
        event = insert_event(db, "delivery.created", delivery_id, response.model_dump())
        await manager.broadcast(event)

    return result
```

**PATCH /deliveries/{delivery_id}** (lines 96-122):

Add `request: Request`. After fetching old delivery, validate transition:
1. Look up lexicon from old delivery's `lexicon_id`
2. If `data.status` is provided and different from old status:
   a. Validate new status is in `lexicon.statuses`
   b. Validate transition: `new_status` must be in `lexicon.transitions[old_status]`
   c. Apply `set_on` rules: for each metadata field where `set_on == new_status`, auto-populate with current timestamp (for datetime type)
3. If status not changing, no validation or auto-population needed

```python
@router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(
    delivery_id: str, data: DeliveryUpdate, db: DbDep, request: Request,
):
    old = get_delivery(db, delivery_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    lexicons = request.app.state.lexicons
    lexicon = lexicons.get(old["lexicon_id"])

    updates = data.model_dump(exclude_none=True)
    old_status = old["status"]
    new_status = updates.get("status")

    if new_status is not None and new_status != old_status:
        if lexicon is None:
            raise HTTPException(status_code=422, detail=f"unknown lexicon_id: {old['lexicon_id']}")
        if new_status not in lexicon.statuses:
            raise HTTPException(
                status_code=422,
                detail=f"status '{new_status}' not valid for lexicon '{old['lexicon_id']}'",
            )
        allowed_transitions = lexicon.transitions.get(old_status, ())
        if new_status not in allowed_transitions:
            raise HTTPException(
                status_code=422,
                detail=f"transition from '{old_status}' to '{new_status}' not allowed for lexicon '{old['lexicon_id']}'",
            )

        # Apply set_on metadata rules
        existing_metadata = json.loads(old.get("metadata", "{}"))
        for field_name, field_def in lexicon.metadata_fields.items():
            if field_def.set_on == new_status:
                if field_def.type == "datetime":
                    existing_metadata[field_name] = datetime.now(timezone.utc).isoformat()
                elif field_def.type == "boolean":
                    existing_metadata[field_name] = True
                elif field_def.type == "string":
                    existing_metadata[field_name] = new_status
        updates["metadata"] = json.dumps(existing_metadata)

    elif "metadata" in updates:
        updates["metadata"] = json.dumps(updates["metadata"])

    result = update_delivery(db, delivery_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    # Deserialize metadata for response
    if isinstance(result.get("metadata"), str):
        result["metadata"] = json.loads(result["metadata"])

    actual_new_status = result["status"]
    if actual_new_status != old_status:
        response = DeliveryResponse(**result)
        event = insert_event(db, "delivery.status_changed", delivery_id, response.model_dump())
        await manager.broadcast(event)

    return result
```

Add `import json` to the top of routes.py.

**GET /deliveries/actionable** (lines 72-80):

Update to pass lexicon actionable statuses to `get_actionable()`:

```python
@router.get("/deliveries/actionable", response_model=list[DeliveryResponse])
async def get_actionable_deliveries(db: DbDep, request: Request):
    lexicons = request.app.state.lexicons
    lexicon_actionable = {
        lid: list(lex.actionable_statuses)
        for lid, lex in lexicons.items()
        if lex.actionable_statuses
    }
    results = get_actionable(db, lexicon_actionable)
    # Deserialize metadata for each result
    for r in results:
        if isinstance(r.get("metadata"), str):
            r["metadata"] = json.loads(r["metadata"])
    return results
```

Also update `list_all_deliveries` and `get_single_delivery` to deserialize metadata:

```python
@router.get("/deliveries", response_model=list[DeliveryResponse])
async def list_all_deliveries(db: DbDep, filters: DeliveryFilters = Depends()):
    results = list_deliveries(db, filters.model_dump(exclude_none=True))
    for r in results:
        if isinstance(r.get("metadata"), str):
            r["metadata"] = json.loads(r["metadata"])
    return results

@router.get("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def get_single_delivery(delivery_id: str, db: DbDep):
    result = get_delivery(db, delivery_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    if isinstance(result.get("metadata"), str):
        result["metadata"] = json.loads(result["metadata"])
    return result
```

**Commit:** `feat: add lexicon validation to POST/PATCH routes with set_on metadata`

<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Write API validation tests

**Verifies:** lexicon-system.AC4.1, lexicon-system.AC4.2, lexicon-system.AC4.3, lexicon-system.AC4.4, lexicon-system.AC4.5, lexicon-system.AC4.6

**Files:**
- Modify: `tests/conftest.py` (update `client` fixture to set up `app.state.lexicons`)
- Create or modify: test file for AC4 tests

**Implementation:**

The `client` fixture in `tests/conftest.py` needs to set up `app.state.lexicons` with test lexicon data so route validation works. Create a test lexicon that matches the QAR lexicon structure:

```python
from pipeline.lexicons.models import Lexicon, MetadataField

TEST_LEXICON = Lexicon(
    id="soc.qar",
    statuses=("pending", "passed", "failed"),
    transitions={"pending": ("passed", "failed"), "passed": (), "failed": ()},
    dir_map={"msoc": "passed", "msoc_new": "pending"},
    actionable_statuses=("passed",),
    metadata_fields={"passed_at": MetadataField(type="datetime", set_on="passed")},
    derive_hook=None,
)
```

In the `client` fixture, after creating the TestClient, set `app.state.lexicons`:

```python
app.state.lexicons = {"soc.qar": TEST_LEXICON}
```

**Testing:**

Tests must verify each AC listed above:

- **lexicon-system.AC4.1:** POST with `lexicon_id="soc.qar"` and `status="pending"`. Assert 200 response.
- **lexicon-system.AC4.2:** POST with `status="nonexistent"` for `lexicon_id="soc.qar"`. Assert 422 response with detail mentioning invalid status.
- **Unknown lexicon_id (additional):** POST with `lexicon_id="nonexistent"` and valid status. Assert 422 response with detail mentioning unknown lexicon_id.
- **lexicon-system.AC4.3:** Create a delivery with `status="pending"`, then PATCH with `status="passed"`. Assert 200 response.
- **lexicon-system.AC4.4:** Create a delivery with `status="passed"`, then PATCH with `status="pending"`. Assert 422 response (passed → pending not in transitions).
- **lexicon-system.AC4.5:** Create a delivery with `status="pending"`, then PATCH with `status="passed"`. Assert response `metadata` contains `passed_at` with a valid ISO timestamp.
- **lexicon-system.AC4.6:** Create a delivery with `status="pending"`, then PATCH with same `status="pending"`. Assert no event emitted (query events table, count should be 1 — only the creation event). Assert `metadata` does NOT contain `passed_at`.

Follow project testing patterns: class-based tests, `client` and `test_db` fixtures, direct DB queries for event verification.

**Verification:**

```bash
uv run pytest tests/registry_api/test_routes.py -v
```

Expected: All tests pass.

**Commit:** `test: add AC4.1-AC4.6 coverage for API lexicon validation`

<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Run full test suite, verify no regressions

**Verifies:** None (regression check)

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: All tests pass.

**Commit:** No commit if clean.

<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->
