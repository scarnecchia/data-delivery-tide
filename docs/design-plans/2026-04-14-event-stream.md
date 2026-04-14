# Event Stream Design

## Summary

The registry API currently records deliveries and exposes them via REST, but has no mechanism for downstream consumers to learn about changes in real time — they'd have to poll. This design adds a live event stream: when the crawler registers a new healthcare data delivery or a QA status changes (pending → passed/failed), the registry persists an event record to SQLite and broadcasts it to any connected WebSocket clients. The persistent event log also doubles as a catch-up mechanism, so consumers that disconnect and reconnect can retrieve any events they missed without requiring the producer to re-emit them.

The implementation is split into five sequential phases: database layer (events table + query functions), WebSocket broadcast infrastructure (`ConnectionManager` + `/ws/events` endpoint), route integration (wiring event emission into the POST and PATCH delivery handlers), REST catch-up endpoint (`GET /events?after=<seq>`), and a reference consumer module that handles reconnect, catch-up, and deduplication. The design explicitly scopes to single-process deployment — no pub/sub backend — and defers authentication to when the broader registry-auth design lands.

## Definition of Done

- Registry API emits `delivery.created` and `delivery.status_changed` events over WebSocket
- Multiple consumers can connect concurrently to `/ws/events`
- Event payload includes event type, timestamp, sequence number, and full delivery record
- All events persisted to an `events` table with monotonic sequence numbers
- REST endpoint `GET /events?after=<seq>` for consumer catch-up on reconnect
- Reference consumer module with reconnect, catch-up on connect, and event handler pattern
- No WS auth (deferred until registry-auth lands)
- Existing tests continue to pass; new tests cover broadcast, persistence, catch-up, and consumer behaviour

## Acceptance Criteria

### event-stream.AC1: API emits delivery.created events
- **event-stream.AC1.1 Success:** POST with new delivery_id creates event with type `delivery.created`, correct seq, and full delivery payload
- **event-stream.AC1.2 Success:** Event broadcast received by connected WebSocket client
- **event-stream.AC1.3 Success:** Re-crawl of existing delivery (same delivery_id, same fingerprint) produces no event
- **event-stream.AC1.4 Edge:** First POST after API restart correctly detects new vs existing deliveries

### event-stream.AC2: API emits delivery.status_changed events
- **event-stream.AC2.1 Success:** PATCH changing qa_status from pending to passed creates event with type `delivery.status_changed`
- **event-stream.AC2.2 Success:** PATCH changing qa_status from pending to failed creates event with type `delivery.status_changed`
- **event-stream.AC2.3 Success:** Event payload contains the updated delivery record (new status reflected)
- **event-stream.AC2.4 Success:** PATCH that doesn't change qa_status (e.g., setting parquet_converted_at) produces no event
- **event-stream.AC2.5 Success:** PATCH with same qa_status value as current produces no event

### event-stream.AC3: Multiple concurrent consumers
- **event-stream.AC3.1 Success:** Two connected WS clients both receive the same broadcast event
- **event-stream.AC3.2 Success:** Client disconnect does not affect other connected clients
- **event-stream.AC3.3 Success:** Dead connection (network drop) is cleaned up without crashing broadcast loop

### event-stream.AC4: Event persistence with monotonic sequence
- **event-stream.AC4.1 Success:** Each persisted event has a seq higher than all previous events
- **event-stream.AC4.2 Success:** Event payload stored as JSON matches the broadcast payload
- **event-stream.AC4.3 Success:** Events persist even if no WS clients are connected

### event-stream.AC5: Catch-up REST endpoint
- **event-stream.AC5.1 Success:** GET /events?after=N returns only events with seq > N, ordered by seq ASC
- **event-stream.AC5.2 Success:** GET /events?after=N&limit=M returns at most M events
- **event-stream.AC5.3 Success:** GET /events?after=\<latest_seq\> returns empty array
- **event-stream.AC5.4 Failure:** GET /events without after parameter returns 422

### event-stream.AC6: Reference consumer
- **event-stream.AC6.1 Success:** Consumer receives real-time events via WebSocket
- **event-stream.AC6.2 Success:** Consumer catches up on missed events via REST on reconnect
- **event-stream.AC6.3 Success:** Consumer deduplicates events received via both REST and WS (by seq)
- **event-stream.AC6.4 Success:** Consumer reconnects automatically after disconnection with backoff

