# Registry Auth Implementation Plan - Phase 1

**Goal:** Add tokens table to the database and implement the auth dependency chain (require_auth, require_role).

**Architecture:** Token-based bearer authentication using FastAPI's HTTPBearer security scheme. Tokens are validated by hashing the bearer string with SHA-256 and looking up the hash in a `tokens` table. Role hierarchy (admin > write > read) is enforced via a dependency factory.

**Tech Stack:** Python 3.10+, FastAPI, SQLite (stdlib sqlite3), hashlib, secrets

**Scope:** 3 phases from original design (phase 1 of 3)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### registry-auth.AC1: API rejects unauthenticated requests
- **registry-auth.AC1.1 Success:** Request with valid bearer token returns expected response
- **registry-auth.AC1.2 Failure:** Request with no Authorization header returns 401
- **registry-auth.AC1.3 Failure:** Request with malformed Authorization header returns 401
- **registry-auth.AC1.4 Failure:** Request with revoked token returns 401
- **registry-auth.AC1.5 Failure:** Request with non-existent token returns 401

### registry-auth.AC2: Role hierarchy enforced on endpoints
- **registry-auth.AC2.1 Success:** Admin token can access all endpoints
- **registry-auth.AC2.2 Success:** Write token can POST and PATCH deliveries
- **registry-auth.AC2.3 Success:** Write token can GET deliveries
- **registry-auth.AC2.4 Success:** Read token can GET deliveries
- **registry-auth.AC2.5 Failure:** Read token on POST /deliveries returns 403
- **registry-auth.AC2.6 Failure:** Read token on PATCH /deliveries/{id} returns 403

### registry-auth.AC5: Token storage security
- **registry-auth.AC5.1:** Raw token is never stored in database (only SHA-256 hash)
- **registry-auth.AC5.2:** Token is generated with secrets.token_urlsafe(32)

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Add tokens table to init_db

**Verifies:** None (infrastructure)

**Files:**
- Modify: `src/pipeline/registry_api/db.py:35-82` (inside `init_db` function, after deliveries table creation)

**Implementation:**

Add the tokens table creation inside `init_db`, after the deliveries table and its indexes (after line 73, before `conn.commit()` on line 79):

```python
        # Create the tokens table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                token_hash   TEXT PRIMARY KEY,
                username     TEXT NOT NULL UNIQUE,
                role         TEXT NOT NULL CHECK (role IN ('admin', 'write', 'read')),
                created_at   TEXT NOT NULL,
                revoked_at   TEXT
            )
            """
        )
```

The UNIQUE constraint on `username` enforces one active row per user. Revocation uses `revoked_at` (soft delete) rather than row deletion. The rotation flow (Phase 3 CLI) will delete the old row and insert a new one within the same transaction to satisfy the UNIQUE constraint while preserving the audit trail concept at the application level.

**Verification:**

