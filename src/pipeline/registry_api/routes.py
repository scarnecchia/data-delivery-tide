# pattern: Imperative Shell
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Request

from pipeline.registry_api.db import (
    DbDep,
    delivery_exists,
    get_events_after,
    insert_event,
    make_delivery_id,
    upsert_delivery,
    get_delivery,
    list_deliveries,
    get_actionable,
    update_delivery,
)
from pipeline.registry_api.models import (
    DeliveryCreate,
    DeliveryUpdate,
    DeliveryResponse,
    DeliveryFilters,
    EventRecord,
)
from pipeline.registry_api.events import manager

router = APIRouter()


def _deserialize_metadata(row: dict) -> dict:
    """Deserialize metadata field from JSON string if needed.

    Modifies the row in place and returns it for chaining.
    If metadata is already a dict, leaves it unchanged.
    If metadata is a string, parses it as JSON.
    """
    if isinstance(row.get("metadata"), str):
        row["metadata"] = json.loads(row["metadata"])
    return row


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(data: DeliveryCreate, db: DbDep, request: Request):
    """
    Create or upsert a delivery.

    If a delivery with the same source_path already exists, updates its fields
    while preserving first_seen_at. Returns the created or updated delivery.

    Validates that the status is valid for the specified lexicon.
    Serializes metadata to JSON for database storage.

    Emits a delivery.created event if this is a genuinely new delivery
    (not a re-crawl of an existing one).
    """
    lexicons = request.app.state.lexicons
    lexicon = lexicons.get(data.lexicon_id)
    if lexicon is None:
        raise HTTPException(status_code=422, detail=f"unknown lexicon_id: {data.lexicon_id}")

    if data.status not in lexicon.statuses:
        raise HTTPException(
            status_code=422,
            detail=f"status '{data.status}' not valid for lexicon '{data.lexicon_id}'",
        )

    delivery_id = make_delivery_id(data.source_path)
    is_new = not delivery_exists(db, delivery_id)

    db_data = data.model_dump()
    db_data["metadata"] = json.dumps(db_data.get("metadata") if db_data.get("metadata") is not None else {})

    result = upsert_delivery(db, db_data)

    if result:
        _deserialize_metadata(result)

    if is_new:
        response = DeliveryResponse(**result)
        event = insert_event(db, "delivery.created", delivery_id, response.model_dump())
        await manager.broadcast(event)

    return result


@router.get("/deliveries", response_model=list[DeliveryResponse])
async def list_all_deliveries(db: DbDep, filters: DeliveryFilters = Depends()):
    """
    List deliveries with optional filtering.

    Query parameters:
    - dp_id, project, request_type, workplan_id, request_id, status, lexicon_id, scan_root: exact match
    - converted: boolean, True = converted, False = not converted
    - version: exact match or "latest" for highest version per (dp_id, workplan_id)
    """
    results = list_deliveries(db, filters.model_dump(exclude_none=True))
    for r in results:
        _deserialize_metadata(r)
    return results


@router.get("/deliveries/actionable", response_model=list[DeliveryResponse])
async def get_actionable_deliveries(db: DbDep, request: Request):
    """
    Get actionable deliveries (not yet converted to Parquet) based on lexicon definitions.

    Returns all deliveries where status is in the lexicon's actionable_statuses
    AND parquet_converted_at IS NULL.
    """
    lexicons = request.app.state.lexicons
    lexicon_actionable = {
        lid: list(lex.actionable_statuses)
        for lid, lex in lexicons.items()
        if lex.actionable_statuses
    }
    results = get_actionable(db, lexicon_actionable)
    for r in results:
        _deserialize_metadata(r)
    return results


@router.get("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def get_single_delivery(delivery_id: str, db: DbDep):
    """
    Retrieve a delivery by ID.

    Returns 404 if delivery not found.
    """
    result = get_delivery(db, delivery_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    _deserialize_metadata(result)
    return result


@router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(delivery_id: str, data: DeliveryUpdate, db: DbDep, request: Request):
    """
    Partially update a delivery.

    Only provided fields are updated. Empty body is a valid no-op.
    Returns 404 if delivery not found.

    Validates status transitions against lexicon definitions.
    Auto-populates metadata fields marked with set_on when status transitions.

    Emits a delivery.status_changed event if status transitions
    to a different value.
    """
    old = get_delivery(db, delivery_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    lexicons = request.app.state.lexicons
    lexicon = lexicons.get(old["lexicon_id"])

    updates = data.model_dump(exclude_none=True)
    old_status = old["status"]
    new_status = updates.get("status")

    if new_status is not None and new_status != old_status:
        if lexicon is None:
            raise HTTPException(status_code=422, detail=f"unknown lexicon_id: {old['lexicon_id']}")
        if new_status not in lexicon.statuses:
            raise HTTPException(
                status_code=422,
                detail=f"status '{new_status}' not valid for lexicon '{old['lexicon_id']}'",
            )
        allowed_transitions = lexicon.transitions.get(old_status, ())
        if new_status not in allowed_transitions:
            raise HTTPException(
                status_code=422,
                detail=f"transition from '{old_status}' to '{new_status}' not allowed for lexicon '{old['lexicon_id']}'",
            )

        # Metadata is returned from db.py deserialized as dict; handle both dict and string for safety
        metadata_val = old.get("metadata", {})
        existing_metadata = metadata_val if isinstance(metadata_val, dict) else json.loads(metadata_val or "{}")

        for field_name, field_def in lexicon.metadata_fields.items():
            if field_def.set_on == new_status:
                if field_def.type == "datetime":
                    existing_metadata[field_name] = datetime.now(timezone.utc).isoformat()
                elif field_def.type == "boolean":
                    existing_metadata[field_name] = True
                elif field_def.type == "string":
                    existing_metadata[field_name] = new_status
        updates["metadata"] = json.dumps(existing_metadata)

    elif "metadata" in updates:
        # Deep-merge metadata: preserve existing keys, merge in new keys
        metadata_val = old.get("metadata", {})
        existing_metadata = (
            metadata_val if isinstance(metadata_val, dict) else json.loads(metadata_val or "{}")
        )
        merged = {**existing_metadata, **updates["metadata"]}
        updates["metadata"] = json.dumps(merged)

    result = update_delivery(db, delivery_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    _deserialize_metadata(result)

    actual_new_status = result["status"]
    if actual_new_status != old_status:
        response = DeliveryResponse(**result)
        event = insert_event(db, "delivery.status_changed", delivery_id, response.model_dump())
        await manager.broadcast(event)

    return result


@router.get("/events", response_model=list[EventRecord])
async def get_events(db: DbDep, after: int, limit: int = 100):
    """
    Retrieve events after a given sequence number for consumer catch-up.

    Args:
        after: Return events with seq strictly greater than this value (required).
        limit: Maximum number of events to return (default 100, max 1000).

    Returns empty array if no events match.
    """
    return get_events_after(db, after, limit)