### event-stream.AC7: Backward compatibility
- **event-stream.AC7.1 Success:** Existing delivery POST/PATCH behaviour unchanged (same request/response contract)
- **event-stream.AC7.2 Success:** All existing tests pass without modification

## Glossary

- **WebSocket**: A persistent, full-duplex TCP connection between client and server, used here as a one-way broadcast channel from the registry API to event consumers.
- **ConnectionManager**: A module-level singleton class in `events.py` that tracks active WebSocket connections and fans out broadcast messages to each one. Failed sends are caught and the dead connection is removed.
- **Monotonic sequence number (`seq`)**: An integer that increases strictly over time. SQLite's `INTEGER PRIMARY KEY` auto-assigns these as rowids; the design relies on the guarantee that rowids are never reused across a live events table.
- **Catch-up**: The pattern where a reconnecting consumer requests all events with `seq` greater than the last one it successfully processed, closing the gap between its last known state and the present.
- **Deduplication (by `seq`)**: The consumer buffers incoming WebSocket events while performing a REST catch-up request; any events received via both channels are dropped based on matching sequence numbers, ensuring each event is processed exactly once.
- **Upsert**: An insert-or-update operation (`INSERT OR REPLACE` / `ON CONFLICT DO UPDATE` in SQLite). The POST delivery route uses an upsert, so a pre-query is needed to distinguish genuinely new deliveries from re-crawls of existing ones.
- **Re-crawl**: The crawler visiting a delivery directory it has seen before. If the delivery already exists in the registry (same `delivery_id`, same fingerprint), no event is emitted.
- **`delivery_id`**: A deterministic SHA-256 hash of the source path, used as the primary key for a delivery record.
- **QA status**: Tri-state field (`pending`, `passed`, `failed`) tracking where a delivery is in the quality-assurance workflow. Status transitions on the `PATCH /deliveries/{id}` route are the trigger for `delivery.status_changed` events.
- **`DeliveryResponse`**: The Pydantic model representing a full delivery record as returned by the API. Event payloads embed a snapshot of this at event time, not a diff.
- **`DbDep`**: FastAPI dependency injection type alias for the SQLite connection, resolved via `Depends(get_db())` on each request.
- **WAL mode**: Write-Ahead Logging — a SQLite journal mode that allows concurrent reads during writes. Relevant here because event inserts and delivery queries happen on the same database.
- **`EventConsumer`**: The reference consumer class in `src/pipeline/events/consumer.py`. It manages the WebSocket connection, REST catch-up on reconnect, deduplication, and an exponential-ish reconnect loop.
- **Fire-and-forget (per connection)**: The broadcast strategy where a failed send to one WebSocket client does not abort the broadcast to others — the dead connection is cleaned up and the rest continue.
- **`INTEGER PRIMARY KEY` (SQLite)**: In SQLite, declaring a column as `INTEGER PRIMARY KEY` makes it an alias for the internal rowid, which auto-increments on insert. The design uses this instead of `AUTOINCREMENT` because SQLite only reuses rowids after deletion of the maximum rowid, which doesn't happen here.

## Architecture

Real-time event broadcasting over WebSocket with persistent event log for catch-up. When the crawler registers a new delivery or a delivery's QA status changes, the registry API persists an event to SQLite and broadcasts it to all connected WebSocket clients.

**Event flow:** Route handler detects a meaningful change (new delivery or status transition), writes an event row to the `events` table (getting a monotonic sequence number), then broadcasts the event JSON to all active WebSocket connections via a `ConnectionManager`. DB write happens first — if broadcast fails for any connection, the event is still persisted and consumers catch up via REST.

**Two event types:**
- `delivery.created` — emitted when a `POST /deliveries` inserts a new delivery (not on re-crawl of existing)
- `delivery.status_changed` — emitted when a `PATCH /deliveries/{id}` changes `qa_status` (e.g., pending → passed)

**Detection:** The POST route runs a pre-query (`SELECT delivery_id`) before the upsert to distinguish new deliveries from re-crawls. The PATCH route reads the current `qa_status` before applying the update to detect transitions. Neither changes the DB layer's contract.

**Single-process constraint:** The `ConnectionManager` holds connections in process memory. This works with one Uvicorn worker (current setup). Multi-worker deployment would require a pub/sub backend — out of scope, noted as a future concern.

