def make_delivery_payload(**overrides):
    """
    Helper to create a valid DeliveryCreate payload with sensible defaults.

    Allows overriding any field via keyword arguments.
    """
    defaults = {
        "request_id": "req-001",
        "project": "test-project",
        "request_type": "scan",
        "workplan_id": "wp-001",
        "dp_id": "dp-001",
        "version": "1.0.0",
        "scan_root": "/data/scans",
        "qa_status": "pending",
        "source_path": "/source/test",
    }
    defaults.update(overrides)
    return defaults


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
        assert data["qa_status"] == "pending"
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

        # Second POST with same source_path but different qa_status
        payload_updated = make_delivery_payload(
            source_path="/data/unique-scan",
            qa_status="passed",
        )
        response2 = client.post("/deliveries", json=payload_updated, headers=auth_headers)

        assert response2.status_code == 200
        data2 = response2.json()

        # Same delivery_id (deterministic from source_path)
        assert data2["delivery_id"] == delivery_id
        # first_seen_at should be preserved
        assert data2["first_seen_at"] == first_seen_at_1
        # qa_status should be updated
        assert data2["qa_status"] == "passed"

    def test_create_missing_required_field(self, client, auth_headers):
        """AC3.1: POST /deliveries without required field returns 422."""
        payload = make_delivery_payload()
        del payload["source_path"]

        response = client.post("/deliveries", json=payload, headers=auth_headers)
        assert response.status_code == 422

    def test_create_invalid_qa_status(self, client, auth_headers):
        """AC3.2: POST /deliveries with invalid qa_status returns 422."""
        payload = make_delivery_payload(qa_status="invalid")
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
        assert len(data) == 2

    def test_list_filtered_by_qa_status(self, client, auth_headers):
        """GET /deliveries?qa_status=pending filters by qa_status."""
        payload_pending = make_delivery_payload(
            source_path="/data/filter-pending",
            qa_status="pending",
        )
        payload_passed = make_delivery_payload(
            source_path="/data/filter-passed",
            qa_status="passed",
        )

        client.post("/deliveries", json=payload_pending, headers=auth_headers)
        client.post("/deliveries", json=payload_passed, headers=auth_headers)

        response = client.get("/deliveries?qa_status=pending", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["qa_status"] == "pending"

    def test_list_filtered_by_dp_id(self, client, auth_headers):
        """GET /deliveries?dp_id=X filters by dp_id."""
        payload1 = make_delivery_payload(source_path="/data/dp-1", dp_id="dp-alpha")
        payload2 = make_delivery_payload(source_path="/data/dp-2", dp_id="dp-beta")

        client.post("/deliveries", json=payload1, headers=auth_headers)
        client.post("/deliveries", json=payload2, headers=auth_headers)

        response = client.get("/deliveries?dp_id=dp-alpha", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["dp_id"] == "dp-alpha"


class TestActionableDeliveries:
    """Test GET /deliveries/actionable endpoint."""

    def test_actionable_returns_passed_unconverted(self, client, auth_headers):
        """AC1.8: GET /deliveries/actionable returns passed+unconverted deliveries."""
        # Create one passed+unconverted (actionable)
        payload_actionable = make_delivery_payload(
            source_path="/data/actionable-1",
            qa_status="passed",
        )

        # Create one pending (not actionable)
        payload_pending = make_delivery_payload(
            source_path="/data/not-actionable-1",
            qa_status="pending",
        )

        # Create one passed delivery that we'll mark as converted
        payload_for_converted = make_delivery_payload(
            source_path="/data/converted-1",
            qa_status="passed",
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
        assert data[0]["qa_status"] == "passed"
        assert data[0]["parquet_converted_at"] is None
        assert data[0]["source_path"] == "/data/actionable-1"

    def test_actionable_empty_when_none_match(self, client, auth_headers):
        """GET /deliveries/actionable returns empty list when no deliveries are actionable."""
        payload_pending = make_delivery_payload(
            source_path="/data/pending-only",
            qa_status="pending",
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
        original_qa_status = post_response.json()["qa_status"]

        # PATCH only output_path
        update_payload = {"output_path": "/new/output/path"}
        response = client.patch(f"/deliveries/{delivery_id}", json=update_payload, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["output_path"] == "/new/output/path"
        assert data["qa_status"] == original_qa_status

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
        assert data["qa_status"] == original_data["qa_status"]
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
            qa_status="pending",
        )
        post_response = client.post("/deliveries", json=payload, headers=auth_headers)
        delivery_id = post_response.json()["delivery_id"]

        response = client.patch(
            f"/deliveries/{delivery_id}",
            json={"qa_status": "passed"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["qa_status"] == "passed"

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