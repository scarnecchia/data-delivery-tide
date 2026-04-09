# QA Registry Implementation Plan — Phase 5: API Routes

**Goal:** All HTTP endpoints wired up and functional — FastAPI app with lifespan, routes calling db functions, integration tests via TestClient.

**Architecture:** `main.py` creates the FastAPI app with lifespan handler for `init_db()`. `routes.py` defines all 6 endpoints using dependency injection for the db connection. Routes call db functions directly. TestClient integration tests override the db dependency to use in-memory SQLite.

**Tech Stack:** FastAPI 0.115+, Pydantic v2, stdlib sqlite3, httpx (TestClient)

**Scope:** 6 phases from original design (phase 5 of 6)

**Codebase verified:** 2026-04-09 — greenfield, Phase 3 provides db functions, Phase 4 provides Pydantic models.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### qa-registry.AC1: API Endpoints
- **qa-registry.AC1.1 Success:** `POST /deliveries` creates a new delivery and returns it with server-computed `delivery_id`
- **qa-registry.AC1.2 Success:** `POST /deliveries` with same `source_path` upserts (updates fields, preserves `first_seen_at`)
- **qa-registry.AC1.3 Success:** `GET /deliveries/{delivery_id}` returns the delivery
- **qa-registry.AC1.4 Failure:** `GET /deliveries/{delivery_id}` returns 404 for nonexistent ID
- **qa-registry.AC1.5 Success:** `PATCH /deliveries/{delivery_id}` updates only provided fields
- **qa-registry.AC1.6 Failure:** `PATCH /deliveries/{delivery_id}` returns 404 for nonexistent ID
- **qa-registry.AC1.7 Success:** `GET /health` returns `{"status": "ok"}`
- **qa-registry.AC1.8 Success:** `GET /deliveries/actionable` returns only deliveries with `qa_status=passed` and `parquet_converted_at IS NULL`

### qa-registry.AC3: Validation & Error Handling
- **qa-registry.AC3.1 Failure:** `POST /deliveries` with missing required fields returns 422
- **qa-registry.AC3.2 Failure:** `POST /deliveries` with invalid `qa_status` value returns 422
- **qa-registry.AC3.3 Failure:** `PATCH /deliveries/{delivery_id}` with empty body is a no-op (not an error)
- **qa-registry.AC3.4 Success:** `delivery_id` is deterministic — same `source_path` always produces same ID

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Create main.py with FastAPI app and lifespan

**Files:**
- Create: `src/pipeline/registry_api/main.py`

**Implementation:**

The `main.py` module needs:

1. **Lifespan context manager** using `@asynccontextmanager`:
   - On startup: call `init_db(settings.db_path)` from `pipeline.config`
   - On shutdown: nothing needed (connections are per-request)

2. **FastAPI app** — `app = FastAPI(title="QA Registry", lifespan=lifespan)`

3. **Router inclusion** — import and include the router from `routes.py` (created in Task 3)

4. **`run()` function** — the entrypoint called by the `registry-api` script:
   ```python
   def run():
       import uvicorn
       uvicorn.run("pipeline.registry_api.main:app", host="0.0.0.0", port=8000)
   ```

Note: `get_db()` and `DbDep` are defined in `db.py` (not here) to avoid circular imports between `main.py` and `routes.py`. Import `get_db` from `db.py` when needed for dependency overrides in tests.

**Step 1: Create the file**

