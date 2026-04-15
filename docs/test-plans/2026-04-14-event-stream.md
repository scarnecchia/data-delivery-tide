# Event Stream — Human Test Plan

## Prerequisites

- Package installed: `pip install -e ".[registry,consumer,dev]"`
- Registry API running locally: `registry-api` (port 8000)
- All automated tests passing: `pytest tests/ -v` (237 tests, 0 failures)
- A WebSocket client tool available (e.g., `websocat`, browser dev tools, or the reference consumer at `src/pipeline/events/consumer.py`)

## Phase 1: Verify Existing Tests Unmodified (AC7.2)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Run `git diff --name-only 6c8f041 -- tests/` | Lists only new files or files with additions. Should NOT show modifications to pre-existing test functions. |
| 2 | For any changed test files, run `git diff 6c8f041 -- <file>` and inspect the diff | Changes should be additive only: new imports, new test classes, new test functions. No existing test function body should be altered. |
| 3 | Run `pytest tests/ -v` | All tests pass. No test names from before the event-stream work should be missing or renamed. |

## Phase 2: End-to-End Event Stream Walkthrough

Purpose: Validates that a real WebSocket client receives events triggered by HTTP operations, covering the full POST -> event -> WS broadcast -> REST catch-up pipeline.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Start the registry API: `registry-api` | API starts on port 8000, logs to stderr. |
| 2 | Connect a WebSocket client to `ws://localhost:8000/ws/events` | Connection accepted. Client stays connected, waiting for messages. |
| 3 | In a separate terminal, POST a new delivery: `curl -X POST http://localhost:8000/deliveries -H "Content-Type: application/json" -d '{"request_id":"req-e2e","project":"test-proj","request_type":"scan","workplan_id":"wp-001","dp_id":"dp-001","version":"1.0.0","scan_root":"/data","qa_status":"pending","source_path":"/data/e2e-test-1"}'` | HTTP 200 response with delivery_id, request_id, project, etc. |
| 4 | Check the WebSocket client | Should have received a JSON message: `{"seq": 1, "event_type": "delivery.created", "delivery_id": "<sha256-of-source_path>", "payload": {...}, "created_at": "..."}`. |
| 5 | POST the same delivery again (identical payload) | HTTP 200 response. WebSocket client should receive NO new message (re-crawl suppression). |
| 6 | PATCH the delivery's qa_status: `curl -X PATCH http://localhost:8000/deliveries/<delivery_id> -H "Content-Type: application/json" -d '{"qa_status":"passed"}'` | HTTP 200 with updated qa_status="passed". |
| 7 | Check the WebSocket client | Should have received: `{"seq": 2, "event_type": "delivery.status_changed", ...}` with payload showing qa_status="passed". |
| 8 | PATCH with non-status field only: `curl -X PATCH http://localhost:8000/deliveries/<delivery_id> -H "Content-Type: application/json" -d '{"output_path":"/out/test"}'` | HTTP 200. WebSocket client should receive NO new message. |
| 9 | Fetch events via REST: `curl "http://localhost:8000/events?after=0"` | Returns JSON array with 2 events (seq 1 and 2), ordered by seq ASC. |
| 10 | Fetch events after latest: `curl "http://localhost:8000/events?after=2"` | Returns empty JSON array `[]`. |
| 11 | Fetch events without after param: `curl "http://localhost:8000/events"` | Returns HTTP 422 (validation error). |

## Phase 3: Multi-Client and Disconnection

Purpose: Validates broadcast fan-out and connection resilience under real networking conditions.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Connect two WebSocket clients to `ws://localhost:8000/ws/events` | Both connections accepted. |
| 2 | POST a new delivery (different source_path from Phase 2) | Both WS clients receive the same `delivery.created` event with identical seq and payload. |
| 3 | Disconnect one WS client (close tab or Ctrl+C) | No error in API logs. |
| 4 | POST another new delivery | Remaining connected client receives the event. No crash or error in API logs. |

## Phase 4: API Restart Resilience

Purpose: Validates that event stream correctly handles API restart (DB state persists, in-memory WS state resets).

| Step | Action | Expected |
|------|--------|----------|
| 1 | With API running and some deliveries already registered, stop the API (Ctrl+C) | API shuts down cleanly. |
| 2 | Restart the API: `registry-api` | API starts. SQLite DB with existing data is reloaded. |
| 3 | Connect a WS client | Connection accepted. |
| 4 | POST the same delivery that existed before restart | HTTP 200 (upsert). No `delivery.created` event on WS (already existed in DB). |
| 5 | POST a genuinely new delivery | HTTP 200. WS client receives `delivery.created` event. |
| 6 | Fetch events via REST: `curl "http://localhost:8000/events?after=0"` | Returns the new event (and any events from before restart that were persisted). |

