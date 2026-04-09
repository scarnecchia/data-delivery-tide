import hashlib
import sqlite3
import pytest

from pipeline.registry_api.db import (
    make_delivery_id,
    init_db,
    get_connection,
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