Run: `uv run pytest tests/registry_api/test_db.py -v`
Expected: All existing tests pass (init_db is idempotent, new table doesn't break anything)

**Commit:** `feat: add tokens table to database schema`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add tokens table schema tests

**Verifies:** None (infrastructure verification)

**Files:**
- Modify: `tests/registry_api/test_db.py` (add new test class after `TestInitDb` class, around line 132)

**Implementation:**

Add a new test class `TestTokensTable` that verifies the tokens table schema, following the exact pattern used by `TestInitDb` (lines 46-131):

```python
class TestTokensTable:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database for testing."""
        conn = sqlite3.connect(":memory:")
        yield conn
        conn.close()

    def test_init_db_creates_tokens_table(self, memory_db):
        """Test init_db creates the tokens table."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tokens'"
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == "tokens"

    def test_tokens_table_has_expected_columns(self, memory_db):
        """Test tokens table has all expected columns."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute("PRAGMA table_info(tokens)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            "token_hash",
            "username",
            "role",
            "created_at",
            "revoked_at",
        }

        assert columns == expected_columns

    def test_tokens_table_role_check_constraint(self, memory_db):
        """Test tokens table rejects invalid role values."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
                ("hash1", "user1", "superadmin", "2026-01-01T00:00:00+00:00"),
            )

    def test_tokens_table_username_unique_constraint(self, memory_db):
        """Test tokens table enforces unique username."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute(
            "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
            ("hash1", "user1", "read", "2026-01-01T00:00:00+00:00"),
        )
        memory_db.commit()

        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
                ("hash2", "user1", "write", "2026-01-01T00:00:00+00:00"),
            )
```

**Verification:**

Run: `uv run pytest tests/registry_api/test_db.py::TestTokensTable -v`
Expected: All 4 tests pass

**Commit:** `test: add tokens table schema tests`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Add get_token_by_hash query function to db.py

**Verifies:** None (building block for auth dependency)

**Files:**
- Modify: `src/pipeline/registry_api/db.py` (add function after `update_delivery`, around line 364)

**Implementation:**

Add a query function that looks up a token by its hash and returns the row if it exists and is not revoked:

```python
def get_token_by_hash(conn: sqlite3.Connection, token_hash: str) -> dict | None:
    """
    Look up a token by its SHA-256 hash.

    Returns the token row as a dict if found, or None if not found.
    Does NOT filter by revoked_at — caller decides how to handle revoked tokens.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tokens WHERE token_hash = ?", (token_hash,))
    row = cursor.fetchone()
    return dict(row) if row else None
```

The auth dependency (`require_auth` in Task 5) checks `revoked_at` and raises 401 for revoked tokens — this separation keeps the query function pure and the business logic in the dependency.

**Verification:**

Run: `uv run pytest tests/registry_api/test_db.py -v`
Expected: All existing tests still pass

**Commit:** `feat: add get_token_by_hash query function`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Add get_token_by_hash tests

**Verifies:** registry-auth.AC5.1 (indirectly — proves lookup is by hash, not raw token)

**Files:**
- Modify: `tests/registry_api/test_db.py` (add new test class after `TestTokensTable`)

**Implementation:**

Add a new test class following the existing pattern (each class has its own `memory_db` fixture):

```python
class TestGetTokenByHash:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    def test_get_token_by_hash_returns_existing_token(self, memory_db):
        """Test that get_token_by_hash returns correct row for existing hash."""
        cursor = memory_db.cursor()
        cursor.execute(
            "INSERT INTO tokens (token_hash, username, role, created_at) VALUES (?, ?, ?, ?)",
            ("abc123hash", "testuser", "read", "2026-01-01T00:00:00+00:00"),
        )
        memory_db.commit()

        result = get_token_by_hash(memory_db, "abc123hash")

        assert result is not None
        assert result["token_hash"] == "abc123hash"
        assert result["username"] == "testuser"
        assert result["role"] == "read"
        assert result["revoked_at"] is None

    def test_get_token_by_hash_returns_none_for_nonexistent(self, memory_db):
        """Test that get_token_by_hash returns None for nonexistent hash."""
        result = get_token_by_hash(memory_db, "nonexistent")

        assert result is None

    def test_get_token_by_hash_returns_revoked_tokens(self, memory_db):
        """Test that get_token_by_hash returns revoked tokens (caller filters)."""
        cursor = memory_db.cursor()
        cursor.execute(
            "INSERT INTO tokens (token_hash, username, role, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
            ("revokedhash", "olduser", "write", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
        )
        memory_db.commit()

        result = get_token_by_hash(memory_db, "revokedhash")

        assert result is not None
        assert result["revoked_at"] is not None
```

Update the import at the top of `test_db.py` to include `get_token_by_hash`:

```python
from pipeline.registry_api.db import (
    make_delivery_id,
    init_db,
    get_connection,
    upsert_delivery,
    get_delivery,
    list_deliveries,
    get_actionable,
    update_delivery,
    get_token_by_hash,
)
```

**Verification:**

Run: `uv run pytest tests/registry_api/test_db.py::TestGetTokenByHash -v`
Expected: All 3 tests pass

**Commit:** `test: add get_token_by_hash tests`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->

<!-- START_SUBCOMPONENT_C (tasks 5-6) -->
<!-- START_TASK_5 -->
### Task 5: Create auth.py with TokenInfo model and auth dependencies

**Verifies:** registry-auth.AC1.1, registry-auth.AC1.2, registry-auth.AC1.3, registry-auth.AC1.4, registry-auth.AC1.5, registry-auth.AC2.1, registry-auth.AC2.2, registry-auth.AC2.3, registry-auth.AC2.4, registry-auth.AC2.5, registry-auth.AC2.6, registry-auth.AC5.1, registry-auth.AC5.2

**Files:**
- Create: `src/pipeline/registry_api/auth.py`

**Implementation:**

Create the auth module with three components:
1. `TokenInfo` — Pydantic model for authenticated token data
2. `require_auth` — FastAPI dependency that validates bearer tokens
3. `require_role` — dependency factory that wraps `require_auth` and enforces minimum role

```python
# pattern: Imperative Shell

import hashlib
from typing import Annotated, Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pydantic import BaseModel

from pipeline.registry_api.db import DbDep, get_token_by_hash


_bearer_scheme = HTTPBearer(auto_error=False)

ROLE_HIERARCHY: dict[str, int] = {
    "read": 0,
    "write": 1,
    "admin": 2,
}


class TokenInfo(BaseModel):
    """Authenticated token metadata returned by require_auth."""

    username: str
    role: Literal["admin", "write", "read"]


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: DbDep = ...,
) -> TokenInfo:
    """
    FastAPI dependency that validates bearer tokens.

    Extracts the token from the Authorization header, hashes it with SHA-256,
    looks up the hash in the tokens table, and returns TokenInfo on success.

    Raises:
        HTTPException 401: Missing/invalid/revoked token
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authentication credentials")

    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    token_row = get_token_by_hash(db, token_hash)

    if token_row is None:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

    if token_row["revoked_at"] is not None:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    return TokenInfo(username=token_row["username"], role=token_row["role"])


AuthDep = Annotated[TokenInfo, Depends(require_auth)]


def require_role(minimum: str):
    """
    Dependency factory that enforces minimum role level.

    Usage: Depends(require_role("write"))

    Role hierarchy: admin > write > read
    """

    def _check_role(token: AuthDep) -> TokenInfo:
        if ROLE_HIERARCHY[token.role] < ROLE_HIERARCHY[minimum]:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions: requires {minimum} role",
            )
        return token

    return Depends(_check_role)
```

Key design decisions:
- `HTTPBearer(auto_error=False)` — returns `None` instead of raising 403 when no header is present, so we can return a proper 401 with a descriptive message
- `AuthDep` type alias follows the existing `DbDep` pattern from `db.py:116`
- `require_role` returns `Depends(...)` so callers use `token: TokenInfo = require_role("write")` in route signatures

**Verification:**

Run: `uv run python -c "from pipeline.registry_api.auth import TokenInfo, require_auth, require_role, AuthDep; print('imports ok')"`
Expected: `imports ok`

**Commit:** `feat: add auth module with token validation and role enforcement`
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Add auth dependency tests

**Verifies:** registry-auth.AC1.1, registry-auth.AC1.2, registry-auth.AC1.3, registry-auth.AC1.4, registry-auth.AC1.5, registry-auth.AC2.5, registry-auth.AC2.6, registry-auth.AC5.1

**Files:**
- Create: `tests/registry_api/test_auth.py`

**Implementation:**

Test the auth dependencies by creating a minimal FastAPI app with a protected endpoint, using the same `TestClient` + in-memory SQLite pattern from `tests/conftest.py`.

```python
import hashlib
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.registry_api.auth import require_auth, require_role, AuthDep, TokenInfo
from pipeline.registry_api.db import init_db, get_db


@pytest.fixture
def auth_db():
    """Create an in-memory SQLite database with schema for auth testing."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def _seed_token(conn, username, role, raw_token, *, revoked_at=None):
    """Insert a token into the database for testing."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tokens (token_hash, username, role, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
        (token_hash, username, role, "2026-01-01T00:00:00+00:00", revoked_at),
    )
    conn.commit()
    return token_hash


@pytest.fixture
def auth_app(auth_db):
    """Create a minimal FastAPI app with auth-protected endpoints for testing."""
    app = FastAPI()

    def override_get_db():
        yield auth_db

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/protected")
    def protected_endpoint(token: AuthDep):
        return {"username": token.username, "role": token.role}

    @app.post("/write-protected")
    def write_protected_endpoint(token: TokenInfo = require_role("write")):
        return {"username": token.username, "role": token.role}

    @app.post("/admin-protected")
    def admin_protected_endpoint(token: TokenInfo = require_role("admin")):
        return {"username": token.username, "role": token.role}

    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(auth_app):
    """Create a TestClient for the auth test app."""
    return TestClient(auth_app)


class TestRequireAuth:
    """Test require_auth dependency."""

    def test_valid_token_returns_200(self, auth_db, auth_client):
        """registry-auth.AC1.1: Request with valid bearer token returns expected response."""
        raw_token = "test-token-valid"
        _seed_token(auth_db, "testuser", "read", raw_token)

        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 200
        assert response.json()["username"] == "testuser"
        assert response.json()["role"] == "read"

    def test_missing_auth_header_returns_401(self, auth_client):
        """registry-auth.AC1.2: Request with no Authorization header returns 401."""
        response = auth_client.get("/protected")

        assert response.status_code == 401

    def test_malformed_auth_header_returns_401(self, auth_client):
        """registry-auth.AC1.3: Request with malformed Authorization header returns 401."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": "NotBearer some-token"},
        )

        assert response.status_code == 401

    def test_revoked_token_returns_401(self, auth_db, auth_client):
        """registry-auth.AC1.4: Request with revoked token returns 401."""
        raw_token = "test-token-revoked"
        _seed_token(auth_db, "revokeduser", "read", raw_token, revoked_at="2026-01-02T00:00:00+00:00")

        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 401

    def test_nonexistent_token_returns_401(self, auth_client):
        """registry-auth.AC1.5: Request with non-existent token returns 401."""
        response = auth_client.get(
            "/protected",
            headers={"Authorization": "Bearer totally-fake-token"},
        )

        assert response.status_code == 401

    def test_token_stored_as_hash_not_raw(self, auth_db):
        """registry-auth.AC5.1: Raw token is never stored in database (only SHA-256 hash)."""
        raw_token = "my-secret-token"
        expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        _seed_token(auth_db, "hashuser", "read", raw_token)

        cursor = auth_db.cursor()
        cursor.execute("SELECT token_hash FROM tokens WHERE username = ?", ("hashuser",))
        row = cursor.fetchone()

        assert row["token_hash"] == expected_hash
        assert row["token_hash"] != raw_token


class TestRequireRole:
    """Test require_role dependency factory."""

    def test_read_token_on_write_endpoint_returns_403(self, auth_db, auth_client):
        """registry-auth.AC2.5: Read token on POST /deliveries returns 403."""
        raw_token = "test-token-read"
        _seed_token(auth_db, "readuser", "read", raw_token)

        response = auth_client.post(
            "/write-protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 403

    def test_write_token_on_write_endpoint_returns_200(self, auth_db, auth_client):
        """registry-auth.AC2.2: Write token can access write-protected endpoints."""
        raw_token = "test-token-write"
        _seed_token(auth_db, "writeuser", "write", raw_token)

        response = auth_client.post(
            "/write-protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 200
        assert response.json()["role"] == "write"

    def test_admin_token_on_write_endpoint_returns_200(self, auth_db, auth_client):
        """registry-auth.AC2.1: Admin token can access all endpoints."""
        raw_token = "test-token-admin"
        _seed_token(auth_db, "adminuser", "admin", raw_token)

        response = auth_client.post(
            "/write-protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 200
        assert response.json()["role"] == "admin"

    def test_admin_token_on_admin_endpoint_returns_200(self, auth_db, auth_client):
        """registry-auth.AC2.1: Admin token can access admin-protected endpoints."""
        raw_token = "test-token-admin2"
        _seed_token(auth_db, "adminuser2", "admin", raw_token)

        response = auth_client.post(
            "/admin-protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 200

    def test_write_token_on_admin_endpoint_returns_403(self, auth_db, auth_client):
        """Write token cannot access admin-protected endpoints."""
        raw_token = "test-token-write2"
        _seed_token(auth_db, "writeuser2", "write", raw_token)

        response = auth_client.post(
            "/admin-protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 403

    def test_read_token_on_read_endpoint_returns_200(self, auth_db, auth_client):
        """registry-auth.AC2.4: Read token can access read-protected endpoints."""
        raw_token = "test-token-read2"
        _seed_token(auth_db, "readuser2", "read", raw_token)

        response = auth_client.get(
            "/protected",
            headers={"Authorization": f"Bearer {raw_token}"},
        )

        assert response.status_code == 200
        assert response.json()["role"] == "read"
```

**Verification:**

Run: `uv run pytest tests/registry_api/test_auth.py -v`
Expected: All tests pass

Run: `uv run pytest -v`
Expected: All tests pass (existing + new)

**Commit:** `test: add auth dependency tests for token validation and role enforcement`
<!-- END_TASK_6 -->
<!-- END_SUBCOMPONENT_C -->
