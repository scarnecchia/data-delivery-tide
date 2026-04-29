# GH21 Phase 4: WebSocket fakes for ConnectionManager tests

**Goal:** Replace every `AsyncMock()` instance that simulates a WebSocket connection in `tests/registry_api/test_events.py` and the single occurrence in `tests/registry_api/test_routes.py:TestWebSocketBroadcast` with a small `FakeWebSocket` class. The `TestWebSocketEndpoint` integration tests (real Starlette `client` fixture, real WebSocket connections) are left untouched per the design's "What is not changing" section.

**Architecture:** `ConnectionManager.broadcast` calls only `websocket.send_json(data)`; `ConnectionManager.connect` calls `websocket.accept()`. `FakeWebSocket` implements both as `async` methods that record calls and optionally raise — no `unittest.mock` machinery. Tests assert against `fake_ws.sent` (list of dicts) and `fake_ws.accepted` (bool) where they currently call `mock_ws.send_json.assert_called_once_with(...)` and `mock_ws.accept.assert_called_once()`.

**Tech Stack:** Python 3.10+, pytest, `pytest-asyncio`. No new dependencies.

**Scope:** 4 of 5 phases of GH21. Touches `tests/registry_api/test_events.py` and `tests/registry_api/test_routes.py` only. Independent of phases 1, 2, 3, 5.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH21.AC5: `tests/registry_api/test_routes.py`
- **GH21.AC5.1 Success:** `TestWebSocketBroadcast.test_ws_client_receives_delivery_created_event` uses a standalone fake `WebSocket` class instead of `AsyncMock()` for `mock_ws`
- **GH21.AC5.2 Success:** The fake `WebSocket` implements `send_json(data)` and records calls without `AsyncMock`

### GH21.AC6: `tests/registry_api/test_events.py`
- **GH21.AC6.1 Success:** `TestConnectionManager` tests use a standalone fake `WebSocket` class instead of `AsyncMock()` for each `mock_ws`
- **GH21.AC6.2 Success:** The fake records `send_json` calls and can be configured to raise on demand (for dead-connection tests)
- **GH21.AC6.3 Success:** `TestWebSocketEndpoint` integration tests (using the real `client` fixture) are untouched — they use real WebSocket connections

---

## Codebase verification findings

- ✓ `src/pipeline/registry_api/events.py:14-41` — `ConnectionManager` has `connect(websocket)` (calls `websocket.accept()`), `disconnect(websocket)` (no method calls — just `set.discard`), and `broadcast(event)` (calls `websocket.send_json(event)` and removes connections that raise).
- ✓ `tests/registry_api/test_events.py:4` — `from unittest.mock import AsyncMock` is the only mock import; used 12 times in `TestConnectionManager` tests at lines 18, 28, 38, 57, 58, 71, 72, 90, 91, 92, 118, 119, 136, 137, 157.
- ✓ `tests/registry_api/test_events.py:172-247` — `TestWebSocketEndpoint` uses the real `client` fixture (Starlette `TestClient`) and never instantiates `AsyncMock` directly. Per AC6.3 these tests are untouched.
- ✓ `tests/registry_api/test_routes.py:4` — `from unittest.mock import AsyncMock`. Single use at lines 739-740 within `TestWebSocketBroadcast.test_ws_client_receives_delivery_created_event`.
- ✓ `tests/registry_api/test_routes.py` "client.patch(...)" calls are HTTP-method calls on Starlette TestClient — not `unittest.mock.patch`. They stay.
- ✓ The design (line 14) explicitly carves out an exception: "The one `AsyncMock` usage in `test_routes.py` that simulates a WS client session (not testing `ConnectionManager` itself) is documented as acceptable and kept with a comment explaining why" — but the AC text at GH21.AC5.1 contradicts this and says it should be replaced. Resolution: follow the **AC** (replace it), since AC text is the authoritative specification per the design plan structure. The Definition of Done line is hedging language; the AC is the spec.

## External dependency findings

N/A — `typing.Protocol` is stdlib (used as a type hint reference, not at runtime). Tests don't depend on FastAPI/Starlette at the unit level.

---

<!-- START_TASK_1 -->
### Task 1: Define `FakeWebSocket` co-located in each test module

**Verifies:** GH21.AC5.2, GH21.AC6.2 (helper exists with required interface)

**Files:**
- Modify: `tests/registry_api/test_events.py` — add the helper near the top of the file, after imports, before `TestConnectionManager`.
- Modify: `tests/registry_api/test_routes.py` — add the same helper at the same position relative to its other class definitions, or import from `test_events.py` if both files agree.

**Implementation:**

The helper:

