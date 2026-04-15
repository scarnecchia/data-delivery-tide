import pytest
from pydantic import ValidationError

from pipeline.registry_api.models import (
    DeliveryCreate,
    DeliveryUpdate,
    DeliveryResponse,
    DeliveryFilters,
    EventRecord,
)


class TestDeliveryCreate:
    def test_delivery_create_valid_with_required_fields_only(self):
        """Test DeliveryCreate accepts valid input with all required fields."""
        model = DeliveryCreate(
            request_id="req-123",
            project="proj-a",
            request_type="full",
            workplan_id="wp-456",
            dp_id="dp-789",
            version="v01",
            scan_root="/scan",
            lexicon_id="qa-standard",
            status="pending",
            source_path="/source",
        )

        assert model.request_id == "req-123"
        assert model.project == "proj-a"
        assert model.request_type == "full"
        assert model.workplan_id == "wp-456"
        assert model.dp_id == "dp-789"
        assert model.version == "v01"
        assert model.scan_root == "/scan"
        assert model.lexicon_id == "qa-standard"
        assert model.status == "pending"
        assert model.source_path == "/source"
        assert model.metadata is None
        assert model.file_count is None
        assert model.total_bytes is None
        assert model.fingerprint is None

    def test_delivery_create_valid_with_optional_fields(self):
        """Test DeliveryCreate accepts valid input with optional fields included."""
        model = DeliveryCreate(
            request_id="req-123",
            project="proj-a",
            request_type="full",
            workplan_id="wp-456",
            dp_id="dp-789",
            version="v01",
            scan_root="/scan",
            lexicon_id="qa-standard",
            status="passed",
            source_path="/source",
            metadata={"passed_at": "2026-01-01T00:00:00+00:00"},
            file_count=100,
            total_bytes=1024,
            fingerprint="hash-abc",
        )

        assert model.metadata == {"passed_at": "2026-01-01T00:00:00+00:00"}
        assert model.file_count == 100
        assert model.total_bytes == 1024
        assert model.fingerprint == "hash-abc"

    def test_delivery_create_rejects_missing_required_field_source_path(self):
        """Test AC3.1 (model layer): DeliveryCreate with missing required field raises ValidationError."""
        with pytest.raises(ValidationError):
            DeliveryCreate(
                request_id="req-123",
                project="proj-a",
                request_type="full",
                workplan_id="wp-456",
                dp_id="dp-789",
                version="v01",
                scan_root="/scan",
                lexicon_id="qa-standard",
                status="pending",
                # Missing: source_path
            )

    def test_delivery_create_rejects_missing_required_field_request_id(self):
        """Test DeliveryCreate with missing required field request_id raises ValidationError."""
        with pytest.raises(ValidationError):
            DeliveryCreate(
                project="proj-a",
                request_type="full",
                workplan_id="wp-456",
                dp_id="dp-789",
                version="v01",
                scan_root="/scan",
                lexicon_id="qa-standard",
                status="pending",
                source_path="/source",
            )

    def test_delivery_create_accepts_failed_status(self):
        """Test DeliveryCreate accepts 'failed' status."""
        model = DeliveryCreate(
            request_id="req-123",
            project="proj-a",
            request_type="full",
            workplan_id="wp-456",
            dp_id="dp-789",
            version="v01",
            scan_root="/scan",
            lexicon_id="qa-standard",
            status="failed",
            source_path="/source",
        )
        assert model.status == "failed"

    def test_delivery_create_rejects_missing_lexicon_id(self):
        """Test AC3.2: DeliveryCreate with missing lexicon_id raises ValidationError."""
        with pytest.raises(ValidationError):
            DeliveryCreate(
                request_id="req-123",
                project="proj-a",
                request_type="full",
                workplan_id="wp-456",
                dp_id="dp-789",
                version="v01",
                scan_root="/scan",
                status="pending",
                source_path="/source",
                # Missing: lexicon_id
            )

    def test_delivery_create_rejects_status_none(self):
        """Test DeliveryCreate rejects None for required status field."""
        with pytest.raises(ValidationError):
            DeliveryCreate(
                request_id="req-123",
                project="proj-a",
                request_type="full",
                workplan_id="wp-456",
                dp_id="dp-789",
                version="v01",
                scan_root="/scan",
                lexicon_id="qa-standard",
                status=None,
                source_path="/source",
            )


