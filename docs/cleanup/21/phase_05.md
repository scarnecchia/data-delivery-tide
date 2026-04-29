# GH21 Phase 5: EventConsumer http_client_factory injection

**Goal:** Replace the five `patch("pipeline.events.consumer.httpx.AsyncClient", ...)` blocks in `tests/events/test_consumer.py` (lines 80, 125, 159, 195, 232) with an `http_client_factory` keyword parameter on `EventConsumer._catch_up`. The five `_catch_up` tests inject a factory returning the existing manually-constructed `mock_client`. The two `patch.object(consumer, ...)` usages in `test_session_receives_ws_events` and `test_reconnection_after_disconnect` (lines 286-287, 337) and the `patch("pipeline.events.consumer.connect")` at line 335 are out of scope per the design's Phase 5 footer (line 307-309).

**Architecture:** `_catch_up` accepts a keyword-only `http_client_factory` defaulting to `httpx.AsyncClient`. Production calls leave it at the default; tests pass `lambda: mock_client` where `mock_client` is the existing manually-constructed object with `__aenter__`, `__aexit__`, and `get`. No source change to `_session` or `run`. No source change to the WebSocket handling path. The remaining `patch.object` usages are explicitly endorsed by the design as targeting instance methods rather than module symbols (acceptable scope).

**Tech Stack:** Python 3.10+, `httpx` (already a dependency for the consumer), pytest, `pytest-asyncio`. No new dependencies.

**Scope:** 5 of 5 phases of GH21. Touches `src/pipeline/events/consumer.py` and `tests/events/test_consumer.py` only. Independent of phases 1, 2, 3, 4.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH21.AC7: `tests/events/test_consumer.py`
- **GH21.AC7.1 Success:** All eleven tests pass without `patch("pipeline.events.consumer.httpx.AsyncClient", ...)`
- **GH21.AC7.2 Success:** `EventConsumer._catch_up` accepts an `http_client_factory` parameter (default `httpx.AsyncClient`) that tests inject with a factory returning a fake async context manager
- **GH21.AC7.3 Success:** `test_session_receives_ws_events` and `test_reconnection_after_disconnect` use `patch.object` on the consumer instance (not on a module import) — these are acceptable as they test integration between `_session` and its sub-methods on the same object; they do not patch external module symbols

---

## Codebase verification findings

- ✓ `src/pipeline/events/consumer.py:107-123` — `async def _catch_up(self) -> None`. Constructs `httpx.AsyncClient` directly at line 109. Uses it as an `async with` context manager and calls `.get(...)` returning a response with `.raise_for_status()` and `.json()`.
- ✓ `tests/events/test_consumer.py:8` — `from unittest.mock import AsyncMock, patch, MagicMock` (note: `MagicMock` is imported but **never used** in this file — verify with grep before removing).
- ✓ `tests/events/test_consumer.py:80, 125, 159, 195, 232` — five `with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):` blocks, all in `_catch_up` tests.
- ✓ `tests/events/test_consumer.py:286-287, 337` — `with patch.object(consumer, "_buffer_ws", ...)` / `patch.object(consumer, "_catch_up", ...)` / `patch.object(consumer, "_session", ...)`. Out of scope per design line 307: "they are testing integration between `_session` and its internal sub-methods on the same object; the consumer is the unit, and the patch.object calls isolate specific internal paths".
- ✓ `tests/events/test_consumer.py:335` — `with patch("pipeline.events.consumer.connect") as mock_connect`. Out of scope per design line 309: "Phase 5 targets only the `httpx.AsyncClient` injection."
- ✓ `mock_client` shape across all five `_catch_up` tests is consistent: `mock_client = AsyncMock(); mock_client.get = mock_get; mock_client.__aenter__ = AsyncMock(return_value=mock_client); mock_client.__aexit__ = AsyncMock(return_value=None)`. The factory `lambda: mock_client` produces a fresh callable returning this same object on each `_catch_up` call.
- ✓ `httpx.AsyncClient()` accepts no positional arguments in the production call (`async with httpx.AsyncClient() as client`). The factory signature is `() -> AsyncClient` — `lambda: mock_client` matches.

## External dependency findings

