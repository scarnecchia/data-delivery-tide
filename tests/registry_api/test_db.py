import hashlib
import sqlite3
import pytest

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
    insert_event,
    get_events_after,
    delivery_exists,
)


class TestMakeDeliveryId:
    def test_make_delivery_id_deterministic(self):
        """Test that make_delivery_id produces deterministic SHA-256 hex digest."""
        source_path = "/path/to/delivery"

        id1 = make_delivery_id(source_path)
        id2 = make_delivery_id(source_path)

        assert id1 == id2

    def test_make_delivery_id_different_inputs(self):
        """Test that different inputs produce different IDs."""
        id1 = make_delivery_id("/path/one")
        id2 = make_delivery_id("/path/two")

        assert id1 != id2

    def test_make_delivery_id_is_sha256_hex(self):
        """Test that delivery_id is valid SHA-256 hex digest."""
        source_path = "test"
        expected = hashlib.sha256(source_path.encode()).hexdigest()

        result = make_delivery_id(source_path)

        assert result == expected
        assert len(result) == 64  # SHA-256 hex is 64 chars
        assert all(c in "0123456789abcdef" for c in result)


class TestInitDb:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database for testing."""
        conn = sqlite3.connect(":memory:")
        yield conn
        conn.close()

    def test_init_db_with_connection(self, memory_db):
        """Test init_db creates table when given a connection."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='deliveries'"
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == "deliveries"

    def test_init_db_creates_all_columns(self, memory_db):
        """Test init_db creates table with all expected columns."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute("PRAGMA table_info(deliveries)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            "delivery_id",
            "request_id",
            "project",
            "request_type",
            "workplan_id",
            "dp_id",
            "version",
            "scan_root",
            "lexicon_id",
            "status",
            "metadata",
            "first_seen_at",
            "parquet_converted_at",
            "file_count",
            "total_bytes",
            "source_path",
            "output_path",
            "fingerprint",
            "last_updated_at",
        }

        assert columns == expected_columns

    def test_init_db_idempotent(self, memory_db):
        """Test init_db is idempotent (calling twice doesn't error)."""
        init_db(memory_db)
        init_db(memory_db)  # Should not raise

        cursor = memory_db.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='deliveries'"
        )
        assert cursor.fetchone()[0] == 1

    def test_init_db_creates_indexes(self, memory_db):
        """Test init_db creates expected indexes."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN ('idx_actionable', 'idx_dp_wp', 'idx_request_id')"
        )
        indexes = {row[0] for row in cursor.fetchall()}

        expected_indexes = {"idx_actionable", "idx_dp_wp", "idx_request_id"}
        assert indexes == expected_indexes

    def test_init_db_with_memory_connection_no_wal(self, memory_db):
        """Test that WAL mode is not set on in-memory databases."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        # In-memory databases should remain in memory mode
        assert journal_mode in ("memory", "memory mode")


