# Phase 3: consumer.py exception clause narrowing (Category C)

**Goal:** Replace the broad `except (CancelledError, ConnectionClosed, Exception): pass` clauses in `events/consumer.py` with split handling: silent for expected transients, DEBUG-logged for anything else.

**Architecture:** Two `try/except` clauses around a cancelled `buffer_task` await. The current code lumps expected (`CancelledError`, `ConnectionClosed`) and unexpected (`Exception`) into one handler. We split them so unexpected exceptions are logged at DEBUG with `exc_info=True`. `_buffer_ws` is unchanged — it already explicitly re-raises `CancelledError` and `ConnectionClosed`.

**Tech Stack:** stdlib `logging`, `asyncio`, `websockets.exceptions.ConnectionClosed`.

**Scope:** 3 of 5 phases (issue #23, slug `GH23`).

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH23.AC3: consumer.py narrows exception clauses
- **GH23.AC3.1 Success:** After buffer_task.cancel(), `CancelledError` and `ConnectionClosed` are caught and suppressed silently (expected transient).
- **GH23.AC3.2 Success:** Any other exception (bare `Exception`) from buffer_task is logged at DEBUG with `exc_info=True` before being suppressed.
- **GH23.AC3.3 Success:** The `finally` block in `_session` applies the same split: silent for `CancelledError`/`ConnectionClosed`, logged DEBUG for other exceptions.
- **GH23.AC3.4 Edge:** `_buffer_ws` continues to explicitly re-raise `CancelledError` and `ConnectionClosed` unchanged.

### GH23.AC6 (partial): Test coverage for logged exceptions
- **GH23.AC6.3 Success:** Tests for consumer.py verify that unexpected exceptions from buffer_task are logged at DEBUG; verify CancelledError and ConnectionClosed are not logged.

---

## Codebase verification findings

- ✓ `src/pipeline/events/consumer.py` line 12: `logger = logging.getLogger(__name__)` already exists.
- ✓ Lines 73–77: `buffer_task.cancel()` followed by `try: await buffer_task; except (asyncio.CancelledError, ConnectionClosed, Exception): pass`.
- ✓ Lines 89–95: identical pattern inside the `finally` block of `_session`.
- ✓ Lines 97–105: `_buffer_ws` already does `except asyncio.CancelledError: raise` and `except ConnectionClosed: raise` — design says to leave this untouched. Confirmed: no change needed.
- ✓ Test file `tests/events/test_consumer.py` exists.

**No external dependency research needed.** `asyncio.CancelledError` and `websockets.exceptions.ConnectionClosed` are already imported.

---

<!-- START_TASK_1 -->
### Task 1: Split the broad except clauses in consumer.py _session

**Verifies:** GH23.AC3.1, GH23.AC3.2, GH23.AC3.3, GH23.AC3.4

**Files:**
- Modify: `src/pipeline/events/consumer.py` (lines 73–77 and 89–95)
- Test: `tests/events/test_consumer.py` (add narrowing tests)

**Implementation:**

1. Modify the first clause at lines 73–77. Current code:

```python
            buffer_task.cancel()
            try:
                await buffer_task
            except (asyncio.CancelledError, ConnectionClosed, Exception):
                pass
```

Replace with:

```python
            buffer_task.cancel()
            try:
                await buffer_task
            except (asyncio.CancelledError, ConnectionClosed):
                pass
            except Exception:
                logger.debug("buffer task raised unexpected exception", exc_info=True)
```

2. Modify the second clause inside the `finally` block at lines 89–95. Current code:

```python
        finally:
            if not buffer_task.done():
                buffer_task.cancel()
                try:
                    await buffer_task
                except (asyncio.CancelledError, ConnectionClosed, Exception):
                    pass
```

Replace with:

```python
        finally:
            if not buffer_task.done():
                buffer_task.cancel()
                try:
                    await buffer_task
                except (asyncio.CancelledError, ConnectionClosed):
                    pass
                except Exception:
                    logger.debug("buffer task raised unexpected exception", exc_info=True)
```

3. Do NOT modify `_buffer_ws` (lines 97–105). Its explicit `raise` for `CancelledError` and `ConnectionClosed` is the intended pattern (AC3.4) and the source of the exceptions the `_session` handlers must distinguish.

**Testing:**

Add tests in `tests/events/test_consumer.py`. Use `caplog.set_level(logging.DEBUG, logger="pipeline.events.consumer")`. Tests must verify each AC:

- **GH23.AC3.1:** Drive `_session` so the buffer_task ends with `asyncio.CancelledError` (the natural outcome of `buffer_task.cancel()` when the task is sleeping/iterating). Assert no DEBUG record from `pipeline.events.consumer` is emitted.
- **GH23.AC3.1:** Same setup but the buffer_task raises `ConnectionClosed` (e.g., a fake websocket whose `__aiter__` raises). Assert no DEBUG record.
- **GH23.AC3.2:** Make `_buffer_ws` raise `RuntimeError("boom")` inside the inner loop (e.g., feed it a fake websocket whose iteration yields data that breaks `json.loads`, or monkeypatch `json.loads` to raise). After `_session` processes catch-up, assert one DEBUG record with message `"buffer task raised unexpected exception"` and `record.exc_info[0] is RuntimeError`.
- **GH23.AC3.3:** Drive the `finally` path (e.g., make `await self._catch_up()` raise so control exits the outer `try` while `buffer_task` is still in flight). Repeat the three sub-cases above against this path.
- **GH23.AC3.4:** Confirm `_buffer_ws` still raises `CancelledError`/`ConnectionClosed` to its caller (assert the test's outer await observes the propagation, e.g., via `pytest.raises` on a directly-driven `_buffer_ws` task).

A shared fake websocket helper (async iterator yielding controllable values or raising controllable exceptions) keeps these tests compact. Existing `test_consumer.py` already drives `EventConsumer` with stubbed transport — reuse those fixtures.

**Verification:**

Run: `uv run pytest tests/events/test_consumer.py -v`
Expected: all tests pass.

**Commit:** `refactor(events): narrow consumer.py except clauses; log unexpected buffer task errors`
<!-- END_TASK_1 -->

---

## Done when

- Task 1 committed.
- `uv run pytest` passes.
- AC3.1–AC3.4 and AC6.3 verified.
