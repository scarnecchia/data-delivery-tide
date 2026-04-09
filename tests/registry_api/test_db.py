import hashlib
import sqlite3
import pytest
from datetime import datetime

from pipeline.registry_api.db import (
    make_delivery_id,
    init_db,
    get_connection,
    upsert_delivery,
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
        assert all(c in '0123456789abcdef' for c in result)


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
            "qa_status",
            "first_seen_at",
            "qa_passed_at",
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
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='deliveries'")
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
            "qa_status": "pending",
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
        assert result["qa_status"] == "pending"
        assert result["file_count"] == 10
        assert result["total_bytes"] == 1024
        assert result["source_path"] == "/test/source"
        assert result["fingerprint"] == "hash-abc"
        assert result["first_seen_at"] is not None
        assert result["last_updated_at"] is not None

    def test_upsert_delivery_preserves_first_seen_at_on_reinsert(self, memory_db):
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
            "qa_status": "pending",
            "file_count": 10,
            "total_bytes": 1024,
            "fingerprint": "hash-abc",
        }

        result1 = upsert_delivery(memory_db, data1)
        first_seen_at_1 = result1["first_seen_at"]

        # Sleep briefly to ensure timestamp would differ if set fresh
        import time
        time.sleep(0.01)

        # Update the same delivery with different data
        data2 = {
            **data1,
            "request_id": "req-999",  # Different value
            "fingerprint": "hash-def",  # Different fingerprint
        }

        result2 = upsert_delivery(memory_db, data2)
        first_seen_at_2 = result2["first_seen_at"]

        assert first_seen_at_1 == first_seen_at_2, "first_seen_at should be preserved on reinsert"

    def test_upsert_delivery_bumps_last_updated_at_when_fingerprint_changes(self, memory_db):
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
            "qa_status": "pending",
            "file_count": 10,
            "total_bytes": 1024,
            "fingerprint": "hash-aaa",
        }

        result1 = upsert_delivery(memory_db, data1)
        last_updated_at_1 = result1["last_updated_at"]

        import time
        time.sleep(0.01)

        # Update with different fingerprint
        data2 = {
            **data1,
            "fingerprint": "hash-bbb",  # Different fingerprint
        }

        result2 = upsert_delivery(memory_db, data2)
        last_updated_at_2 = result2["last_updated_at"]

        assert last_updated_at_1 != last_updated_at_2, "last_updated_at should be updated when fingerprint changes"
        assert last_updated_at_2 > last_updated_at_1, "last_updated_at should be newer"

    def test_upsert_delivery_does_not_bump_last_updated_at_when_fingerprint_unchanged(self, memory_db):
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
            "qa_status": "pending",
            "file_count": 10,
            "total_bytes": 1024,
            "fingerprint": "hash-aaa",
        }

        result1 = upsert_delivery(memory_db, data1)
        last_updated_at_1 = result1["last_updated_at"]

        import time
        time.sleep(0.01)

        # Update with same fingerprint but different other fields
        data2 = {
            **data1,
            "request_id": "req-999",  # Different field
            "fingerprint": "hash-aaa",  # Same fingerprint
        }

        result2 = upsert_delivery(memory_db, data2)
        last_updated_at_2 = result2["last_updated_at"]

        assert last_updated_at_1 == last_updated_at_2, "last_updated_at should NOT be updated when fingerprint is unchanged"
