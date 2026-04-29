# pattern: test file
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock

import pytest


def make_delivery_payload(**overrides):
    """
    Helper to create a valid DeliveryCreate payload with sensible defaults.

    Allows overriding any field via keyword arguments.

    Default lexicon_id is "soc.qar" (matches TEST_LEXICON in conftest).
    """
    defaults = {
        "request_id": "req-001",
        "project": "test-project",
        "request_type": "scan",
        "workplan_id": "wp-001",
        "dp_id": "dp-001",
        "version": "1.0.0",
        "scan_root": "/data/scans",
        "lexicon_id": "soc.qar",
        "status": "pending",
        "source_path": "/source/test",
    }
    defaults.update(overrides)
    return defaults


def get_events(db):
    """Helper to fetch all events from the test database."""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM events ORDER BY seq ASC")
    rows = cursor.fetchall()
    return [
        {**dict(row), "payload": json.loads(dict(row)["payload"])}
        for row in rows
    ]


class TestHealth:
    """Test /health endpoint."""

    def test_health_returns_ok(self, client):
        """AC1.7: GET /health returns {"status": "ok"}."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestCreateDelivery:
    """Test POST /deliveries endpoint."""

    def test_create_delivery_success(self, client, auth_headers):
        """AC1.1: POST /deliveries with valid body → 200, includes server-computed delivery_id."""
        payload = make_delivery_payload()
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        # Verify all fields are present
        assert data["delivery_id"]
        assert data["request_id"] == "req-001"
        assert data["project"] == "test-project"
        assert data["request_type"] == "scan"
        assert data["workplan_id"] == "wp-001"
        assert data["dp_id"] == "dp-001"
        assert data["version"] == "1.0.0"
        assert data["scan_root"] == "/data/scans"
        assert data["status"] == "pending"
        assert data["source_path"] == "/source/test"
        assert data["first_seen_at"]

    def test_create_delivery_deterministic_id(self, client, auth_headers):
        """AC3.4: same source_path always produces same delivery_id."""
        payload1 = make_delivery_payload(source_path="/data/scan-123")
        payload2 = make_delivery_payload(source_path="/data/scan-123")

        response1 = client.post("/deliveries", json=payload1, headers=auth_headers)
        response2 = client.post("/deliveries", json=payload2, headers=auth_headers)

        assert response1.json()["delivery_id"] == response2.json()["delivery_id"]

    def test_upsert_preserves_first_seen_at(self, client, auth_headers):
        """AC1.2: POST same source_path twice → second returns 200, first_seen_at preserved."""
        payload = make_delivery_payload(source_path="/data/unique-scan")

        # First POST
        response1 = client.post("/deliveries", json=payload, headers=auth_headers)
        first_seen_at_1 = response1.json()["first_seen_at"]
        delivery_id = response1.json()["delivery_id"]

        # Second POST with same source_path but different status
        payload_updated = make_delivery_payload(
            source_path="/data/unique-scan",
            status="passed",
        )
        response2 = client.post("/deliveries", json=payload_updated, headers=auth_headers)

        assert response2.status_code == 200
        data2 = response2.json()

        # Same delivery_id (deterministic from source_path)
        assert data2["delivery_id"] == delivery_id
        # first_seen_at should be preserved
        assert data2["first_seen_at"] == first_seen_at_1
        # status should be updated
        assert data2["status"] == "passed"

    def test_create_missing_required_field(self, client, auth_headers):
        """AC3.1: POST /deliveries without required field returns 422."""
        payload = make_delivery_payload()
        del payload["source_path"]

        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 422

    def test_create_invalid_qa_status(self, client, auth_headers):
        """AC3.2: POST /deliveries with invalid qa_status returns 422."""
        payload = make_delivery_payload(status="invalid")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 422


class TestGetDelivery:
    """Test GET /deliveries/{delivery_id} endpoint."""

    def test_get_delivery_exists(self, client, auth_headers):
        """AC1.3: GET /deliveries/{delivery_id} after POST returns 200, matching delivery."""
        payload = make_delivery_payload(source_path="/data/get-test")
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        response = client.get(f"/deliveries/{delivery_id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["delivery_id"] == delivery_id
        assert data["source_path"] == "/data/get-test"

    def test_get_delivery_not_found(self, client, auth_headers):
        """AC1.4: GET /deliveries/{delivery_id} with nonexistent ID returns 404."""
        response = client.get("/deliveries/nonexistent-id-12345", headers=auth_headers)
        assert response.status_code == 404


class TestListDeliveries:
    """Test GET /deliveries endpoint with filtering."""

    def test_list_all_deliveries(self, client, auth_headers):
        """GET /deliveries with no filters returns all deliveries."""
        payload1 = make_delivery_payload(source_path="/data/list-1")
        payload2 = make_delivery_payload(source_path="/data/list-2")

        client.post("/deliveries", json=payload1, headers=auth_headers)
        client.post("/deliveries", json=payload2, headers=auth_headers)

        response = client.get("/deliveries", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_list_filtered_by_qa_status(self, client, auth_headers):
        """GET /deliveries?qa_status=pending filters by qa_status."""
        payload_pending = make_delivery_payload(
            source_path="/data/filter-pending",
            status="pending",
        )
        payload_passed = make_delivery_payload(
            source_path="/data/filter-passed",
            status="passed",
        )

        client.post("/deliveries", json=payload_pending, headers=auth_headers)
        client.post("/deliveries", json=payload_passed, headers=auth_headers)

        response = client.get("/deliveries?status=pending", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "pending"

    def test_list_filtered_by_dp_id(self, client, auth_headers):
        """GET /deliveries?dp_id=X filters by dp_id."""
        payload1 = make_delivery_payload(source_path="/data/dp-1", dp_id="dp-alpha")
        payload2 = make_delivery_payload(source_path="/data/dp-2", dp_id="dp-beta")

        client.post("/deliveries", json=payload1, headers=auth_headers)
        client.post("/deliveries", json=payload2, headers=auth_headers)

        response = client.get("/deliveries?dp_id=dp-alpha", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["dp_id"] == "dp-alpha"

    def test_list_with_pagination_limit_offset(self, client, auth_headers):
        """AC7.1: GET /deliveries?limit=N&offset=M uses offset pagination."""
        # Create 4 deliveries to paginate through
        for i in range(1, 5):
            payload = make_delivery_payload(source_path=f"/data/page-test-{i}")
            client.post("/deliveries", json=payload, headers=auth_headers)

        # Get first page
        response1 = client.get("/deliveries?limit=2&offset=0", headers=auth_headers)
        data1 = response1.json()
        assert len(data1["items"]) == 2
        assert data1["total"] == 4
        assert data1["limit"] == 2
        assert data1["offset"] == 0

        # Get second page
        response2 = client.get("/deliveries?limit=2&offset=2", headers=auth_headers)
        data2 = response2.json()
        assert len(data2["items"]) == 2
        assert data2["total"] == 4

        # Pages should not overlap
        ids1 = {d["delivery_id"] for d in data1["items"]}
        ids2 = {d["delivery_id"] for d in data2["items"]}
        assert ids1.isdisjoint(ids2)

    def test_list_with_converted_and_pagination(self, client, auth_headers):
        """AC7.1: Pagination works with converted=false filter."""
        # Create mixed converted/unconverted deliveries
        for i in range(1, 5):
            payload = make_delivery_payload(
                source_path=f"/data/converted-test-{i}",
                status="passed",
            )
            resp = client.post("/deliveries", json=payload, headers=auth_headers)
            if i % 2 == 0:
                # Mark every other as converted
                did = resp.json()["delivery_id"]
                client.patch(
                    f"/deliveries/{did}",
                    json={"parquet_converted_at": "2026-01-01T00:00:00Z"},
                    headers=auth_headers,
                )

        # Get unconverted with pagination
        response = client.get("/deliveries?converted=false&limit=1", headers=auth_headers)
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["parquet_converted_at"] is None
        assert data["total"] == 2


class TestActionableDeliveries:
    """Test GET /deliveries/actionable endpoint."""

    def test_actionable_returns_passed_unconverted(self, client, auth_headers):
        """AC1.8: GET /deliveries/actionable returns passed+unconverted deliveries."""
        # Create one passed+unconverted (actionable)
        payload_actionable = make_delivery_payload(
            source_path="/data/actionable-1",
            status="passed",
        )

        # Create one pending (not actionable)
        payload_pending = make_delivery_payload(
            source_path="/data/not-actionable-1",
            status="pending",
        )

        # Create one passed delivery that we'll mark as converted
        payload_for_converted = make_delivery_payload(
            source_path="/data/converted-1",
            status="passed",
        )

        client.post("/deliveries", json=payload_actionable, headers=auth_headers)
        client.post("/deliveries", json=payload_pending, headers=auth_headers)
        post3 = client.post("/deliveries", json=payload_for_converted, headers=auth_headers)

        # Mark the third delivery as converted via PATCH
        converted_id = post3.json()["delivery_id"]
        client.patch(
            f"/deliveries/{converted_id}",
            json={"parquet_converted_at": "2026-04-09T10:00:00+00:00"},
            headers=auth_headers,
        )

        response = client.get("/deliveries/actionable", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        # Should only return the passed+unconverted one
        assert len(data) == 1
        assert data[0]["status"] == "passed"
        assert data[0]["parquet_converted_at"] is None
        assert data[0]["source_path"] == "/data/actionable-1"

    def test_actionable_empty_when_none_match(self, client, auth_headers):
        """GET /deliveries/actionable returns empty list when no deliveries are actionable."""
        payload_pending = make_delivery_payload(
            source_path="/data/pending-only",
            status="pending",
        )

        client.post("/deliveries", json=payload_pending, headers=auth_headers)

        response = client.get("/deliveries/actionable", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestUpdateDelivery:
    """Test PATCH /deliveries/{delivery_id} endpoint."""

    def test_update_delivery_partial(self, client, auth_headers):
        """AC1.5: PATCH /deliveries/{delivery_id} with {"output_path": ...} → only that field changed."""
        payload = make_delivery_payload(source_path="/data/update-test")
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]
        original_status = post_response.json()["status"]

        # PATCH only output_path
        update_payload = {"output_path": "/new/output/path"}
        response = client.patch(f"/deliveries/{delivery_id}", json=update_payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["output_path"] == "/new/output/path"
        assert data["status"] == original_status

    def test_update_delivery_empty_body_noop(self, client, auth_headers):
        """AC3.3: PATCH /deliveries/{delivery_id} with empty body {} is a no-op."""
        payload = make_delivery_payload(source_path="/data/noop-test")
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]
        original_data = post_response.json()

        # PATCH with empty body
        response = client.patch(f"/deliveries/{delivery_id}", json={}, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        # All fields should remain unchanged
        assert data["status"] == original_data["status"]
        assert data["output_path"] == original_data["output_path"]

    def test_update_delivery_not_found(self, client, auth_headers):
        """AC1.6: PATCH /deliveries/{delivery_id} with nonexistent ID returns 404."""
        response = client.patch(
            "/deliveries/nonexistent-id-99999",
            json={"output_path": "/new/path"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_update_delivery_qa_status(self, client, auth_headers):
        """PATCH /deliveries/{delivery_id} can update qa_status."""
        payload = make_delivery_payload(
            source_path="/data/status-update",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "passed"

    def test_update_delivery_parquet_converted_at(self, client, auth_headers):
        """PATCH /deliveries/{delivery_id} can update parquet_converted_at."""
        payload = make_delivery_payload(source_path="/data/parquet-update")
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"parquet_converted_at": "2026-04-09T15:30:00+00:00"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["parquet_converted_at"] == "2026-04-09T15:30:00+00:00"

    def test_ac7_2_metadata_merge_preserves_existing_keys(self, client, auth_headers):
        """AC7.2: PATCH metadata deep-merges, preserving existing keys."""
        # Create with initial metadata
        payload = make_delivery_payload(
            source_path="/data/metadata-merge-test",
            metadata={"qa_passed_at": "2026-04-15T00:00:00Z", "other": "keep"},
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]
        assert post_response.json()["metadata"]["qa_passed_at"] == "2026-04-15T00:00:00Z"
        assert post_response.json()["metadata"]["other"] == "keep"

        # PATCH to add conversion_error
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={
                "metadata": {
                    "conversion_error": {
                        "class": "parse_error",
                        "message": "bad",
                        "at": "2026-04-16T00:00:00Z",
                        "converter_version": "0.1.0",
                    }
                }
            },
            headers=auth_headers,
        )

        assert patch_response.status_code == 200
        data = patch_response.json()
        # All three keys should be present
        assert data["metadata"]["qa_passed_at"] == "2026-04-15T00:00:00Z"
        assert data["metadata"]["other"] == "keep"
        assert data["metadata"]["conversion_error"]["class"] == "parse_error"
        assert data["metadata"]["conversion_error"]["message"] == "bad"

    def test_ac7_3_metadata_clear_error_by_null(self, client, auth_headers):
        """AC7.3: PATCH with conversion_error: null clears the error, preserves other keys."""
        # First, create and add error
        payload = make_delivery_payload(
            source_path="/data/metadata-clear-test",
            metadata={"qa_passed_at": "2026-04-15T00:00:00Z", "other": "keep"},
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        # Add error
        client.patch(
            f"/deliveries/{delivery_id}",
            json={
                "metadata": {
                    "conversion_error": {
                        "class": "parse_error",
                        "message": "bad",
                    }
                }
            },
            headers=auth_headers,
        )

        # Now clear the error by setting to null
        clear_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"metadata": {"conversion_error": None}},
            headers=auth_headers,
        )

        assert clear_response.status_code == 200
        data = clear_response.json()
        # Existing keys preserved
        assert data["metadata"]["qa_passed_at"] == "2026-04-15T00:00:00Z"
        assert data["metadata"]["other"] == "keep"
        # Error is None
        assert data["metadata"]["conversion_error"] is None

    def test_status_and_metadata_combined(self, client, auth_headers):
        """
        PATCH with both status transition AND user-supplied metadata merges all three sources:
        1. Existing metadata from the delivery
        2. User-supplied metadata from the PATCH body
        3. Lexicon-derived set_on fields applied to the new status
        """
        # Create with initial metadata and pending status
        payload = make_delivery_payload(
            source_path="/data/status-metadata-combined",
            status="pending",
            metadata={"existing_key": "existing_value", "preserved": "yes"},
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]
        assert post_response.json()["metadata"]["existing_key"] == "existing_value"

        # PATCH with both status (pending -> passed) and new metadata
        # The soc.qar lexicon has a set_on field that fires on "passed" status
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={
                "status": "passed",
                "metadata": {"user_supplied": "new_value"},
            },
            headers=auth_headers,
        )

        assert patch_response.status_code == 200
        data = patch_response.json()
        assert data["status"] == "passed"

        # Verify the union of all three metadata sources:
        # 1. Existing metadata preserved
        assert data["metadata"]["existing_key"] == "existing_value"
        assert data["metadata"]["preserved"] == "yes"
        # 2. User-supplied metadata merged in
        assert data["metadata"]["user_supplied"] == "new_value"
        # 3. Lexicon-derived set_on field applied (soc.qar lexicon sets
        # "passed_at" as datetime when transitioning to "passed")
        assert "passed_at" in data["metadata"]
        # Verify it's an ISO datetime string
        assert "T" in data["metadata"]["passed_at"]



class TestLexiconValidation:
    """Test lexicon-based validation of statuses and transitions (AC4.1-AC4.6)."""

    def test_ac4_1_post_with_valid_status(self, client, auth_headers):
        """AC4.1: POST with valid status for lexicon succeeds."""
        payload = make_delivery_payload(
            source_path="/data/ac4-1-test",
            lexicon_id="soc.qar",
            status="pending",
        )
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["lexicon_id"] == "soc.qar"

    def test_post_with_unknown_lexicon_id(self, client, auth_headers):
        """POST with unknown lexicon_id returns 422 with "unknown lexicon_id" detail."""
        payload = make_delivery_payload(
            source_path="/data/unknown-lexicon-test",
            lexicon_id="nonexistent.lexicon",
            status="pending",
        )
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "unknown lexicon_id" in detail

    def test_ac4_2_post_with_invalid_status(self, client, auth_headers):
        """AC4.2: POST with status not in lexicon's statuses returns 422."""
        payload = make_delivery_payload(
            source_path="/data/ac4-2-test",
            lexicon_id="soc.qar",
            status="nonexistent",
        )
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "not valid for lexicon" in detail

    def test_ac4_3_patch_with_legal_transition(self, client, auth_headers):
        """AC4.3: PATCH with legal transition succeeds."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac4-3-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        # PATCH to passed (legal transition: pending -> passed)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200
        data = patch_response.json()
        assert data["status"] == "passed"

    def test_ac4_4_patch_with_illegal_transition(self, client, auth_headers):
        """AC4.4: PATCH with illegal transition returns 422."""
        # Create with passed status
        payload = make_delivery_payload(
            source_path="/data/ac4-4-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        # First transition to passed (legal)
        client.patch(f"/deliveries/{delivery_id}", json={"status": "passed"}, headers=auth_headers)

        # Now try to transition back to pending (illegal: passed -> pending not in transitions)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "pending"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 422
        detail = patch_response.json()["detail"]
        assert "not allowed" in detail or "transition" in detail

    def test_ac4_5_set_on_metadata_auto_populated(self, client, auth_headers):
        """AC4.5: set_on metadata field auto-populated on matching status transition."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac4-5-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]
        assert post_response.json().get("metadata", {}).get("passed_at") is None

        # PATCH to passed (should trigger set_on for passed_at)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200
        data = patch_response.json()
        assert data["status"] == "passed"
        # Verify passed_at is populated with a valid ISO timestamp
        assert "passed_at" in data["metadata"]
        assert data["metadata"]["passed_at"] is not None
        # Verify it parses as a valid ISO datetime
        datetime.fromisoformat(data["metadata"]["passed_at"])

    def test_ac4_6_no_status_change_no_metadata_auto_pop(self, client, test_db, auth_headers):
        """AC4.6: PATCH without status change produces no event and no metadata auto-population."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac4-6-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        # Count events before PATCH
        events_before = get_events(test_db)
        initial_event_count = len(events_before)

        # PATCH without changing status
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "pending"},  # Same as current status
            headers=auth_headers,
        )

        assert patch_response.status_code == 200
        data = patch_response.json()
        assert data["status"] == "pending"

        # Verify no new event was created
        events_after = get_events(test_db)
        assert len(events_after) == initial_event_count

        # Verify passed_at was NOT auto-populated
        assert "passed_at" not in data["metadata"] or data["metadata"].get("passed_at") is None


class TestDeliveryCreatedEvents:
    """Test delivery.created event emission on POST /deliveries."""

    def test_new_delivery_creates_event(self, client, test_db, auth_headers):
        """event-stream.AC1.1: POST new delivery creates delivery.created event."""
        payload = make_delivery_payload(source_path="/data/new-event-test")
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Query events table directly
        events = get_events(test_db)

        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "delivery.created"
        assert event["delivery_id"] == delivery_id
        assert event["payload"]["delivery_id"] == delivery_id
        assert event["payload"]["source_path"] == "/data/new-event-test"
        assert event["payload"]["status"] == "pending"

    def test_recrawl_no_event(self, client, test_db, auth_headers):
        """event-stream.AC1.3: Re-crawl of existing delivery produces no event."""
        payload = make_delivery_payload(source_path="/data/recrawl-test")

        # First POST - creates event
        response1 = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response1.status_code == 200

        events_after_first = get_events(test_db)
        assert len(events_after_first) == 1

        # Second POST with same source_path and fingerprint - should not create event
        response2 = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response2.status_code == 200

        events_after_second = get_events(test_db)
        assert len(events_after_second) == 1  # Still only one event

    def test_backward_compatibility_response(self, client, auth_headers):
        """event-stream.AC7.1: POST response unchanged after adding event emission."""
        payload = make_delivery_payload(source_path="/data/compat-test")
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        # Verify all expected fields are present
        assert data["delivery_id"]
        assert data["request_id"] == "req-001"
        assert data["project"] == "test-project"
        assert data["source_path"] == "/data/compat-test"
        assert data["status"] == "pending"
        assert data["first_seen_at"]


class TestWebSocketBroadcast:
    """Test WebSocket broadcast of events on POST /deliveries."""

    @pytest.mark.asyncio
    async def test_ws_client_receives_delivery_created_event(self, client, auth_headers):
        """AC1.2: POST /deliveries broadcasts delivery.created to connected WS client."""
        from pipeline.registry_api.events import manager

        received_events = []

        async def ws_client_session():
            """Simulate a WebSocket client connecting and waiting for events."""
            # Create a mock WebSocket
            mock_ws = AsyncMock()
            mock_ws.send_json = AsyncMock()

            # Add it to the connection manager
            manager.active_connections.add(mock_ws)

            try:
                # Wait a moment for the HTTP request to complete and broadcast
                await asyncio.sleep(0.1)

                # Check what was sent
                if mock_ws.send_json.called:
                    # Get the first call's arguments
                    call_args = mock_ws.send_json.call_args[0][0]
                    received_events.append(call_args)
            finally:
                manager.active_connections.discard(mock_ws)

        # Start the WS client in a background task
        client_task = asyncio.create_task(ws_client_session())

        # Give the client time to "connect"
        await asyncio.sleep(0.05)

        # POST a new delivery via the HTTP client
        payload = make_delivery_payload(source_path="/data/ws-broadcast-test")
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Wait for the client to receive and process
        await client_task

        # Verify the WS client received the event
        assert len(received_events) == 1
        event = received_events[0]
        assert event["event_type"] == "delivery.created"
        assert event["delivery_id"] == delivery_id


class TestAPIRestartDeliveryDistinction:
    """Test that API restart distinguishes new vs existing deliveries."""

    def test_post_after_restart_no_event_for_existing(self, client, test_db, auth_headers):
        """AC1.4: POST same source_path after restart (DB state persists) produces no event."""
        from pipeline.registry_api.db import upsert_delivery

        source_path = "/data/restart-existing"

        # Simulate pre-restart state: insert delivery directly into DB
        payload = make_delivery_payload(source_path=source_path, status="pending")
        pre_restart_delivery = upsert_delivery(test_db, payload)
        test_db.commit()

        # Clear events that might exist
        events = get_events(test_db)
        initial_event_count = len(events)

        # Now POST the same source_path (simulating API restart then re-crawl)
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200

        # Check events table
        events_after = get_events(test_db)
        # Should still be the same count (no new event)
        assert len(events_after) == initial_event_count

    def test_post_after_restart_event_for_new(self, client, test_db, auth_headers):
        """AC1.4: POST new delivery after restart produces delivery.created event."""
        from pipeline.registry_api.db import upsert_delivery

        # Insert one delivery (simulating pre-restart state)
        payload1 = make_delivery_payload(source_path="/data/restart-old")
        upsert_delivery(test_db, payload1)
        test_db.commit()

        # Clear the events table to simulate fresh API start
        cursor = test_db.cursor()
        cursor.execute("DELETE FROM events")
        test_db.commit()

        # POST a genuinely new delivery
        payload2 = make_delivery_payload(source_path="/data/restart-new")
        response = client.post("/deliveries", json=payload2, headers=auth_headers)
        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Check events
        events = get_events(test_db)
        assert len(events) == 1
        assert events[0]["event_type"] == "delivery.created"
        assert events[0]["delivery_id"] == delivery_id


class TestDeliveryStatusChangedEvents:
    """Test delivery.status_changed event emission on PATCH /deliveries/{id}."""

    def test_status_pending_to_passed_creates_event(self, client, test_db, auth_headers):
        """event-stream.AC2.1: PATCH with status pending→passed creates event."""
        payload = make_delivery_payload(
            source_path="/data/status-change-1",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH to change status
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        # Should have exactly one more event (the status_changed)
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 1
        event = new_events[0]
        assert event["event_type"] == "delivery.status_changed"
        assert event["delivery_id"] == delivery_id
        assert event["payload"]["status"] == "passed"

    def test_status_pending_to_failed_creates_event(self, client, test_db, auth_headers):
        """event-stream.AC2.2: PATCH with status pending→failed creates event."""
        payload = make_delivery_payload(
            source_path="/data/status-change-2",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH to change status to failed
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "failed"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 1
        event = new_events[0]
        assert event["event_type"] == "delivery.status_changed"
        assert event["delivery_id"] == delivery_id
        assert event["payload"]["status"] == "failed"

    def test_event_payload_reflects_new_status(self, client, test_db, auth_headers):
        """event-stream.AC2.3: Event payload contains updated delivery record."""
        payload = make_delivery_payload(
            source_path="/data/payload-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH to change status and output_path
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed", "output_path": "/new/output"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 1
        event = new_events[0]
        # Payload should reflect new status
        assert event["payload"]["status"] == "passed"
        assert event["payload"]["output_path"] == "/new/output"

    def test_no_event_on_non_status_update(self, client, test_db, auth_headers):
        """event-stream.AC2.4: PATCH non-status field produces no event."""
        payload = make_delivery_payload(source_path="/data/non-status-test")
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH only parquet_converted_at (no status change)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"parquet_converted_at": "2026-04-09T10:00:00+00:00"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        # Filter for events after the POST event
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 0  # No event should be created for non-status changes

    def test_no_event_on_same_status_patch(self, client, test_db, auth_headers):
        """event-stream.AC2.5: PATCH with same status value produces no event."""
        payload = make_delivery_payload(
            source_path="/data/same-status-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH with same status value
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "pending"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 0  # No event should be created


class TestEventPayloadShape:
    """Test event payload shape contains new lexicon system fields (AC6.1-AC6.3)."""

    def test_ac6_1_delivery_created_contains_lexicon_id_status_metadata(self, client, test_db, auth_headers):
        """AC6.1: delivery.created event payload contains lexicon_id, status, metadata."""
        payload = make_delivery_payload(
            source_path="/data/ac6-1-test",
            lexicon_id="soc.qar",
            status="pending",
            metadata={"custom_field": "custom_value"},
        )
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Query events
        events = get_events(test_db)
        assert len(events) >= 1

        # Find the delivery.created event
        created_event = None
        for event in events:
            if event["event_type"] == "delivery.created" and event["delivery_id"] == delivery_id:
                created_event = event
                break

        assert created_event is not None, "No delivery.created event found"

        # Verify payload contains required fields
        payload_dict = created_event["payload"]
        assert "lexicon_id" in payload_dict
        assert "status" in payload_dict
        assert "metadata" in payload_dict

        # Verify values
        assert payload_dict["lexicon_id"] == "soc.qar"
        assert payload_dict["status"] == "pending"
        assert isinstance(payload_dict["metadata"], dict)
        assert payload_dict["metadata"].get("custom_field") == "custom_value"

    def test_ac6_2_delivery_status_changed_contains_status_and_metadata(self, client, test_db, auth_headers):
        """AC6.2: delivery.status_changed event payload contains updated status and metadata."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac6-2-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        # PATCH to change status to passed
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200

        # Query events
        events = get_events(test_db)

        # Find the delivery.status_changed event
        status_changed_event = None
        for event in events:
            if (
                event["event_type"] == "delivery.status_changed"
                and event["delivery_id"] == delivery_id
            ):
                status_changed_event = event
                break

        assert status_changed_event is not None, "No delivery.status_changed event found"

        # Verify payload contains required fields
        payload_dict = status_changed_event["payload"]
        assert "status" in payload_dict
        assert "metadata" in payload_dict

        # Verify values
        assert payload_dict["status"] == "passed"
        assert isinstance(payload_dict["metadata"], dict)
        # Verify passed_at was populated by set_on rule
        assert "passed_at" in payload_dict["metadata"]
        assert payload_dict["metadata"]["passed_at"] is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(payload_dict["metadata"]["passed_at"])

    def test_ac6_3_delivery_created_does_not_contain_old_field_names(self, client, test_db, auth_headers):
        """AC6.3: delivery.created event payload does not contain qa_status or qa_passed_at."""
        payload = make_delivery_payload(
            source_path="/data/ac6-3-created-test",
            status="pending",
        )
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Query events
        events = get_events(test_db)

        # Find the delivery.created event
        created_event = None
        for event in events:
            if event["event_type"] == "delivery.created" and event["delivery_id"] == delivery_id:
                created_event = event
                break

        assert created_event is not None

        # Verify old field names are NOT present
        payload_dict = created_event["payload"]
        assert "qa_status" not in payload_dict
        assert "qa_passed_at" not in payload_dict

    def test_ac6_3_delivery_status_changed_does_not_contain_old_field_names(self, client, test_db, auth_headers):
        """AC6.3: delivery.status_changed event payload does not contain qa_status or qa_passed_at."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac6-3-changed-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        # PATCH to change status
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=auth_headers,
        )

        assert patch_response.status_code == 200

        # Query events
        events = get_events(test_db)

        # Find the delivery.status_changed event
        status_changed_event = None
        for event in events:
            if (
                event["event_type"] == "delivery.status_changed"
                and event["delivery_id"] == delivery_id
            ):
                status_changed_event = event
                break

        assert status_changed_event is not None

        # Verify old field names are NOT present
        payload_dict = status_changed_event["payload"]
        assert "qa_status" not in payload_dict
        assert "qa_passed_at" not in payload_dict


class TestCatchUpEndpoint:
    """Test GET /events catch-up endpoint."""

    def test_get_events_after_filters_by_seq(self, client, test_db, auth_headers):
        """event-stream.AC5.1: GET /events?after=N returns only events with seq > N, ordered by seq ASC."""
        from pipeline.registry_api.db import insert_event

        # Insert 3 events manually
        insert_event(test_db, "delivery.created", "id-1", {"test": "payload1"})
        insert_event(test_db, "delivery.created", "id-2", {"test": "payload2"})
        insert_event(test_db, "delivery.created", "id-3", {"test": "payload3"})

        # Fetch events after seq 1
        response = client.get("/events?after=1", headers=auth_headers)

        assert response.status_code == 200
        events = response.json()

        # Should contain seq 2 and 3, not seq 1
        assert len(events) == 2
        assert events[0]["seq"] == 2
        assert events[1]["seq"] == 3
        # Verify order (seq ASC)
        assert events[0]["seq"] < events[1]["seq"]

    def test_get_events_respects_limit(self, client, test_db, auth_headers):
        """event-stream.AC5.2: GET /events?after=N&limit=M returns at most M events."""
        from pipeline.registry_api.db import insert_event

        # Insert 5 events
        for i in range(5):
            insert_event(test_db, "delivery.created", f"id-{i}", {"test": f"payload{i}"})

        # Fetch with limit=2
        response = client.get("/events?after=0&limit=2", headers=auth_headers)

        assert response.status_code == 200
        events = response.json()

        # Should return exactly 2 events
        assert len(events) == 2
        assert events[0]["seq"] == 1
        assert events[1]["seq"] == 2

    def test_get_events_after_latest_returns_empty(self, client, test_db, auth_headers):
        """event-stream.AC5.3: GET /events?after=<latest_seq> returns empty array."""
        from pipeline.registry_api.db import insert_event

        # Insert 3 events
        insert_event(test_db, "delivery.created", "id-1", {"test": "payload1"})
        insert_event(test_db, "delivery.created", "id-2", {"test": "payload2"})
        insert_event(test_db, "delivery.created", "id-3", {"test": "payload3"})

        # Fetch events after the last one (seq=3)
        response = client.get("/events?after=3", headers=auth_headers)

        assert response.status_code == 200
        events = response.json()
        assert events == []

    def test_get_events_without_after_returns_422(self, client, auth_headers):
        """event-stream.AC5.4: GET /events without after parameter returns 422."""
        response = client.get("/events", headers=auth_headers)

        assert response.status_code == 422

    def test_get_events_limit_capping(self, client, test_db, auth_headers):
        """GET /events caps limit at 1000 without erroring."""
        from pipeline.registry_api.db import insert_event

        # Insert 5 events (less than the 5000 requested)
        for i in range(5):
            insert_event(test_db, "delivery.created", f"id-{i}", {"test": f"payload{i}"})

        # Request with limit way over 1000
        response = client.get("/events?after=0&limit=5000", headers=auth_headers)

        assert response.status_code == 200
        events = response.json()

        # Should return all 5 (capped at 1000 but less available)
        assert len(events) == 5

    def test_get_events_response_shape(self, client, test_db, auth_headers):
        """GET /events response includes all required fields."""
        from pipeline.registry_api.db import insert_event

        insert_event(test_db, "delivery.created", "test-id", {"key": "value"})

        response = client.get("/events?after=0", headers=auth_headers)

        assert response.status_code == 200
        events = response.json()

        assert len(events) == 1
        event = events[0]

        # Verify all required fields
        assert "seq" in event
        assert "event_type" in event
        assert "delivery_id" in event
        assert "payload" in event
        assert "created_at" in event

        # Verify types
        assert isinstance(event["seq"], int)
        assert isinstance(event["event_type"], str)
        assert isinstance(event["delivery_id"], str)
        assert isinstance(event["payload"], dict)
        assert isinstance(event["created_at"], str)

        # Verify values
        assert event["seq"] == 1
        assert event["event_type"] == "delivery.created"
        assert event["delivery_id"] == "test-id"
        assert event["payload"] == {"key": "value"}


class TestEmitEvent:
    """Test POST /events endpoint for converter-emitted lifecycle events (AC6.4)."""

    def test_emit_conversion_completed_happy_path(self, client, test_db, auth_headers):
        """AC6.4: POST /events with conversion.completed event succeeds and broadcasts."""
        # First create a delivery
        payload = make_delivery_payload(source_path="/data/emit-test-1")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # POST conversion.completed event
        event_payload = {
            "event_type": "conversion.completed",
            "delivery_id": delivery_id,
            "payload": {
                "delivery_id": delivery_id,
                "output_path": "/output/converted.parquet",
                "row_count": 42,
                "bytes_written": 1024,
                "wrote_at": "2026-04-16T00:00:00Z",
            },
        }

        response = client.post("/events", json=event_payload, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "conversion.completed"
        assert data["delivery_id"] == delivery_id
        assert data["payload"]["row_count"] == 42

        # Verify event was persisted
        events = get_events(test_db)
        conversion_events = [
            e for e in events
            if e["event_type"] == "conversion.completed"
        ]
        assert len(conversion_events) == 1
        assert conversion_events[0]["delivery_id"] == delivery_id

    def test_emit_conversion_failed_happy_path(self, client, test_db, auth_headers):
        """AC6.4: POST /events with conversion.failed event succeeds."""
        # Create delivery
        payload = make_delivery_payload(source_path="/data/emit-test-2")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # POST conversion.failed event
        event_payload = {
            "event_type": "conversion.failed",
            "delivery_id": delivery_id,
            "payload": {
                "delivery_id": delivery_id,
                "error_class": "ParseError",
                "error_message": "invalid SAS format",
                "at": "2026-04-16T00:00:00Z",
                "converter_version": "0.1.0",
            },
        }

        response = client.post("/events", json=event_payload, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "conversion.failed"
        assert data["delivery_id"] == delivery_id
        assert data["payload"]["error_class"] == "ParseError"

    def test_emit_event_with_nonexistent_delivery_returns_404(self, client, auth_headers):
        """AC6.4: POST /events with unknown delivery_id returns 404."""
        event_payload = {
            "event_type": "conversion.completed",
            "delivery_id": "nonexistent-delivery-id-99999",
            "payload": {"row_count": 0},
        }

        response = client.post("/events", json=event_payload, headers=auth_headers)

        assert response.status_code == 404
        assert response.json()["detail"] == "delivery not found"

    def test_emit_event_rejects_registry_internal_event_types(self, client, auth_headers):
        """AC6.4: POST /events rejects delivery.created and delivery.status_changed."""
        # Create delivery first
        payload = make_delivery_payload(source_path="/data/emit-test-3")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Try to emit delivery.created (should be rejected by model validation)
        event_payload = {
            "event_type": "delivery.created",
            "delivery_id": delivery_id,
            "payload": {},
        }

        response = client.post("/events", json=event_payload, headers=auth_headers)

        assert response.status_code == 422

    def test_emit_event_rejects_invalid_event_type(self, client, auth_headers):
        """AC6.4: POST /events rejects invalid event_type."""
        # Create delivery first
        payload = make_delivery_payload(source_path="/data/emit-test-4")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Try to emit invalid event
        event_payload = {
            "event_type": "nonsense.event",
            "delivery_id": delivery_id,
            "payload": {},
        }

        response = client.post("/events", json=event_payload, headers=auth_headers)

        assert response.status_code == 422

    # WebSocket broadcast for POST /events is tested in test_events.py
    # (TestWebSocketEndpoint.test_emit_event_broadcasts_conversion_events)
    # because the WS tests require proper connection lifecycle management
    # that's already handled by that test class's autouse fixture.


class TestSubDeliveryIntegration:
    """Test sub-delivery integration through the API (AC5.1-AC5.4)."""

    def test_sub_delivery_queryable_by_lexicon_id(self, client, auth_headers):
        """AC5.1: Sub-deliveries appear in GET /deliveries?lexicon_id=test.sub."""
        # POST parent delivery with lexicon_id="soc.qar"
        parent_payload = make_delivery_payload(
            source_path="/data/parent-sub-test",
            lexicon_id="soc.qar",
            status="passed",
        )
        parent_response = client.post("/deliveries", json=parent_payload, headers=auth_headers)
        assert parent_response.status_code == 200

        # POST sub-delivery with lexicon_id="test.sub"
        sub_payload = make_delivery_payload(
            source_path="/data/parent-sub-test/sub",
            lexicon_id="test.sub",
            status="passed",
        )
        sub_response = client.post("/deliveries", json=sub_payload, headers=auth_headers)
        assert sub_response.status_code == 200

        # Query by test.sub lexicon_id
        response = client.get("/deliveries?lexicon_id=test.sub", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Only the sub-delivery should be returned
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["lexicon_id"] == "test.sub"
        assert data["items"][0]["source_path"] == "/data/parent-sub-test/sub"

    def test_parent_and_sub_correlated_by_identity(self, client, auth_headers):
        """AC5.2: Parent and sub-delivery are correlated by identity fields."""
        # POST parent delivery
        parent_payload = make_delivery_payload(
            request_id="req-correlation",
            workplan_id="wp-correlation",
            dp_id="dp-correlation",
            version="1.0.0",
            source_path="/data/parent-corr",
            lexicon_id="soc.qar",
            status="passed",
        )
        parent_response = client.post("/deliveries", json=parent_payload, headers=auth_headers)
        assert parent_response.status_code == 200
        parent_id = parent_response.json()["delivery_id"]

        # POST sub-delivery with same identity fields, different source_path
        sub_payload = make_delivery_payload(
            request_id="req-correlation",
            workplan_id="wp-correlation",
            dp_id="dp-correlation",
            version="1.0.0",
            source_path="/data/parent-corr/sub",
            lexicon_id="test.sub",
            status="passed",
        )
        sub_response = client.post("/deliveries", json=sub_payload, headers=auth_headers)
        assert sub_response.status_code == 200
        sub_id = sub_response.json()["delivery_id"]

        # Query all deliveries with request_id
        response = client.get("/deliveries?request_id=req-correlation", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Both parent and sub should be returned
        assert data["total"] == 2
        assert len(data["items"]) == 2
        data = data["items"]

        # Find parent and sub by lexicon_id
        parent = next(d for d in data if d["lexicon_id"] == "soc.qar")
        sub = next(d for d in data if d["lexicon_id"] == "test.sub")

        # Verify identity fields match
        assert parent["request_id"] == sub["request_id"] == "req-correlation"
        assert parent["workplan_id"] == sub["workplan_id"] == "wp-correlation"
        assert parent["dp_id"] == sub["dp_id"] == "dp-correlation"
        assert parent["version"] == sub["version"] == "1.0.0"

        # Verify they are different deliveries
        assert parent["delivery_id"] != sub["delivery_id"]
        assert parent["delivery_id"] == parent_id
        assert sub["delivery_id"] == sub_id

    def test_sub_delivery_appears_in_actionable(self, client, auth_headers):
        """AC5.3: Sub-deliveries appear in actionable when status matches actionable_statuses."""
        # POST sub-delivery with status="passed" (in test.sub's actionable_statuses)
        # and parquet_converted_at=null (not yet converted)
        sub_payload = make_delivery_payload(
            source_path="/data/sub-actionable",
            lexicon_id="test.sub",
            status="passed",
        )
        sub_response = client.post("/deliveries", json=sub_payload, headers=auth_headers)
        assert sub_response.status_code == 200

        # Query actionable deliveries
        response = client.get("/deliveries/actionable", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Sub-delivery should appear in actionable list
        actionable_subs = [d for d in data if d["lexicon_id"] == "test.sub"]
        assert len(actionable_subs) == 1
        assert actionable_subs[0]["source_path"] == "/data/sub-actionable"
        assert actionable_subs[0]["status"] == "passed"

    def test_sub_delivery_creation_emits_event(self, client, test_db, auth_headers):
        """AC5.4: POST sub-delivery emits delivery.created event with correct lexicon_id."""
        # POST sub-delivery
        sub_payload = make_delivery_payload(
            source_path="/data/sub-event-test",
            lexicon_id="test.sub",
            status="passed",
        )
        response = client.post("/deliveries", json=sub_payload, headers=auth_headers)
        assert response.status_code == 200
        sub_delivery_id = response.json()["delivery_id"]

        # Get events
        events = get_events(test_db)

        # Find the event for this sub-delivery
        sub_event = next(
            (e for e in events if e["delivery_id"] == sub_delivery_id),
            None,
        )

        assert sub_event is not None
        assert sub_event["event_type"] == "delivery.created"
        assert sub_event["payload"]["lexicon_id"] == "test.sub"
        assert sub_event["payload"]["source_path"] == "/data/sub-event-test"

class TestHealthNoAuth:
    """Test that /health is accessible without authentication."""

    def test_health_no_auth_header_returns_200(self, client):
        """registry-auth.AC1.6: /health returns 200 with no Authorization header."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestAuthEnforcement:
    """Test authentication and authorization enforcement on delivery routes."""

    def test_get_deliveries_no_auth_returns_401(self, client):
        """GET /deliveries without auth returns 401."""
        response = client.get("/deliveries")
        assert response.status_code == 401

    def test_post_deliveries_no_auth_returns_401(self, client):
        """POST /deliveries without auth returns 401."""
        payload = make_delivery_payload()
        response = client.post("/deliveries", json=payload)
        assert response.status_code == 401

    def test_patch_delivery_no_auth_returns_401(self, client):
        """PATCH /deliveries/{id} without auth returns 401."""
        response = client.patch(
            "/deliveries/some-id",
            json={"status": "passed"},
        )
        assert response.status_code == 401

    def test_get_actionable_no_auth_returns_401(self, client):
        """GET /deliveries/actionable without auth returns 401."""
        response = client.get("/deliveries/actionable")
        assert response.status_code == 401

    def test_read_token_can_get_deliveries(self, client, read_auth_headers):
        """registry-auth.AC2.4: Read token can GET deliveries."""
        response = client.get("/deliveries", headers=read_auth_headers)
        assert response.status_code == 200

    def test_read_token_cannot_post_deliveries(self, client, read_auth_headers):
        """registry-auth.AC2.5: Read token on POST /deliveries returns 403."""
        payload = make_delivery_payload()
        response = client.post("/deliveries", json=payload, headers=read_auth_headers)
        assert response.status_code == 403

    def test_read_token_cannot_patch_deliveries(self, client, auth_headers, read_auth_headers):
        """registry-auth.AC2.6: Read token on PATCH /deliveries/{id} returns 403."""
        payload = make_delivery_payload(source_path="/data/role-test")
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=read_auth_headers,
        )
        assert response.status_code == 403


