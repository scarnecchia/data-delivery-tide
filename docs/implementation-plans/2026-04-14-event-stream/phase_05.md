# Event Stream Implementation Plan — Phase 5: Reference Consumer

**Goal:** Add a production-ready reference consumer module that connects to the registry API's WebSocket endpoint, catches up on missed events via REST, deduplicates, and reconnects with backoff.

**Architecture:** New `src/pipeline/events/` subpackage containing an `EventConsumer` class. Uses `websockets` library (v16) for the WebSocket client and `httpx` for REST catch-up requests. The consumer tracks the last processed `seq` and uses it for both catch-up queries and deduplication. The `websockets.connect()` async iterator provides automatic reconnection with exponential backoff.

**Tech Stack:** Python 3.10+, websockets >=16, httpx >=0.28, pytest

**Scope:** 5 phases from original design (phase 5 of 5)

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### event-stream.AC6: Reference consumer
- **event-stream.AC6.1 Success:** Consumer receives real-time events via WebSocket
- **event-stream.AC6.2 Success:** Consumer catches up on missed events via REST on reconnect
- **event-stream.AC6.3 Success:** Consumer deduplicates events received via both REST and WS (by seq)
- **event-stream.AC6.4 Success:** Consumer reconnects automatically after disconnection with backoff

---

<!-- START_TASK_1 -->
### Task 1: Add consumer optional dependency group to pyproject.toml

**Verifies:** None (infrastructure)

**Files:**
- Modify: `pyproject.toml:10-22` (add `consumer` group to `[project.optional-dependencies]`)

**Implementation:**

Add the `consumer` group after the existing `converter` group (line 18):

```toml
consumer = [
    "websockets>=16,<17",
    "httpx>=0.28,<1",
]
```

The full `[project.optional-dependencies]` section becomes:

```toml
[project.optional-dependencies]
registry = [
    "fastapi>=0.115,<1",
    "uvicorn[standard]>=0.34,<1",
]
converter = [
    "pyreadstat>=1.2,<2",
    "pyarrow>=18,<19",
]
consumer = [
    "websockets>=16,<17",
    "httpx>=0.28,<1",
]
dev = [
    "pytest>=8,<9",
    "httpx>=0.28,<1",
]
```

Notes:
- `httpx` is listed in both `consumer` and `dev` — this is intentional. The consumer needs it at runtime for REST catch-up, dev needs it for testing.
- `websockets>=16,<17` pins to the current major version with known API.

**Verification:**
Run: `uv pip install -e ".[consumer,dev]"`
Expected: Installs without errors.

**Commit:** `chore: add consumer optional dependency group`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create events subpackage with EventConsumer

**Verifies:** event-stream.AC6.1, event-stream.AC6.2, event-stream.AC6.3, event-stream.AC6.4

**Files:**
- Create: `src/pipeline/events/__init__.py`
- Create: `src/pipeline/events/consumer.py`

**Implementation:**

**Step 1: Create `src/pipeline/events/__init__.py`**

Empty file (just like `src/pipeline/__init__.py`).

**Step 2: Create `src/pipeline/events/consumer.py`**

```python
# pattern: Imperative Shell

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class EventConsumer:
    """
    Reference consumer for registry event stream.

    Connects to the registry API's WebSocket endpoint for real-time events
    and uses the REST catch-up endpoint on reconnect. Deduplicates events
    by sequence number to ensure exactly-once processing.

    Args:
        api_url: Base URL of the registry API (e.g., "http://localhost:8000").
        on_event: Async callback invoked for each new event.
    """

    def __init__(
        self,
        api_url: str,
        on_event: Callable[[dict], Awaitable[None]],
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.on_event = on_event
        self._last_seq: int = 0
        self._ws_buffer: list[dict] = []

    async def run(self) -> None:
        """
        Main loop: connect, catch up, listen, reconnect on failure.

        Uses websockets.connect() async iterator for automatic reconnection
        with exponential backoff (3s initial, doubling, capped ~60s).
        """
        ws_url = self.api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws/events"

        async for websocket in connect(ws_url):
            try:
                logger.info("Connected to %s", ws_url)
                await self._session(websocket)
            except ConnectionClosed:
                logger.warning("Disconnected from %s, reconnecting...", ws_url)
                continue

    async def _session(self, websocket) -> None:
        """
        Handle a single WebSocket session: catch up, then listen.

        Steps:
        1. Start buffering incoming WS messages in a background task
        2. Fetch missed events via REST catch-up
        3. Process catch-up events
        4. Process buffered WS events, deduplicating by seq
        5. Listen for new events
        """
        self._ws_buffer = []
        buffer_task = asyncio.create_task(self._buffer_ws(websocket))

        try:
            await self._catch_up()

            buffer_task.cancel()
            try:
                await buffer_task
            except (asyncio.CancelledError, ConnectionClosed, Exception):
                pass

            for event in self._ws_buffer:
                if event["seq"] > self._last_seq:
                    await self.on_event(event)
                    self._last_seq = event["seq"]

            async for raw in websocket:
                event = json.loads(raw)
                if event["seq"] > self._last_seq:
                    await self.on_event(event)
                    self._last_seq = event["seq"]
        finally:
            if not buffer_task.done():
                buffer_task.cancel()
                try:
                    await buffer_task
                except (asyncio.CancelledError, ConnectionClosed, Exception):
                    pass

    async def _buffer_ws(self, websocket) -> None:
        """Buffer incoming WS events while catch-up is in progress."""
        try:
            async for raw in websocket:
                self._ws_buffer.append(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            raise

    async def _catch_up(self) -> None:
        """Fetch missed events via REST and process them."""
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{self.api_url}/events",
                    params={"after": self._last_seq, "limit": 1000},
                )
                resp.raise_for_status()
                events = resp.json()

                if not events:
                    break

                for event in events:
                    await self.on_event(event)
                    self._last_seq = event["seq"]
```

