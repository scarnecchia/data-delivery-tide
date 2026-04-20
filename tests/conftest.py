import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from pipeline.registry_api.db import init_db, get_db
from pipeline.registry_api.main import app
from pipeline.lexicons.models import Lexicon, MetadataField
from pipeline.config import ScanRoot


TEST_LEXICON = Lexicon(
    id="soc.qar",
    statuses=("pending", "passed", "failed"),
    transitions={"pending": ("passed", "failed"), "passed": (), "failed": ()},
    dir_map={"msoc": "passed", "msoc_new": "pending"},
    actionable_statuses=("passed",),
    metadata_fields={"passed_at": MetadataField(type="datetime", set_on="passed")},
    derive_hook=None,
)

TEST_SUB_LEXICON = Lexicon(
    id="test.sub",
    statuses=("pending", "passed", "failed"),
    transitions={"pending": ("passed", "failed"), "passed": (), "failed": ()},
    dir_map={"msoc": "passed", "msoc_new": "pending"},
    actionable_statuses=("passed",),
    metadata_fields={},
    derive_hook=None,
)


@pytest.fixture
def test_db():
    """
    Create an in-memory SQLite database for testing.

    Initializes the schema and yields the connection for the test.
    Closes the connection after the test completes.

    Uses check_same_thread=False to allow TestClient to use the connection
    across multiple threads.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    init_db(conn)

    yield conn

    conn.close()


@pytest.fixture
def client(test_db):
    """
    Create a FastAPI TestClient with dependency overrides.

    Overrides the get_db dependency to use the in-memory test database.
    Sets up app.state.lexicons with test lexicon data.
    Cleans up the overrides after the test completes.
    """

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    app.state.lexicons = {"soc.qar": TEST_LEXICON, "test.sub": TEST_SUB_LEXICON}
    app.state.scan_roots = [
        ScanRoot(path="/data", label="Test Data", lexicon="soc.qar"),
        ScanRoot(path="/source", label="Test Source", lexicon="soc.qar"),
        ScanRoot(path="/requests/qa", label="QA Packages", lexicon="soc.qar"),
        ScanRoot(path="/scan", label="Scans", lexicon="soc.qar"),
        ScanRoot(path="/test", label="Tests", lexicon="soc.qar"),
    ]

    yield TestClient(app)

    app.dependency_overrides.clear()


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
