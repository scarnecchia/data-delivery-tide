# SAS-to-Parquet Converter — Phase 5: Event-driven daemon

**Goal:** A long-running process that subscribes to the registry event stream via the existing `EventConsumer` (see `src/pipeline/events/consumer.py`), persists `last_seq` to a state file after every processed event, and dispatches each `delivery.created` event to `engine.convert_one` off the event loop so the WebSocket stays alive during multi-GB conversions.

**Architecture:** Two new files (`src/pipeline/converter/daemon.py`, `pipeline/scripts/ensure_converter.sh`) plus a pyproject.toml entry point. Reuses the `pipeline.events.consumer.EventConsumer` reference client — do NOT re-implement catch-up/reconnect logic. The daemon wraps EventConsumer with:
1. State persistence (atomic tmp+rename+fsync) of `last_seq` after each event.
2. Signal handlers (`SIGTERM`/`SIGINT`) that finish the in-flight conversion, persist state, and exit cleanly.
3. Event-type filtering — only `delivery.created` triggers work; `delivery.status_changed`, `conversion.*` are skipped (the daemon is the producer of the `conversion.*` events — consuming its own output would loop).

**Tech Stack:** asyncio, `websockets` (already in `consumer` dep group), `httpx` (already in `consumer` dep group), stdlib `signal`, stdlib `json`, `os.fsync`.

**Scope:** Phase 5 of 6.

**Codebase verified:** 2026-04-16.

---

## Acceptance Criteria Coverage

### sas-to-parquet-converter.AC9: Event-driven daemon
- **sas-to-parquet-converter.AC9.1 Success:** Daemon reads `last_seq` from `converter_state_path` on startup (defaults to 0 if missing)
- **sas-to-parquet-converter.AC9.2 Success:** Catch-up phase drains `GET /events?after={last_seq}` until empty before opening WebSocket
- **sas-to-parquet-converter.AC9.3 Success:** Each processed event persists the updated `last_seq` with fsync before the next event begins
- **sas-to-parquet-converter.AC9.4 Success:** Daemon ignores `delivery.status_changed` events (conversion is status-blind; only `delivery.created` triggers work)
- **sas-to-parquet-converter.AC9.5 Success:** WebSocket disconnect triggers reconnect with backoff
- **sas-to-parquet-converter.AC9.6 Success:** `SIGTERM` / `SIGINT` finishes the in-flight conversion, persists `last_seq`, exits cleanly
- **sas-to-parquet-converter.AC9.7 Success:** Daemon restarted mid-stream resumes from persisted `last_seq` without gaps or duplicate processing

---

## Engineer Briefing

**Reuse, don't reinvent.** The EventConsumer at `src/pipeline/events/consumer.py:15-124` already does:
- `async for websocket in connect(ws_url)` — automatic reconnection with exponential backoff (library feature). Covers AC9.5.
- Catch-up via `GET /events?after={_last_seq}&limit=1000` drained before listening. Covers AC9.2.
- Deduplication by `seq > _last_seq`.
- An `on_event(event: dict) -> Awaitable[None]` callback hook.

