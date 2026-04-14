"""Tests for EventConsumer.

Tests exercise actual consumer methods (_catch_up, _session)
with mocked dependencies rather than reimplementing dedup logic inline.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from pipeline.events.consumer import EventConsumer


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
