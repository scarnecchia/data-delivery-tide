# Event Stream Implementation Plan — Phase 2: ConnectionManager and WebSocket Endpoint

**Goal:** Add WebSocket broadcast infrastructure and a `/ws/events` endpoint so clients can connect and receive real-time event broadcasts.

**Architecture:** A `ConnectionManager` singleton in a new `events.py` module manages active WebSocket connections and fans out broadcasts. The `/ws/events` WebSocket route is added directly to the FastAPI app in `main.py` (not to the API router, since WebSocket endpoints have different lifecycle semantics).

**Tech Stack:** Python 3.10+, FastAPI (built-in WebSocket support), pytest + TestClient

**Scope:** 5 phases from original design (phase 2 of 5)

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### event-stream.AC3: Multiple concurrent consumers
- **event-stream.AC3.1 Success:** Two connected WS clients both receive the same broadcast event
- **event-stream.AC3.2 Success:** Client disconnect does not affect other connected clients
- **event-stream.AC3.3 Success:** Dead connection (network drop) is cleaned up without crashing broadcast loop

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Create ConnectionManager in events.py

**Verifies:** None (infrastructure — validated by tests in Task 3)

**Files:**
- Create: `src/pipeline/registry_api/events.py`

**Implementation:**

Create a new file `src/pipeline/registry_api/events.py` with `# pattern: Imperative Shell` annotation. The `ConnectionManager` holds active WebSocket connections in a set and broadcasts JSON to all of them. Failed sends are caught per-connection — a dead connection is removed without affecting others.

```python
# pattern: Imperative Shell

import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and add it to the active set."""
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active set."""
        self.active_connections.discard(websocket)

    async def broadcast(self, event: dict) -> None:
        """
        Send event as JSON to all active connections.

        Failed sends are caught per-connection. Dead connections are
        removed silently — the consumer's reconnect loop handles recovery.
        """
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(event)
            except Exception:
                dead.append(connection)

        for connection in dead:
            self.active_connections.discard(connection)
            logger.warning("Removed dead WebSocket connection during broadcast")


manager = ConnectionManager()
```

Notes:
- Uses a `set` not a `list` — O(1) add/discard, and connection identity matters (not order).
- `broadcast()` collects dead connections in a separate list to avoid mutating the set during iteration.
- Module-level `manager` singleton follows the same pattern as `app` in `main.py`.
- No auth — deferred until registry-auth lands (per design).

**Verification:**
Run: `python -c "from pipeline.registry_api.events import manager; print(type(manager))"`
Expected: `<class 'pipeline.registry_api.events.ConnectionManager'>`

**Commit:** `feat(registry): add ConnectionManager for WebSocket broadcast`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add /ws/events WebSocket endpoint to main.py

**Verifies:** None (endpoint wiring — validated by tests in Task 3)

**Files:**
- Modify: `src/pipeline/registry_api/main.py:2` (add imports)
- Modify: `src/pipeline/registry_api/main.py:24` (add WebSocket route after router inclusion)

**Implementation:**

**Step 1: Add imports**

