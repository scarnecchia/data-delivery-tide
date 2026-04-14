import sqlite3

import pytest
from fastapi.testclient import TestClient

from pipeline.registry_api.db import init_db, get_db
from pipeline.registry_api.main import app
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
    app.state.lexicons = {"soc.qar": TEST_LEXICON}

    yield TestClient(app)

    app.dependency_overrides.clear()