```python
class FakeWebSocket:
    """Minimal stand-in for a Starlette/FastAPI WebSocket.

    Implements only the subset of the protocol used by ConnectionManager:
    `accept()` and `send_json(data)`. Records all activity for assertion.

    Pass `fail_on_send=True` to make `send_json` raise — this models a dead
    connection that ConnectionManager.broadcast must remove from
    active_connections.
    """

    def __init__(self, *, fail_on_send: bool = False, send_exception: BaseException | None = None) -> None:
        self.accepted: bool = False
        self.sent: list[dict] = []
        self._fail_on_send = fail_on_send
        self._send_exception = send_exception or RuntimeError("Connection closed")

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        if self._fail_on_send:
            raise self._send_exception
        self.sent.append(data)
```

Co-location decision: define it once in each file rather than introducing `tests/fakes.py`. The class is ~20 lines; the design (Section "Shared fakes") says "If they drift toward 20+ lines or are needed by more than two test files, a `tests/fakes.py` module is the natural home." Two files = co-locate; one shared definition = duplication risk. Co-locate.

**Verification:**

Class instantiation should not fail:

```bash
uv run python -c "
import sys; sys.path.insert(0, 'tests/registry_api')
" || true
# direct verification deferred to Task 2 — once the FakeWebSocket is used by
# rewritten tests, pytest collection will fail loudly if the class has bugs.
```

**Commit:** deferred to Task 3.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Rewrite `TestConnectionManager` tests in `test_events.py` to use `FakeWebSocket`

**Verifies:** GH21.AC6.1, GH21.AC6.2

**Files:**
- Modify: `tests/registry_api/test_events.py:11-169` — every `TestConnectionManager` method.

**Implementation:**

The mapping is mechanical. Each test currently constructs `mock_ws = AsyncMock()` (or several), adds them to `manager.active_connections`, calls `manager.broadcast(...)`, and asserts via `mock_ws.send_json.assert_called_once_with(...)`. Each one becomes:

```python
fake_ws = FakeWebSocket()
manager.active_connections.add(fake_ws)
await manager.broadcast({"event": "test"})
assert fake_ws.sent == [{"event": "test"}]
```

`mock_ws.accept.assert_called_once()` becomes `assert fake_ws.accepted is True`.

For dead-connection tests (`test_broadcast_removes_dead_connection`, `test_broadcast_with_multiple_dead_connections`), construct `FakeWebSocket(fail_on_send=True)` instead of `mock_ws_dead.send_json.side_effect = RuntimeError(...)`:

```python
@pytest.mark.asyncio
async def test_broadcast_removes_dead_connection(self):
    """Test that broadcast() removes dead connections without crashing."""
    manager = ConnectionManager()
    fake_good = FakeWebSocket()
    fake_dead = FakeWebSocket(fail_on_send=True)
    manager.active_connections.add(fake_good)
    manager.active_connections.add(fake_dead)

    await manager.broadcast({"test": "data"})

    assert fake_dead not in manager.active_connections
    assert fake_good in manager.active_connections
    assert fake_good.sent == [{"test": "data"}]
```

The `Exception("Connection lost")` shape used in `test_broadcast_with_multiple_dead_connections` is the production code's catch-all — `ConnectionManager.broadcast` (`registry_api/events.py:36-37`) catches bare `Exception`, so the default `RuntimeError("Connection closed")` produced by `FakeWebSocket(fail_on_send=True)` is sufficient. If a test specifically wants `Exception(...)`, pass `send_exception=Exception("Connection lost")`.

`test_disconnect_*` tests don't call `send_json` or `accept`. They only need an object that hashes (Python class instances do by default). `FakeWebSocket()` works:

```python
def test_disconnect_removes_websocket_from_active_connections(self):
    manager = ConnectionManager()
    fake_ws = FakeWebSocket()
    manager.active_connections.add(fake_ws)

    manager.disconnect(fake_ws)

    assert fake_ws not in manager.active_connections
```

`test_connect_adds_websocket_to_active_connections` uses both `accept` and `add`:

```python
@pytest.mark.asyncio
async def test_connect_adds_websocket_to_active_connections(self):
    manager = ConnectionManager()
    fake_ws = FakeWebSocket()

    await manager.connect(fake_ws)

    assert fake_ws in manager.active_connections
    assert fake_ws.accepted is True
```

Apply this rewrite to all 12 `TestConnectionManager` methods. The class has no other state to migrate.

The import line `from unittest.mock import AsyncMock` (line 4) becomes deletable after this task — verify with grep before removal.

**Testing:**

Tests must verify each AC listed above:
- GH21.AC6.1: All 12 `TestConnectionManager` test methods use `FakeWebSocket` not `AsyncMock`.
- GH21.AC6.2: Dead-connection tests use `fail_on_send=True`.
- GH21.AC6.3: `TestWebSocketEndpoint` (lines 172-247) is unchanged — verify with `git diff tests/registry_api/test_events.py` after edits, expect no changes in that range.

**Verification:**

```bash
grep -n "AsyncMock\|unittest\.mock" tests/registry_api/test_events.py
```

