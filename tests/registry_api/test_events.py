import asyncio
import threading
import time
from unittest.mock import AsyncMock

import pytest

from pipeline.registry_api.events import ConnectionManager, manager


class TestConnectionManager:
    """Unit tests for ConnectionManager class."""

    @pytest.mark.asyncio
    async def test_connect_adds_websocket_to_active_connections(self):
        """Test that connect() accepts a WebSocket and adds it to active_connections."""
        manager = ConnectionManager()
        mock_ws = AsyncMock()

        await manager.connect(mock_ws)

        assert mock_ws in manager.active_connections
        mock_ws.accept.assert_called_once()

    def test_disconnect_removes_websocket_from_active_connections(self):
        """Test that disconnect() removes a WebSocket from active_connections."""
        manager = ConnectionManager()
        mock_ws = AsyncMock()
        manager.active_connections.add(mock_ws)

        manager.disconnect(mock_ws)

        assert mock_ws not in manager.active_connections

    def test_disconnect_with_unknown_websocket_does_not_raise(self):
        """Test that disconnect() with unknown WebSocket does not raise (discard semantics)."""
        manager = ConnectionManager()
        mock_ws = AsyncMock()

        # Should not raise
        manager.disconnect(mock_ws)

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
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        manager.active_connections.add(mock_ws1)
        manager.active_connections.add(mock_ws2)

        await manager.broadcast({"event": "test"})

        mock_ws1.send_json.assert_called_once_with({"event": "test"})
        mock_ws2.send_json.assert_called_once_with({"event": "test"})

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connection(self):
        """Test that broadcast() removes dead connections without crashing."""
        manager = ConnectionManager()
        mock_ws_good = AsyncMock()
        mock_ws_dead = AsyncMock()
        mock_ws_dead.send_json.side_effect = RuntimeError("Connection closed")
        manager.active_connections.add(mock_ws_good)
        manager.active_connections.add(mock_ws_dead)

        await manager.broadcast({"test": "data"})

        # Dead connection should be removed
        assert mock_ws_dead not in manager.active_connections
        # Good connection should remain
        assert mock_ws_good in manager.active_connections
        # Good connection should have received the broadcast
        mock_ws_good.send_json.assert_called_once_with({"test": "data"})

    @pytest.mark.asyncio
    async def test_broadcast_with_multiple_dead_connections(self):
        """Test broadcast() handles multiple dead connections gracefully."""
        manager = ConnectionManager()
        mock_ws_good = AsyncMock()
        mock_ws_dead1 = AsyncMock()
        mock_ws_dead2 = AsyncMock()

        mock_ws_dead1.send_json.side_effect = Exception("Connection lost")
        mock_ws_dead2.send_json.side_effect = Exception("Connection lost")

        manager.active_connections.add(mock_ws_good)
        manager.active_connections.add(mock_ws_dead1)
        manager.active_connections.add(mock_ws_dead2)

        await manager.broadcast({"test": "data"})

        # Both dead connections should be removed
        assert mock_ws_dead1 not in manager.active_connections
        assert mock_ws_dead2 not in manager.active_connections
        # Good connection should remain
        assert mock_ws_good in manager.active_connections