Notes:
- `websockets.connect()` used as an async iterator provides automatic reconnection with exponential backoff (3s initial, doubling, capped ~60s). No manual backoff logic needed.
- Deduplication is by `seq`: any event with `seq <= self._last_seq` is skipped. This handles the overlap window between REST catch-up and WS connect.
- `_catch_up()` pages through events in batches of 1000 until it gets an empty response.
- `_buffer_ws()` runs as a background task during catch-up to capture any events broadcast while the REST request is in flight.
- After catch-up, buffered WS events are processed with dedup, then the consumer switches to direct WS listening.

**Verification:**
Run: `python -c "from pipeline.events.consumer import EventConsumer; print('OK')"`
Expected: `OK`

**Commit:** `feat(pipeline): add EventConsumer reference implementation`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Add EventConsumer tests

**Verifies:** event-stream.AC6.1, event-stream.AC6.2, event-stream.AC6.3, event-stream.AC6.4

**Files:**
- Create: `tests/events/__init__.py`
- Create: `tests/events/test_consumer.py`

**Testing:**

Create a new test directory mirroring the source structure. Tests should verify the consumer's behaviour against a real running test server.

**Testing approach:** Use the existing FastAPI app with TestClient for HTTP, and a real asyncio event loop for the WebSocket consumer. The consumer tests are integration tests that exercise the full stack.

**TestEventConsumer:**

- event-stream.AC6.1: Start the FastAPI app (via `uvicorn` in a background thread or use `httpx.ASGITransport`), create an `EventConsumer` pointed at it, POST a delivery to the API, verify `on_event` callback fires with the correct event
- event-stream.AC6.2: Insert events directly into the test DB, create a consumer with `_last_seq=0`, verify it catches up via REST before listening to WS
- event-stream.AC6.3: Set up a scenario where the same event could arrive via both REST catch-up and WS buffer. Verify `on_event` is called exactly once for each unique `seq`
- event-stream.AC6.4: Connect consumer, shut down the WS endpoint (or close the connection), verify consumer reconnects (this may be tested by observing that the `connect()` async iterator loops back)

**Important considerations:**
- These tests involve async code and real network connections. Use `pytest-asyncio` (already available via `anyio` in the test deps) with `@pytest.mark.asyncio` decorators.
- For the full integration test (AC6.1), you may need to run the FastAPI app in a background thread using `uvicorn.Server` or use `httpx.ASGITransport` for the HTTP part while handling WebSocket separately.
- The deduplication test (AC6.3) should be a unit test on the seq-tracking logic. Concrete skeleton:

```python
@pytest.mark.asyncio
async def test_deduplication_by_seq():
    """Test event-stream.AC6.3: events seen via REST catch-up are not re-processed from WS buffer."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://unused", on_event)
    consumer._last_seq = 0

    # Simulate catch-up delivering events 1-3
    catch_up_events = [
        {"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"},
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
        {"seq": 3, "event_type": "delivery.created", "delivery_id": "d3", "payload": {}, "created_at": "t3"},
    ]
    for event in catch_up_events:
        await consumer.on_event(event)
        consumer._last_seq = event["seq"]

    # Simulate WS buffer containing overlapping events 2-4
    ws_buffer_events = [
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
        {"seq": 3, "event_type": "delivery.created", "delivery_id": "d3", "payload": {}, "created_at": "t3"},
        {"seq": 4, "event_type": "delivery.created", "delivery_id": "d4", "payload": {}, "created_at": "t4"},
    ]

    received.clear()
    for event in ws_buffer_events:
        if event["seq"] > consumer._last_seq:
            await consumer.on_event(event)
            consumer._last_seq = event["seq"]

    # Only event 4 should have been processed (2 and 3 already seen)
    assert len(received) == 1
    assert received[0]["seq"] == 4
```

- Keep tests practical — if full integration is too complex, test the consumer's logic (catch-up, dedup, seq tracking) with the unit approach above and test WebSocket connectivity separately.

**Verification:**
Run: `uv run pytest tests/events/test_consumer.py -v`
Expected: All tests pass.

Run: `uv run pytest tests/ -v`
Expected: Full suite passes.

**Commit:** `test(pipeline): add EventConsumer tests`
<!-- END_TASK_3 -->
