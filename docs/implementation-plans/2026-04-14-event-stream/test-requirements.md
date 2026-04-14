# Test Requirements — Event Stream

## Automated Tests

| AC | Description | Test Type | Test File | Phase |
|----|-------------|-----------|-----------|-------|
| event-stream.AC1.1 | POST with new delivery_id creates event with type `delivery.created`, correct seq, and full delivery payload | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC1.2 | Event broadcast received by connected WebSocket client | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC1.3 | Re-crawl of existing delivery (same delivery_id, same fingerprint) produces no event | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC1.4 | First POST after API restart correctly detects new vs existing deliveries | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC2.1 | PATCH changing qa_status from pending to passed creates `delivery.status_changed` event | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC2.2 | PATCH changing qa_status from pending to failed creates `delivery.status_changed` event | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC2.3 | Event payload contains the updated delivery record (new status reflected) | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC2.4 | PATCH that doesn't change qa_status (e.g., setting parquet_converted_at) produces no event | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC2.5 | PATCH with same qa_status value as current produces no event | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC3.1 | Two connected WS clients both receive the same broadcast event | integration | tests/registry_api/test_events.py | 2 |
| event-stream.AC3.2 | Client disconnect does not affect other connected clients | integration | tests/registry_api/test_events.py | 2 |
| event-stream.AC3.3 | Dead connection (network drop) is cleaned up without crashing broadcast loop | integration | tests/registry_api/test_events.py | 2 |
| event-stream.AC4.1 | Each persisted event has a seq higher than all previous events | unit | tests/registry_api/test_db.py | 1 |
| event-stream.AC4.2 | Event payload stored as JSON matches the broadcast payload | unit | tests/registry_api/test_db.py | 1 |
| event-stream.AC4.3 | Events persist even if no WS clients are connected | integration | tests/registry_api/test_routes.py | 3 |
| event-stream.AC5.1 | GET /events?after=N returns only events with seq > N, ordered by seq ASC | unit, integration | tests/registry_api/test_db.py, tests/registry_api/test_routes.py | 1, 4 |
| event-stream.AC5.2 | GET /events?after=N&limit=M returns at most M events | unit, integration | tests/registry_api/test_db.py, tests/registry_api/test_routes.py | 1, 4 |
| event-stream.AC5.3 | GET /events?after=\<latest_seq\> returns empty array | integration | tests/registry_api/test_routes.py | 4 |
| event-stream.AC5.4 | GET /events without after parameter returns 422 | integration | tests/registry_api/test_routes.py | 4 |
| event-stream.AC6.1 | Consumer receives real-time events via WebSocket | integration | tests/events/test_consumer.py | 5 |
| event-stream.AC6.2 | Consumer catches up on missed events via REST on reconnect | integration | tests/events/test_consumer.py | 5 |
| event-stream.AC6.3 | Consumer deduplicates events received via both REST and WS (by seq) | unit | tests/events/test_consumer.py | 5 |
| event-stream.AC6.4 | Consumer reconnects automatically after disconnection with backoff | integration | tests/events/test_consumer.py | 5 |
| event-stream.AC7.1 | Existing delivery POST/PATCH behaviour unchanged (same request/response contract) | integration | tests/registry_api/test_routes.py | 3 |

## Human Verification

| AC | Description | Why Not Automated | Verification Approach |
|----|-------------|-------------------|----------------------|
| event-stream.AC7.2 | All existing tests pass without modification | Meta-criterion about the test suite itself, not a testable behaviour | After each phase, run `uv run pytest tests/ -v` and confirm: (1) all pre-existing tests pass, (2) no existing test file was modified to accommodate event stream changes (verify via `git diff --name-only <base-commit> -- tests/` and inspect any changed test files to confirm only additions, no edits to existing test functions). Check at the end of Phase 3 and again after Phase 5. |

## Coverage Notes

### Test layering by AC

Some acceptance criteria are tested at multiple layers. This is intentional — the unit tests (Phase 1) validate the DB functions in isolation, while the integration tests (Phases 3-4) validate the same behaviour end-to-end through the HTTP API.

- **AC4.1, AC4.2**: Tested at the unit level in Phase 1 (`test_db.py`) via direct `insert_event` / `get_events_after` calls. Also implicitly validated in Phase 3 integration tests that query the events table after HTTP requests.
- **AC5.1, AC5.2**: Tested at the unit level in Phase 1 (`test_db.py`) via `get_events_after`, and at the integration level in Phase 4 (`test_routes.py`) via `GET /events`.
- **AC4.3**: Not directly testable in Phase 1 (no WS infrastructure yet). Tested in Phase 3 by POSTing a delivery with no WS clients connected and verifying the event row exists in the DB.

### Test file inventory

| Test File | Created In | ACs Covered |
|-----------|------------|-------------|
| tests/registry_api/test_models.py | Phase 1 (modified) | Model validation for EventRecord (supports AC4.2) |
| tests/registry_api/test_db.py | Phase 1 (modified) | AC4.1, AC4.2, AC5.1, AC5.2 |
| tests/registry_api/test_events.py | Phase 2 (created) | AC3.1, AC3.2, AC3.3 |
| tests/registry_api/test_routes.py | Phase 3, 4 (modified) | AC1.1-AC1.4, AC2.1-AC2.5, AC4.3, AC5.1-AC5.4, AC7.1 |
| tests/events/test_consumer.py | Phase 5 (created) | AC6.1, AC6.2, AC6.3, AC6.4 |