### Data model

**`events` table** (added to `init_db` alongside `deliveries`):

| Column | Type | Constraints |
|--------|------|-------------|
| `seq` | INTEGER | PRIMARY KEY (auto-assigned rowid, monotonic) |
| `event_type` | TEXT | NOT NULL, CHECK IN ('delivery.created', 'delivery.status_changed') |
| `delivery_id` | TEXT | NOT NULL |
| `payload` | TEXT | NOT NULL (JSON-serialised DeliveryResponse) |
| `created_at` | TEXT | NOT NULL (ISO 8601 UTC) |

`seq` uses SQLite's `INTEGER PRIMARY KEY` which auto-assigns monotonically increasing rowids. No `AUTOINCREMENT` needed — SQLite only reuses rowids after deletion of the max row, and individual event deletion isn't part of this design.

### Event payload

```python
# Contract — not implementation
{
    "seq": 147,
    "event_type": "delivery.created",
    "delivery_id": "abc123...",
    "payload": { ... },  # full DeliveryResponse dict
    "created_at": "2026-04-14T19:30:00Z"
}
```

Same shape over WebSocket and from the catch-up REST endpoint. `payload` is a snapshot of the delivery record at event time, not a diff.

### ConnectionManager contract

```python
# Contract — not implementation
class ConnectionManager:
    async def connect(self, websocket: WebSocket) -> None
        # Accept connection, add to active set

    def disconnect(self, websocket: WebSocket) -> None
        # Remove from active set

    async def broadcast(self, event: dict) -> None
        # Send JSON to all active connections
        # Catch failed sends, remove dead connections
```

Lives in `src/pipeline/registry_api/events.py`. Instantiated once at module level. `broadcast()` is fire-and-forget per connection — failed sends remove the dead connection silently. The consumer's reconnect loop handles recovery.

### WebSocket endpoint

`GET /ws/events` — one-way broadcast channel. On connect: added to ConnectionManager. On disconnect: removed. The receive loop exists only to detect disconnection; clients don't send messages.

No auth for now. When registry-auth lands, token validation happens during the handshake via query param (`/ws/events?token=<token>`), rejecting before `accept()`.

### Catch-up endpoint

`GET /events?after=<seq>&limit=<n>` — returns JSON array of events where `seq > after`, ordered by `seq ASC`, capped at `limit` (default 100, max 1000). Empty array if nothing new.

Consumers track their last processed `seq` and request missed events on reconnect. No pagination cursors — the highest `seq` in the response becomes the next `after` value.

### Route integration

| Endpoint | Event | Detection |
|----------|-------|-----------|
| `POST /deliveries` | `delivery.created` | Pre-query: delivery_id not in DB before upsert |
| `PATCH /deliveries/{id}` | `delivery.status_changed` | Pre-read: old qa_status != new qa_status |
| All other endpoints | none | — |

### Reference consumer contract

```python
# Contract — not implementation
class EventConsumer:
    def __init__(self, api_url: str, on_event: Callable[[dict], Awaitable[None]]) -> None
        # api_url: base URL of registry API
        # on_event: async callback for each event

    async def run(self) -> None
        # Connect WS, catch up via REST, listen, reconnect on failure
```

Lives in `src/pipeline/events/consumer.py`. Behaviour:
1. Connect to WebSocket, buffer incoming events
2. Call `GET /events?after={last_seq}` for catch-up
3. Process catch-up events, deduplicate by `seq` against buffer
4. Process buffered WS events
5. Listen for new events, pass each to `on_event`
6. On disconnect: wait 5 seconds, return to step 1

Deduplication by `seq` handles the overlap window between REST catch-up and WS connect. The consumer processes events exactly once regardless of timing.

## Existing Patterns

This design follows established patterns from the codebase:

- **SQLite table in `init_db`**: `events` table added alongside `deliveries` using the same `CREATE TABLE IF NOT EXISTS` pattern in `db.py`
- **Dependency injection via `Depends()`**: catch-up endpoint uses existing `DbDep` pattern from `db.py:116`
- **Pydantic models**: event payload model follows conventions in `models.py`
- **Per-request connections**: event queries use the same `get_db()` dependency
- **Route structure**: catch-up endpoint added to existing router in `routes.py`

