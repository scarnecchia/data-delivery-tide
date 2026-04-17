# pattern: Functional Core

from typing import Literal

from pydantic import BaseModel


class DeliveryCreate(BaseModel):
    """POST body for creating/upserting deliveries."""

    request_id: str
    project: str
    request_type: str
    workplan_id: str
    dp_id: str
    version: str
    scan_root: str
    lexicon_id: str
    status: str
    source_path: str
    metadata: dict | None = None
    file_count: int | None = None
    total_bytes: int | None = None
    fingerprint: str | None = None


class DeliveryUpdate(BaseModel):
    """PATCH body for partial updates."""

    parquet_converted_at: str | None = None
    output_path: str | None = None
    status: str | None = None
    metadata: dict | None = None


class DeliveryResponse(BaseModel):
    """Full delivery record for all GET responses."""

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
    metadata: dict | None = None
    first_seen_at: str
    parquet_converted_at: str | None = None
    file_count: int | None = None
    total_bytes: int | None = None
    source_path: str
    output_path: str | None = None
    fingerprint: str | None = None
    last_updated_at: str | None = None


class DeliveryFilters(BaseModel):
    """Query params model for filtering deliveries."""

    dp_id: str | None = None
    project: str | None = None
    request_type: str | None = None
    workplan_id: str | None = None
    request_id: str | None = None
    status: str | None = None
    lexicon_id: str | None = None
    converted: bool | None = None
    version: str | None = None
    scan_root: str | None = None


class EventRecord(BaseModel):
    """Persisted event record for delivery lifecycle changes."""

    seq: int
    event_type: Literal[
        "delivery.created",
        "delivery.status_changed",
        "conversion.completed",
        "conversion.failed",
    ]
    delivery_id: str
    payload: dict
    created_at: str