class TestPagination:
    """Test pagination on GET /deliveries (Issue #12)."""

    def test_default_pagination(self, client, auth_headers):
        """Default limit=100, offset=0 is applied."""
        payload = make_delivery_payload(source_path="/data/page-1")
        client.post("/deliveries", json=payload, headers=auth_headers)

        response = client.get("/deliveries", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 100
        assert data["offset"] == 0
        assert data["total"] == 1
        assert len(data["items"]) == 1

    def test_limit_and_offset(self, client, auth_headers):
        """limit and offset control returned results."""
        for i in range(5):
            payload = make_delivery_payload(source_path=f"/data/paginate-{i}")
            client.post("/deliveries", json=payload, headers=auth_headers)

        response = client.get("/deliveries?limit=2&offset=0", headers=auth_headers)
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

        response2 = client.get("/deliveries?limit=2&offset=2", headers=auth_headers)
        data2 = response2.json()
        assert data2["total"] == 5
        assert len(data2["items"]) == 2
        assert data2["offset"] == 2

    def test_offset_beyond_results(self, client, auth_headers):
        """offset beyond total returns empty items but correct total."""
        payload = make_delivery_payload(source_path="/data/offset-test")
        client.post("/deliveries", json=payload, headers=auth_headers)

        response = client.get("/deliveries?offset=100", headers=auth_headers)
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 0

    def test_limit_capped_at_1000(self, client, auth_headers):
        """limit > 1000 is clamped to 1000."""
        response = client.get("/deliveries?limit=5000", headers=auth_headers)
        data = response.json()
        assert data["limit"] == 1000

    def test_invalid_limit_clamped_to_1(self, client, auth_headers):
        """limit < 1 is clamped to 1."""
        response = client.get("/deliveries?limit=0", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 1

    def test_negative_offset_clamped_to_0(self, client, auth_headers):
        """offset < 0 is clamped to 0."""
        response = client.get("/deliveries?offset=-1", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["offset"] == 0


class TestSourcePathValidation:
    """Test source_path validation against scan_roots (Issue #10)."""

    def test_valid_path_within_scan_root(self, client, auth_headers):
        """source_path within a configured scan_root is accepted."""
        payload = make_delivery_payload(source_path="/data/valid/delivery")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["source_path"] == "/data/valid/delivery"

    def test_path_outside_all_scan_roots_rejected(self, client, auth_headers):
        """source_path not within any scan_root returns 422."""
        payload = make_delivery_payload(source_path="/unauthorized/path/file")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 422
        assert "not within any configured scan_root" in response.json()["detail"]

    def test_path_traversal_caught(self, client, auth_headers):
        """Path traversal via .. that escapes scan_root is rejected."""
        payload = make_delivery_payload(source_path="/data/../etc/passwd")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 422
        assert "not within any configured scan_root" in response.json()["detail"]

    def test_path_traversal_staying_within_root(self, client, auth_headers):
        """Path with .. that still resolves within scan_root is accepted."""
        payload = make_delivery_payload(source_path="/data/subdir/../valid/file")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200

    def test_relative_path_rejected(self, client, auth_headers):
        """Relative path (not starting with /) is rejected."""
        payload = make_delivery_payload(source_path="relative/path/file")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 422
        assert "absolute path" in response.json()["detail"]

    def test_multiple_scan_roots_any_match(self, client, auth_headers):
        """source_path in /source (second scan_root) is also accepted."""
        payload = make_delivery_payload(source_path="/source/test/delivery")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200

    def test_scan_root_exact_match(self, client, auth_headers):
        """source_path equal to scan_root path itself is accepted."""
        payload = make_delivery_payload(source_path="/data")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200

    def test_scan_root_prefix_attack(self, client, auth_headers):
        """Path that starts with scan_root as prefix but not as directory is rejected."""
        # /data-exfil starts with /data but is not under /data/
        payload = make_delivery_payload(source_path="/data-exfil/secret")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 422


class TestUsernameInEvents:
    """Test that username is recorded in audit events (Issue #14)."""

    def test_delivery_created_event_has_username(self, client, auth_headers, test_db):
        """delivery.created event records the authenticated username."""
        payload = make_delivery_payload(source_path="/data/username-test-1")
        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 200

        events = get_events(test_db)
        assert len(events) == 1
        assert events[0]["event_type"] == "delivery.created"
        assert events[0]["username"] == "test-writer"

    def test_status_changed_event_has_username(self, client, auth_headers, test_db):
        """delivery.status_changed event records the authenticated username."""
        payload = make_delivery_payload(source_path="/data/username-test-2", status="pending")
        post_resp = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_resp.json()["delivery_id"]

        # Transition to passed
        client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
            headers=auth_headers,
        )

        events = get_events(test_db)
        # Should have created + status_changed
        status_events = [e for e in events if e["event_type"] == "delivery.status_changed"]
        assert len(status_events) == 1
        assert status_events[0]["username"] == "test-writer"

    def test_get_events_endpoint_includes_username(self, client, auth_headers, test_db):
        """GET /events returns username in event records."""
        payload = make_delivery_payload(source_path="/data/username-test-3")
        client.post("/deliveries", json=payload, headers=auth_headers)

        response = client.get("/events?after=0", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["username"] == "test-writer"


class TestWebSocketAuth:
    """Test WebSocket authentication (Issue #9)."""

    def test_ws_connect_with_valid_token(self, client, auth_headers):
        """WebSocket connection with valid token query param succeeds."""
        with client.websocket_connect("/ws/events?token=test-integration-token") as ws:
            # Connection succeeded - just close gracefully
            pass

    def test_ws_connect_without_token_rejected(self, client):
        """WebSocket connection without token is rejected with 1008."""
        from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect
        with pytest.raises(StarletteWSDisconnect) as exc_info:
            with client.websocket_connect("/ws/events"):
                pass
        assert exc_info.value.code == 1008

    def test_ws_connect_with_invalid_token_rejected(self, client, auth_headers):
        """WebSocket connection with invalid token is rejected with 1008."""
        from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect
        with pytest.raises(StarletteWSDisconnect) as exc_info:
            with client.websocket_connect("/ws/events?token=bogus-token"):
                pass
        assert exc_info.value.code == 1008

    def test_ws_connect_with_revoked_token_rejected(self, client, test_db):
        """WebSocket connection with revoked token is rejected with 1008."""
        import hashlib
        from starlette.websockets import WebSocketDisconnect as StarletteWSDisconnect

        # Create a revoked token
        revoked_token = "revoked-ws-token"
        token_hash = hashlib.sha256(revoked_token.encode()).hexdigest()
        cursor = test_db.cursor()
        cursor.execute(
            "INSERT INTO tokens (token_hash, username, role, created_at, revoked_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash, "revoked-user", "read", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
        )
        test_db.commit()

        with pytest.raises(StarletteWSDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/events?token={revoked_token}"):
                pass
        assert exc_info.value.code == 1008