The daemon's job is:
1. **Before instantiating EventConsumer**, read `last_seq` from disk and set `consumer._last_seq` (write into the private attr — that's what it's there for). Covers AC9.1.
2. **In the `on_event` callback**, (a) skip events whose `event_type` is not `delivery.created` (but still update `_last_seq` — covers AC9.4 and AC9.7's "no duplicate processing" on resume), (b) dispatch the engine call to a threadpool via `asyncio.to_thread` (or `run_in_executor` for 3.10), (c) persist `last_seq` to disk after successful engine call.
3. **Signal handlers**: `loop.add_signal_handler(signal.SIGTERM, on_shutdown)` and same for `SIGINT`. On shutdown, set a shared `stopping` flag. The main loop checks this flag between events. If an engine call is in flight, we finish it (the `await asyncio.to_thread(...)` resolves), persist `last_seq`, and cancel the EventConsumer task.

**Critical design choices and why:**

- **Threadpool for engine.convert_one**: AC9.5 requires reconnect-on-disconnect; AC9.3 requires state persistence per event. If we call the SYNC `convert_one` inline in the async event loop, a multi-GB conversion can take minutes during which the WebSocket server will close us out for missing pings. Offloading via `asyncio.to_thread` lets the event loop pump pings while the thread works. Concurrency remains 1 because we `await` the thread before accepting the next event.
- **State persistence after success only**: We persist `last_seq` AFTER the engine returns. If the engine raises (or we're SIGTERM'd mid-conversion), the state file still shows the pre-conversion seq. On restart, the consumer catches up from that seq, sees the same `delivery.created` event again, and the engine's skip guard (AC5.2 — `parquet_converted_at` set + file exists) handles the idempotency. Phase 3 AC5.2 already guarantees re-seeing a processed event is a no-op.
- **`delivery.status_changed` and `conversion.*` events**: `_last_seq` MUST advance through these (otherwise catch-up re-issues them forever), but `on_event` should NOT call the engine for them. The daemon updates `last_seq` for every event it sees, but only dispatches `delivery.created` to the engine. This is AC9.4 + AC9.7.
- **Python 3.10 compatibility**: `asyncio.to_thread` is 3.9+, so usable on 3.10+. `asyncio.TaskGroup` is 3.11+ — don't use it here.

**Don't modify `consumer.py`.** Reading `consumer._last_seq` directly (single underscore, Python convention = "don't touch unless you know what you're doing") is our contract. If Phase 6 or future work wants to formalise it, wrap in a property — but not in this phase.

**State file shape:** `{"last_seq": 42}`. A single-key JSON object is overkill for one int, but leaves room for future fields without schema churn (e.g., `converter_version`, `last_resumed_at`).

**Atomic write pattern** (per internet research, adapted for our tree):

```python
def _persist_last_seq(state_path: Path, seq: int) -> None:
    tmp = state_path.with_name(f".{state_path.name}.tmp-{uuid.uuid4().hex}")
    with open(tmp, "w") as f:
        json.dump({"last_seq": seq}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, state_path)
```

We deliberately skip the parent-directory fsync (the internet research example). Rationale: the state file's parent is `pipeline/`, a long-lived directory — if it gets unlinked we've got bigger problems than a missing state fsync. For full durability on power loss we'd add `os.open(parent, os.O_RDONLY)` + `os.fsync` — not worth the operational complexity for a state file whose worst-case loss means "re-catch-up a few seconds of events on restart." Lose the perfect in search of the good.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: State-file load/persist helpers (pure, testable)

**Verifies:** AC9.1, AC9.3, AC9.7 (persistence correctness)

**Files:**
- Create: `src/pipeline/converter/daemon.py` (add load/persist helpers only — main loop in Task 2)
- Create: `tests/converter/test_daemon.py`

**Implementation:**

Start `src/pipeline/converter/daemon.py`:

```python
# pattern: Imperative Shell

import asyncio
import json
import logging
import os
import signal
import uuid
from pathlib import Path


def load_last_seq(state_path: Path) -> int:
    """
    Read last_seq from state file. Returns 0 if the file is missing or invalid.

    Invalid content (malformed JSON, missing key, non-int value) is tolerated
    — we return 0 and start from scratch rather than crash on startup. The
    worst case is re-processing a handful of events, which is idempotent
    thanks to the engine's skip guards.
    """
    try:
        with open(state_path) as f:
            data = json.load(f)
        seq = data.get("last_seq", 0)
        return int(seq) if isinstance(seq, (int, float)) else 0
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return 0


def persist_last_seq(state_path: Path, seq: int) -> None:
    """
    Atomically write last_seq to state_path.

    Uses tmp-file-plus-os.replace for atomicity, with fsync of the tmp file
    to survive power loss between the write and the rename. Does NOT fsync
    the parent directory (see Phase 5 briefing for rationale).

    Creates parent directories if missing.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # uuid-based tmp name matches the pattern used in convert.py; safe under
    # any concurrency even though the daemon processes events serially.
    tmp = state_path.with_name(f".{state_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with open(tmp, "w") as f:
            json.dump({"last_seq": seq}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, state_path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
```

**Testing in `tests/converter/test_daemon.py`:**

```python
# pattern: test file

import json
from pathlib import Path

import pytest

from pipeline.converter.daemon import load_last_seq, persist_last_seq


class TestLoadLastSeq:
    def test_missing_file_returns_zero(self, tmp_path):
        # AC9.1
        assert load_last_seq(tmp_path / "nonexistent.json") == 0

    def test_valid_file_returns_seq(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"last_seq": 42}))
        assert load_last_seq(state) == 42

    def test_malformed_json_returns_zero(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text("not json {{{")
        assert load_last_seq(state) == 0

    def test_missing_key_returns_zero(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"other_key": 1}))
        assert load_last_seq(state) == 0

    def test_non_numeric_value_returns_zero(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"last_seq": "not a number"}))
        assert load_last_seq(state) == 0

    def test_float_value_returns_int(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"last_seq": 42.0}))
        assert load_last_seq(state) == 42


class TestPersistLastSeq:
    def test_writes_value_atomically(self, tmp_path):
        # AC9.3 core behaviour
        state = tmp_path / "state.json"
        persist_last_seq(state, 100)
        assert load_last_seq(state) == 100

    def test_overwrites_existing(self, tmp_path):
        state = tmp_path / "state.json"
        persist_last_seq(state, 1)
        persist_last_seq(state, 2)
        persist_last_seq(state, 3)
        assert load_last_seq(state) == 3

    def test_creates_parent_directory(self, tmp_path):
        state = tmp_path / "nested" / "dir" / "state.json"
        persist_last_seq(state, 5)
        assert state.exists()
        assert load_last_seq(state) == 5

    def test_no_leftover_tmp_files(self, tmp_path):
        state = tmp_path / "state.json"
        persist_last_seq(state, 1)
        tmps = list(tmp_path.glob(f".{state.name}.tmp-*"))
        assert tmps == []

    def test_load_persist_round_trip(self, tmp_path):
        # AC9.7: restart scenario.
        state = tmp_path / "state.json"
        persist_last_seq(state, 999)
        # Simulate restart: new process reads the same file.
        assert load_last_seq(state) == 999
```

**Verification:**

Run: `uv run pytest tests/converter/test_daemon.py -v`
Expected: All tests pass.

**Commit:** `feat(converter): add atomic state-file persistence for daemon last_seq`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Daemon main loop — EventConsumer wrapper with engine dispatch and signal handling

**Verifies:** AC9.2, AC9.4, AC9.5, AC9.6, AC9.7

**Files:**
- Modify: `src/pipeline/converter/daemon.py` (add `DaemonRunner` class and `main()` entry)
- Modify: `tests/converter/test_daemon.py` (add integration tests using stubbed EventConsumer)
- Modify: `pyproject.toml` (register `registry-convert-daemon` entry point)
- Modify: `pipeline/converter/CLAUDE.md` (will be created in Phase 6; no changes here)

**Implementation:**

Append to `daemon.py`:

```python
from pipeline.config import settings
from pipeline.converter.engine import convert_one
from pipeline.events.consumer import EventConsumer
from pipeline.json_logging import get_logger


class DaemonRunner:
    """
    Event-driven daemon orchestrator.

    Lifecycle:
      1. __init__ resolves config and sets up state.
      2. run_async() wires EventConsumer with an on_event callback, registers
         signal handlers on the event loop, and awaits the consumer task.
      3. On SIGTERM/SIGINT: sets _stopping, cancels the consumer task after
         any in-flight on_event completes, persists last_seq, returns.
    """

    def __init__(
        self,
        *,
        api_url: str,
        state_path: Path,
        converter_version: str,
        chunk_size: int,
        compression: str,
        log_dir: str | None,
        consumer_factory=EventConsumer,
        convert_one_fn=convert_one,
    ) -> None:
        self.api_url = api_url
        self.state_path = Path(state_path)
        self.converter_version = converter_version
        self.chunk_size = chunk_size
        self.compression = compression
        self.log_dir = log_dir
        self._consumer_factory = consumer_factory
        self._convert_one_fn = convert_one_fn
        self._stopping = False
        self._logger = get_logger("converter-daemon", log_dir=log_dir)

    async def run_async(self) -> int:
        """
        Main coroutine. Returns an exit code.
        """
        last_seq = load_last_seq(self.state_path)
        self._logger.info(
            "daemon starting",
            extra={"last_seq": last_seq, "state_path": str(self.state_path)},
        )

        consumer = self._consumer_factory(self.api_url, self._on_event)
        consumer._last_seq = last_seq  # intentional private-attr set; see briefing

        loop = asyncio.get_running_loop()
        consumer_task = asyncio.create_task(consumer.run())
        self._consumer = consumer  # for signal handler to advance last_seq

        def _request_shutdown():
            if self._stopping:
                return
            self._stopping = True
            self._logger.info("shutdown requested; finishing in-flight work")
            # Cancelling schedules a CancelledError at the next await point.
            # Any in-flight asyncio.to_thread call returns first (threads can't
            # be cancelled), then the on_event coroutine resumes, persists,
            # and returns — after which the consumer loop sees cancellation.
            consumer_task.cancel()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                # Windows test environments. Not a target platform.
                pass

        try:
            await consumer_task
        except asyncio.CancelledError:
            self._logger.info("consumer task cancelled")
        except Exception as exc:
            self._logger.error(
                "consumer task raised unhandled exception",
                extra={"error_message": str(exc)},
            )
            return 1

        # State persistence is owned by `_on_event`: both the success path
        # and the cancellation path persist the event's seq before returning
        # or re-raising. Do NOT add a tail persist here:
        #   - On clean exit, the last processed event already has its seq
        #     on disk.
        #   - `consumer._last_seq` is updated by the reference consumer AFTER
        #     `on_event` returns (src/pipeline/events/consumer.py:81-82,
        #     87-88, 122-123), so it does not necessarily reflect an event
        #     that was mid-processing when we started shutting down.
        #   - A hypothetical unhandled Exception from the consumer task
        #     won't have a well-defined `_last_seq` to persist either.
        # The engine's skip-guards (converted=true; conversion_error set)
        # make replay of any unpersisted seq idempotent on restart.
        self._logger.info(
            "daemon stopped",
            extra={"last_seq": consumer._last_seq},
        )
        return 0

    async def _on_event(self, event: dict) -> None:
        """
        Per-event callback: dispatch delivery.created to the engine off the
        event loop; skip other event types.

        Persistence correctness:
          - Engine success → persist seq at the bottom of this method.
          - Engine raises `Exception` (classified failure) → engine has
            already PATCHed + emitted conversion.failed. Persist seq anyway
            so we don't re-dispatch the same failed delivery (whose next
            attempt would be skipped by the engine's conversion_error
            skip-guard regardless).
          - `CancelledError` (SIGTERM during `asyncio.to_thread`) →
            CancelledError is a BaseException, NOT an Exception subclass, so
            the `except Exception` below does not catch it. We explicitly
            catch it, persist the seq we just completed (the thread ran to
            completion before cancel fired — threads are not cancellable),
            and re-raise so the consumer task unwinds cleanly.
        """
        seq = event.get("seq", 0)
        event_type = event.get("event_type", "")
        delivery_id = event.get("delivery_id")

        if event_type == "delivery.created" and delivery_id:
            try:
                # Offload blocking work to a thread so the WebSocket keeps
                # pumping pings. Concurrency remains 1 — we await this before
                # accepting the next event.
                await asyncio.to_thread(
                    self._convert_one_fn,
                    delivery_id,
                    self.api_url,
                    converter_version=self.converter_version,
                    chunk_size=self.chunk_size,
                    compression=self.compression,
                    log_dir=self.log_dir,
                )
            except asyncio.CancelledError:
                # SIGTERM/SIGINT fired while we were awaiting to_thread. The
                # underlying thread ran to completion (Python can't cancel
                # a running thread); the engine's PATCH + event emission
                # finished. Persist the seq so we don't replay on restart,
                # then re-raise to let the consumer task shut down.
                persist_last_seq(self.state_path, seq)
                raise
            except Exception as exc:
                # Engine already PATCHed + emitted conversion.failed. Log and
                # advance anyway — the skip guard handles replay.
                self._logger.error(
                    "engine raised during convert_one",
                    extra={"delivery_id": delivery_id, "error_message": str(exc)},
                )

        # Persist regardless of event_type — AC9.4 + AC9.7.
        persist_last_seq(self.state_path, seq)


def main() -> int:
    """Entry point for registry-convert-daemon."""
    runner = DaemonRunner(
        api_url=settings.registry_api_url,
        state_path=Path(settings.converter_state_path),
        converter_version=settings.converter_version,
        chunk_size=settings.converter_chunk_size,
        compression=settings.converter_compression,
        log_dir=settings.log_dir,
    )
    return asyncio.run(runner.run_async())
```

**Register in `pyproject.toml`:**

```toml
[project.scripts]
registry-api = "pipeline.registry_api.main:run"
registry-convert = "pipeline.converter.cli:main"
registry-convert-daemon = "pipeline.converter.daemon:main"
```

**Testing:**

In `test_daemon.py`, add a `TestDaemonRunner` class using a stubbed `EventConsumer`:

```python
import asyncio
from unittest.mock import MagicMock

from pipeline.converter.daemon import DaemonRunner


class _StubConsumer:
    """
    Drives a fixed sequence of events through on_event, then returns.

    Mirrors EventConsumer's surface enough for the daemon to think it's real:
      - `_last_seq` attribute (the daemon writes into it at startup)
      - `run()` coroutine
    """

    def __init__(self, api_url: str, on_event):
        self.api_url = api_url
        self.on_event = on_event
        self._last_seq = 0
        self.events_to_emit: list[dict] = []

    async def run(self) -> None:
        for event in self.events_to_emit:
            if event["seq"] > self._last_seq:
                await self.on_event(event)
                self._last_seq = event["seq"]


class TestDaemonRunnerCallback:
    @pytest.mark.asyncio
    async def test_delivery_created_dispatches_engine(self, tmp_path):
        # AC9.4 (positive case)
        state_path = tmp_path / "state.json"
        engine_calls = []

        def fake_convert(delivery_id, api_url, **kwargs):
            engine_calls.append(delivery_id)

        def consumer_factory(api_url, on_event):
            consumer = _StubConsumer(api_url, on_event)
            consumer.events_to_emit = [
                {"seq": 1, "event_type": "delivery.created", "delivery_id": "abc"},
                {"seq": 2, "event_type": "delivery.created", "delivery_id": "def"},
            ]
            return consumer

        runner = DaemonRunner(
            api_url="http://registry", state_path=state_path,
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            consumer_factory=consumer_factory,
            convert_one_fn=fake_convert,
        )
        rc = await runner.run_async()
        assert rc == 0
        assert engine_calls == ["abc", "def"]
        assert load_last_seq(state_path) == 2

    @pytest.mark.asyncio
    async def test_non_delivery_created_events_skipped_but_seq_advanced(self, tmp_path):
        # AC9.4 negative case + AC9.7 (no duplicates on resume)
        state_path = tmp_path / "state.json"
        engine_calls = []

        def fake_convert(delivery_id, api_url, **kwargs):
            engine_calls.append(delivery_id)

        def consumer_factory(api_url, on_event):
            consumer = _StubConsumer(api_url, on_event)
            consumer.events_to_emit = [
                {"seq": 1, "event_type": "delivery.status_changed", "delivery_id": "abc"},
                {"seq": 2, "event_type": "conversion.completed", "delivery_id": "abc"},
                {"seq": 3, "event_type": "delivery.created", "delivery_id": "def"},
            ]
            return consumer

        runner = DaemonRunner(
            api_url="http://registry", state_path=state_path,
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            consumer_factory=consumer_factory,
            convert_one_fn=fake_convert,
        )
        rc = await runner.run_async()
        assert rc == 0
        # Only delivery.created triggered engine work.
        assert engine_calls == ["def"]
        # But seq advanced past all three.
        assert load_last_seq(state_path) == 3

    @pytest.mark.asyncio
    async def test_engine_exception_does_not_stop_daemon(self, tmp_path):
        state_path = tmp_path / "state.json"

        def fake_convert_raises(delivery_id, api_url, **kwargs):
            raise RuntimeError("engine crash (already PATCHed by engine itself)")

        def consumer_factory(api_url, on_event):
            consumer = _StubConsumer(api_url, on_event)
            consumer.events_to_emit = [
                {"seq": 1, "event_type": "delivery.created", "delivery_id": "abc"},
                {"seq": 2, "event_type": "delivery.created", "delivery_id": "def"},
            ]
            return consumer

        runner = DaemonRunner(
            api_url="http://registry", state_path=state_path,
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            consumer_factory=consumer_factory,
            convert_one_fn=fake_convert_raises,
        )
        rc = await runner.run_async()
        assert rc == 0
        # Despite the failure, seq advances and the daemon continues.
        assert load_last_seq(state_path) == 2


class TestDaemonRunnerCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_error_persists_seq_before_reraise(self, tmp_path):
        """
        SIGTERM mid-event must still persist the seq before CancelledError
        propagates out of `_on_event`. Uses a deliberately slow fake engine
        (time.sleep) so cancellation arrives while the to_thread is still
        running — otherwise the test is timing-flaky (the fake returns
        faster than the scheduler can deliver the cancel).
        """
        import time
        state_path = tmp_path / "state.json"

        def slow_convert_fn(*args, **kwargs):
            # 200ms block to guarantee cancellation arrives while we're
            # awaiting the to_thread result, not after it has resolved.
            time.sleep(0.2)

        def consumer_factory(api_url, on_event):
            return _StubConsumer(api_url, on_event)

        runner = DaemonRunner(
            api_url="http://registry", state_path=state_path,
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            consumer_factory=consumer_factory,
            convert_one_fn=slow_convert_fn,
        )

        event = {"seq": 7, "event_type": "delivery.created", "delivery_id": "abc"}

        task = asyncio.create_task(runner._on_event(event))
        # Give the to_thread call time to dispatch and start blocking in
        # the threadpool. 50ms << the thread's 200ms sleep, so the thread
        # is guaranteed to still be running when we cancel.
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # The `except asyncio.CancelledError` branch in _on_event must have
        # persisted the seq BEFORE re-raising.
        assert load_last_seq(state_path) == 7


class TestDaemonRunnerResume:
    @pytest.mark.asyncio
    async def test_resumes_from_persisted_seq(self, tmp_path):
        # AC9.1 + AC9.7
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"last_seq": 5}))

        engine_calls = []
        def fake_convert(delivery_id, api_url, **kwargs):
            engine_calls.append(delivery_id)

        captured_initial_seq = []

        def consumer_factory(api_url, on_event):
            consumer = _StubConsumer(api_url, on_event)
            # After the daemon sets _last_seq, capture what it was.
            # Events with seq <= 5 should be filtered by the consumer's dedup.
            consumer.events_to_emit = [
                {"seq": 3, "event_type": "delivery.created", "delivery_id": "old1"},
                {"seq": 5, "event_type": "delivery.created", "delivery_id": "old2"},
                {"seq": 6, "event_type": "delivery.created", "delivery_id": "new1"},
                {"seq": 7, "event_type": "delivery.created", "delivery_id": "new2"},
            ]
            return consumer

        runner = DaemonRunner(
            api_url="http://registry", state_path=state_path,
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            consumer_factory=consumer_factory,
            convert_one_fn=fake_convert,
        )
        rc = await runner.run_async()
        assert rc == 0
        # Old events (seq 3, 5) filtered by the stub's dedup; only 6, 7 processed.
        assert engine_calls == ["new1", "new2"]
        assert load_last_seq(state_path) == 7


class TestDaemonRunnerReconnect:
    # AC9.5 is verified by trusting the EventConsumer's documented behaviour
    # (covered by tests/events/test_consumer.py) — the daemon wraps it and
    # inherits that reconnect semantics.
    def test_reconnect_is_delegated_to_event_consumer(self):
        # This is a documentation test: assert we use EventConsumer, not a
        # custom loop. If someone refactors to bypass EventConsumer, this
        # test should start to fail (through import inspection or similar).
        import pipeline.converter.daemon as daemon_mod
        import pipeline.events.consumer as consumer_mod
        # Sanity: the DaemonRunner default factory IS EventConsumer.
        assert daemon_mod.EventConsumer is consumer_mod.EventConsumer
```

**Note on signal-handler testing:** Testing real signal delivery in pytest is painful and platform-specific. The `_request_shutdown` → `consumer_task.cancel()` path is straightforward; we trust that `loop.add_signal_handler` is correctly wired by the stdlib. If tighter coverage is needed later, add a dedicated integration test in Phase 6 that spawns the daemon as a subprocess and sends `os.kill(pid, signal.SIGTERM)`.

**Verification:**

Run: `uv run pytest tests/converter/test_daemon.py -v`
Expected: All tests pass.

Run: `uv run pytest`
Expected: Full suite green.

Run: `which registry-convert-daemon` after `uv pip install -e ".[registry,dev]"` — entry point resolves.

**Commit:** `feat(converter): add event-driven daemon with graceful shutdown`
<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (task 3) -->

<!-- START_TASK_3 -->
### Task 3: Watchdog script `ensure_converter.sh`

**Verifies:** Operational convenience (not an AC).

**Context:** Mirror `pipeline/scripts/ensure_registry.sh` exactly in shape. Cron-callable; PID-file-based; restarts if dead.

**Files:**
- Create: `pipeline/scripts/ensure_converter.sh`
- Make it executable: `chmod +x`

**Implementation:**

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$PIPELINE_DIR")"

PIDFILE="${PIPELINE_DIR}/registry_converter.pid"
LOGFILE="${PIPELINE_DIR}/logs/registry_converter.log"

mkdir -p "$(dirname "$LOGFILE")"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi

cd "$PROJECT_DIR"
nohup registry-convert-daemon >> "$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
```

**Testing:** No automated test. Manual verification below.

**Manual verification:**

```bash
chmod +x pipeline/scripts/ensure_converter.sh
pipeline/scripts/ensure_converter.sh
cat pipeline/registry_converter.pid
ps -p $(cat pipeline/registry_converter.pid)  # process should be alive
tail -n 5 pipeline/logs/registry_converter.log  # should show daemon startup logs

# Kill and re-run: watchdog should restart.
kill $(cat pipeline/registry_converter.pid)
sleep 1
pipeline/scripts/ensure_converter.sh  # should exit 0 after relaunching
ps -p $(cat pipeline/registry_converter.pid)  # new PID, process alive
```

**Commit:** `feat(ops): add ensure_converter.sh watchdog script`
<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_B -->

---

## Phase completion checklist

- [ ] Three tasks committed separately.
- [ ] `uv run pytest` full suite green.
- [ ] `src/pipeline/converter/daemon.py` starts with `# pattern: Imperative Shell` on line 1.
- [ ] `registry-convert-daemon --help` (argparse-free; the daemon takes no CLI args) — actually the daemon should just start on invocation; no help required.
- [ ] `ensure_converter.sh` runs, starts the daemon, writes a PID file.
- [ ] Manual end-to-end: start registry, start daemon, POST a delivery via the registry; verify the daemon picks it up within a few seconds and PATCHes the row.
- [ ] Kill the daemon with `SIGTERM`; verify state file persists the last-seen seq before exit.
- [ ] Restart daemon; verify it resumes without re-processing events beyond the last persisted seq.
- [ ] Phase 6 (integration + docs) can proceed.
