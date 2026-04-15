# Lexicon System Implementation Plan — Phase 3: Database Schema Update

**Goal:** Replace `qa_status`/`qa_passed_at` columns with generic `status`/`lexicon_id`/`metadata` columns in the SQLite schema and update all DB functions and Pydantic models.

**Architecture:** Fresh schema (no migration) — `qa_status` → `status`, `qa_passed_at` removed, `lexicon_id` and `metadata` (JSON TEXT) columns added. CHECK constraint on `qa_status` removed (validation moves to app layer in Phase 4). Index updated to include `lexicon_id`. Pydantic models updated to match.

**Tech Stack:** Python 3.10+, sqlite3 stdlib, Pydantic

**Scope:** Phase 3 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### lexicon-system.AC3: Database schema
- **lexicon-system.AC3.1 Success:** Delivery created with `lexicon_id`, `status`, and `metadata` fields
- **lexicon-system.AC3.2 Success:** `metadata` JSON round-trips correctly through upsert and query
- **lexicon-system.AC3.3 Success:** Actionable query returns deliveries matching per-lexicon `actionable_statuses`
- **lexicon-system.AC3.4 Success:** Actionable query works across multiple lexicons with different actionable statuses
- **lexicon-system.AC3.5 Success:** List/filter deliveries by `lexicon_id` and `status`

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Update database schema DDL and DB functions

**Verifies:** None (infrastructure — tested in Task 3)

**Files:**
- Modify: `src/pipeline/registry_api/db.py:40-86` (schema DDL, indexes)
- Modify: `src/pipeline/registry_api/db.py:138-231` (upsert_delivery)
- Modify: `src/pipeline/registry_api/db.py:250-304` (list_deliveries)
- Modify: `src/pipeline/registry_api/db.py:307-324` (get_actionable)
- Modify: `src/pipeline/registry_api/db.py:327-377` (update_delivery)

**Implementation:**

**Schema DDL changes** in `init_db()` (lines 40-86):

Replace the deliveries CREATE TABLE statement. Key changes:
- `qa_status` → `status TEXT NOT NULL` (remove CHECK constraint — validation at app layer)
- Remove `qa_passed_at`
- Add `lexicon_id TEXT NOT NULL`
- Add `metadata TEXT DEFAULT '{}'`

```sql
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id          TEXT PRIMARY KEY,
    request_id           TEXT NOT NULL,
    project              TEXT NOT NULL,
    request_type         TEXT NOT NULL,
    workplan_id          TEXT NOT NULL,
    dp_id                TEXT NOT NULL,
    version              TEXT NOT NULL,
    scan_root            TEXT NOT NULL,
    lexicon_id           TEXT NOT NULL,
    status               TEXT NOT NULL,
    metadata             TEXT DEFAULT '{}',
    first_seen_at        TEXT NOT NULL,
    parquet_converted_at TEXT,
    file_count           INTEGER,
    total_bytes          INTEGER,
    source_path          TEXT NOT NULL UNIQUE,
    output_path          TEXT,
    fingerprint          TEXT,
    last_updated_at      TEXT
)
```

Update indexes:
- Replace `idx_actionable` with `(lexicon_id, status, parquet_converted_at)` — supports actionable queries scoped by lexicon
- Keep `idx_dp_wp` as-is: `(dp_id, workplan_id)`
- Keep `idx_request_id` as-is
- Add new `idx_lexicon`: `(lexicon_id)` — for filtering by delivery type

```sql
CREATE INDEX IF NOT EXISTS idx_actionable ON deliveries (lexicon_id, status, parquet_converted_at)
CREATE INDEX IF NOT EXISTS idx_dp_wp ON deliveries (dp_id, workplan_id)
CREATE INDEX IF NOT EXISTS idx_request_id ON deliveries (request_id)
CREATE INDEX IF NOT EXISTS idx_lexicon ON deliveries (lexicon_id)
```