class TestWebSocketEndpoint:
    """Integration tests for the /ws/events WebSocket endpoint."""

    def cleanup(self):
        """Clear active connections before/after tests."""
        manager.active_connections.clear()

    def test_websocket_connect_accepted(self, client):
        """Test that WebSocket connection is accepted."""
        self.cleanup()
        with client.websocket_connect("/ws/events") as ws:
            # If we get here, connection was accepted
            assert ws is not None
        self.cleanup()

    def test_websocket_disconnect_removes_connection(self, client):
        """Test event-stream.AC3.2: Disconnect removes connection from active set."""
        self.cleanup()
        # Connect a client
        with client.websocket_connect("/ws/events"):
            initial_count = len(manager.active_connections)
            assert initial_count >= 1

        # After exiting context, connection should be closed
        # (The finally block in websocket_events will call disconnect)
        final_count = len(manager.active_connections)
        assert final_count == initial_count - 1
        self.cleanup()

    def test_broadcast_to_single_client(self, client):
        """Test that a single connected client receives a broadcast."""
        self.cleanup()

        with client.websocket_connect("/ws/events") as ws:
            # Verify connection is open
            assert ws is not None

            # Trigger a broadcast via a helper that can run in the test event loop
            # Since TestClient is synchronous, we have to be creative with timing
            def broadcast_in_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(manager.broadcast({"type": "test", "data": "hello"}))
                finally:
                    loop.close()

            thread = threading.Thread(target=broadcast_in_thread)
            thread.start()

            # Receive the message from the WebSocket
            data = ws.receive_json()
            thread.join(timeout=2)

            assert data == {"type": "test", "data": "hello"}

        self.cleanup()

    def test_broadcast_to_multiple_clients_ac31(self, client):
        """Test event-stream.AC3.1: Two connected clients both receive the same broadcast.

        This test verifies that when multiple clients are connected, a broadcast reaches all of them.
        Since TestClient is synchronous and single-threaded, we verify this by checking that:
        1. Multiple WebSockets can be added to the active_connections set
        2. A broadcast sends to all active connections without error
        """
        self.cleanup()

        # Verify that the manager can hold multiple connections
        from unittest.mock import AsyncMock

        ws1 = AsyncMock()
        ws2 = AsyncMock()

        # Simulate connecting two clients
        manager.active_connections.add(ws1)
        manager.active_connections.add(ws2)

        # Broadcast should send to both
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(manager.broadcast({"type": "event", "content": "test"}))
        finally:
            loop.close()

        # Both should have received the message
        ws1.send_json.assert_called_once_with({"type": "event", "content": "test"})
        ws2.send_json.assert_called_once_with({"type": "event", "content": "test"})

        self.cleanup()

    def test_client_disconnect_does_not_affect_other_clients_ac32(self, client):
        """Test event-stream.AC3.2: Disconnecting one client doesn't affect others.

        This test verifies that when one client disconnects, other clients continue to work.
        """
        self.cleanup()
        from unittest.mock import AsyncMock

        ws1 = AsyncMock()
        ws2 = AsyncMock()

        # Simulate two clients connecting
        manager.active_connections.add(ws1)
        manager.active_connections.add(ws2)

        # First broadcast - both receive
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(manager.broadcast({"type": "first", "num": 1}))
        finally:
            loop.close()

        # Both got the message
        ws1.send_json.assert_called_once_with({"type": "first", "num": 1})
        ws2.send_json.assert_called_once_with({"type": "first", "num": 1})

        # Disconnect first client (remove from active_connections)
        manager.disconnect(ws1)
        assert ws1 not in manager.active_connections
        assert ws2 in manager.active_connections

        # Second broadcast - only second client receives
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(manager.broadcast({"type": "after_disconnect", "message": "still works"}))
        finally:
            loop.close()

        # Second client got the second message too
        assert ws2.send_json.call_count == 2
        ws2.send_json.assert_called_with({"type": "after_disconnect", "message": "still works"})
        # First client was only called once (before disconnect)
        assert ws1.send_json.call_count == 1

        self.cleanup()

    def test_dead_connection_cleanup_ac33(self, client):
        """Test event-stream.AC3.3: Dead connection is cleaned up without crashing."""
        self.cleanup()

        def connect_and_close():
            """Connect a client, then close the connection."""
            ws = client.websocket_connect("/ws/events")
            ws.__enter__()
            ws.__exit__(None, None, None)
            # Connection is now closed/dead

        # Connect and immediately close a client
        connect_and_close()

        # Give it a moment to clean up
        time.sleep(0.05)

        # Now broadcast - should not crash even though we just closed a connection
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(manager.broadcast({"type": "test", "data": "safe"}))
            finally:
                loop.close()
            broadcast_succeeded = True
        except Exception:
            broadcast_succeeded = False

        assert broadcast_succeeded, "Broadcast should not crash with dead connections"
        self.cleanup()

    def test_broadcast_persists_across_calls(self, client):
        """Test that broadcast calls accumulate and persist messages for clients.

        This verifies that multiple broadcasts don't interfere with each other and
        a connected client can receive any message that was broadcast while connected.
        """
        self.cleanup()
        from unittest.mock import AsyncMock

        # Simulate a client connection
        ws = AsyncMock()
        manager.active_connections.add(ws)

        # Send 3 sequential broadcasts
        for i in range(3):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(manager.broadcast({"id": i, "count": i + 1}))
            finally:
                loop.close()

        # Verify all 3 were sent to the client
        assert ws.send_json.call_count == 3
        calls = ws.send_json.call_args_list
        assert calls[0][0][0] == {"id": 0, "count": 1}
        assert calls[1][0][0] == {"id": 1, "count": 2}
        assert calls[2][0][0] == {"id": 2, "count": 3}

        self.cleanup()