- ✓ `httpx.AsyncClient` API (verified against the package's documented contract): instances are async context managers (`__aenter__`/`__aexit__`) yielding the same client, with `.get(url, params=...)` returning `httpx.Response` with `.raise_for_status()` (raises on 4xx/5xx) and `.json()` (synchronous, returns parsed JSON). The fake `mock_client` already implements all of these.
- ✓ The factory pattern (zero-arg callable returning a usable context manager) is a stable idiom — even if `httpx.AsyncClient` later requires arguments (e.g., `timeout=...`), production code constructing it at the call site can adopt that change without breaking the factory contract.
- 📖 Source: httpx documentation (https://www.python-httpx.org/async/), confirmed against the codebase's actual usage at `consumer.py:109-114`.

---

<!-- START_TASK_1 -->
### Task 1: Add `http_client_factory` keyword parameter to `EventConsumer._catch_up`

**Verifies:** GH21.AC7.2

**Files:**
- Modify: `src/pipeline/events/consumer.py:107-123` — change signature of `_catch_up`, replace `httpx.AsyncClient()` call.

**Implementation:**

```python
async def _catch_up(self, *, http_client_factory=httpx.AsyncClient) -> None:
    """Fetch missed events via REST and process them.

    `http_client_factory` is a zero-argument callable returning an async
    context manager that yields an httpx-compatible client. Production
    callers leave it at the default; tests inject fakes.
    """
    async with http_client_factory() as client:
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

The two changes versus the current source: `async def _catch_up(self) -> None:` gains the `*, http_client_factory=httpx.AsyncClient` keyword-only argument; `httpx.AsyncClient()` becomes `http_client_factory()`.

The default is `httpx.AsyncClient` (the **class**, not an instance), so calling `http_client_factory()` constructs a fresh client per `_catch_up` invocation, identical to current behaviour. Tests pass `lambda: mock_client` instead, returning the same pre-built `mock_client` on each call.

**Why no parameter on `__init__` or `run()`:** The design (line 309) explicitly limits Phase 5 to `httpx.AsyncClient` injection at the `_catch_up` seam. Adding `http_client_factory` to `__init__` would also work but expands surface area beyond what tests need; defer that until a real consumer (converter daemon) needs to swap clients globally.

**Verification:**

```bash
uv run python -c "
import inspect
import httpx
from pipeline.events.consumer import EventConsumer
sig = inspect.signature(EventConsumer._catch_up)
p = sig.parameters['http_client_factory']
assert p.kind is inspect.Parameter.KEYWORD_ONLY
assert p.default is httpx.AsyncClient
print('OK')
"
```

Expected: `OK`.

**Commit:** deferred to Task 2.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Replace the five `patch("...httpx.AsyncClient", ...)` blocks with factory injection, prune unused imports, run tests, commit phase

**Verifies:** GH21.AC7.1, GH21.AC7.3 (verifies AC7.3 by leaving the two `patch.object` sites untouched and the `patch("...connect")` site untouched)

**Files:**
- Modify: `tests/events/test_consumer.py:8` — narrow the `unittest.mock` import to only what remains in use.
- Modify: `tests/events/test_consumer.py` — five `_catch_up` test bodies (functions ending around lines 86, 129, 162, 199, 238).

**Implementation:**

The mapping is mechanical — each block of:

```python
with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):
    await consumer._catch_up()
```

becomes:

```python
await consumer._catch_up(http_client_factory=lambda: mock_client)
```

Five tests need this change:

| Test | Current line | After |
|------|--------------|-------|
| `test_catch_up_single_page` | 80-81 | `await consumer._catch_up(http_client_factory=lambda: mock_client)` |
| `test_catch_up_pagination` | 125-126 | same |
| `test_catch_up_respects_last_seq` | 159-160 | same |
| `test_catch_up_calls_on_event_for_each` | 195-196 | same |
| `test_catch_up_rest_endpoint_query_uses_last_seq` | 232-233 | same |

The `mock_client = AsyncMock()`/`mock_client.get = mock_get`/`__aenter__`/`__aexit__` setup before each `with patch(...)` block stays — those are legitimate fake objects (manually constructed, not `unittest.mock.patch`-driven). The design (line 305) confirms: "The `mock_client` is already a manually constructed object with `mock_client.get = mock_get`, so the test logic itself needs no change — only the injection mechanism."

**The remaining `unittest.mock` symbols after this task:**
- `AsyncMock`: still used to build `mock_client`, `mock_response`, and `mock_ws1`/`mock_ws2` in `test_reconnection_after_disconnect` (line 327-328). These are fakes for awaitable objects; the design (Glossary, "AsyncMock") accepts these as shorthand for async objects, prohibited only "where they are the primary test double for a public interface" — `mock_client` is not a public interface, it's an internal HTTP client and the `EventConsumer` author owns the protocol.
- `patch`: still used for `patch.object(consumer, "_buffer_ws", ...)`, `patch.object(consumer, "_catch_up", ...)`, `patch.object(consumer, "_session", ...)` (lines 286-287, 337) and `patch("pipeline.events.consumer.connect")` (line 335). Per design AC7.3, these stay.
- `MagicMock`: imported at line 8 but **not used anywhere in the file** — confirmed via `grep -c "MagicMock\b" tests/events/test_consumer.py` (only matches the import). Remove from the import list.

The new import line:

```python
from unittest.mock import AsyncMock, patch
```

This is the project's other documented `unittest.mock` survivor, alongside `MagicMock` in `tests/crawler/test_main.py` (Phase 3) and the absence of `unittest.mock` everywhere else by end of GH21.

**Concrete example** for `test_catch_up_single_page` (lines 51-86):

```python
@pytest.mark.asyncio
async def test_catch_up_single_page():
    """Test event-stream.AC6.2: _catch_up fetches and processes events via REST."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://localhost:8000", on_event)

    events = [
        {"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"},
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
    ]

    call_count = [0]

    async def mock_get(*args, **kwargs):
        call_count[0] += 1
        mock_response = AsyncMock()
        mock_response.json = lambda: events if call_count[0] == 1 else []
        mock_response.raise_for_status = lambda: None
        return mock_response

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    await consumer._catch_up(http_client_factory=lambda: mock_client)

    assert len(received) == 2
    assert consumer._last_seq == 2
    assert received[0]["seq"] == 1
    assert received[1]["seq"] == 2
```

Apply the identical transformation to all four other `_catch_up` tests.

**Testing:**

Tests must verify each AC listed above:
- GH21.AC7.1: All eleven tests in `tests/events/test_consumer.py` pass without `patch("pipeline.events.consumer.httpx.AsyncClient", ...)`.
- GH21.AC7.2: `_catch_up` accepts `http_client_factory` and tests inject `lambda: mock_client`.
- GH21.AC7.3: The `patch.object(consumer, ...)` and `patch("pipeline.events.consumer.connect")` sites are unchanged. Verify by `git diff tests/events/test_consumer.py:286-345` after edits — only line numbers should drift if other edits move them; substantive content unchanged.

**Verification:**

```bash
grep -n 'patch("pipeline\.events\.consumer\.httpx\.AsyncClient"' tests/events/test_consumer.py
```

Expected: zero matches.

```bash
grep -n "patch\.object\|patch(.pipeline\.events\.consumer\.connect" tests/events/test_consumer.py
```

Expected: 4 matches (3 `patch.object`, 1 `patch("...connect")`) — preserved per AC7.3.

```bash
grep -n "MagicMock" tests/events/test_consumer.py
```

Expected: zero matches (import removed; never used in the file).

```bash
uv run pytest tests/events/test_consumer.py -v
```

Expected: all eleven tests pass with the same count as before this phase.

**Commit:**

```bash
git add src/pipeline/events/consumer.py tests/events/test_consumer.py
git commit -m "refactor(events.consumer): inject http_client_factory into _catch_up (GH21 phase 5)"
```
<!-- END_TASK_2 -->

---

## Phase 5 Done When

- `EventConsumer._catch_up` accepts `http_client_factory` as a keyword-only parameter with default `httpx.AsyncClient`.
- The five `_catch_up` test methods use `http_client_factory=lambda: mock_client` instead of `with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):`.
- `tests/events/test_consumer.py` import line is `from unittest.mock import AsyncMock, patch` (no `MagicMock`).
- The two `patch.object(consumer, ...)` and one `patch("pipeline.events.consumer.connect")` sites are unchanged per AC7.3.
- `uv run pytest tests/events/test_consumer.py` passes with the same test count as before this phase.

## Notes for executor

- **Phase ordering:** independent of phases 1, 2, 3, 4.
- **Conflict surface:** GH23 phase 3 modifies `events/consumer.py` `_session` (lines 73-77 and 89-95) for narrowed exception logging. GH21's edit targets `_catch_up` (lines 107-123) — different methods, no line overlap. GH27 prepends `# pattern: test file` to `test_consumer.py:1` (currently a docstring `"""Tests for EventConsumer.\n`). Either ordering works; the Edit tool's exact-match shape will surface drift.
- **`MagicMock` removal:** Verify with `grep -c "\bMagicMock\b" tests/events/test_consumer.py` before removing the import — should be 1 (the import line itself) before edit, 0 after. If any non-import use is found, leave the import in place and surface it.
- **Out of scope per design line 307-309:** the `patch.object` and `patch("...connect")` sites. Do not touch them. They are tracked under AC7.3 specifically as "acceptable as-is".
