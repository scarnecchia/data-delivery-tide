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

    def test_create_delivery_success(self, client):
        """AC1.1: POST /deliveries with valid body → 200, includes server-computed delivery_id."""
        payload = make_delivery_payload()
        response = client.post("/deliveries", json=payload)

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
        assert data["lexicon_id"] == "soc.qar"
        assert data["status"] == "pending"
        assert data["source_path"] == "/source/test"
        assert data["first_seen_at"]

    def test_create_delivery_deterministic_id(self, client):
        """AC3.4: same source_path always produces same delivery_id."""
        payload1 = make_delivery_payload(source_path="/data/scan-123")
        payload2 = make_delivery_payload(source_path="/data/scan-123")

        response1 = client.post("/deliveries", json=payload1)
        response2 = client.post("/deliveries", json=payload2)

        assert response1.json()["delivery_id"] == response2.json()["delivery_id"]

    def test_upsert_preserves_first_seen_at(self, client):
        """AC1.2: POST same source_path twice → second returns 200, first_seen_at preserved."""
        payload = make_delivery_payload(source_path="/data/unique-scan")

        # First POST
        response1 = client.post("/deliveries", json=payload)
        first_seen_at_1 = response1.json()["first_seen_at"]
        delivery_id = response1.json()["delivery_id"]

        # Second POST with same source_path but different status
        payload_updated = make_delivery_payload(
            source_path="/data/unique-scan",
            status="passed",
        )
        response2 = client.post("/deliveries", json=payload_updated)

        assert response2.status_code == 200
        data2 = response2.json()

        # Same delivery_id (deterministic from source_path)
        assert data2["delivery_id"] == delivery_id
        # first_seen_at should be preserved
        assert data2["first_seen_at"] == first_seen_at_1
        # status should be updated
        assert data2["status"] == "passed"

    def test_create_missing_required_field(self, client):
        """AC3.1: POST /deliveries without required field returns 422."""
        payload = make_delivery_payload()
        del payload["source_path"]

        response = client.post("/deliveries", json=payload)
        assert response.status_code == 422

    def test_create_invalid_qa_status(self, client):
        """AC3.2: POST /deliveries without required lexicon_id returns 422."""
        payload = make_delivery_payload()
        del payload["lexicon_id"]
        response = client.post("/deliveries", json=payload)
        assert response.status_code == 422


