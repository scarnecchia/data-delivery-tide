# Event Consumer

Last verified: 2026-04-14

## Purpose

Reference consumer for the registry API event stream. Demonstrates the WebSocket + REST catch-up pattern for exactly-once event processing. Intended as a starting point for downstream consumers (e.g., converter auto-trigger).

## Contracts

- **Expects**: Registry API running at a given base URL with `/ws/events` and `/events?after={seq}` endpoints
- **Guarantees**: Exactly-once processing via sequence-number deduplication; events are delivered to `on_event` callback in seq order
- **Reconnect**: Automatic reconnection with catch-up from last-seen seq; no events lost across reconnects

## Dependencies

- **Uses**: `websockets` (WebSocket client), `httpx` (REST catch-up)
- **Used by**: nothing yet (reference implementation)
- **Boundary**: no imports from registry_api internals; communicates only via HTTP/WS

## Key Files

- `consumer.py` -- EventConsumer class: connects, catches up, listens, deduplicates, calls back

## Invariants

- `_last_seq` only increases (never reset, never decremented)
- Events with seq <= `_last_seq` are silently dropped (dedup)
- Catch-up runs before processing any WebSocket messages on reconnect (buffered during catch-up)

## Gotchas

- Requires the `consumer` optional dependency group (`websockets`, `httpx`)
- The consumer is async-only; call `asyncio.run(consumer.run())` from sync code