## Phase 5: Reference Consumer

Purpose: Validates the EventConsumer reconnection and deduplication behaviour end-to-end.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Start the registry API | Running on port 8000. |
| 2 | Create a small test script that instantiates `EventConsumer("http://localhost:8000", callback)` with a callback that prints received events, then calls `await consumer.run()` | Consumer connects via WS and begins listening. |
| 3 | POST a new delivery via curl | Consumer prints the received event. |
| 4 | Stop the registry API (Ctrl+C) | Consumer should log a disconnection and begin reconnection attempts with backoff. |
| 5 | Restart the registry API | Consumer reconnects automatically. |
| 6 | POST another new delivery | Consumer receives the event after reconnection. The consumer should NOT re-process events already seen before the restart. |

## Human Verification Required

| Criterion | Why Manual | Steps |
|-----------|------------|-------|
| AC7.2: All existing tests pass without modification | Meta-criterion about the test suite itself | (1) Run `git diff --name-only 6c8f041 -- tests/` to list changed test files. (2) For each changed file, run `git diff 6c8f041 -- <file>` and confirm all changes are additive. (3) Run `pytest tests/ -v` and confirm all 237 tests pass. |

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| AC1.1 | `test_routes.py::TestDeliveryCreatedEvents::test_new_delivery_creates_event` | Phase 2, Steps 3-4 |
| AC1.2 | `test_routes.py::TestWebSocketBroadcast::test_ws_client_receives_delivery_created_event` | Phase 2, Step 4 |
| AC1.3 | `test_routes.py::TestDeliveryCreatedEvents::test_recrawl_no_event` | Phase 2, Step 5 |
| AC1.4 | `test_routes.py::TestAPIRestartDeliveryDistinction::test_post_after_restart_*` | Phase 4, Steps 4-5 |
| AC2.1 | `test_routes.py::TestDeliveryStatusChangedEvents::test_status_pending_to_passed_creates_event` | Phase 2, Steps 6-7 |
| AC2.2 | `test_routes.py::TestDeliveryStatusChangedEvents::test_status_pending_to_failed_creates_event` | -- |
| AC2.3 | `test_routes.py::TestDeliveryStatusChangedEvents::test_event_payload_reflects_new_status` | Phase 2, Step 7 |
| AC2.4 | `test_routes.py::TestDeliveryStatusChangedEvents::test_no_event_on_non_status_update` | Phase 2, Step 8 |
| AC2.5 | `test_routes.py::TestDeliveryStatusChangedEvents::test_no_event_on_same_status_patch` | -- |
| AC3.1 | `test_events.py::TestConnectionManager::test_broadcast_to_multiple_connections_ac31` | Phase 3, Step 2 |
| AC3.2 | `test_events.py::test_disconnect_does_not_affect_other_connections_ac32` | Phase 3, Steps 3-4 |
| AC3.3 | `test_events.py::test_broadcast_removes_dead_connection` / `test_dead_connection_cleanup_ac33` | Phase 3, Step 4 |
| AC4.1 | `test_db.py::TestInsertEvent::test_insert_event_ac4_1_monotonic_sequence` | Phase 2, Step 9 |
| AC4.2 | `test_db.py::TestInsertEvent::test_insert_event_ac4_2_payload_matches_broadcast` | Phase 2, Steps 4, 7, 9 |
| AC4.3 | `test_db.py::test_insert_event_ac4_3_persists_without_clients` | Phase 4, Step 6 |
| AC5.1 | `test_db.py::test_get_events_after_ac5_1` + `test_routes.py::test_get_events_after_filters_by_seq` | Phase 2, Step 9 |
| AC5.2 | `test_db.py::test_get_events_after_ac5_2` + `test_routes.py::test_get_events_respects_limit` | Phase 2, Step 9 |
| AC5.3 | `test_routes.py::test_get_events_after_latest_returns_empty` | Phase 2, Step 10 |
| AC5.4 | `test_routes.py::test_get_events_without_after_returns_422` | Phase 2, Step 11 |
| AC6.1 | `test_consumer.py::test_session_receives_ws_events` | Phase 5, Step 3 |
| AC6.2 | `test_consumer.py::test_catch_up_*` (4 tests) | Phase 5, Step 6 |
| AC6.3 | `test_consumer.py::test_deduplication_by_seq` | Phase 5, Step 6 |
| AC6.4 | `test_consumer.py::test_reconnection_after_disconnect` | Phase 5, Steps 4-5 |
| AC7.1 | `test_routes.py::TestDeliveryCreatedEvents::test_backward_compatibility_response` | Phase 2, Step 3 |
| AC7.2 | -- (meta-criterion) | Phase 1, Steps 1-3 |