class TestMigrateEventsCheckConstraint:
    """Tests for the events table CHECK constraint migration."""

    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database for testing."""
        conn = sqlite3.connect(":memory:")
        yield conn
        conn.close()

    def test_fresh_db_supports_conversion_events(self, memory_db):
        """AC6.1: Fresh DB created via init_db accepts conversion event types."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("conversion.completed", "delivery-1", '{}', "2026-01-01T00:00:00Z"),
        )
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("conversion.failed", "delivery-2", '{}', "2026-01-01T00:00:00Z"),
        )

        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'conversion.completed'")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'conversion.failed'")
        assert cursor.fetchone()[0] == 1

    def test_old_schema_db_migrates_and_preserves_data(self, memory_db):
        """AC6.1 edge: Old 2-value CHECK constraint migrates, preserving existing rows."""
        cursor = memory_db.cursor()

        # Create the OLD events table with only 2 event types
        old_events_sql = """
        CREATE TABLE events (
            seq         INTEGER PRIMARY KEY,
            event_type  TEXT NOT NULL CHECK (event_type IN ('delivery.created', 'delivery.status_changed')),
            delivery_id TEXT NOT NULL,
            payload     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
        """
        cursor.execute(old_events_sql)

        # Insert an old-style event
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("delivery.created", "delivery-old", '{}', "2026-01-01T00:00:00Z"),
        )
        memory_db.commit()

        # Now run init_db which should detect and migrate
        init_db(memory_db)

        # Verify old row survived
        cursor.execute("SELECT event_type FROM events WHERE delivery_id = 'delivery-old'")
        old_row = cursor.fetchone()
        assert old_row is not None
        assert old_row[0] == "delivery.created"

        # Verify new event types now work
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("conversion.completed", "delivery-new", '{}', "2026-01-01T00:00:00Z"),
        )
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("conversion.failed", "delivery-failed", '{}', "2026-01-01T00:00:00Z"),
        )

        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'conversion.completed'")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'conversion.failed'")
        assert cursor.fetchone()[0] == 1

    def test_migration_idempotency(self, memory_db):
        """AC6.1 idempotency: Running init_db twice preserves data and state."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("delivery.created", "delivery-1", '{}', "2026-01-01T00:00:00Z"),
        )
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("conversion.completed", "delivery-2", '{}', "2026-01-01T00:00:00Z"),
        )

        memory_db.commit()
        first_count = cursor.execute("SELECT COUNT(*) FROM events").fetchone()[0]

        # Run init_db again
        init_db(memory_db)

        # Verify data survived
        cursor.execute("SELECT COUNT(*) FROM events")
        second_count = cursor.fetchone()[0]
        assert second_count == first_count == 2

        # Verify new events still work
        cursor.execute(
            "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
            ("conversion.failed", "delivery-3", '{}', "2026-01-01T00:00:00Z"),
        )

        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'conversion.failed'")
        assert cursor.fetchone()[0] == 1

    def test_check_constraint_rejects_invalid_types(self, memory_db):
        """AC6.1 rejection: Invalid event_type raises IntegrityError."""
        init_db(memory_db)

        cursor = memory_db.cursor()
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO events (event_type, delivery_id, payload, created_at) VALUES (?, ?, ?, ?)",
                ("nonsense", "delivery-1", '{}', "2026-01-01T00:00:00Z"),
            )


class TestGetConnection:
    def test_get_connection_creates_connection(self, tmp_path):
        """Test that get_connection creates a valid connection."""
        db_path = str(tmp_path / "test.db")

        conn = get_connection(db_path)

        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_get_connection_sets_row_factory(self, tmp_path):
        """Test that get_connection sets row_factory to sqlite3.Row."""
        db_path = str(tmp_path / "test.db")

        conn = get_connection(db_path)

        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_get_connection_allows_threaded_access(self, tmp_path):
        """Test that check_same_thread=False is set."""
        db_path = str(tmp_path / "test.db")

        conn = get_connection(db_path)

        # We can't directly check check_same_thread, but we verify the connection works
        # by executing a query. If check_same_thread was True (default), threading issues
        # would manifest in integration tests.
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_get_connection_enables_wal(self, tmp_path):
        """Test that get_connection enables WAL mode."""
        db_path = str(tmp_path / "test.db")

        conn = get_connection(db_path)

        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        assert journal_mode == "wal"
        conn.close()


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


class TestUpsertDelivery:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    def test_upsert_delivery_creates_delivery_with_all_fields(self, memory_db):
        """Test AC2.1: Upsert creates delivery with all metadata fields populated."""
        data = {
            "source_path": "/test/source",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "metadata": {"notes": "test"},
            "file_count": 10,
            "total_bytes": 1024,
            "fingerprint": "hash-abc",
        }

        result = upsert_delivery(memory_db, data)

        assert result["delivery_id"] == make_delivery_id("/test/source")
        assert result["request_id"] == "req-123"
        assert result["project"] == "proj-a"
        assert result["request_type"] == "full"
        assert result["workplan_id"] == "wp-456"
        assert result["dp_id"] == "dp-789"
        assert result["version"] == "v01"
        assert result["scan_root"] == "/scan"
        assert result["lexicon_id"] == "qa-standard"
        assert result["status"] == "pending"
        assert result["file_count"] == 10
        assert result["total_bytes"] == 1024
        assert result["source_path"] == "/test/source"
        assert result["fingerprint"] == "hash-abc"
        assert result["first_seen_at"] is not None
        assert result["last_updated_at"] is not None

    def test_upsert_delivery_preserves_first_seen_at_on_reinsert(
        self, memory_db, monkeypatch
    ):
        """Test AC2.2: Upsert preserves first_seen_at when re-inserting existing delivery."""
        data1 = {
            "source_path": "/test/source",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "file_count": 10,
            "total_bytes": 1024,
            "fingerprint": "hash-abc",
        }

        # Mock first call to return timestamp T1
        monkeypatch.setattr(
            "pipeline.registry_api.db._get_iso_now", lambda: "2026-01-01T00:00:00+00:00"
        )
        result1 = upsert_delivery(memory_db, data1)
        first_seen_at_1 = result1["first_seen_at"]

        # Mock second call to return a different timestamp T2
        monkeypatch.setattr(
            "pipeline.registry_api.db._get_iso_now", lambda: "2026-01-01T00:00:01+00:00"
        )

        # Update the same delivery with different data
        data2 = {
            **data1,
            "request_id": "req-999",  # Different value
            "fingerprint": "hash-def",  # Different fingerprint
        }

        result2 = upsert_delivery(memory_db, data2)
        first_seen_at_2 = result2["first_seen_at"]

        assert first_seen_at_1 == first_seen_at_2, (
            "first_seen_at should be preserved on reinsert"
        )

    def test_upsert_delivery_bumps_last_updated_at_when_fingerprint_changes(
        self, memory_db, monkeypatch
    ):
        """Test AC2.3: Upsert bumps last_updated_at when fingerprint changes."""
        data1 = {
            "source_path": "/test/source",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "file_count": 10,
            "total_bytes": 1024,
            "fingerprint": "hash-aaa",
        }

        # Mock first call to return timestamp T1
        monkeypatch.setattr(
            "pipeline.registry_api.db._get_iso_now", lambda: "2026-01-01T00:00:00+00:00"
        )
        result1 = upsert_delivery(memory_db, data1)
        last_updated_at_1 = result1["last_updated_at"]

        # Mock second call to return a different timestamp T2
        monkeypatch.setattr(
            "pipeline.registry_api.db._get_iso_now", lambda: "2026-01-01T00:00:01+00:00"
        )

        # Update with different fingerprint
        data2 = {
            **data1,
            "fingerprint": "hash-bbb",  # Different fingerprint
        }

        result2 = upsert_delivery(memory_db, data2)
        last_updated_at_2 = result2["last_updated_at"]

        assert last_updated_at_1 != last_updated_at_2, (
            "last_updated_at should be updated when fingerprint changes"
        )
        assert last_updated_at_2 > last_updated_at_1, "last_updated_at should be newer"

    def test_upsert_delivery_does_not_bump_last_updated_at_when_fingerprint_unchanged(
        self, memory_db, monkeypatch
    ):
        """Test AC2.4: Upsert does NOT bump last_updated_at when fingerprint is unchanged."""
        data1 = {
            "source_path": "/test/source",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "file_count": 10,
            "total_bytes": 1024,
            "fingerprint": "hash-aaa",
        }

        # Mock first call to return timestamp T1
        monkeypatch.setattr(
            "pipeline.registry_api.db._get_iso_now", lambda: "2026-01-01T00:00:00+00:00"
        )
        result1 = upsert_delivery(memory_db, data1)
        last_updated_at_1 = result1["last_updated_at"]

        # Mock second call to return a different timestamp T2
        monkeypatch.setattr(
            "pipeline.registry_api.db._get_iso_now", lambda: "2026-01-01T00:00:01+00:00"
        )

        # Update with same fingerprint but different other fields
        data2 = {
            **data1,
            "request_id": "req-999",  # Different field
            "fingerprint": "hash-aaa",  # Same fingerprint
        }

        result2 = upsert_delivery(memory_db, data2)
        last_updated_at_2 = result2["last_updated_at"]

        assert last_updated_at_1 == last_updated_at_2, (
            "last_updated_at should NOT be updated when fingerprint is unchanged"
        )


class TestGetDelivery:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    def test_get_delivery_returns_existing_delivery(self, memory_db):
        """Test that get_delivery returns correct row for existing delivery_id."""
        data = {
            "source_path": "/test/source",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "fingerprint": "hash-abc",
        }

        upsert_delivery(memory_db, data)
        delivery_id = make_delivery_id("/test/source")

        result = get_delivery(memory_db, delivery_id)

        assert result is not None
        assert result["delivery_id"] == delivery_id
        assert result["request_id"] == "req-123"

    def test_get_delivery_returns_none_for_nonexistent(self, memory_db):
        """Test that get_delivery returns None for nonexistent delivery_id."""
        result = get_delivery(memory_db, "nonexistent-id")

        assert result is None


class TestListDeliveries:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    @pytest.fixture
    def sample_deliveries(self, memory_db):
        """Insert sample deliveries for testing filters."""
        deliveries = [
            {
                "source_path": "/path/1",
                "request_id": "req-1",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan/1",
                "lexicon_id": "qa-standard",
                "status": "pending",
                "fingerprint": "hash-1",
            },
            {
                "source_path": "/path/2",
                "request_id": "req-2",
                "project": "proj-b",
                "request_type": "partial",
                "workplan_id": "wp-100",
                "dp_id": "dp-2",
                "version": "v01",
                "scan_root": "/scan/2",
                "lexicon_id": "qa-standard",
                "status": "passed",
                "parquet_converted_at": "2026-01-01T00:00:00+00:00",
                "fingerprint": "hash-2",
            },
            {
                "source_path": "/path/3",
                "request_id": "req-3",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-200",
                "dp_id": "dp-1",
                "version": "v02",
                "scan_root": "/scan/3",
                "lexicon_id": "qa-standard",
                "status": "passed",
                "fingerprint": "hash-3",
            },
            {
                "source_path": "/path/4",
                "request_id": "req-4",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-200",
                "dp_id": "dp-1",
                "version": "v03",
                "scan_root": "/scan/3",
                "lexicon_id": "qa-standard",
                "status": "pending",
                "fingerprint": "hash-4",
            },
        ]
        for d in deliveries:
            upsert_delivery(memory_db, d)
        return deliveries

    def test_list_deliveries_empty_filters_returns_all(
        self, memory_db, sample_deliveries
    ):
        """Test AC2.8: Empty filter set returns all deliveries."""
        results, _ = list_deliveries(memory_db, {})

        assert len(results) == 4

    def test_list_deliveries_filter_by_dp_id(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by dp_id."""
        results, _ = list_deliveries(memory_db, {"dp_id": "dp-1"})

        assert len(results) == 3
        assert all(r["dp_id"] == "dp-1" for r in results)

    def test_list_deliveries_filter_by_project(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by project."""
        results, _ = list_deliveries(memory_db, {"project": "proj-a"})

        assert len(results) == 3
        assert all(r["project"] == "proj-a" for r in results)

    def test_list_deliveries_filter_by_request_type(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by request_type."""
        results, _ = list_deliveries(memory_db, {"request_type": "full"})

        assert len(results) == 3
        assert all(r["request_type"] == "full" for r in results)

    def test_list_deliveries_filter_by_workplan_id(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by workplan_id."""
        results, _ = list_deliveries(memory_db, {"workplan_id": "wp-100"})

        assert len(results) == 2
        assert all(r["workplan_id"] == "wp-100" for r in results)

    def test_list_deliveries_filter_by_request_id(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by request_id."""
        results, _ = list_deliveries(memory_db, {"request_id": "req-1"})

        assert len(results) == 1
        assert results[0]["request_id"] == "req-1"

    def test_list_deliveries_filter_by_status(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by status."""
        results, _ = list_deliveries(memory_db, {"status": "passed"})

        assert len(results) == 2
        assert all(r["status"] == "passed" for r in results)

    def test_list_deliveries_filter_by_scan_root(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by scan_root."""
        results, _ = list_deliveries(memory_db, {"scan_root": "/scan/1"})

        assert len(results) == 1
        assert results[0]["scan_root"] == "/scan/1"

    def test_list_deliveries_filter_by_converted_true(
        self, memory_db, sample_deliveries
    ):
        """Test AC2.5: list_deliveries filters by converted=True."""
        results, _ = list_deliveries(memory_db, {"converted": True})

        assert len(results) == 1
        assert results[0]["parquet_converted_at"] is not None

    def test_list_deliveries_filter_by_converted_false(
        self, memory_db, sample_deliveries
    ):
        """Test AC2.5: list_deliveries filters by converted=False."""
        results, _ = list_deliveries(memory_db, {"converted": False})

        assert len(results) == 3
        assert all(r["parquet_converted_at"] is None for r in results)

    def test_list_deliveries_version_latest(self, memory_db, sample_deliveries):
        """Test AC2.6: version=latest returns highest version per (dp_id, workplan_id)."""
        results, _ = list_deliveries(
            memory_db, {"version": "latest", "workplan_id": "wp-200", "dp_id": "dp-1"}
        )

        assert len(results) == 1
        assert results[0]["version"] == "v03"

    def test_list_deliveries_multiple_filters_and_semantics(
        self, memory_db, sample_deliveries
    ):
        """Test AC2.7: Multiple filters combine with AND semantics."""
        results, _ = list_deliveries(
            memory_db, {"project": "proj-a", "status": "passed"}
        )

        assert len(results) == 1
        assert results[0]["project"] == "proj-a"
        assert results[0]["status"] == "passed"

    def test_list_deliveries_limit(self, memory_db, sample_deliveries):
        """AC7.1 limit: list_deliveries with limit= returns at most N rows."""
        results, total = list_deliveries(memory_db, {"limit": 2})

        assert len(results) == 2
        assert total == 4

    def test_list_deliveries_offset(self, memory_db, sample_deliveries):
        """AC7.1 offset: list_deliveries with offset= skips rows."""
        results, total = list_deliveries(memory_db, {"limit": 2, "offset": 2})

        assert len(results) == 2
        assert total == 4

    def test_list_deliveries_limit_capped_at_1000(
        self, memory_db, sample_deliveries
    ):
        """AC7.1 cap: limit larger than 1000 is capped, returns all available rows without error."""
        results, total = list_deliveries(memory_db, {"limit": 5000})

        assert len(results) == 4, "Should return all 4 available rows"
        assert total == 4

    def test_list_deliveries_offset_with_converted_filter(
        self, memory_db, sample_deliveries
    ):
        """AC7.1 offset with filters: pagination works with other filters like converted=."""
        results_all, total = list_deliveries(memory_db, {"converted": False})
        assert total == 3

        results_page, total2 = list_deliveries(
            memory_db, {"converted": False, "limit": 2, "offset": 0}
        )

        assert len(results_page) == 2
        assert total2 == 3
        assert all(r["parquet_converted_at"] is None for r in results_page)


class TestGetActionable:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    def test_get_actionable_returns_passed_unconverted(self, memory_db):
        """Test get_actionable returns only passed and unconverted deliveries."""
        # passed, unconverted
        upsert_delivery(
            memory_db,
            {
                "source_path": "/path/1",
                "request_id": "req-1",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan/1",
                "lexicon_id": "qa-standard",
                "status": "passed",
                "fingerprint": "hash-1",
            },
        )

        results = get_actionable(memory_db, {"qa-standard": ["passed"]})

        assert len(results) == 1
        assert results[0]["status"] == "passed"
        assert results[0]["parquet_converted_at"] is None

    def test_get_actionable_excludes_pending(self, memory_db):
        """Test get_actionable excludes deliveries with status=pending."""
        upsert_delivery(
            memory_db,
            {
                "source_path": "/path/1",
                "request_id": "req-1",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan/1",
                "lexicon_id": "qa-standard",
                "status": "pending",
                "fingerprint": "hash-1",
            },
        )

        results = get_actionable(memory_db, {"qa-standard": ["passed"]})

        assert len(results) == 0

    def test_get_actionable_excludes_converted(self, memory_db):
        """Test get_actionable excludes deliveries already converted."""
        upsert_delivery(
            memory_db,
            {
                "source_path": "/path/1",
                "request_id": "req-1",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan/1",
                "lexicon_id": "qa-standard",
                "status": "passed",
                "parquet_converted_at": "2026-01-01T00:00:00+00:00",
                "fingerprint": "hash-1",
            },
        )

        results = get_actionable(memory_db, {"qa-standard": ["passed"]})

        assert len(results) == 0


class TestUpdateDelivery:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    @pytest.fixture
    def sample_delivery(self, memory_db):
        """Insert a sample delivery for testing."""
        data = {
            "source_path": "/test/source",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "fingerprint": "hash-abc",
        }
        return upsert_delivery(memory_db, data)

    def test_update_delivery_updates_specified_fields(self, memory_db, sample_delivery):
        """Test update_delivery updates only specified fields."""
        delivery_id = sample_delivery["delivery_id"]

        result = update_delivery(
            memory_db,
            delivery_id,
            {
                "status": "passed",
                "metadata": {"passed_at": "2026-01-01T00:00:00+00:00"},
            },
        )

        assert result["status"] == "passed"
        assert result["metadata"] == {"passed_at": "2026-01-01T00:00:00+00:00"}
        # Other fields unchanged
        assert result["request_id"] == "req-123"

    def test_update_delivery_returns_none_for_nonexistent(self, memory_db):
        """Test update_delivery returns None for nonexistent delivery_id."""
        result = update_delivery(memory_db, "nonexistent-id", {"status": "passed"})

        assert result is None

    def test_update_delivery_empty_dict_is_noop(self, memory_db, sample_delivery):
        """Test update_delivery with empty dict is a no-op (returns unchanged row)."""
        delivery_id = sample_delivery["delivery_id"]
        original_status = sample_delivery["status"]

        result = update_delivery(memory_db, delivery_id, {})

        assert result is not None
        assert result["delivery_id"] == delivery_id
        assert result["status"] == original_status


class TestInsertEvent:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    def test_insert_event_creates_event_with_all_fields(self, memory_db):
        """Test insert_event creates an event with correct fields."""
        payload = {"delivery_id": "abc123", "status": "passed"}

        result = insert_event(
            memory_db,
            event_type="delivery.created",
            delivery_id="abc123",
            payload=payload,
        )

        assert result["event_type"] == "delivery.created"
        assert result["delivery_id"] == "abc123"
        assert result["payload"] == payload
        assert result["seq"] is not None
        assert isinstance(result["seq"], int)
        assert result["created_at"] is not None

    def test_insert_event_ac4_1_monotonic_sequence(self, memory_db):
        """Test event-stream.AC4.1: Each event has seq higher than all previous events."""
        payload1 = {"status": "created"}
        payload2 = {"status": "updated"}

        result1 = insert_event(
            memory_db,
            event_type="delivery.created",
            delivery_id="id-1",
            payload=payload1,
        )
        result2 = insert_event(
            memory_db,
            event_type="delivery.status_changed",
            delivery_id="id-1",
            payload=payload2,
        )

        assert result2["seq"] > result1["seq"]

    def test_insert_event_ac4_2_payload_matches_broadcast(self, memory_db):
        """Test event-stream.AC4.2: Event payload matches broadcast payload."""
        payload = {"delivery_id": "abc123", "request_id": "req-456", "status": "passed"}

        result = insert_event(
            memory_db,
            event_type="delivery.created",
            delivery_id="abc123",
            payload=payload,
        )

        assert result["payload"] == payload

    def test_insert_event_accepts_delivery_created(self, memory_db):
        """Test insert_event accepts 'delivery.created' event type."""
        result = insert_event(
            memory_db,
            event_type="delivery.created",
            delivery_id="id-1",
            payload={},
        )

        assert result["event_type"] == "delivery.created"

    def test_insert_event_accepts_delivery_status_changed(self, memory_db):
        """Test insert_event accepts 'delivery.status_changed' event type."""
        result = insert_event(
            memory_db,
            event_type="delivery.status_changed",
            delivery_id="id-1",
            payload={},
        )

        assert result["event_type"] == "delivery.status_changed"

    def test_insert_event_rejects_invalid_event_type(self, memory_db):
        """Test insert_event with invalid event_type raises sqlite3.IntegrityError (CHECK constraint)."""
        with pytest.raises(sqlite3.IntegrityError):
            insert_event(
                memory_db,
                event_type="invalid.event",
                delivery_id="id-1",
                payload={},
            )

    def test_insert_event_ac4_3_persists_without_clients(self, memory_db):
        """Test event-stream.AC4.3: Events persist even if no WS clients connected."""
        payload = {"test": "data"}

        result = insert_event(
            memory_db,
            event_type="delivery.created",
            delivery_id="id-1",
            payload=payload,
        )

        # Verify it's actually persisted by fetching it back
        cursor = memory_db.cursor()
        cursor.execute("SELECT * FROM events WHERE seq = ?", (result["seq"],))
        row = cursor.fetchone()

        assert row is not None
        assert row["delivery_id"] == "id-1"


class TestGetEventsAfter:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    @pytest.fixture
    def sample_events(self, memory_db):
        """Insert sample events for testing."""
        events = []
        for i in range(1, 4):
            result = insert_event(
                memory_db,
                event_type="delivery.created",
                delivery_id=f"id-{i}",
                payload={"num": i},
            )
            events.append(result)
        return events

    def test_get_events_after_ac5_1_returns_only_after_seq(self, memory_db, sample_events):
        """Test event-stream.AC5.1: Returns only events with seq > after_seq, ordered ASC."""
        results = get_events_after(memory_db, after_seq=1)

        assert len(results) == 2
        assert results[0]["seq"] == sample_events[1]["seq"]
        assert results[1]["seq"] == sample_events[2]["seq"]

    def test_get_events_after_ac5_2_respects_limit(self, memory_db):
        """Test event-stream.AC5.2: Returns at most limit events."""
        # Insert 5 events
        for i in range(5):
            insert_event(memory_db, "delivery.created", f"id-{i}", {})

        results = get_events_after(memory_db, after_seq=0, limit=2)

        assert len(results) == 2

    def test_get_events_after_ordered_ascending(self, memory_db, sample_events):
        """Test get_events_after returns results ordered by seq ASC."""
        results = get_events_after(memory_db, after_seq=0)

        seqs = [r["seq"] for r in results]
        assert seqs == sorted(seqs)

    def test_get_events_after_limit_capped_at_1000(self, memory_db):
        """Test get_events_after caps limit at 1000."""
        # Insert 5 events
        for i in range(5):
            insert_event(memory_db, "delivery.created", f"id-{i}", {})

        # Request limit=2000, should behave same as limit=1000 (which is still > 5)
        results = get_events_after(memory_db, after_seq=0, limit=2000)

        assert len(results) == 5

    def test_get_events_after_empty_result(self, memory_db, sample_events):
        """Test get_events_after returns empty list when no events match."""
        results = get_events_after(memory_db, after_seq=999)

        assert results == []

    def test_get_events_after_payload_deserialized(self, memory_db):
        """Test get_events_after returns payload as dict, not JSON string."""
        payload = {"delivery_id": "abc", "status": "passed"}
        insert_event(memory_db, "delivery.created", "id-1", payload)

        results = get_events_after(memory_db, after_seq=0)

        assert len(results) == 1
        assert results[0]["payload"] == payload
        assert isinstance(results[0]["payload"], dict)


class TestDeliveryExists:
    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    def test_delivery_exists_returns_true_for_existing_delivery(self, memory_db):
        """Test delivery_exists returns True for a delivery that has been upserted."""
        data = {
            "source_path": "/test/source",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "fingerprint": "hash-abc",
        }

        upsert_delivery(memory_db, data)
        delivery_id = make_delivery_id("/test/source")

        result = delivery_exists(memory_db, delivery_id)

        assert result is True

    def test_delivery_exists_returns_false_for_nonexistent_delivery(self, memory_db):
        """Test delivery_exists returns False for a delivery_id that does not exist."""
        result = delivery_exists(memory_db, "nonexistent-id")

        assert result is False


class TestLexiconSchema:
    """Tests for AC3.1-AC3.5: Lexicon schema changes."""

    @pytest.fixture
    def memory_db(self):
        """Create an in-memory SQLite database with schema for testing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        yield conn
        conn.close()

    def test_ac3_1_delivery_with_lexicon_id_status_metadata(self, memory_db):
        """AC3.1 Success: Delivery created with lexicon_id, status, and metadata fields."""
        data = {
            "source_path": "/test/delivery-ac3-1",
            "request_id": "req-001",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-001",
            "dp_id": "dp-001",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "metadata": {"source": "automated_crawler"},
            "fingerprint": "hash-001",
        }

        result = upsert_delivery(memory_db, data)

        assert result["lexicon_id"] == "qa-standard"
        assert result["status"] == "pending"
        assert result["metadata"] is not None

    def test_ac3_2_metadata_json_roundtrip(self, memory_db):
        """AC3.2 Success: metadata JSON round-trips correctly through upsert and query."""
        metadata_in = {"passed_at": "2026-04-14T12:00:00Z", "notes": "test delivery"}

        data = {
            "source_path": "/test/delivery-ac3-2",
            "request_id": "req-002",
            "project": "proj-b",
            "request_type": "partial",
            "workplan_id": "wp-002",
            "dp_id": "dp-002",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-extended",
            "status": "passed",
            "metadata": metadata_in,
            "fingerprint": "hash-002",
        }

        # Upsert the delivery
        upsert_result = upsert_delivery(memory_db, data)
        assert upsert_result["metadata"] == metadata_in

        # Query it back
        delivery_id = make_delivery_id("/test/delivery-ac3-2")
        fetched = get_delivery(memory_db, delivery_id)
        assert fetched["metadata"] == metadata_in

    def test_ac3_3_actionable_query_returns_matching_statuses(self, memory_db):
        """AC3.3 Success: Actionable query returns deliveries matching per-lexicon actionable_statuses."""
        # Insert deliveries for qa-standard lexicon
        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-3-passed",
                "request_id": "req-passed",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-standard",
                "status": "passed",
                "fingerprint": "hash-p1",
            },
        )

        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-3-pending",
                "request_id": "req-pending",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-standard",
                "status": "pending",
                "fingerprint": "hash-p2",
            },
        )

        # Query with qa-standard's actionable statuses = ["passed"]
        results = get_actionable(memory_db, {"qa-standard": ["passed"]})

        assert len(results) == 1
        assert results[0]["status"] == "passed"
        assert results[0]["source_path"] == "/test/ac3-3-passed"

    def test_ac3_4_actionable_across_multiple_lexicons(self, memory_db):
        """AC3.4 Success: Actionable query works across multiple lexicons with different actionable statuses."""
        # qa-standard: actionable on "passed"
        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-4-std-passed",
                "request_id": "req-std-p",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-standard",
                "status": "passed",
                "fingerprint": "hash-s1",
            },
        )

        # qa-standard: not actionable on "pending"
        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-4-std-pending",
                "request_id": "req-std-pend",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-standard",
                "status": "pending",
                "fingerprint": "hash-s2",
            },
        )

        # qa-extended: actionable on "passed" and "review-pending"
        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-4-ext-pending",
                "request_id": "req-ext-p",
                "project": "proj-b",
                "request_type": "partial",
                "workplan_id": "wp-200",
                "dp_id": "dp-2",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-extended",
                "status": "review-pending",
                "fingerprint": "hash-e1",
            },
        )

        # Query with both lexicons and their respective actionable statuses
        lexicon_actionable = {
            "qa-standard": ["passed"],
            "qa-extended": ["passed", "review-pending"],
        }
        results = get_actionable(memory_db, lexicon_actionable)

        # Should return: 1 from qa-standard (passed) + 1 from qa-extended (review-pending)
        assert len(results) == 2
        statuses = {r["status"] for r in results}
        assert "passed" in statuses
        assert "review-pending" in statuses

    def test_ac3_5_list_deliveries_filter_by_lexicon_id(self, memory_db):
        """AC3.5 Success: List/filter deliveries by lexicon_id."""
        # Create deliveries for different lexicons
        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-5-lex1-1",
                "request_id": "req-l1-1",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-standard",
                "status": "passed",
                "fingerprint": "hash-l1-1",
            },
        )

        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-5-lex1-2",
                "request_id": "req-l1-2",
                "project": "proj-a",
                "request_type": "full",
                "workplan_id": "wp-100",
                "dp_id": "dp-1",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-standard",
                "status": "pending",
                "fingerprint": "hash-l1-2",
            },
        )

        upsert_delivery(
            memory_db,
            {
                "source_path": "/test/ac3-5-lex2-1",
                "request_id": "req-l2-1",
                "project": "proj-b",
                "request_type": "partial",
                "workplan_id": "wp-200",
                "dp_id": "dp-2",
                "version": "v01",
                "scan_root": "/scan",
                "lexicon_id": "qa-extended",
                "status": "passed",
                "fingerprint": "hash-l2-1",
            },
        )

        # Filter by lexicon_id
        results_standard, _ = list_deliveries(memory_db, {"lexicon_id": "qa-standard"})
        results_extended, _ = list_deliveries(memory_db, {"lexicon_id": "qa-extended"})

        # Verify filtering works
        assert len(results_standard) == 2
        assert all(r["lexicon_id"] == "qa-standard" for r in results_standard)

        assert len(results_extended) == 1
        assert all(r["lexicon_id"] == "qa-extended" for r in results_extended)

    def test_ac3_5_list_deliveries_filter_by_status(self, memory_db):
        """AC3.5 Success: List/filter deliveries by status."""
        # Create deliveries with different statuses
        for i, status in enumerate(["pending", "passed", "failed", "pending"]):
            upsert_delivery(
                memory_db,
                {
                    "source_path": f"/test/ac3-5-status-{i}",
                    "request_id": f"req-st-{i}",
                    "project": "proj-a",
                    "request_type": "full",
                    "workplan_id": "wp-100",
                    "dp_id": "dp-1",
                    "version": "v01",
                    "scan_root": "/scan",
                    "lexicon_id": "qa-standard",
                    "status": status,
                    "fingerprint": f"hash-st-{i}",
                },
            )

        # Filter by status
        pending_results, _ = list_deliveries(memory_db, {"status": "pending"})
        passed_results, _ = list_deliveries(memory_db, {"status": "passed"})
        failed_results, _ = list_deliveries(memory_db, {"status": "failed"})

        # Verify filtering works
        assert len(pending_results) == 2
        assert all(r["status"] == "pending" for r in pending_results)

        assert len(passed_results) == 1
        assert all(r["status"] == "passed" for r in passed_results)

        assert len(failed_results) == 1
        assert all(r["status"] == "failed" for r in failed_results)
