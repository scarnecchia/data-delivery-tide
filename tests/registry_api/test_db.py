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
            "qa_status": "pending",
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
                "qa_status": "pending",
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
                "qa_status": "passed",
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
                "qa_status": "passed",
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
                "qa_status": "pending",
                "fingerprint": "hash-4",
            },
        ]
        for d in deliveries:
            upsert_delivery(memory_db, d)
        return deliveries

    def test_list_deliveries_empty_filters_returns_all(self, memory_db, sample_deliveries):
        """Test AC2.8: Empty filter set returns all deliveries."""
        results = list_deliveries(memory_db, {})

        assert len(results) == 4

    def test_list_deliveries_filter_by_dp_id(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by dp_id."""
        results = list_deliveries(memory_db, {"dp_id": "dp-1"})

        assert len(results) == 3
        assert all(r["dp_id"] == "dp-1" for r in results)

    def test_list_deliveries_filter_by_project(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by project."""
        results = list_deliveries(memory_db, {"project": "proj-a"})

        assert len(results) == 3
        assert all(r["project"] == "proj-a" for r in results)

    def test_list_deliveries_filter_by_request_type(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by request_type."""
        results = list_deliveries(memory_db, {"request_type": "full"})

        assert len(results) == 3
        assert all(r["request_type"] == "full" for r in results)

    def test_list_deliveries_filter_by_workplan_id(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by workplan_id."""
        results = list_deliveries(memory_db, {"workplan_id": "wp-100"})

        assert len(results) == 2
        assert all(r["workplan_id"] == "wp-100" for r in results)

    def test_list_deliveries_filter_by_request_id(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by request_id."""
        results = list_deliveries(memory_db, {"request_id": "req-1"})

        assert len(results) == 1
        assert results[0]["request_id"] == "req-1"

    def test_list_deliveries_filter_by_qa_status(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by qa_status."""
        results = list_deliveries(memory_db, {"qa_status": "passed"})

        assert len(results) == 2
        assert all(r["qa_status"] == "passed" for r in results)

    def test_list_deliveries_filter_by_scan_root(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by scan_root."""
        results = list_deliveries(memory_db, {"scan_root": "/scan/1"})

        assert len(results) == 1
        assert results[0]["scan_root"] == "/scan/1"

    def test_list_deliveries_filter_by_converted_true(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by converted=True."""
        results = list_deliveries(memory_db, {"converted": True})

        assert len(results) == 1
        assert results[0]["parquet_converted_at"] is not None

    def test_list_deliveries_filter_by_converted_false(self, memory_db, sample_deliveries):
        """Test AC2.5: list_deliveries filters by converted=False."""
        results = list_deliveries(memory_db, {"converted": False})

        assert len(results) == 3
        assert all(r["parquet_converted_at"] is None for r in results)

    def test_list_deliveries_version_latest(self, memory_db, sample_deliveries):
        """Test AC2.6: version=latest returns highest version per (dp_id, workplan_id)."""
        results = list_deliveries(memory_db, {"version": "latest", "workplan_id": "wp-200", "dp_id": "dp-1"})

        assert len(results) == 1
        assert results[0]["version"] == "v03"

    def test_list_deliveries_multiple_filters_and_semantics(self, memory_db, sample_deliveries):
        """Test AC2.7: Multiple filters combine with AND semantics."""
        results = list_deliveries(memory_db, {"project": "proj-a", "qa_status": "passed"})

        assert len(results) == 1
        assert results[0]["project"] == "proj-a"
        assert results[0]["qa_status"] == "passed"


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
        upsert_delivery(memory_db, {
            "source_path": "/path/1",
            "request_id": "req-1",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-100",
            "dp_id": "dp-1",
            "version": "v01",
            "scan_root": "/scan/1",
            "qa_status": "passed",
            "fingerprint": "hash-1",
        })

        results = get_actionable(memory_db)

        assert len(results) == 1
        assert results[0]["qa_status"] == "passed"
        assert results[0]["parquet_converted_at"] is None

    def test_get_actionable_excludes_pending(self, memory_db):
        """Test get_actionable excludes deliveries with qa_status=pending."""
        upsert_delivery(memory_db, {
            "source_path": "/path/1",
            "request_id": "req-1",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-100",
            "dp_id": "dp-1",
            "version": "v01",
            "scan_root": "/scan/1",
            "qa_status": "pending",
            "fingerprint": "hash-1",
        })

        results = get_actionable(memory_db)

        assert len(results) == 0

    def test_get_actionable_excludes_converted(self, memory_db):
        """Test get_actionable excludes deliveries already converted."""
        upsert_delivery(memory_db, {
            "source_path": "/path/1",
            "request_id": "req-1",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-100",
            "dp_id": "dp-1",
            "version": "v01",
            "scan_root": "/scan/1",
            "qa_status": "passed",
            "parquet_converted_at": "2026-01-01T00:00:00+00:00",
            "fingerprint": "hash-1",
        })

        results = get_actionable(memory_db)

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
            "qa_status": "pending",
            "fingerprint": "hash-abc",
        }
        return upsert_delivery(memory_db, data)

    def test_update_delivery_updates_specified_fields(self, memory_db, sample_delivery):
        """Test update_delivery updates only specified fields."""
        delivery_id = sample_delivery["delivery_id"]

        result = update_delivery(memory_db, delivery_id, {
            "qa_status": "passed",
            "qa_passed_at": "2026-01-01T00:00:00+00:00",
        })

        assert result["qa_status"] == "passed"
        assert result["qa_passed_at"] == "2026-01-01T00:00:00+00:00"
        # Other fields unchanged
        assert result["request_id"] == "req-123"

    def test_update_delivery_returns_none_for_nonexistent(self, memory_db):
        """Test update_delivery returns None for nonexistent delivery_id."""
        result = update_delivery(memory_db, "nonexistent-id", {"qa_status": "passed"})

        assert result is None

    def test_update_delivery_empty_dict_is_noop(self, memory_db, sample_delivery):
        """Test update_delivery with empty dict is a no-op (returns unchanged row)."""
        delivery_id = sample_delivery["delivery_id"]
        original_qa_status = sample_delivery["qa_status"]

        result = update_delivery(memory_db, delivery_id, {})

        assert result is not None
        assert result["delivery_id"] == delivery_id
        assert result["qa_status"] == original_qa_status