class TestDeliveryUpdate:
    def test_delivery_update_accepts_empty_body(self):
        """Test DeliveryUpdate accepts empty body (all fields are optional)."""
        model = DeliveryUpdate()

        assert model.parquet_converted_at is None
        assert model.output_path is None
        assert model.status is None
        assert model.metadata is None

    def test_delivery_update_accepts_partial_fields(self):
        """Test DeliveryUpdate accepts partial update with some fields set."""
        model = DeliveryUpdate(
            status="passed",
            metadata={"passed_at": "2026-01-01T00:00:00+00:00"},
        )

        assert model.status == "passed"
        assert model.metadata == {"passed_at": "2026-01-01T00:00:00+00:00"}
        assert model.parquet_converted_at is None
        assert model.output_path is None

    def test_delivery_update_accepts_all_fields(self):
        """Test DeliveryUpdate accepts all optional fields."""
        model = DeliveryUpdate(
            parquet_converted_at="2026-01-01T00:00:00+00:00",
            output_path="/output",
            status="passed",
            metadata={"passed_at": "2026-01-01T00:00:00+00:00"},
        )

        assert model.parquet_converted_at == "2026-01-01T00:00:00+00:00"
        assert model.output_path == "/output"
        assert model.status == "passed"
        assert model.metadata == {"passed_at": "2026-01-01T00:00:00+00:00"}

    def test_delivery_update_accepts_failed_status(self):
        """Test DeliveryUpdate accepts 'failed' status."""
        model = DeliveryUpdate(status="failed")
        assert model.status == "failed"

    def test_delivery_update_accepts_none_values_explicitly(self):
        """Test DeliveryUpdate with explicitly set None values."""
        model = DeliveryUpdate(
            parquet_converted_at=None,
            output_path=None,
            status=None,
            metadata=None,
        )

        assert model.parquet_converted_at is None
        assert model.output_path is None
        assert model.status is None
        assert model.metadata is None


class TestDeliveryResponse:
    def test_delivery_response_from_dict_with_all_fields(self):
        """Test DeliveryResponse round-trips from dict (simulating db row)."""
        data = {
            "delivery_id": "abc123",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "passed",
            "metadata": {"passed_at": "2026-01-01T01:00:00+00:00"},
            "first_seen_at": "2026-01-01T00:00:00+00:00",
            "parquet_converted_at": "2026-01-01T02:00:00+00:00",
            "file_count": 100,
            "total_bytes": 1024,
            "source_path": "/source",
            "output_path": "/output",
            "fingerprint": "hash-abc",
            "last_updated_at": "2026-01-01T03:00:00+00:00",
        }

        model = DeliveryResponse(**data)

        assert model.delivery_id == "abc123"
        assert model.request_id == "req-123"
        assert model.project == "proj-a"
        assert model.request_type == "full"
        assert model.workplan_id == "wp-456"
        assert model.dp_id == "dp-789"
        assert model.version == "v01"
        assert model.scan_root == "/scan"
        assert model.lexicon_id == "qa-standard"
        assert model.status == "passed"
        assert model.metadata == {"passed_at": "2026-01-01T01:00:00+00:00"}
        assert model.first_seen_at == "2026-01-01T00:00:00+00:00"
        assert model.parquet_converted_at == "2026-01-01T02:00:00+00:00"
        assert model.file_count == 100
        assert model.total_bytes == 1024
        assert model.source_path == "/source"
        assert model.output_path == "/output"
        assert model.fingerprint == "hash-abc"
        assert model.last_updated_at == "2026-01-01T03:00:00+00:00"

    def test_delivery_response_with_minimal_fields(self):
        """Test DeliveryResponse with only required fields."""
        data = {
            "delivery_id": "abc123",
            "request_id": "req-123",
            "project": "proj-a",
            "request_type": "full",
            "workplan_id": "wp-456",
            "dp_id": "dp-789",
            "version": "v01",
            "scan_root": "/scan",
            "lexicon_id": "qa-standard",
            "status": "pending",
            "first_seen_at": "2026-01-01T00:00:00+00:00",
            "source_path": "/source",
        }

        model = DeliveryResponse(**data)

        assert model.delivery_id == "abc123"
        assert model.metadata is None
        assert model.parquet_converted_at is None
        assert model.file_count is None
        assert model.total_bytes is None
        assert model.output_path is None
        assert model.fingerprint is None
        assert model.last_updated_at is None


