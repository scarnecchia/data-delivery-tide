# pattern: test file
import asyncio
import threading
import time

import pytest

from pipeline.registry_api.events import ConnectionManager, manager


class FakeWebSocket:
    """Minimal stand-in for a Starlette/FastAPI WebSocket.

    Implements only the subset of the protocol used by ConnectionManager:
    `accept()` and `send_json(data)`. Records all activity for assertion.
    """

    def __init__(
        self,
        *,
        fail_on_send: bool = False,
        send_exception: BaseException | None = None,
    ) -> None:
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


class TestConnectionManager:
    """Unit tests for ConnectionManager class."""

    @pytest.mark.asyncio
    async def test_connect_adds_websocket_to_active_connections(self):
        """Test that connect() accepts a WebSocket and adds it to active_connections."""
        manager = ConnectionManager()
        fake_ws = FakeWebSocket()

        await manager.connect(fake_ws)

        assert fake_ws in manager.active_connections
        assert fake_ws.accepted is True

    def test_disconnect_removes_websocket_from_active_connections(self):
        """Test that disconnect() removes a WebSocket from active_connections."""
        manager = ConnectionManager()
        fake_ws = FakeWebSocket()
        manager.active_connections.add(fake_ws)

        manager.disconnect(fake_ws)

        assert fake_ws not in manager.active_connections

    def test_disconnect_with_unknown_websocket_does_not_raise(self):
        """Test that disconnect() with unknown WebSocket does not raise (discard semantics)."""
        manager = ConnectionManager()
        fake_ws = FakeWebSocket()

        # Should not raise
        manager.disconnect(fake_ws)

        assert len(manager.active_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections_does_not_raise(self):
        """Test that broadcast() with no connections does not raise."""
        manager = ConnectionManager()

        # Should not raise
        await manager.broadcast({"test": "data"})

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_connections(self):
        """Test that broadcast() sends event to all active connections."""
        manager = ConnectionManager()
        fake_ws1 = FakeWebSocket()
        fake_ws2 = FakeWebSocket()
        manager.active_connections.add(fake_ws1)
        manager.active_connections.add(fake_ws2)

        await manager.broadcast({"event": "test"})

        assert fake_ws1.sent == [{"event": "test"}]
        assert fake_ws2.sent == [{"event": "test"}]

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connection(self):
        """Test that broadcast() removes dead connections without crashing."""
        manager = ConnectionManager()
        fake_good = FakeWebSocket()
        fake_dead = FakeWebSocket(fail_on_send=True)
        manager.active_connections.add(fake_good)
        manager.active_connections.add(fake_dead)

        await manager.broadcast({"test": "data"})

        # Dead connection should be removed
        assert fake_dead not in manager.active_connections
        # Good connection should remain
        assert fake_good in manager.active_connections
        # Good connection should have received the broadcast
        assert fake_good.sent == [{"test": "data"}]

    @pytest.mark.asyncio
    async def test_broadcast_with_multiple_dead_connections(self):
        """Test broadcast() handles multiple dead connections gracefully."""
        manager = ConnectionManager()
        fake_good = FakeWebSocket()
        fake_dead1 = FakeWebSocket(
            fail_on_send=True, send_exception=Exception("Connection lost"),
        )
        fake_dead2 = FakeWebSocket(
            fail_on_send=True, send_exception=Exception("Connection lost"),
        )

        manager.active_connections.add(fake_good)
        manager.active_connections.add(fake_dead1)
        manager.active_connections.add(fake_dead2)

        await manager.broadcast({"test": "data"})

        # Both dead connections should be removed
        assert fake_dead1 not in manager.active_connections
        assert fake_dead2 not in manager.active_connections
        # Good connection should remain
        assert fake_good in manager.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_connections_ac31(self):
        """Test event-stream.AC3.1: Two connected clients both receive the same broadcast."""
        test_manager = ConnectionManager()
        fake_ws1 = FakeWebSocket()
        fake_ws2 = FakeWebSocket()
        test_manager.active_connections.add(fake_ws1)
        test_manager.active_connections.add(fake_ws2)

        await test_manager.broadcast({"type": "event", "content": "test"})

        assert fake_ws1.sent == [{"type": "event", "content": "test"}]
        assert fake_ws2.sent == [{"type": "event", "content": "test"}]

    def test_disconnect_does_not_affect_other_connections_ac32(self):
        """Test event-stream.AC3.2: Disconnecting one client doesn't affect others."""
        test_manager = ConnectionManager()
        fake_ws1 = FakeWebSocket()
        fake_ws2 = FakeWebSocket()
        test_manager.active_connections.add(fake_ws1)
        test_manager.active_connections.add(fake_ws2)

        test_manager.disconnect(fake_ws1)

        assert fake_ws1 not in test_manager.active_connections
        assert fake_ws2 in test_manager.active_connections
        assert len(test_manager.active_connections) == 1

    @pytest.mark.asyncio
    async def test_broadcast_persists_across_calls(self):
        """Test that broadcast calls accumulate messages for connected clients."""
        test_manager = ConnectionManager()
        fake_ws = FakeWebSocket()
        test_manager.active_connections.add(fake_ws)

        for i in range(3):
            await test_manager.broadcast({"id": i, "count": i + 1})

        assert fake_ws.sent == [
            {"id": 0, "count": 1},
            {"id": 1, "count": 2},
            {"id": 2, "count": 3},
        ]


class TestWebSocketEndpoint:
    """Integration tests for the /ws/events WebSocket endpoint."""

    @pytest.fixture(autouse=True)
    def _clear_connections(self):
        """Clear active connections before and after each test."""
        manager.active_connections.clear()
        yield
        manager.active_connections.clear()

    def test_websocket_connect_accepted(self, client, auth_headers):
        """Test that WebSocket connection is accepted."""
        with client.websocket_connect("/ws/events?token=test-integration-token") as ws:
            # If we get here, connection was accepted
            assert ws is not None

    def test_websocket_disconnect_removes_connection(self, client, auth_headers):
        """Test event-stream.AC3.2: Disconnect removes connection from active set."""
        # Connect a client
        with client.websocket_connect("/ws/events?token=test-integration-token"):
            initial_count = len(manager.active_connections)
            assert initial_count >= 1

        # After exiting context, connection should be closed
        # (The finally block in websocket_events will call disconnect)
        final_count = len(manager.active_connections)
        assert final_count == initial_count - 1

    def test_broadcast_to_single_client(self, client, auth_headers):
        """Test that a single connected client receives a broadcast."""
        with client.websocket_connect("/ws/events?token=test-integration-token") as ws:
            # Verify connection is open
            assert ws is not None

            # Trigger a broadcast via a helper that can run in the test event loop
            # Since TestClient is synchronous, we have to be creative with timing
            def broadcast_in_thread():
                asyncio.run(manager.broadcast({"type": "test", "data": "hello"}))

            thread = threading.Thread(target=broadcast_in_thread)
            thread.start()

            # Receive the message from the WebSocket
            data = ws.receive_json()
            thread.join(timeout=2)

            assert data == {"type": "test", "data": "hello"}

    def test_dead_connection_cleanup_ac33(self, client, auth_headers):
        """Test event-stream.AC3.3: Dead connection is cleaned up without crashing."""
        def connect_and_close():
            """Connect a client, then close the connection."""
            ws = client.websocket_connect("/ws/events?token=test-integration-token")
            ws.__enter__()
            ws.__exit__(None, None, None)
            # Connection is now closed/dead

        # Connect and immediately close a client
        connect_and_close()

        # Poll for connection cleanup instead of using time.sleep
        for _ in range(50):  # up to 0.5s
            if len(manager.active_connections) == 0:
                break
            time.sleep(0.01)

        # Now broadcast - should not crash even though we just closed a connection
        try:
            asyncio.run(manager.broadcast({"type": "test", "data": "safe"}))
            broadcast_succeeded = True
        except Exception:
            broadcast_succeeded = False

        assert broadcast_succeeded, "Broadcast should not crash with dead connections"



# ---- GH23 phase 4: failed send_json logged at DEBUG ----

import logging


class TestBroadcastExcInfoLogging:
    """GH23.AC4: failed send_json logs DEBUG with exc_info before marking dead."""

    @pytest.mark.asyncio
    async def test_failed_send_logs_debug_with_exc_info(self, caplog):
        manager = ConnectionManager()
        bad = FakeWebSocket(fail_on_send=True, send_exception=RuntimeError("boom"))
        manager.active_connections.add(bad)

        caplog.set_level(logging.DEBUG, logger="pipeline.registry_api.events")
        await manager.broadcast({"seq": 1})

        debug_records = [r for r in caplog.records
                         if r.name == "pipeline.registry_api.events"
                         and r.levelno == logging.DEBUG
                         and r.message == "WebSocket send failed, marking connection dead"]
        assert len(debug_records) == 1
        assert debug_records[0].exc_info is not None
        assert debug_records[0].exc_info[0] is RuntimeError

    @pytest.mark.asyncio
    async def test_failed_send_still_warns_and_removes(self, caplog):
        manager = ConnectionManager()
        bad = FakeWebSocket(fail_on_send=True, send_exception=RuntimeError("boom"))
        manager.active_connections.add(bad)

        caplog.set_level(logging.DEBUG, logger="pipeline.registry_api.events")
        await manager.broadcast({"seq": 1})

        warn_records = [r for r in caplog.records
                        if r.name == "pipeline.registry_api.events"
                        and r.levelno == logging.WARNING
                        and r.message == "Removed dead WebSocket connection during broadcast"]
        assert len(warn_records) == 1
        assert bad not in manager.active_connections

    @pytest.mark.asyncio
    async def test_successful_send_emits_no_records(self, caplog):
        manager = ConnectionManager()
        good = FakeWebSocket()
        manager.active_connections.add(good)

        caplog.set_level(logging.DEBUG, logger="pipeline.registry_api.events")
        await manager.broadcast({"seq": 1})

        records = [r for r in caplog.records if r.name == "pipeline.registry_api.events"]
        assert records == []
        assert good in manager.active_connections
