# pattern: Imperative Shell
from fastapi import APIRouter, HTTPException, Depends

from pipeline.registry_api.db import (
    DbDep,
    delivery_exists,
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
)
from pipeline.registry_api.events import manager

router = APIRouter()


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(data: DeliveryCreate, db: DbDep):
    """
    Create or upsert a delivery.

    If a delivery with the same source_path already exists, updates its fields
    while preserving first_seen_at. Returns the created or updated delivery.

    Emits a delivery.created event if this is a genuinely new delivery
    (not a re-crawl of an existing one).
    """
    delivery_id = make_delivery_id(data.source_path)
    is_new = not delivery_exists(db, delivery_id)

    result = upsert_delivery(db, data.model_dump())

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
    - dp_id, project, request_type, workplan_id, request_id, qa_status, scan_root: exact match
    - converted: boolean, True = converted, False = not converted
    - version: exact match or "latest" for highest version per (dp_id, workplan_id)
    """
    results = list_deliveries(db, filters.model_dump(exclude_none=True))
    return results


@router.get("/deliveries/actionable", response_model=list[DeliveryResponse])
async def get_actionable_deliveries(db: DbDep):
    """
    Get actionable deliveries (passed QA but not yet converted to Parquet).

    Returns all deliveries where qa_status='passed' AND parquet_converted_at IS NULL.
    """
    results = get_actionable(db)
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
    return result


@router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(delivery_id: str, data: DeliveryUpdate, db: DbDep):
    """
    Partially update a delivery.

    Only provided fields are updated. Empty body is a valid no-op.
    Returns 404 if delivery not found.

    Emits a delivery.status_changed event if qa_status transitions
    to a different value.
    """
    old = get_delivery(db, delivery_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    old_status = old["qa_status"]
    result = update_delivery(db, delivery_id, data.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")

    new_status = result["qa_status"]
    if new_status != old_status:
        response = DeliveryResponse(**result)
        event = insert_event(db, "delivery.status_changed", delivery_id, response.model_dump())
        await manager.broadcast(event)

    return result
