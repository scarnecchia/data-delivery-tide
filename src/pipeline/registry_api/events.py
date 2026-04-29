# pattern: Imperative Shell

import logging
from typing import Any

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

    async def broadcast(self, event: dict[str, Any]) -> None:
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
                logger.debug(
                    "WebSocket send failed, marking connection dead",
                    exc_info=True,
                )
                dead.append(connection)

        for connection in dead:
            self.active_connections.discard(connection)
            logger.warning("Removed dead WebSocket connection during broadcast")


manager = ConnectionManager()