class TestGetDelivery:
    """Test GET /deliveries/{delivery_id} endpoint."""

    def test_get_delivery_exists(self, client):
        """AC1.3: GET /deliveries/{delivery_id} after POST returns 200, matching delivery."""
        payload = make_delivery_payload(source_path="/data/get-test")
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        response = client.get(f"/deliveries/{delivery_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["delivery_id"] == delivery_id
        assert data["source_path"] == "/data/get-test"

    def test_get_delivery_not_found(self, client):
        """AC1.4: GET /deliveries/{delivery_id} with nonexistent ID returns 404."""
        response = client.get("/deliveries/nonexistent-id-12345")
        assert response.status_code == 404


class TestListDeliveries:
    """Test GET /deliveries endpoint with filtering."""

    def test_list_all_deliveries(self, client):
        """GET /deliveries with no filters returns all deliveries."""
        payload1 = make_delivery_payload(source_path="/data/list-1")
        payload2 = make_delivery_payload(source_path="/data/list-2")

        client.post("/deliveries", json=payload1)
        client.post("/deliveries", json=payload2)

        response = client.get("/deliveries")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_filtered_by_qa_status(self, client):
        """GET /deliveries?status=pending filters by status."""
        payload_pending = make_delivery_payload(
            source_path="/data/filter-pending",
            status="pending",
        )
        payload_passed = make_delivery_payload(
            source_path="/data/filter-passed",
            status="passed",
        )

        client.post("/deliveries", json=payload_pending)
        client.post("/deliveries", json=payload_passed)

        response = client.get("/deliveries?status=pending")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "pending"

    def test_list_filtered_by_dp_id(self, client):
        """GET /deliveries?dp_id=X filters by dp_id."""
        payload1 = make_delivery_payload(source_path="/data/dp-1", dp_id="dp-alpha")
        payload2 = make_delivery_payload(source_path="/data/dp-2", dp_id="dp-beta")

        client.post("/deliveries", json=payload1)
        client.post("/deliveries", json=payload2)

        response = client.get("/deliveries?dp_id=dp-alpha")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["dp_id"] == "dp-alpha"


class TestActionableDeliveries:
    """Test GET /deliveries/actionable endpoint.

    Returns deliveries with status in lexicon's actionable_statuses
    AND parquet_converted_at IS NULL.
    """

    def test_actionable_returns_passed_unconverted(self, client):
        """AC1.8: GET /deliveries/actionable returns passed+unconverted deliveries."""
        # Create a pending delivery (not actionable)
        payload_pending = make_delivery_payload(
            source_path="/data/actionable-pending",
            status="pending",
        )
        client.post("/deliveries", json=payload_pending)

        # Create a passed delivery without parquet_converted_at (actionable)
        payload_passed = make_delivery_payload(
            source_path="/data/actionable-passed",
            status="passed",
        )
        client.post("/deliveries", json=payload_passed)

        response = client.get("/deliveries/actionable")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "passed"
        assert data[0]["source_path"] == "/data/actionable-passed"

    def test_actionable_empty_when_none_match(self, client):
        """GET /deliveries/actionable returns empty list when no deliveries are actionable."""
        # Create only pending deliveries (not actionable)
        payload1 = make_delivery_payload(
            source_path="/data/actionable-test-1",
            status="pending",
        )
        payload2 = make_delivery_payload(
            source_path="/data/actionable-test-2",
            status="pending",
        )
        client.post("/deliveries", json=payload1)
        client.post("/deliveries", json=payload2)

        response = client.get("/deliveries/actionable")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0


class TestUpdateDelivery:
    """Test PATCH /deliveries/{delivery_id} endpoint."""

    def test_update_delivery_partial(self, client):
        """AC1.5: PATCH /deliveries/{delivery_id} with {"output_path": ...} → only that field changed."""
        payload = make_delivery_payload(source_path="/data/update-test")
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]
        original_status = post_response.json()["status"]

        # PATCH only output_path
        update_payload = {"output_path": "/new/output/path"}
        response = client.patch(f"/deliveries/{delivery_id}", json=update_payload)

        assert response.status_code == 200
        data = response.json()
        assert data["output_path"] == "/new/output/path"
        assert data["status"] == original_status

    def test_update_delivery_empty_body_noop(self, client):
        """AC3.3: PATCH /deliveries/{delivery_id} with empty body {} is a no-op."""
        payload = make_delivery_payload(source_path="/data/noop-test")
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]
        original_data = post_response.json()

        # PATCH with empty body
        response = client.patch(f"/deliveries/{delivery_id}", json={})

        assert response.status_code == 200
        data = response.json()
        # All fields should remain unchanged
        assert data["status"] == original_data["status"]
        assert data["output_path"] == original_data["output_path"]

    def test_update_delivery_not_found(self, client):
        """AC1.6: PATCH /deliveries/{delivery_id} with nonexistent ID returns 404."""
        response = client.patch(
            "/deliveries/nonexistent-id-99999",
            json={"output_path": "/new/path"},
        )
        assert response.status_code == 404

    def test_update_delivery_qa_status(self, client):
        """PATCH /deliveries/{delivery_id} can update status."""
        payload = make_delivery_payload(
            source_path="/data/status-update",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "passed"

    def test_update_delivery_parquet_converted_at(self, client):
        """PATCH /deliveries/{delivery_id} can update parquet_converted_at."""
        payload = make_delivery_payload(source_path="/data/parquet-update")
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"parquet_converted_at": "2026-04-09T15:30:00+00:00"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["parquet_converted_at"] == "2026-04-09T15:30:00+00:00"


class TestLexiconValidation:
    """Test lexicon-based validation of statuses and transitions (AC4.1-AC4.6)."""

    def test_ac4_1_post_with_valid_status(self, client):
        """AC4.1: POST with valid status for lexicon succeeds."""
        payload = make_delivery_payload(
            source_path="/data/ac4-1-test",
            lexicon_id="soc.qar",
            status="pending",
        )
        response = client.post("/deliveries", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["lexicon_id"] == "soc.qar"

    def test_post_with_unknown_lexicon_id(self, client):
        """POST with unknown lexicon_id returns 422 with "unknown lexicon_id" detail."""
        payload = make_delivery_payload(
            source_path="/data/unknown-lexicon-test",
            lexicon_id="nonexistent.lexicon",
            status="pending",
        )
        response = client.post("/deliveries", json=payload)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "unknown lexicon_id" in detail

    def test_ac4_2_post_with_invalid_status(self, client):
        """AC4.2: POST with status not in lexicon's statuses returns 422."""
        payload = make_delivery_payload(
            source_path="/data/ac4-2-test",
            lexicon_id="soc.qar",
            status="nonexistent",
        )
        response = client.post("/deliveries", json=payload)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "not valid for lexicon" in detail

    def test_ac4_3_patch_with_legal_transition(self, client):
        """AC4.3: PATCH with legal transition succeeds."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac4-3-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        # PATCH to passed (legal transition: pending -> passed)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
        )

        assert patch_response.status_code == 200
        data = patch_response.json()
        assert data["status"] == "passed"

    def test_ac4_4_patch_with_illegal_transition(self, client):
        """AC4.4: PATCH with illegal transition returns 422."""
        # Create with passed status
        payload = make_delivery_payload(
            source_path="/data/ac4-4-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        # First transition to passed (legal)
        client.patch(f"/deliveries/{delivery_id}", json={"status": "passed"})

        # Now try to transition back to pending (illegal: passed -> pending not in transitions)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "pending"},
        )

        assert patch_response.status_code == 422
        detail = patch_response.json()["detail"]
        assert "not allowed" in detail or "transition" in detail

    def test_ac4_5_set_on_metadata_auto_populated(self, client):
        """AC4.5: set_on metadata field auto-populated on matching status transition."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac4-5-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]
        assert post_response.json().get("metadata", {}).get("passed_at") is None

        # PATCH to passed (should trigger set_on for passed_at)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
        )

        assert patch_response.status_code == 200
        data = patch_response.json()
        assert data["status"] == "passed"
        # Verify passed_at is populated with a valid ISO timestamp
        assert "passed_at" in data["metadata"]
        assert data["metadata"]["passed_at"] is not None
        # Verify it parses as a valid ISO datetime
        datetime.fromisoformat(data["metadata"]["passed_at"])

    def test_ac4_6_no_status_change_no_metadata_auto_pop(self, client, test_db):
        """AC4.6: PATCH without status change produces no event and no metadata auto-population."""
        # Create with pending status
        payload = make_delivery_payload(
            source_path="/data/ac4-6-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        # Count events before PATCH
        events_before = get_events(test_db)
        initial_event_count = len(events_before)

        # PATCH without changing status
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "pending"},  # Same as current status
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

    def test_new_delivery_creates_event(self, client, test_db):
        """event-stream.AC1.1: POST new delivery creates delivery.created event."""
        payload = make_delivery_payload(source_path="/data/new-event-test")
        response = client.post("/deliveries", json=payload)

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

    def test_recrawl_no_event(self, client, test_db):
        """event-stream.AC1.3: Re-crawl of existing delivery produces no event."""
        payload = make_delivery_payload(source_path="/data/recrawl-test")

        # First POST - creates event
        response1 = client.post("/deliveries", json=payload)
        assert response1.status_code == 200

        events_after_first = get_events(test_db)
        assert len(events_after_first) == 1

        # Second POST with same source_path and fingerprint - should not create event
        response2 = client.post("/deliveries", json=payload)
        assert response2.status_code == 200

        events_after_second = get_events(test_db)
        assert len(events_after_second) == 1  # Still only one event

    def test_backward_compatibility_response(self, client):
        """event-stream.AC7.1: POST response unchanged after adding event emission."""
        payload = make_delivery_payload(source_path="/data/compat-test")
        response = client.post("/deliveries", json=payload)

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
    async def test_ws_client_receives_delivery_created_event(self, client):
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
        response = client.post("/deliveries", json=payload)

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

    def test_post_after_restart_no_event_for_existing(self, client, test_db):
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
        response = client.post("/deliveries", json=payload)
        assert response.status_code == 200

        # Check events table
        events_after = get_events(test_db)
        # Should still be the same count (no new event)
        assert len(events_after) == initial_event_count

    def test_post_after_restart_event_for_new(self, client, test_db):
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
        response = client.post("/deliveries", json=payload2)
        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        # Check events
        events = get_events(test_db)
        assert len(events) == 1
        assert events[0]["event_type"] == "delivery.created"
        assert events[0]["delivery_id"] == delivery_id


class TestDeliveryStatusChangedEvents:
    """Test delivery.status_changed event emission on PATCH /deliveries/{id}."""

    def test_status_pending_to_passed_creates_event(self, client, test_db):
        """event-stream.AC2.1: PATCH with status pending→passed creates event."""
        payload = make_delivery_payload(
            source_path="/data/status-change-1",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH to change status
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed"},
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

    def test_status_pending_to_failed_creates_event(self, client, test_db):
        """event-stream.AC2.2: PATCH with status pending→failed creates event."""
        payload = make_delivery_payload(
            source_path="/data/status-change-2",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH to change status to failed
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "failed"},
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 1
        event = new_events[0]
        assert event["event_type"] == "delivery.status_changed"
        assert event["delivery_id"] == delivery_id
        assert event["payload"]["status"] == "failed"

    def test_event_payload_reflects_new_status(self, client, test_db):
        """event-stream.AC2.3: Event payload contains updated delivery record."""
        payload = make_delivery_payload(
            source_path="/data/payload-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH to change status and output_path
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "passed", "output_path": "/new/output"},
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 1
        event = new_events[0]
        # Payload should reflect new status
        assert event["payload"]["status"] == "passed"
        assert event["payload"]["output_path"] == "/new/output"

    def test_no_event_on_non_status_update(self, client, test_db):
        """event-stream.AC2.4: PATCH non-status field produces no event."""
        payload = make_delivery_payload(source_path="/data/non-status-test")
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH only parquet_converted_at (no status change)
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"parquet_converted_at": "2026-04-09T10:00:00+00:00"},
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        # Filter for events after the POST event
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 0  # No event should be created for non-status changes

    def test_no_event_on_same_status_patch(self, client, test_db):
        """event-stream.AC2.5: PATCH with same status value produces no event."""
        payload = make_delivery_payload(
            source_path="/data/same-status-test",
            status="pending",
        )
        post_response = client.post("/deliveries", json=payload)
        delivery_id = post_response.json()["delivery_id"]

        events_before = get_events(test_db)

        # PATCH with same status value
        patch_response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"status": "pending"},
        )

        assert patch_response.status_code == 200

        events_after = get_events(test_db)
        new_events = [e for e in events_after if e["seq"] > max(ev["seq"] for ev in events_before)] if events_before else events_after
        assert len(new_events) == 0  # No event should be created


