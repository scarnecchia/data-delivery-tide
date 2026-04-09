import sqlite3

import pytest
from fastapi.testclient import TestClient

from pipeline.registry_api.db import init_db, get_db
from pipeline.registry_api.main import app


@pytest.fixture
def test_db():
    """
    Create an in-memory SQLite database for testing.

    Initializes the schema and yields the connection for the test.
    Closes the connection after the test completes.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    init_db(conn)

    yield conn

    conn.close()


@pytest.fixture
def client(test_db):
    """
    Create a FastAPI TestClient with dependency overrides.

    Overrides the get_db dependency to use the in-memory test database.
    Cleans up the overrides after the test completes.
    """

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app)

    app.dependency_overrides.clear()
