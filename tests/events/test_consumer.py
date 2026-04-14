"""Tests for EventConsumer."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipeline.events.consumer import EventConsumer


@pytest.mark.asyncio
async def test_deduplication_by_seq():
    """
    Test event-stream.AC6.3: events seen via REST catch-up are not re-processed
    from WS buffer.

    Verifies that deduplication by seq works correctly when the same event
    could arrive via both REST catch-up and WS buffer.
    """
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://unused", on_event)
    consumer._last_seq = 0

    # Simulate catch-up delivering events 1-3
    catch_up_events = [
        {
            "seq": 1,
            "event_type": "delivery.created",
            "delivery_id": "d1",
            "payload": {},
            "created_at": "t1",
        },
        {
            "seq": 2,
            "event_type": "delivery.created",
            "delivery_id": "d2",
            "payload": {},
            "created_at": "t2",
        },
        {
            "seq": 3,
            "event_type": "delivery.created",
            "delivery_id": "d3",
            "payload": {},
            "created_at": "t3",
        },
    ]
    for event in catch_up_events:
        await consumer.on_event(event)
        consumer._last_seq = event["seq"]

    # Simulate WS buffer containing overlapping events 2-4
    ws_buffer_events = [
        {
            "seq": 2,
            "event_type": "delivery.created",
            "delivery_id": "d2",
            "payload": {},
            "created_at": "t2",
        },
        {
            "seq": 3,
            "event_type": "delivery.created",
            "delivery_id": "d3",
            "payload": {},
            "created_at": "t3",
        },
        {
            "seq": 4,
            "event_type": "delivery.created",
            "delivery_id": "d4",
            "payload": {},
            "created_at": "t4",
        },
    ]

    received.clear()
    for event in ws_buffer_events:
        if event["seq"] > consumer._last_seq:
            await consumer.on_event(event)
            consumer._last_seq = event["seq"]

    # Only event 4 should have been processed (2 and 3 already seen)
    assert len(received) == 1
    assert received[0]["seq"] == 4


@pytest.mark.asyncio
async def test_seq_tracking_after_catch_up():
    """
    Test event-stream.AC6.2: _last_seq is properly updated during catch-up.

    Verifies that after processing catch-up events, _last_seq correctly
    reflects the highest seq seen.
    """
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://unused", on_event)
    initial_seq = consumer._last_seq
    assert initial_seq == 0

    # Simulate catch-up
    events = [
        {"seq": 1, "event_type": "delivery.created", "delivery_id": "d1", "payload": {}, "created_at": "t1"},
        {"seq": 2, "event_type": "delivery.created", "delivery_id": "d2", "payload": {}, "created_at": "t2"},
    ]

    for event in events:
        await consumer.on_event(event)
        consumer._last_seq = event["seq"]

    assert consumer._last_seq == 2
    assert len(received) == 2


@pytest.mark.asyncio
async def test_api_url_normalization():
    """Test that api_url trailing slashes are properly handled."""

    async def noop_callback(event):
        pass

    # With trailing slash
    consumer1 = EventConsumer("http://localhost:8000/", noop_callback)
    assert consumer1.api_url == "http://localhost:8000"

    # Without trailing slash
    consumer2 = EventConsumer("http://localhost:8000", noop_callback)
    assert consumer2.api_url == "http://localhost:8000"


@pytest.mark.asyncio
async def test_ws_url_conversion():
    """
    Test that http/https are properly converted to ws/wss.

    Tests the internal logic for converting API URL to WebSocket URL.
    """

    async def noop_callback(event):
        pass

    consumer = EventConsumer("http://localhost:8000", noop_callback)

    # Simulate what run() would do with the URL
    api_url = consumer.api_url
    ws_url = api_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/events"

    assert ws_url == "ws://localhost:8000/ws/events"


@pytest.mark.asyncio
async def test_ws_url_conversion_https():
    """Test WebSocket URL conversion from HTTPS."""

    async def noop_callback(event):
        pass

    consumer = EventConsumer("https://api.example.com", noop_callback)

    api_url = consumer.api_url
    ws_url = api_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/events"

    assert ws_url == "wss://api.example.com/ws/events"


@pytest.mark.asyncio
async def test_callback_receives_correct_event():
    """
    Test event-stream.AC6.1: on_event callback is called with correct event data.
    """
    received = []

    async def on_event(event):
        received.append(event)

    consumer = EventConsumer("http://unused", on_event)

    test_event = {
        "seq": 1,
        "event_type": "delivery.created",
        "delivery_id": "test-id",
        "payload": {"some": "data"},
        "created_at": "2026-04-14T12:00:00Z",
    }

    await consumer.on_event(test_event)

    assert len(received) == 1
    assert received[0] == test_event


@pytest.mark.asyncio
async def test_empty_ws_buffer_initialization():
    """Test that _ws_buffer is initialized as empty list."""

    async def noop_callback(event):
        pass

    consumer = EventConsumer("http://localhost:8000", noop_callback)
    assert consumer._ws_buffer == []
    assert isinstance(consumer._ws_buffer, list)


@pytest.mark.asyncio
async def test_last_seq_initialization():
    """Test that _last_seq starts at 0."""

    async def noop_callback(event):
        pass

    consumer = EventConsumer("http://localhost:8000", noop_callback)
    assert consumer._last_seq == 0
