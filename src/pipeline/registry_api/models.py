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
    qa_status: Literal["pending", "passed"]
    source_path: str
    qa_passed_at: str | None = None
    file_count: int | None = None
    total_bytes: int | None = None
    fingerprint: str | None = None


class DeliveryUpdate(BaseModel):
    """PATCH body for partial updates."""

    parquet_converted_at: str | None = None
    output_path: str | None = None
    qa_status: Literal["pending", "passed"] | None = None
    qa_passed_at: str | None = None


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
    qa_status: str
    first_seen_at: str
    qa_passed_at: str | None = None
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
    qa_status: Literal["pending", "passed"] | None = None
    converted: bool | None = None
    version: str | None = None
    scan_root: str | None = None