New patterns introduced:
- **Module-level singleton** (`ConnectionManager` in `events.py`): no existing equivalent, but follows the same pattern as FastAPI's `app` instance in `main.py`
- **WebSocket endpoint**: new transport, added to `main.py` alongside existing HTTP routes
- **Consumer module** (`src/pipeline/events/`): new subpackage for event consumption, not part of the registry API

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Event persistence

**Goal:** Add events table and event writing functions to the database layer.

**Components:**
- `src/pipeline/registry_api/db.py` — add `events` table to `init_db`, add `insert_event()` and `get_events_after()` query functions
- `src/pipeline/registry_api/models.py` — add `EventRecord` Pydantic model for the event payload shape

**Dependencies:** None (first phase)

**Done when:** Events can be inserted and queried by sequence number. Tests cover insert, query with `after` parameter, query with `limit`, and empty result set.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: ConnectionManager and WebSocket endpoint

**Goal:** WebSocket broadcast infrastructure and the `/ws/events` endpoint.

**Components:**
- `src/pipeline/registry_api/events.py` — new file: `ConnectionManager` class with connect, disconnect, broadcast methods
- `src/pipeline/registry_api/main.py` — add WebSocket route `/ws/events` using the ConnectionManager

**Dependencies:** None (independent of Phase 1 at this stage — broadcast doesn't persist yet)

**Done when:** Multiple WebSocket clients can connect and receive broadcast messages. Tests cover connect, disconnect, broadcast to multiple clients, and dead connection cleanup.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Route integration

**Goal:** Wire event emission into POST and PATCH delivery routes. Persist event, then broadcast.

**Components:**
- `src/pipeline/registry_api/routes.py` — add pre-query detection and event emission to POST and PATCH handlers
- `src/pipeline/registry_api/db.py` — add `delivery_exists()` query function for the pre-query check

**Dependencies:** Phase 1 (event persistence), Phase 2 (ConnectionManager)

**Done when:** POSTing a new delivery creates a `delivery.created` event in the DB and broadcasts it. PATCHing a status change creates a `delivery.status_changed` event and broadcasts it. Re-crawls and non-status PATCHes produce no events. Tests cover all four scenarios.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: Catch-up REST endpoint

**Goal:** REST endpoint for consumers to retrieve missed events by sequence number.

**Components:**
- `src/pipeline/registry_api/routes.py` — add `GET /events` endpoint with `after` and `limit` query params

**Dependencies:** Phase 1 (event query functions)

**Done when:** Endpoint returns correct event subsets for various `after` values, respects `limit`, returns empty array when no events match. Tests cover normal retrieval, boundary cases, and limit enforcement.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Reference consumer

**Goal:** Production-ready reference consumer module with reconnect, catch-up, and deduplication.

**Components:**
- `src/pipeline/events/__init__.py` — new subpackage
- `src/pipeline/events/consumer.py` — `EventConsumer` class with WS connection, REST catch-up, reconnect loop, and seq-based deduplication
- `pyproject.toml` — add `websockets` to a new `consumer` optional dependency group

**Dependencies:** Phase 2 (WebSocket endpoint), Phase 4 (catch-up endpoint)

**Done when:** Consumer connects, catches up on missed events, receives real-time events, reconnects after disconnection, and deduplicates events seen via both REST and WS. Tests cover reconnect behaviour and deduplication logic.
<!-- END_PHASE_5 -->

## Additional Considerations

**Event retention:** Not in scope for this design. Healthcare delivery data arrives at low volume (periodic crawl runs, not continuous streams). The events table will grow slowly. When retention becomes necessary, a simple `DELETE FROM events WHERE created_at < datetime('now', '-90 days')` followed by `VACUUM` can be run as an operational task.

**Auth integration:** When the registry-auth design lands, the WebSocket endpoint will validate tokens during the handshake via query param. The catch-up REST endpoint will use the same bearer token mechanism as other API routes. The reference consumer will accept a `token` parameter. No architectural changes needed — auth slots into the existing connection and request paths.

**Multi-worker deployment:** The ConnectionManager is in-process memory. If the registry API ever needs multiple Uvicorn workers, broadcast would need a pub/sub backend (e.g., `encode/broadcaster` with PostgreSQL or Redis). The event persistence layer already handles this correctly — the `events` table is the source of truth regardless of how many workers exist. Only the real-time broadcast path would change.
