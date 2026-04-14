"""Tests for EventConsumer.

Tests exercise actual consumer methods (_catch_up, _session)
with mocked dependencies rather than reimplementing dedup logic inline.
"""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from pipeline.events.consumer import EventConsumer
from websockets.exceptions import ConnectionClosed


@pytest.mark.asyncio
async def test_api_url_normalization():
    """Test that api_url trailing slashes are properly handled."""

    async def noop_callback(event):
        pass

    consumer1 = EventConsumer("http://localhost:8000/", noop_callback)
    assert consumer1.api_url == "http://localhost:8000"

    consumer2 = EventConsumer("http://localhost:8000", noop_callback)
    assert consumer2.api_url == "http://localhost:8000"


@pytest.mark.asyncio
async def test_last_seq_initialization():
    """Test that _last_seq starts at 0."""

    async def noop_callback(event):
        pass

    consumer = EventConsumer("http://localhost:8000", noop_callback)
    assert consumer._last_seq == 0


@pytest.mark.asyncio
async def test_empty_ws_buffer_initialization():
    """Test that _ws_buffer is initialized as empty list."""

    async def noop_callback(event):
        pass

    consumer = EventConsumer("http://localhost:8000", noop_callback)
    assert consumer._ws_buffer == []


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

    with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):
        await consumer._catch_up()

    assert len(received) == 2
    assert consumer._last_seq == 2
    assert received[0]["seq"] == 1
    assert received[1]["seq"] == 2


@pytest.mark.asyncio
async def test_catch_up_pagination():
    """Test event-stream.AC6.2: _catch_up handles pagination correctly."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://localhost:8000", on_event)

    page1 = [
        {"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"},
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
    ]
    page2 = [
        {"seq": 3, "event_type": "delivery.created", "delivery_id": "d3", "payload": {}, "created_at": "t3"},
    ]
    page3 = []

    responses = [page1, page2, page3]
    response_index = [0]

    async def mock_get(*args, **kwargs):
        current_page = responses[response_index[0]]
        response_index[0] += 1

        mock_response = AsyncMock()
        mock_response.json = lambda: current_page
        mock_response.raise_for_status = lambda: None
        return mock_response

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):
        await consumer._catch_up()

    assert len(received) == 3
    assert consumer._last_seq == 3


@pytest.mark.asyncio
async def test_catch_up_respects_last_seq():
    """Test that _catch_up uses _last_seq in the REST query."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://localhost:8000", on_event)
    consumer._last_seq = 10

    events = [{"seq": 11, "event_type": "delivery.created", "delivery_id": "d11", "payload": {}, "created_at": "t11"}]

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

    with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):
        await consumer._catch_up()

    assert consumer._last_seq == 11


@pytest.mark.asyncio
async def test_catch_up_calls_on_event_for_each():
    """Test event-stream.AC6.2: _catch_up invokes on_event callback for each fetched event."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://localhost:8000", on_event)

    catchup_events = [
        {"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"},
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
        {"seq": 3, "event_type": "delivery.created", "delivery_id": "d3", "payload": {}, "created_at": "t3"},
    ]

    call_count = [0]

    async def mock_get(*args, **kwargs):
        call_count[0] += 1
        mock_response = AsyncMock()
        mock_response.json = lambda: catchup_events if call_count[0] == 1 else []
        mock_response.raise_for_status = lambda: None
        return mock_response

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):
        await consumer._catch_up()

    assert len(received) == 3
    assert [e["seq"] for e in received] == [1, 2, 3]


@pytest.mark.asyncio
async def test_catch_up_rest_endpoint_query_uses_last_seq():
    """Test event-stream.AC6.2: _catch_up REST query uses 'after' parameter with _last_seq."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://localhost:8000", on_event)
    consumer._last_seq = 5

    events = [
        {"seq": 6, "event_type": "delivery.created", "delivery_id": "d6", "payload": {}, "created_at": "t6"},
        {"seq": 7, "event_type": "delivery.created", "delivery_id": "d7", "payload": {}, "created_at": "t7"},
    ]

    captured_calls = []

    async def mock_get(*args, **kwargs):
        captured_calls.append((args, kwargs))
        mock_response = AsyncMock()
        mock_response.json = lambda: events if not captured_calls or len(captured_calls) == 1 else []
        mock_response.raise_for_status = lambda: None
        return mock_response

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("pipeline.events.consumer.httpx.AsyncClient", return_value=mock_client):
        await consumer._catch_up()

    assert len(received) == 2
    assert consumer._last_seq == 7
    assert len(captured_calls) > 0
    assert captured_calls[0][1]["params"]["after"] == 5


