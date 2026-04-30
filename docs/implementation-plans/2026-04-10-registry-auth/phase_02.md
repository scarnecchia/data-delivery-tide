# Registry Auth Implementation Plan - Phase 2

**Goal:** Wire auth into the API by splitting routers and protecting delivery endpoints with role-based access control.

**Architecture:** Split the single router into a public router (/health) and a protected router (/deliveries). The protected router gets `require_auth` as a router-level dependency. POST and PATCH endpoints add an explicit `require_role("write")` dependency. Existing tests are updated to include bearer tokens.

**Tech Stack:** Python 3.10+, FastAPI, SQLite (stdlib sqlite3)

**Scope:** 3 phases from original design (phase 2 of 3)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### registry-auth.AC1: API rejects unauthenticated requests
- **registry-auth.AC1.6 Success:** /health returns 200 with no Authorization header

### registry-auth.AC2: Role hierarchy enforced on endpoints
- **registry-auth.AC2.1 Success:** Admin token can access all endpoints
- **registry-auth.AC2.2 Success:** Write token can POST and PATCH deliveries
- **registry-auth.AC2.3 Success:** Write token can GET deliveries
- **registry-auth.AC2.4 Success:** Read token can GET deliveries
- **registry-auth.AC2.5 Failure:** Read token on POST /deliveries returns 403
- **registry-auth.AC2.6 Failure:** Read token on PATCH /deliveries/{id} returns 403

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Split routes.py into public and protected routers

**Verifies:** None (infrastructure wiring — verified by tests in Task 3)

**Files:**
- Modify: `src/pipeline/registry_api/routes.py` (restructure into two routers)
- Modify: `src/pipeline/registry_api/main.py` (mount both routers)

**Implementation:**

**routes.py** — Split into `public_router` (health) and `protected_router` (deliveries). The protected router gets `require_auth` as a router-level dependency via `dependencies=[Depends(require_auth)]`. POST and PATCH endpoints add `require_role("write")` as an additional per-endpoint dependency.

Replace the entire `routes.py` content:

```python
# pattern: Imperative Shell
from fastapi import APIRouter, Depends, HTTPException

from pipeline.registry_api.auth import AuthDep, TokenInfo, require_auth, require_role
from pipeline.registry_api.db import (
    DbDep,
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

public_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(require_auth)])


@public_router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@protected_router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(
    data: DeliveryCreate,
    db: DbDep,
    token: TokenInfo = require_role("write"),
):
    """
    Create or upsert a delivery.

    If a delivery with the same source_path already exists, updates its fields
    while preserving first_seen_at. Returns the created or updated delivery.
    """
    result = upsert_delivery(db, data.model_dump())
    return result


@protected_router.get("/deliveries", response_model=list[DeliveryResponse])
async def list_all_deliveries(db: DbDep, filters: DeliveryFilters = Depends()):
    """
    List deliveries with optional filtering.

    Query parameters:
    - dp_id, project, request_type, workplan_id, request_id, qa_status, scan_root: exact match
    - converted: boolean, True = converted, False = not converted
    - version: exact match or "latest" for highest version per (dp_id, workplan_id)
    """
    results = list_deliveries(db, filters.model_dump(exclude_none=True))
    return results


@protected_router.get("/deliveries/actionable", response_model=list[DeliveryResponse])
async def get_actionable_deliveries(db: DbDep):
    """
    Get actionable deliveries (passed QA but not yet converted to Parquet).

    Returns all deliveries where qa_status='passed' AND parquet_converted_at IS NULL.
    """
    results = get_actionable(db)
    return results


@protected_router.get("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def get_single_delivery(delivery_id: str, db: DbDep):
    """
    Retrieve a delivery by ID.

    Returns 404 if delivery not found.
    """
    result = get_delivery(db, delivery_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return result


@protected_router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(
    delivery_id: str,
    data: DeliveryUpdate,
    db: DbDep,
    token: TokenInfo = require_role("write"),
):
    """
    Partially update a delivery.

    Only provided fields are updated. Empty body is a valid no-op.
    Returns 404 if delivery not found.
    """
    result = update_delivery(db, delivery_id, data.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return result
```