**upsert_delivery** changes (lines 138-231):

Replace `qa_status` with `status`, `qa_passed_at` with nothing, add `lexicon_id` and `metadata`:

- Column list: replace `qa_status` → `status`, remove `qa_passed_at`, add `lexicon_id`, `metadata`
- VALUES: replace `data.get("qa_status")` → `data.get("status")`, remove `data.get("qa_passed_at")`, add `data.get("lexicon_id")`, `data.get("metadata", "{}")`
- ON CONFLICT SET: replace `qa_status` → `status`, remove `qa_passed_at`, add `lexicon_id`, `metadata`

**list_deliveries** changes (lines 250-304):

Update `exact_match_fields` list at line 274: replace `"qa_status"` with `"status"`, add `"lexicon_id"`.

```python
exact_match_fields = ["dp_id", "project", "request_type", "workplan_id", "request_id", "status", "lexicon_id", "scan_root"]
```

**get_actionable** changes (lines 307-324):

The current implementation hardcodes `qa_status = 'passed'`. The lexicon-driven version must accept a mapping of `lexicon_id → actionable_statuses` so it can build a dynamic WHERE clause. Update signature:

```python
def get_actionable(conn: sqlite3.Connection, lexicon_actionable: dict[str, list[str]]) -> list[dict]:
```

Build OR conditions for each lexicon's actionable statuses:

```python
def get_actionable(conn: sqlite3.Connection, lexicon_actionable: dict[str, list[str]]) -> list[dict]:
    cursor = conn.cursor()

    conditions = []
    params = []
    for lex_id, statuses in lexicon_actionable.items():
        placeholders = ", ".join("?" for _ in statuses)
        conditions.append(f"(lexicon_id = ? AND status IN ({placeholders}))")
        params.append(lex_id)
        params.extend(statuses)

    if not conditions:
        return []

    where = " OR ".join(conditions)
    cursor.execute(
        f"SELECT * FROM deliveries WHERE ({where}) AND parquet_converted_at IS NULL",
        params,
    )

    rows = cursor.fetchall()
    return [dict(row) for row in rows]
```

**update_delivery** changes (lines 327-377):

Update `allowed_fields` at line 352: replace `"qa_status"` with `"status"`, replace `"qa_passed_at"` with `"metadata"`.

```python
allowed_fields = {"parquet_converted_at", "output_path", "status", "metadata"}
```

**Commit:** `feat: update database schema from qa_status to lexicon-driven status/metadata`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update Pydantic models

**Verifies:** None (infrastructure — model changes, tested in Task 3)

**Files:**
- Modify: `src/pipeline/registry_api/models.py` (all models)

**Implementation:**

**DeliveryCreate** (lines 8-23):

Replace `qa_status: Literal["pending", "passed", "failed"]` with `status: str` (runtime validation in Phase 4).
Remove `qa_passed_at: str | None = None`.
Add `lexicon_id: str` and `metadata: dict | None = None`.

```python
class DeliveryCreate(BaseModel):
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
```

**DeliveryUpdate** (lines 26-33):

Replace `qa_status` with `status`, remove `qa_passed_at`, add `metadata`.

```python
class DeliveryUpdate(BaseModel):
    parquet_converted_at: str | None = None
    output_path: str | None = None
    status: str | None = None
    metadata: dict | None = None
```

**DeliveryResponse** (lines 35-55):

Replace `qa_status` with `status`, remove `qa_passed_at`, add `lexicon_id` and `metadata`.

```python
class DeliveryResponse(BaseModel):
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
```

**DeliveryFilters** (lines 58-69):

Replace `qa_status` with `status`, add `lexicon_id`.

```python
class DeliveryFilters(BaseModel):
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
```

**EventRecord** — no changes needed (payload is untyped `dict`).

**Commit:** `feat: update Pydantic models from qa_status to status/lexicon_id/metadata`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Minimal routes.py field renames for consistency