class TestCatchUpEndpoint:
    """Test GET /events catch-up endpoint."""

    def test_get_events_after_filters_by_seq(self, client, test_db):
        """event-stream.AC5.1: GET /events?after=N returns only events with seq > N, ordered by seq ASC."""
        from pipeline.registry_api.db import insert_event

        # Insert 3 events manually
        insert_event(test_db, "delivery.created", "id-1", {"test": "payload1"})
        insert_event(test_db, "delivery.created", "id-2", {"test": "payload2"})
        insert_event(test_db, "delivery.created", "id-3", {"test": "payload3"})

        # Fetch events after seq 1
        response = client.get("/events?after=1")

        assert response.status_code == 200
        events = response.json()

        # Should contain seq 2 and 3, not seq 1
        assert len(events) == 2
        assert events[0]["seq"] == 2
        assert events[1]["seq"] == 3
        # Verify order (seq ASC)
        assert events[0]["seq"] < events[1]["seq"]

    def test_get_events_respects_limit(self, client, test_db):
        """event-stream.AC5.2: GET /events?after=N&limit=M returns at most M events."""
        from pipeline.registry_api.db import insert_event

        # Insert 5 events
        for i in range(5):
            insert_event(test_db, "delivery.created", f"id-{i}", {"test": f"payload{i}"})

        # Fetch with limit=2
        response = client.get("/events?after=0&limit=2")

        assert response.status_code == 200
        events = response.json()

        # Should return exactly 2 events
        assert len(events) == 2
        assert events[0]["seq"] == 1
        assert events[1]["seq"] == 2

    def test_get_events_after_latest_returns_empty(self, client, test_db):
        """event-stream.AC5.3: GET /events?after=<latest_seq> returns empty array."""
        from pipeline.registry_api.db import insert_event

        # Insert 3 events
        insert_event(test_db, "delivery.created", "id-1", {"test": "payload1"})
        insert_event(test_db, "delivery.created", "id-2", {"test": "payload2"})
        insert_event(test_db, "delivery.created", "id-3", {"test": "payload3"})

        # Fetch events after the last one (seq=3)
        response = client.get("/events?after=3")

        assert response.status_code == 200
        events = response.json()
        assert events == []

    def test_get_events_without_after_returns_422(self, client):
        """event-stream.AC5.4: GET /events without after parameter returns 422."""
        response = client.get("/events")

        assert response.status_code == 422

    def test_get_events_limit_capping(self, client, test_db):
        """GET /events caps limit at 1000 without erroring."""
        from pipeline.registry_api.db import insert_event

        # Insert 5 events (less than the 5000 requested)
        for i in range(5):
            insert_event(test_db, "delivery.created", f"id-{i}", {"test": f"payload{i}"})

        # Request with limit way over 1000
        response = client.get("/events?after=0&limit=5000")

        assert response.status_code == 200
        events = response.json()

        # Should return all 5 (capped at 1000 but less available)
        assert len(events) == 5

    def test_get_events_response_shape(self, client, test_db):
        """GET /events response includes all required fields."""
        from pipeline.registry_api.db import insert_event

        insert_event(test_db, "delivery.created", "test-id", {"key": "value"})

        response = client.get("/events?after=0")

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
