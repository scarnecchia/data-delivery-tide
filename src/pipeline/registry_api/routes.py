# pattern: Imperative Shell
import json
import posixpath
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from pipeline.registry_api.auth import TokenInfo, require_auth, require_role
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
    EventCreate,
    EventRecord,
    PaginatedDeliveryResponse,
)
from pipeline.registry_api.events import manager

public_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(require_auth)])


def _validate_source_path(source_path: str, scan_roots: list) -> None:
    """
    Validate that source_path resolves within a configured scan_root.

    Normalizes the path (collapsing .. and .) and checks it starts with at least
    one scan_root path. Raises HTTPException 422 if invalid.
    """
    if not source_path.startswith("/"):
        raise HTTPException(
            status_code=422,
            detail=f"source_path must be an absolute path, got: {source_path}",
        )

    # Normalize to collapse .. and . components
    normalized = posixpath.normpath(source_path)

    # Check against scan roots
    for root in scan_roots:
        root_path = root.path.rstrip("/")
        if normalized == root_path or normalized.startswith(root_path + "/"):
            return

    raise HTTPException(
        status_code=422,
        detail=f"source_path '{source_path}' is not within any configured scan_root",
    )


@public_router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@protected_router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(
    data: DeliveryCreate,
    db: DbDep,
    request: Request,
    token: TokenInfo = require_role("write"),  # type: ignore[assignment]
) -> dict:
    """
    Create or upsert a delivery.

    If a delivery with the same source_path already exists, updates its fields
    while preserving first_seen_at. Returns the created or updated delivery.

    Validates that the status is valid for the specified lexicon.
    Serializes metadata to JSON for database storage.

    Emits a delivery.created event if this is a genuinely new delivery
    (not a re-crawl of an existing one).
    """
    # Validate source_path is within a configured scan_root
    _validate_source_path(data.source_path, request.app.state.scan_roots)

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
    db_data["metadata"] = json.dumps(
        db_data.get("metadata") if db_data.get("metadata") is not None else {}
    )

    result = upsert_delivery(db, db_data)

    if is_new:
        response = DeliveryResponse(**result)
        event = insert_event(
            db, "delivery.created", delivery_id, response.model_dump(), username=token.username
        )
        await manager.broadcast(event)

    return result


@protected_router.get("/deliveries", response_model=PaginatedDeliveryResponse)
async def list_all_deliveries(
    db: DbDep, filters: DeliveryFilters = Depends()
) -> PaginatedDeliveryResponse:
    """
    List deliveries with optional filtering and pagination.

    Query parameters:
    - dp_id, project, request_type, workplan_id, request_id, status, lexicon_id, scan_root: exact match
    - converted: boolean, True = converted, False = not converted
    - version: exact match or "latest" for highest version per (dp_id, workplan_id)
    - limit: max results per page (default 100, max 1000)
    - offset: number of results to skip (default 0)

    Response includes items, total count, limit, and offset for pagination.
    """
    filter_dict = filters.model_dump(exclude_none=True)
    items, total = list_deliveries(db, filter_dict)
    return PaginatedDeliveryResponse(
        items=items,
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@protected_router.get("/deliveries/actionable", response_model=list[DeliveryResponse])
async def get_actionable_deliveries(db: DbDep, request: Request) -> list[dict]:
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
    return get_actionable(db, lexicon_actionable)


@protected_router.get("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def get_single_delivery(delivery_id: str, db: DbDep) -> dict:
    """
    Retrieve a delivery by ID.

    Returns 404 if delivery not found.
    """
    result = get_delivery(db, delivery_id)
    if result is None:
        raise HTTPException(status_code=404, detail="delivery not found")
    return result


@protected_router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(
    delivery_id: str,
    data: DeliveryUpdate,
    db: DbDep,
    request: Request,
    token: TokenInfo = require_role("write"),  # type: ignore[assignment]
) -> dict:
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
        raise HTTPException(status_code=404, detail="delivery not found")

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
        existing_metadata = (
            metadata_val if isinstance(metadata_val, dict) else json.loads(metadata_val or "{}")
        )

        # Merge user-supplied metadata first, then apply set_on overrides
        if "metadata" in updates and isinstance(updates["metadata"], dict):
            existing_metadata = {**existing_metadata, **updates["metadata"]}

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
        raise HTTPException(status_code=404, detail="delivery not found")

    actual_new_status = result["status"]
    if actual_new_status != old_status:
        response = DeliveryResponse(**result)
        event = insert_event(
            db,
            "delivery.status_changed",
            delivery_id,
            response.model_dump(),
            username=token.username,
        )
        await manager.broadcast(event)

    return result


@protected_router.get("/events", response_model=list[EventRecord])
async def get_events(db: DbDep, after: int, limit: int = 100) -> list[dict]:
    """
    Retrieve events after a given sequence number for consumer catch-up.

    Args:
        after: Return events with seq strictly greater than this value (required).
        limit: Maximum number of events to return (default 100, max 1000).

    Returns empty array if no events match.
    """
    return get_events_after(db, after, limit)


@protected_router.post("/events", response_model=EventRecord, status_code=201)
async def emit_event(
    data: EventCreate,
    db: DbDep,
    token: TokenInfo = require_role("write"),  # type: ignore[assignment]
) -> dict:
    """
    Emit a converter lifecycle event.

    Verifies the delivery exists, persists the event via insert_event,
    and broadcasts to connected WebSocket clients.

    Returns 404 if the delivery does not exist.
    """
    if get_delivery(db, data.delivery_id) is None:
        raise HTTPException(status_code=404, detail="delivery not found")

    event = insert_event(
        db, data.event_type, data.delivery_id, data.payload, username=token.username
    )
    await manager.broadcast(event)
    return event