**Verifies:** None (infrastructure — keeps routes compatible with DB and model changes)

**Files:**
- Modify: `src/pipeline/registry_api/routes.py:111-116` (PATCH handler field references)
- Modify: `src/pipeline/registry_api/routes.py:64` (docstring reference to qa_status)

**Implementation:**

The DB schema and Pydantic models now use `status` instead of `qa_status`. Routes must reference the correct field names or they'll break at runtime. This is a minimal rename — full lexicon validation logic is added in Phase 4.

In the PATCH handler at `routes.py:111`:
```python
# Old:
old_status = old["qa_status"]
# New:
old_status = old["status"]
```

At `routes.py:116`:
```python
# Old:
new_status = result["qa_status"]
# New:
new_status = result["status"]
```

Update the list endpoint docstring at line 64: replace `qa_status` with `status` in the query parameters description.

**Commit:** `refactor: rename qa_status -> status in routes.py for DB/model consistency`

<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 4-5) -->
<!-- Note: Task numbering shifted due to addition of Task 3 (routes field rename) -->
<!-- START_TASK_4 -->
### Task 4: Update existing DB and route tests, write new schema tests

**Verifies:** lexicon-system.AC3.1, lexicon-system.AC3.2, lexicon-system.AC3.3, lexicon-system.AC3.4, lexicon-system.AC3.5

**Files:**
- Modify: `tests/registry_api/test_routes.py` (update all `qa_status` references to `status`, add `lexicon_id`, replace `qa_passed_at` with `metadata`)
- Modify: `tests/conftest.py` (if `make_delivery_payload` helper exists there — update field names)
- Create or modify: test file with new AC3 tests

**Implementation:**

All existing tests reference `qa_status` and `qa_passed_at` in payload dicts. These must be updated to `status`, `lexicon_id`, and `metadata`. The `make_delivery_payload` helper (if present in test code) needs `lexicon_id` added and field renames.

**Testing:**

Tests must verify each AC listed above:

- **lexicon-system.AC3.1:** Upsert a delivery with `lexicon_id`, `status`, and `metadata` fields. Assert the returned row has all three fields populated correctly.
- **lexicon-system.AC3.2:** Upsert a delivery with `metadata` as `{"passed_at": "2026-04-14T12:00:00Z"}`. Query it back. Assert `metadata` round-trips as valid JSON with the same content.
- **lexicon-system.AC3.3:** Insert deliveries for one lexicon. Call `get_actionable()` with that lexicon's `actionable_statuses`. Assert only deliveries matching the actionable statuses (and not yet converted) are returned.
- **lexicon-system.AC3.4:** Insert deliveries across two lexicons with different actionable statuses. Call `get_actionable()` with both lexicons' actionable statuses. Assert correct results for each lexicon.
- **lexicon-system.AC3.5:** Insert deliveries with different `lexicon_id` and `status` values. Call `list_deliveries()` with `lexicon_id` filter. Assert only matching deliveries returned. Repeat with `status` filter.

Follow project testing patterns: use `test_db` fixture (in-memory SQLite), direct SQL verification alongside function calls.

**Verification:**

```bash
uv run pytest tests/registry_api/ -v
```

Expected: All tests pass — existing updated + new AC3 tests.

**Commit:** `test: update route tests and add AC3.1-AC3.5 coverage for lexicon schema`

<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Run full test suite, verify no regressions

**Verifies:** None (regression check)

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: All tests pass. Note: the crawler tests still use `qa_status` field names in their fixtures — those will be updated in Phase 5 (Crawler Generalisation). Crawler tests should still pass at this point because the crawler code hasn't been modified yet. If any crawler tests call into registry DB functions, they may need temporary adjustments.

**Commit:** No commit if clean. Fix commit if needed: `fix: resolve test regression from database schema update`

<!-- END_TASK_5 -->
<!-- END_SUBCOMPONENT_B -->
