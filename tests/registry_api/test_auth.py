# pattern: test file
import hashlib
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.registry_api.auth import AuthDep, TokenInfo, require_role
from pipeline.registry_api.db import get_db, init_db


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
    def write_protected_endpoint(token: TokenInfo = require_role("write")):  # noqa: B008
        return {"username": token.username, "role": token.role}

    @app.post("/admin-protected")
    def admin_protected_endpoint(token: TokenInfo = require_role("admin")):  # noqa: B008
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
        _seed_token(
            auth_db, "revokeduser", "read", raw_token, revoked_at="2026-01-02T00:00:00+00:00"
        )

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