Expected: zero matches.

```bash
uv run pytest tests/registry_api/test_events.py -v
```

Expected: same test count as before, all passing.

**Commit:** deferred to Task 3.
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Rewrite `TestWebSocketBroadcast.test_ws_client_receives_delivery_created_event` in `test_routes.py`, run tests, commit phase

**Verifies:** GH21.AC5.1, GH21.AC5.2

**Files:**
- Modify: `tests/registry_api/test_routes.py:4` — remove `from unittest.mock import AsyncMock`.
- Modify: `tests/registry_api/test_routes.py:726-777` — replace the single `AsyncMock` site.

**Implementation:**

Add `FakeWebSocket` to `test_routes.py` per Task 1's class definition (verbatim). Then rewrite the method:

```python
class TestWebSocketBroadcast:
    """Test WebSocket broadcast of events on POST /deliveries."""

    @pytest.mark.asyncio
    async def test_ws_client_receives_delivery_created_event(self, client, auth_headers):
        """AC1.2: POST /deliveries broadcasts delivery.created to connected WS client."""
        from pipeline.registry_api.events import manager

        received_events = []

        async def ws_client_session():
            """Simulate a WebSocket client connecting and waiting for events."""
            fake_ws = FakeWebSocket()
            manager.active_connections.add(fake_ws)

            try:
                # Wait for the HTTP request to complete and broadcast.
                await asyncio.sleep(0.1)

                if fake_ws.sent:
                    # Capture the first event the broadcast delivered.
                    received_events.append(fake_ws.sent[0])
            finally:
                manager.active_connections.discard(fake_ws)

        client_task = asyncio.create_task(ws_client_session())

        # Give the client time to "connect"
        await asyncio.sleep(0.05)

        payload = make_delivery_payload(source_path="/data/ws-broadcast-test")
        response = client.post("/deliveries", json=payload, headers=auth_headers)

        assert response.status_code == 200
        delivery_id = response.json()["delivery_id"]

        await client_task

        assert len(received_events) == 1
        event = received_events[0]
        assert event["event_type"] == "delivery.created"
        assert event["delivery_id"] == delivery_id
```

The shape changes: `mock_ws.send_json.called` → `fake_ws.sent` (truthy if non-empty); `mock_ws.send_json.call_args[0][0]` → `fake_ws.sent[0]`. Same semantics, no information lost.

**Testing:**

Tests must verify GH21.AC5.1 and GH21.AC5.2:
- The single `AsyncMock` site is replaced by `FakeWebSocket`.
- The fake records `send_json` calls without `AsyncMock` machinery.
- The test still passes — the timing-sensitive `asyncio.sleep(0.1)`/`asyncio.sleep(0.05)` structure is preserved verbatim, since the design (line 282-283) flags this as already unusual but acceptable.

**Verification:**

```bash
grep -n "unittest.mock\|AsyncMock" tests/registry_api/test_routes.py tests/registry_api/test_events.py
```

Expected: zero matches across both files.

```bash
uv run pytest tests/registry_api/test_events.py tests/registry_api/test_routes.py -v
```

Expected: all tests pass with same test count as before this phase.

**Commit:**

```bash
git add tests/registry_api/test_events.py tests/registry_api/test_routes.py
git commit -m "refactor(registry_api tests): replace AsyncMock WebSocket with FakeWebSocket (GH21 phase 4)"
```
<!-- END_TASK_3 -->

---

## Phase 4 Done When

- `FakeWebSocket` is defined in both `tests/registry_api/test_events.py` and `tests/registry_api/test_routes.py` (co-located per design).
- Every `AsyncMock()` for a WebSocket simulation in those two files is replaced by `FakeWebSocket(...)`.
- `TestWebSocketEndpoint` (the real Starlette `client`-based integration tests) is unchanged.
- Both test files have zero `unittest.mock` imports.
- `uv run pytest tests/registry_api/test_events.py tests/registry_api/test_routes.py` passes with the same test count as before this phase.

## Notes for executor

- **Phase ordering:** independent of phases 1, 2, 3, 5.
- **Conflict surface:** GH22 modifies error message strings in `routes.py` (test assertions on error messages may be in `test_routes.py`); GH27 prepends `# pattern: test file` to `test_events.py:1` (currently the line is a docstring `"""Tests for EventConsumer.\n` — the prepend goes above the docstring). Neither overlaps with the WS-fake region.
- **Design tension:** the design's Definition of Done says "AsyncMock usage in `test_routes.py` that simulates a WS client session ... is documented as acceptable and kept", but GH21.AC5.1 says "uses a standalone fake `WebSocket` class instead of `AsyncMock()`". This phase follows the AC (replace it) and the resolution is documented in the codebase verification findings above. If reviewer prefers retention with a justifying comment, revert Task 3's substantive changes and keep only the comment + import removal — but that would also fail AC5.1, so the AC takes precedence.