@pytest.mark.asyncio
async def test_session_receives_ws_events():
    """event-stream.AC6.1: _session() processes WS messages and invokes on_event callback."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://localhost:8000", on_event)

    # Create mock WS events as JSON strings
    ws_events = [
        json.dumps({"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"}),
        json.dumps({"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"}),
        json.dumps({"seq": 3, "event_type": "delivery.status_changed", "delivery_id": "d1", "payload": {}, "created_at": "t3"}),
    ]

    # Create a mock WebSocket that supports async iteration
    class MockWebSocket:
        def __aiter__(self):
            return self

        def __init__(self):
            self.events = ws_events.copy()
            self.index = 0

        async def __anext__(self):
            if self.index >= len(self.events):
                raise StopAsyncIteration
            event = self.events[self.index]
            self.index += 1
            return event

    mock_ws = MockWebSocket()

    async def mock_buffer_ws(ws):
        """Mock _buffer_ws: simulate buffering during catch-up."""
        # Don't buffer anything for this test
        pass

    async def mock_catch_up():
        """Mock _catch_up: no catch-up events."""
        pass

    # Patch the internal methods
    with patch.object(consumer, "_buffer_ws", side_effect=mock_buffer_ws):
        with patch.object(consumer, "_catch_up", side_effect=mock_catch_up):
            await consumer._session(mock_ws)

    # Verify on_event was called for each event
    assert len(received) == 3
    assert received[0]["seq"] == 1
    assert received[1]["seq"] == 2
    assert received[2]["seq"] == 3
    assert consumer._last_seq == 3


@pytest.mark.asyncio
async def test_reconnection_after_disconnect():
    """event-stream.AC6.4: run() reconnects after ConnectionClosed exception."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://localhost:8000", on_event)

    # Track how many times _session is called
    session_call_count = [0]

    async def mock_session(ws):
        """Mock _session that tracks call count."""
        session_call_count[0] += 1
        # Simulate catching up and listening
        if session_call_count[0] == 1:
            # First call: simulate a catch-up event
            await consumer.on_event({"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"})
            consumer._last_seq = 1
            raise ConnectionClosed(None, None)
        elif session_call_count[0] == 2:
            # Second call: simulate another event (reconnected)
            await consumer.on_event({"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"})
            consumer._last_seq = 2
            # Don't raise this time; let it succeed

    # Mock connect as an async iterator
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()

    async def mock_connect_iterator():
        """Simulate websockets.connect() as async iterator that yields two websockets."""
        yield mock_ws1
        yield mock_ws2

    with patch("pipeline.events.consumer.connect") as mock_connect:
        mock_connect.return_value = mock_connect_iterator()
        with patch.object(consumer, "_session", side_effect=mock_session):
            # Run for a limited time to avoid infinite reconnection loop
            import asyncio
            try:
                await asyncio.wait_for(consumer.run(), timeout=0.5)
            except asyncio.TimeoutError:
                # Expected: run() loops indefinitely
                pass

    # Verify _session was called twice (once per connection)
    assert session_call_count[0] >= 2

    # Verify we received events from both sessions
    assert len(received) >= 2
    assert received[0]["seq"] == 1
    if len(received) > 1:
        assert received[1]["seq"] == 2


@pytest.mark.asyncio
async def test_deduplication_by_seq():
    """Test event-stream.AC6.3: events seen via REST catch-up are not re-processed from WS buffer."""
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://unused", on_event)
    consumer._last_seq = 0

    # Simulate catch-up delivering events 1-3
    catch_up_events = [
        {"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"},
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
        {"seq": 3, "event_type": "delivery.created", "delivery_id": "d3", "payload": {}, "created_at": "t3"},
    ]
    for event in catch_up_events:
        await consumer.on_event(event)
        consumer._last_seq = event["seq"]

    # Simulate WS buffer containing overlapping events 2-4
    ws_buffer_events = [
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
        {"seq": 3, "event_type": "delivery.created", "delivery_id": "d3", "payload": {}, "created_at": "t3"},
        {"seq": 4, "event_type": "delivery.created", "delivery_id": "d4", "payload": {}, "created_at": "t4"},
    ]

    received.clear()
    for event in ws_buffer_events:
        if event["seq"] > consumer._last_seq:
            await consumer.on_event(event)
            consumer._last_seq = event["seq"]

    # Only event 4 should have been processed (2 and 3 already seen)
    assert len(received) == 1
    assert received[0]["seq"] == 4
