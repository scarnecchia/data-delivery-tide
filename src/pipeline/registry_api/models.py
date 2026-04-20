# pattern: Functional Core

import json
from typing import Literal

from pydantic import BaseModel, field_validator

METADATA_MAX_BYTES = 65_536  # 64KB


def _validate_metadata_size(v: dict | None) -> dict | None:
    """Reject metadata dicts that exceed METADATA_MAX_BYTES when serialized."""
    if v is not None:
        serialized = json.dumps(v)
        if len(serialized.encode("utf-8")) > METADATA_MAX_BYTES:
            raise ValueError(
                f"metadata exceeds maximum size of {METADATA_MAX_BYTES} bytes "
                f"({len(serialized.encode('utf-8'))} bytes serialized)"
            )
    return v


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

    @field_validator("metadata")
    @classmethod
    def check_metadata_size(cls, v):
        return _validate_metadata_size(v)


class DeliveryUpdate(BaseModel):
    """PATCH body for partial updates."""

    parquet_converted_at: str | None = None
    output_path: str | None = None
    status: str | None = None
    metadata: dict | None = None

    @field_validator("metadata")
    @classmethod
    def check_metadata_size(cls, v):
        return _validate_metadata_size(v)


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
    event_type: Literal["delivery.created", "delivery.status_changed"]
    delivery_id: str
    payload: dict
    created_at: str