**Step 2: Verify it imports (will fail on missing routes.py — that's expected)**

Run: `python -c "from pipeline.registry_api.main import app; print(type(app))"`
Expected: May fail because `routes.py` doesn't exist yet. That's OK — Task 3 creates it.

**Step 3: Commit**

```bash
git add src/pipeline/registry_api/main.py
git commit -m "feat: add FastAPI app with lifespan and db dependency injection"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update conftest.py with shared test fixtures

**Files:**
- Modify: `tests/conftest.py`

**Implementation:**

Add these fixtures to `conftest.py`:

1. **`test_db` fixture** (function scope for test isolation):
   - Creates an in-memory SQLite connection with `row_factory = sqlite3.Row`
   - Calls `init_db(conn)` — Phase 3 defined `init_db` to accept either a path string or a `sqlite3.Connection` object
   - Yields the connection
   - Closes it

2. **`client` fixture** that:
   - Takes `test_db` as a parameter (pytest auto-resolves the fixture dependency)
   - Imports `get_db` from `pipeline.registry_api.db` and `app` from `pipeline.registry_api.main`
   - Overrides the `get_db` dependency with a generator that yields `test_db`:
     ```python
     def override_get_db():
         yield test_db
     app.dependency_overrides[get_db] = override_get_db
     ```
   - Creates `TestClient(app)`
   - Yields the client
   - Clears `app.dependency_overrides` in cleanup

**Step 1: Update conftest.py with both fixtures**

**Step 2: Verify fixtures load**

Run: `pytest --fixtures -q | grep -E "test_db|client"`
Expected: Both fixtures listed

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "feat: add test_db and client fixtures for integration testing"
```
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Create routes.py with all 6 endpoints

**Files:**
- Create: `src/pipeline/registry_api/routes.py`

**Implementation:**

Create an `APIRouter` with all 6 endpoints. Each endpoint receives the db connection via `DbDep` (imported from `db.py`) and uses the db functions from Phase 3 and models from Phase 4.

Import `DbDep` from `pipeline.registry_api.db` — it was defined there in Phase 3 to avoid circular imports.

**Endpoints:**

1. **`GET /health`** — Returns `{"status": "ok"}`. No db hit. No dependency injection needed.

2. **`POST /deliveries`** — Accepts `DeliveryCreate` body.
   - Calls `upsert_delivery(db, data.model_dump())`
   - Returns `DeliveryResponse` with status 200
   
3. **`GET /deliveries`** — Accepts `DeliveryFilters` as query params via `Depends(DeliveryFilters)`.
   - Calls `list_deliveries(db, filters.model_dump(exclude_none=True))`
   - Returns `list[DeliveryResponse]`
   - Note: `Depends(DeliveryFilters)` unpacks the Pydantic model fields into individual query parameters. This is the standard FastAPI pattern for model-based query params.

4. **`GET /deliveries/actionable`** — No params.
   - Calls `get_actionable(db)`
   - Returns `list[DeliveryResponse]`
   
   **IMPORTANT:** This route MUST be defined BEFORE `GET /deliveries/{delivery_id}` in the router, otherwise FastAPI will try to match `"actionable"` as a `delivery_id` path parameter.

5. **`GET /deliveries/{delivery_id}`** — Path parameter.
   - Calls `get_delivery(db, delivery_id)`
   - Returns `DeliveryResponse` or raises `HTTPException(404)` if None

6. **`PATCH /deliveries/{delivery_id}`** — Accepts `DeliveryUpdate` body.
   - Calls `update_delivery(db, delivery_id, data.model_dump(exclude_none=True))`
   - Returns `DeliveryResponse` or raises `HTTPException(404)` if None
   - Empty body (all None fields) is a valid no-op — `exclude_none=True` produces empty dict, `update_delivery` returns the unchanged row

**Step 1: Create routes.py with all 6 endpoints**

**Step 3: Verify the app starts (may need all pieces in place)**

Run: `python -c "from pipeline.registry_api.main import app; print('Routes:', [r.path for r in app.routes])"`
Expected: Lists all route paths

**Step 4: Commit**

```bash
git add src/pipeline/registry_api/routes.py src/pipeline/registry_api/main.py src/pipeline/registry_api/db.py
git commit -m "feat: add all 6 API routes with FastAPI router"
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Integration tests for all endpoints

**Verifies:** qa-registry.AC1.1, qa-registry.AC1.2, qa-registry.AC1.3, qa-registry.AC1.4, qa-registry.AC1.5, qa-registry.AC1.6, qa-registry.AC1.7, qa-registry.AC1.8, qa-registry.AC3.1, qa-registry.AC3.2, qa-registry.AC3.3, qa-registry.AC3.4

**Files:**
- Create: `tests/registry_api/test_routes.py`

**Testing:**

Tests use the `client` fixture from `conftest.py` (TestClient with in-memory db override).

Tests must verify each AC:

**AC1 — API Endpoints:**
- **qa-registry.AC1.1:** POST `/deliveries` with valid body → 200, response includes server-computed `delivery_id` and all fields
- **qa-registry.AC1.2:** POST `/deliveries` twice with same `source_path` → second returns 200, `first_seen_at` preserved, other fields updated
- **qa-registry.AC1.3:** GET `/deliveries/{delivery_id}` after POST → 200, returns matching delivery
- **qa-registry.AC1.4:** GET `/deliveries/{delivery_id}` with nonexistent ID → 404
- **qa-registry.AC1.5:** PATCH `/deliveries/{delivery_id}` with `{"output_path": "/out"}` → 200, only `output_path` changed
- **qa-registry.AC1.6:** PATCH `/deliveries/{delivery_id}` with nonexistent ID → 404
- **qa-registry.AC1.7:** GET `/health` → 200, `{"status": "ok"}`
- **qa-registry.AC1.8:** POST two deliveries (one passed+unconverted, one pending), GET `/deliveries/actionable` → returns only the passed+unconverted one

**AC3 — Validation & Error Handling:**
- **qa-registry.AC3.1:** POST `/deliveries` with missing `source_path` → 422
- **qa-registry.AC3.2:** POST `/deliveries` with `qa_status: "invalid"` → 422
- **qa-registry.AC3.3:** PATCH `/deliveries/{delivery_id}` with empty body `{}` → 200, delivery unchanged
- **qa-registry.AC3.4:** POST two deliveries with same `source_path` → both return same `delivery_id`

Create a helper function `make_delivery_payload(**overrides)` that returns a valid `DeliveryCreate`-shaped dict with sensible defaults, accepting keyword overrides. This avoids repeating the full payload in every test.

**Verification:**

Run: `pytest tests/registry_api/test_routes.py -v`
Expected: All tests pass

**Commit:** `test: add integration tests for all API endpoints`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->

<!-- START_TASK_5 -->
### Task 5: Verify full test suite passes

**Step 1: Run all tests**

Run: `pytest -v`
Expected: All tests pass — test_config, test_db, test_models, test_routes

**Step 2: Verify no import errors or warnings**

Run: `python -c "from pipeline.registry_api.main import app; print('App loaded OK')"`
Expected: `App loaded OK`

**Step 3: Commit if any fixes were needed**

```bash
git add -u
git commit -m "fix: resolve any test or import issues from route integration"
```
<!-- END_TASK_5 -->
