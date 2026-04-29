# pattern: Functional Core
"""Frozen dataclass records returned by db.py query functions.

These are the typed shapes the database layer hands back to routes.py
and auth.py. They mirror the SQLite column shapes one-for-one, with
metadata pre-deserialised from JSON to dict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class DeliveryRecord:
    """Mirror of the deliveries table columns, post metadata-deserialise."""

    delivery_id: str
    request_id: str
    project: str
    request_type: str
    workplan_id: str
    dp_id: str
    version: str
    scan_root: str
    lexicon_id: str
    status: str
    metadata: dict[str, Any]
    first_seen_at: str
    parquet_converted_at: str | None
    file_count: int | None
    total_bytes: int | None
    source_path: str
    output_path: str | None
    fingerprint: str | None
    last_updated_at: str | None


@dataclass(frozen=True)
class TokenRecord:
    """Mirror of the tokens table columns."""

    token_hash: str
    username: str
    role: Literal["admin", "write", "read"]
    created_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class EventRow:
    """Mirror of the events table row, with payload deserialised from JSON.

    Named EventRow (not EventRecord) to avoid shadowing the Pydantic
    EventRecord defined in pipeline.registry_api.models when both are
    imported into the same module.
    """

    seq: int
    event_type: Literal[
        "delivery.created",
        "delivery.status_changed",
        "conversion.completed",
        "conversion.failed",
    ]
    delivery_id: str
    payload: dict[str, Any]
    username: str | None
    created_at: str