class TestDeliveryFilters:
    def test_delivery_filters_all_optional_no_fields_set(self):
        """Test DeliveryFilters with no fields set is valid (all optional)."""
        model = DeliveryFilters()

        assert model.dp_id is None
        assert model.project is None
        assert model.request_type is None
        assert model.workplan_id is None
        assert model.request_id is None
        assert model.status is None
        assert model.lexicon_id is None
        assert model.converted is None
        assert model.version is None
        assert model.scan_root is None

    def test_delivery_filters_with_single_filter(self):
        """Test DeliveryFilters with a single filter field set."""
        model = DeliveryFilters(dp_id="dp-789")

        assert model.dp_id == "dp-789"
        assert model.project is None

    def test_delivery_filters_with_multiple_filters(self):
        """Test DeliveryFilters with multiple filter fields set."""
        model = DeliveryFilters(
            dp_id="dp-789",
            project="proj-a",
            status="passed",
            lexicon_id="qa-standard",
            converted=True,
        )

        assert model.dp_id == "dp-789"
        assert model.project == "proj-a"
        assert model.status == "passed"
        assert model.lexicon_id == "qa-standard"
        assert model.converted is True

    def test_delivery_filters_accepts_valid_statuses(self):
        """Test DeliveryFilters accepts all valid status values."""
        model1 = DeliveryFilters(status="pending")
        assert model1.status == "pending"

        model2 = DeliveryFilters(status="passed")
        assert model2.status == "passed"

        model3 = DeliveryFilters(status="failed")
        assert model3.status == "failed"

    def test_delivery_filters_boolean_converted_field(self):
        """Test DeliveryFilters with boolean converted field."""
        model_true = DeliveryFilters(converted=True)
        assert model_true.converted is True

        model_false = DeliveryFilters(converted=False)
        assert model_false.converted is False

        model_none = DeliveryFilters(converted=None)
        assert model_none.converted is None


class TestEventRecord:
    def test_event_record_valid_with_all_fields(self):
        """Test EventRecord accepts valid input with all required fields."""
        model = EventRecord(
            seq=1,
            event_type="delivery.created",
            delivery_id="abc123",
            payload={"key": "value"},
            created_at="2026-01-01T00:00:00+00:00",
        )

        assert model.seq == 1
        assert model.event_type == "delivery.created"
        assert model.delivery_id == "abc123"
        assert model.payload == {"key": "value"}
        assert model.created_at == "2026-01-01T00:00:00+00:00"

    def test_event_record_accepts_delivery_status_changed(self):
        """Test EventRecord accepts 'delivery.status_changed' event_type."""
        model = EventRecord(
            seq=2,
            event_type="delivery.status_changed",
            delivery_id="abc123",
            payload={"status": "passed"},
            created_at="2026-01-01T00:00:00+00:00",
        )

        assert model.event_type == "delivery.status_changed"

    def test_event_record_rejects_invalid_event_type(self):
        """Test EventRecord with invalid event_type raises ValidationError."""
        with pytest.raises(ValidationError):
            EventRecord(
                seq=1,
                event_type="invalid.event",
                delivery_id="abc123",
                payload={},
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_event_record_seq_must_be_int(self):
        """Test EventRecord rejects non-int seq."""
        with pytest.raises(ValidationError):
            EventRecord(
                seq="not-an-int",
                event_type="delivery.created",
                delivery_id="abc123",
                payload={},
                created_at="2026-01-01T00:00:00+00:00",
            )

    def test_event_record_accepts_dict_payload(self):
        """Test EventRecord accepts dict payload with arbitrary structure."""
        complex_payload = {
            "delivery_id": "abc123",
            "request_id": "req-456",
            "status": "passed",
            "nested": {"field": "value"},
            "list": [1, 2, 3],
        }

        model = EventRecord(
            seq=3,
            event_type="delivery.created",
            delivery_id="abc123",
            payload=complex_payload,
            created_at="2026-01-01T00:00:00+00:00",
        )

        assert model.payload == complex_payload