**main.py** — Update to import and mount both routers:

```python
# pattern: Imperative Shell
from contextlib import asynccontextmanager

from fastapi import FastAPI

from pipeline.config import settings
from pipeline.registry_api.db import init_db
from pipeline.registry_api.routes import public_router, protected_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.

    On startup: Initialize the database schema.
    On shutdown: Nothing needed (connections are per-request).
    """
    init_db(settings.db_path)
    yield


app = FastAPI(title="QA Registry", lifespan=lifespan)
app.include_router(public_router)
app.include_router(protected_router)


def run():
    """
    Entrypoint for the registry-api script.

    Starts the FastAPI application using uvicorn.
    """
    import uvicorn

    uvicorn.run("pipeline.registry_api.main:app", host="0.0.0.0", port=8000)
```

**Verification:**

Run: `uv run python -c "from pipeline.registry_api.main import app; print([r.path for r in app.routes])"`
Expected: Routes include `/health`, `/deliveries`, `/deliveries/actionable`, `/deliveries/{delivery_id}`

**Commit:** `feat: split routes into public and protected routers with auth enforcement`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update test fixtures to support auth tokens

**Verifies:** None (infrastructure — enables auth-aware testing)

**Files:**
- Modify: `tests/conftest.py` (add auth token seeding helper and update `client` fixture)

**Implementation:**

Update `tests/conftest.py` to add a helper that seeds a write-role token into the test database and provides headers. The existing `client` fixture stays the same. Add a new `auth_headers` fixture that provides valid bearer headers for tests that need them.

Add the following after the existing `client` fixture:

```python
import hashlib

TEST_TOKEN_RAW = "test-integration-token"
TEST_TOKEN_HASH = hashlib.sha256(TEST_TOKEN_RAW.encode()).hexdigest()


@pytest.fixture
def auth_headers(test_db):
    """
    Seed a write-role token into the test database and return auth headers.

    Provides headers with a valid write-role bearer token for use in route tests.
    """
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
        (TEST_TOKEN_HASH, "test-writer", "write", "2026-01-01T00:00:00+00:00"),
    )
    test_db.commit()
    return {"Authorization": f"Bearer {TEST_TOKEN_RAW}"}


@pytest.fixture
def read_auth_headers(test_db):
    """
    Seed a read-role token into the test database and return auth headers.

    Provides headers with a valid read-role bearer token for role enforcement tests.
    """
    read_token = "test-read-token"
    read_hash = hashlib.sha256(read_token.encode()).hexdigest()
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
        (read_hash, "test-reader", "read", "2026-01-01T00:00:00+00:00"),
    )
    test_db.commit()
    return {"Authorization": f"Bearer {read_token}"}
```

Update the import line at the top of `tests/conftest.py`:

```python
import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from pipeline.registry_api.db import init_db, get_db
from pipeline.registry_api.main import app
```

**Verification:**

Run: `uv run pytest tests/registry_api/test_routes.py::TestHealth -v`
Expected: Health test still passes (no auth required)

**Commit:** `test: add auth token fixtures for route testing`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Update existing route tests to include auth headers

**Verifies:** registry-auth.AC2.2, registry-auth.AC2.3

**Files:**
- Modify: `tests/registry_api/test_routes.py` (add `auth_headers` to all delivery endpoint tests)

**Implementation:**

Every test in `TestCreateDelivery`, `TestGetDelivery`, `TestListDeliveries`, `TestActionableDeliveries`, and `TestUpdateDelivery` that calls a `/deliveries` endpoint needs the `auth_headers` fixture added as a parameter and the headers passed to the request.

Pattern for each test method:

**Before (example from TestCreateDelivery):**
```python
def test_create_delivery_success(self, client):
    payload = make_delivery_payload()
    response = client.post("/deliveries", json=payload)
```

