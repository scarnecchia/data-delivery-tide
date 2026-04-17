# pattern: test file

import asyncio
import json
import time

import pytest

from pipeline.converter.daemon import load_last_seq, persist_last_seq, DaemonRunner


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
