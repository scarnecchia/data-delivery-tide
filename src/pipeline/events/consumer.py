# pattern: Imperative Shell

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class EventConsumer:
    """
    Reference consumer for registry event stream.

    Connects to the registry API's WebSocket endpoint for real-time events
    and uses the REST catch-up endpoint on reconnect. Deduplicates events
    by sequence number to ensure exactly-once processing.

    Args:
        api_url: Base URL of the registry API (e.g., "http://localhost:8000").
        on_event: Async callback invoked for each new event.
    """

    def __init__(
        self,
        api_url: str,
        on_event: Callable[[dict], Awaitable[None]],
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.on_event = on_event
        self._last_seq: int = 0
        self._ws_buffer: list[dict] = []

    async def run(self) -> None:
        """
        Main loop: connect, catch up, listen, reconnect on failure.

        Uses websockets.connect() async iterator for automatic reconnection
        with exponential backoff (3s initial, doubling, capped ~60s).
        """
        ws_url = self.api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws/events"

        async for websocket in connect(ws_url):
            try:
                logger.info("Connected to %s", ws_url)
                await self._session(websocket)
            except ConnectionClosed:
                logger.warning("Disconnected from %s, reconnecting...", ws_url)
                continue

    async def _session(self, websocket: ClientConnection) -> None:
        """
        Handle a single WebSocket session: catch up, then listen.

        Steps:
        1. Start buffering incoming WS messages in a background task
        2. Fetch missed events via REST catch-up
        3. Process catch-up events
        4. Process buffered WS events, deduplicating by seq
        5. Listen for new events
        """
        self._ws_buffer = []
        buffer_task = asyncio.create_task(self._buffer_ws(websocket))

        try:
            await self._catch_up()

            buffer_task.cancel()
            try:
                await buffer_task
            except (asyncio.CancelledError, ConnectionClosed):
                pass
            except Exception:
                logger.debug("buffer task raised unexpected exception", exc_info=True)

            for event in self._ws_buffer:
                if event["seq"] > self._last_seq:
                    await self.on_event(event)
                    self._last_seq = event["seq"]

            async for raw in websocket:
                event = json.loads(raw)
                if event["seq"] > self._last_seq:
                    await self.on_event(event)
                    self._last_seq = event["seq"]
        finally:
            if not buffer_task.done():
                buffer_task.cancel()
                try:
                    await buffer_task
                except (asyncio.CancelledError, ConnectionClosed):
                    pass
                except Exception:
                    logger.debug("buffer task raised unexpected exception", exc_info=True)

    async def _buffer_ws(self, websocket: ClientConnection) -> None:
        """Buffer incoming WS events while catch-up is in progress."""
        try:
            async for raw in websocket:
                self._ws_buffer.append(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            raise

    async def _catch_up(self) -> None:
        """Fetch missed events via REST and process them."""
        async with httpx.AsyncClient() as client:
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