**After:**
```python
def test_create_delivery_success(self, client, auth_headers):
    payload = make_delivery_payload()
    response = client.post("/deliveries", json=payload, headers=auth_headers)
```

Apply this transformation to every test method in these classes:

- `TestCreateDelivery`: 5 methods — add `auth_headers` param, add `headers=auth_headers` to all `.post("/deliveries", ...)` calls
- `TestGetDelivery`: 2 methods — add `auth_headers` param, add `headers=auth_headers` to `.get(f"/deliveries/...")` and `.post(...)` calls
- `TestListDeliveries`: 3 methods — add `auth_headers` param, add `headers=auth_headers` to `.get("/deliveries...")` and `.post(...)` calls
- `TestActionableDeliveries`: 2 methods — add `auth_headers` param, add `headers=auth_headers` to `.get("/deliveries/actionable")`, `.post(...)`, and `.patch(...)` calls
- `TestUpdateDelivery`: 5 methods — add `auth_headers` param, add `headers=auth_headers` to `.patch(f"/deliveries/...")` and `.post(...)` calls

`TestHealth` does NOT get modified — it should continue working without auth headers.

**Verification:**

Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: All existing tests pass with auth headers

**Commit:** `test: update delivery route tests to use auth headers`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Add auth enforcement tests for routes

**Verifies:** registry-auth.AC1.6, registry-auth.AC2.4, registry-auth.AC2.5, registry-auth.AC2.6

**Files:**
- Modify: `tests/registry_api/test_routes.py` (add new test classes)

**Implementation:**

Add two new test classes at the end of `test_routes.py`:

```python
class TestHealthNoAuth:
    """Test that /health is accessible without authentication."""

    def test_health_no_auth_header_returns_200(self, client):
        """registry-auth.AC1.6: /health returns 200 with no Authorization header."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestAuthEnforcement:
    """Test authentication and authorization enforcement on delivery routes."""

    def test_get_deliveries_no_auth_returns_401(self, client):
        """GET /deliveries without auth returns 401."""
        response = client.get("/deliveries")
        assert response.status_code == 401

    def test_post_deliveries_no_auth_returns_401(self, client):
        """POST /deliveries without auth returns 401."""
        payload = make_delivery_payload()
        response = client.post("/deliveries", json=payload)
        assert response.status_code == 401

    def test_patch_delivery_no_auth_returns_401(self, client):
        """PATCH /deliveries/{id} without auth returns 401."""
        response = client.patch(
            "/deliveries/some-id",
            json={"qa_status": "passed"},
        )
        assert response.status_code == 401

    def test_get_actionable_no_auth_returns_401(self, client):
        """GET /deliveries/actionable without auth returns 401."""
        response = client.get("/deliveries/actionable")
        assert response.status_code == 401

    def test_read_token_can_get_deliveries(self, client, read_auth_headers):
        """registry-auth.AC2.4: Read token can GET deliveries."""
        response = client.get("/deliveries", headers=read_auth_headers)
        assert response.status_code == 200

    def test_read_token_cannot_post_deliveries(self, client, read_auth_headers):
        """registry-auth.AC2.5: Read token on POST /deliveries returns 403."""
        payload = make_delivery_payload()
        response = client.post("/deliveries", json=payload, headers=read_auth_headers)
        assert response.status_code == 403

    def test_read_token_cannot_patch_deliveries(self, client, auth_headers, read_auth_headers):
        """registry-auth.AC2.6: Read token on PATCH /deliveries/{id} returns 403."""
        payload = make_delivery_payload(source_path="/data/role-test")
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"qa_status": "passed"},
            headers=read_auth_headers,
        )
        assert response.status_code == 403
```

**Verification:**

Run: `uv run pytest tests/registry_api/test_routes.py -v`
Expected: All tests pass (existing + new auth enforcement tests)

Run: `uv run pytest -v`
Expected: Full test suite passes

**Commit:** `test: add auth enforcement tests for route protection`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->
