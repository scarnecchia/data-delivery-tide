# QA Registry Implementation Plan — Phase 4: Pydantic Models

**Goal:** Request/response schemas for the API boundary — validation, serialisation, and query parameter models.

**Architecture:** Four Pydantic v2 `BaseModel` subclasses in `models.py`. FastAPI uses these for automatic request validation and OpenAPI schema generation.

**Tech Stack:** Pydantic v2 (bundled with FastAPI)

**Scope:** 6 phases from original design (phase 4 of 6)

**Codebase verified:** 2026-04-09 — greenfield, Phase 3 establishes db schema and field shapes.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### qa-registry.AC3: Validation & Error Handling (partial)
- **qa-registry.AC3.1 Failure:** `POST /deliveries` with missing required fields returns 422
- **qa-registry.AC3.2 Failure:** `POST /deliveries` with invalid `qa_status` value returns 422

Note: AC3.1 and AC3.2 are validated by Pydantic at the model layer. The 422 HTTP responses are tested in Phase 5 (routes). This phase tests that the models themselves reject invalid input.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Create models.py with all Pydantic schemas

**Files:**
- Create: `src/pipeline/registry_api/models.py`

**Implementation:**

Define four models:

1. **`DeliveryCreate(BaseModel)`** — POST body for creating/upserting deliveries. Fields:
   - `request_id: str` (required)
   - `project: str` (required)
   - `request_type: str` (required)
   - `workplan_id: str` (required)
   - `dp_id: str` (required)
   - `version: str` (required)
   - `scan_root: str` (required)
   - `qa_status: Literal["pending", "passed"]` (required)
   - `source_path: str` (required)
   - `qa_passed_at: str | None = None`
   - `file_count: int | None = None`
   - `total_bytes: int | None = None`
   - `fingerprint: str | None = None`

   Note: `delivery_id`, `first_seen_at`, `last_updated_at` are computed server-side and NOT in this model.

2. **`DeliveryUpdate(BaseModel)`** — PATCH body for partial updates. All fields optional:
   - `parquet_converted_at: str | None = None`
   - `output_path: str | None = None`
   - `qa_status: Literal["pending", "passed"] | None = None`
   - `qa_passed_at: str | None = None`

3. **`DeliveryResponse(BaseModel)`** — Full delivery record for all GET responses. All fields from the db schema:
   - `delivery_id: str`
   - `request_id: str`
   - `project: str`
   - `request_type: str`
   - `workplan_id: str`
   - `dp_id: str`
   - `version: str`
   - `scan_root: str`
   - `qa_status: str`
   - `first_seen_at: str`
   - `qa_passed_at: str | None = None`
   - `parquet_converted_at: str | None = None`
   - `file_count: int | None = None`
   - `total_bytes: int | None = None`
   - `source_path: str`
   - `output_path: str | None = None`
   - `fingerprint: str | None = None`
   - `last_updated_at: str | None = None`

4. **`DeliveryFilters(BaseModel)`** — Query params model. All fields optional:
   - `dp_id: str | None = None`
   - `project: str | None = None`
   - `request_type: str | None = None`
   - `workplan_id: str | None = None`
   - `request_id: str | None = None`
   - `qa_status: Literal["pending", "passed"] | None = None`
   - `converted: bool | None = None`
   - `version: str | None = None`
   - `scan_root: str | None = None`

Use `from typing import Literal` for the `qa_status` enum constraint.

**Step 1: Create the file with all four models**

**Step 2: Verify imports**

Run: `python -c "from pipeline.registry_api.models import DeliveryCreate, DeliveryUpdate, DeliveryResponse, DeliveryFilters; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/pipeline/registry_api/models.py
git commit -m "feat: add Pydantic request/response models for registry API"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Tests for Pydantic models

**Verifies:** qa-registry.AC3.1 (model layer), qa-registry.AC3.2 (model layer)

**Files:**
- Create: `tests/registry_api/test_models.py`

**Testing:**

Tests must verify:
- **qa-registry.AC3.1 (model layer):** `DeliveryCreate` with missing required fields raises `ValidationError` — omit `source_path`, verify Pydantic rejects it
- **qa-registry.AC3.2 (model layer):** `DeliveryCreate` with invalid `qa_status` (e.g., `"failed"`) raises `ValidationError`

Additional tests:
- `DeliveryCreate` accepts valid input with all required fields
- `DeliveryCreate` accepts valid input with optional fields included
- `DeliveryUpdate` accepts empty body (all fields are optional) — this is valid per AC3.3
- `DeliveryUpdate` with invalid `qa_status` raises `ValidationError`
- `DeliveryResponse` round-trips from dict (simulating db row)
- `DeliveryFilters` with no fields set is valid (all optional)
- `DeliveryFilters` with invalid `qa_status` raises `ValidationError`

**Verification:**

Run: `pytest tests/registry_api/test_models.py -v`
Expected: All tests pass

**Commit:** `test: add Pydantic model validation tests`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->