At the top of `main.py`, add the WebSocket and WebSocketDisconnect imports, plus the manager import:

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from pipeline.registry_api.events import manager
```

The full import section becomes:

```python
# pattern: Imperative Shell
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from pipeline.config import settings
from pipeline.registry_api.db import init_db
from pipeline.registry_api.events import manager
from pipeline.registry_api.routes import router
```

**Step 2: Add WebSocket route**

After `app.include_router(router)` (line 24), add the WebSocket endpoint:

```python
@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    One-way broadcast channel for delivery lifecycle events.

    Clients connect and receive JSON event broadcasts. The receive loop
    exists only to detect disconnection — clients don't send messages.
    """
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    finally:
        manager.disconnect(websocket)
```

Notes:
- The `receive_text()` loop blocks until the client disconnects. This is the standard FastAPI pattern for one-way broadcast endpoints — without this loop, the connection would close immediately.
- `finally` ensures `disconnect()` runs regardless of how the connection ends — normal close, abnormal close, or unexpected exception. This prevents stale entries in `active_connections`.
- The endpoint is on `app` directly (not on `router`) because WebSocket lifecycle is tied to the application, not the API router. This is consistent with FastAPI's recommendation.
- No auth — the design explicitly defers this until registry-auth lands.

**Verification:**
Run: `uv run pytest tests/ -v`
Expected: All existing tests still pass (no regressions from new imports).

**Commit:** `feat(registry): add /ws/events WebSocket endpoint`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3) -->
<!-- START_TASK_3 -->
### Task 3: Add ConnectionManager and WebSocket endpoint tests

**Verifies:** event-stream.AC3.1, event-stream.AC3.2, event-stream.AC3.3

**Files:**
- Create: `tests/registry_api/test_events.py`

**Testing:**

Create a new test file following the project's class-based test pattern. Use `TestClient.websocket_connect()` context manager for WebSocket tests.

**Important testing context:**
- `TestClient.websocket_connect("/ws/events")` returns a context manager
- `websocket.receive_json()` blocks until a message is received
- Exiting the `with` block triggers `WebSocketDisconnect` on the server side
- For multi-client broadcast tests, use threading since TestClient is synchronous

**TestConnectionManager** (unit tests on the class directly):
- `connect()` adds a websocket to `active_connections`
- `disconnect()` removes a websocket from `active_connections`
- `disconnect()` with an unknown websocket does not raise (discard semantics)
- `broadcast()` with no connections does not raise

**TestWebSocketEndpoint** (integration tests via TestClient):
- event-stream.AC3.1: Connect two clients (use threading), broadcast a message from a helper that calls `manager.broadcast()`, verify both clients receive it
- event-stream.AC3.2: Connect two clients, disconnect one (exit its `with` block), verify the other client still receives broadcasts
- event-stream.AC3.3: Test that `broadcast()` handles a dead/closed connection without crashing — connect a client, close it abnormally, then call broadcast and verify no exception propagates

For the ConnectionManager unit tests, you can use `AsyncMock` from `unittest.mock` to create mock WebSocket objects, or test via the integration route. Follow whichever approach produces clearer, more maintainable tests.

For multi-client integration tests, the pattern is:

```python
import threading

def test_broadcast_to_multiple_clients(self, client):
    """Test event-stream.AC3.1: both clients receive broadcast."""
    results = []

    def listen(ws_client, result_list):
        with ws_client.websocket_connect("/ws/events") as ws:
            data = ws.receive_json()
            result_list.append(data)

    t1_results, t2_results = [], []
    t1 = threading.Thread(target=listen, args=(client, t1_results))
    t2 = threading.Thread(target=listen, args=(client, t2_results))
    t1.start()
    t2.start()

    # Wait for both threads to establish connections before broadcasting.
    # Prefer polling manager.active_connections count over time.sleep:
    import asyncio
    for _ in range(50):  # up to 0.5s
        if len(manager.active_connections) >= 2:
            break
        import time; time.sleep(0.01)
    asyncio.run(manager.broadcast({"test": "data"}))

    t1.join(timeout=2)
    t2.join(timeout=2)

    assert t1_results == [{"test": "data"}]
    assert t2_results == [{"test": "data"}]
```

Note: The example uses polling on `manager.active_connections` count instead of `time.sleep()` to avoid flakiness. The exact threading approach may need adjustment based on how TestClient handles concurrent WebSocket connections. The task-implementor should verify the pattern works and adjust if needed.

**Verification:**
Run: `uv run pytest tests/registry_api/test_events.py -v`
Expected: All tests pass.

Run: `uv run pytest tests/ -v`
Expected: All 175+ tests pass (no regressions).

**Commit:** `test(registry): add ConnectionManager and WebSocket endpoint tests`
<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_B -->
