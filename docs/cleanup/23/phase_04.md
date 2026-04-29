# Phase 4: registry_api/events.py broadcast DEBUG logging (Category E)

**Goal:** Log the `send_json` exception at DEBUG before collecting the dead connection, so failed-send details are available for diagnosis. The existing WARNING about "Removed dead WebSocket connection during broadcast" is preserved.

**Architecture:** Single mechanical edit inside `ConnectionManager.broadcast`'s `except Exception:` block. Logger already exists at module level.

**Tech Stack:** stdlib `logging`, FastAPI `WebSocket`.

**Scope:** 4 of 5 phases (issue #23, slug `GH23`).

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH23.AC4: registry_api/events.py logs dead connection exceptions
- **GH23.AC4.1 Success:** When `connection.send_json` raises, the exception is logged at DEBUG with `exc_info=True` before the connection is added to the dead list.
- **GH23.AC4.2 Success:** The existing warning log `"Removed dead WebSocket connection during broadcast"` is retained.
- **GH23.AC4.3 Edge:** The exception type is visible in structured log output (not just the "Removed dead…" message).

### GH23.AC6 (partial): Test coverage for logged exceptions
- **GH23.AC6.4 Success:** Tests for events.py broadcast verify DEBUG log emitted when send_json raises; verify dead connection is still collected.

---

## Codebase verification findings

- ✓ `src/pipeline/registry_api/events.py` line 7: `logger = logging.getLogger(__name__)` already exists.
- ✓ Lines 33–37 contain the broadcast loop: `try: await connection.send_json(event); except Exception: dead.append(connection)`.
- ✓ Lines 39–41 contain the existing `logger.warning("Removed dead WebSocket connection during broadcast")` — must remain.
- ✓ Test file `tests/registry_api/test_events.py` exists.

**No external dependency research needed.**

---

<!-- START_TASK_1 -->
### Task 1: Add DEBUG log for failed send_json before dead-list append

**Verifies:** GH23.AC4.1, GH23.AC4.2, GH23.AC4.3

**Files:**
- Modify: `src/pipeline/registry_api/events.py` (lines 33–37)
- Test: `tests/registry_api/test_events.py` (add log assertions)

**Implementation:**

Modify the inner loop. Current code (lines 32–41):

```python
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(event)
            except Exception:
                dead.append(connection)

        for connection in dead:
            self.active_connections.discard(connection)
            logger.warning("Removed dead WebSocket connection during broadcast")
```

Replace with:

```python
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(event)
            except Exception:
                logger.debug(
                    "WebSocket send failed, marking connection dead",
                    exc_info=True,
                )
                dead.append(connection)

        for connection in dead:
            self.active_connections.discard(connection)
            logger.warning("Removed dead WebSocket connection during broadcast")
```

The DEBUG call is placed BEFORE `dead.append(connection)` (per design AC4.1). The existing WARNING is left intact.

**Testing:**

Add or extend a test in `tests/registry_api/test_events.py`. Use `caplog.set_level(logging.DEBUG, logger="pipeline.registry_api.events")`.

- **GH23.AC4.1, AC4.3:** Construct a `ConnectionManager` with one fake `WebSocket` whose `send_json` is an `AsyncMock` configured to raise `RuntimeError("boom")`. Call `await manager.broadcast({"seq": 1})`. Assert a DEBUG record with message `"WebSocket send failed, marking connection dead"` exists with `record.exc_info[0] is RuntimeError`.
- **GH23.AC4.2:** Same scenario — assert the existing WARNING `"Removed dead WebSocket connection during broadcast"` is also captured.
- **GH23.AC6.4:** Same scenario — assert the failing connection is removed from `manager.active_connections`.

A working-connection control case (one fake websocket whose `send_json` succeeds) confirms no DEBUG/WARNING records on the happy path.

**Verification:**

Run: `uv run pytest tests/registry_api/test_events.py -v`
Expected: all tests pass.

**Commit:** `feat(registry-api): log failed WebSocket sends at DEBUG before marking dead`
<!-- END_TASK_1 -->

---

## Done when

- Task 1 committed.
- `uv run pytest` passes.
- AC4.1, AC4.2, AC4.3, AC6.4 verified.
