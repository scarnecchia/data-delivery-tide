# QA Registry Implementation Plan — Phase 3: Database Layer

**Goal:** SQLite schema initialisation, connection management, and all query functions for the deliveries table.

**Architecture:** Single `db.py` module with standalone query functions (no ORM, no repository class). SQLite in WAL mode on local disk. Connections managed per-request via FastAPI dependency injection with `check_same_thread=False`. `delivery_id` is a deterministic SHA-256 of `source_path`.

**Tech Stack:** Python stdlib `sqlite3`, `hashlib`

**Scope:** 6 phases from original design (phase 3 of 6)

**Codebase verified:** 2026-04-09 — greenfield, Phase 1 creates package structure, Phase 2 creates config module.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### qa-registry.AC2: Database & Query Logic
- **qa-registry.AC2.1 Success:** Upsert creates delivery with all metadata fields populated
- **qa-registry.AC2.2 Success:** Upsert preserves `first_seen_at` when re-inserting existing delivery
- **qa-registry.AC2.3 Success:** Upsert bumps `last_updated_at` when fingerprint changes
- **qa-registry.AC2.4 Success:** Upsert does NOT bump `last_updated_at` when fingerprint is unchanged
- **qa-registry.AC2.5 Success:** `list_deliveries` filters by each supported query param (`dp_id`, `project`, `request_type`, `workplan_id`, `request_id`, `qa_status`, `converted`, `scan_root`)
- **qa-registry.AC2.6 Success:** `version=latest` returns highest version per `(dp_id, workplan_id)`
- **qa-registry.AC2.7 Edge:** Multiple filters combine with AND semantics
- **qa-registry.AC2.8 Edge:** Empty filter set returns all deliveries

### qa-registry.AC3: Validation & Error Handling (partial)
- **qa-registry.AC3.4 Success:** `delivery_id` is deterministic — same `source_path` always produces same ID

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Create db.py with schema init and connection management

**Files:**
- Create: `src/pipeline/registry_api/db.py`

**Implementation:**

The `db.py` module needs these components:

1. **`make_delivery_id(source_path: str) -> str`** — returns `hashlib.sha256(source_path.encode()).hexdigest()`

2. **`init_db(db_path_or_conn: str | sqlite3.Connection) -> None`** — accepts either a file path string or an existing `sqlite3.Connection` (for testing with `:memory:` databases). If given a string, opens a connection, runs schema, and closes it. If given a connection, runs schema on it directly. Creates the `deliveries` table and indexes using the schema from the design:

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
    qa_status            TEXT NOT NULL CHECK (qa_status IN ('pending', 'passed')),
    first_seen_at        TEXT NOT NULL,
    qa_passed_at         TEXT,
    parquet_converted_at TEXT,
    file_count           INTEGER,
    total_bytes          INTEGER,
    source_path          TEXT NOT NULL UNIQUE,
    output_path          TEXT,
    fingerprint          TEXT,
    last_updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_actionable ON deliveries (qa_status, parquet_converted_at);
CREATE INDEX IF NOT EXISTS idx_dp_wp ON deliveries (dp_id, workplan_id);
CREATE INDEX IF NOT EXISTS idx_request_id ON deliveries (request_id);
```

After creating the table, enable WAL mode: `PRAGMA journal_mode=WAL;` (only when given a file path — WAL is irrelevant for in-memory databases used in tests).

3. **`get_connection(db_path: str) -> sqlite3.Connection`** — opens a connection with `check_same_thread=False` and `row_factory = sqlite3.Row`. Also sets `PRAGMA journal_mode=WAL;` on the connection to ensure WAL mode is active for each connection (WAL persists in the db file but setting it per-connection is a safe belt-and-suspenders approach).

4. **`get_db()` generator dependency** — a FastAPI dependency injection generator that:
   - Imports `settings` from `pipeline.config` (lazy import inside the function body to avoid import-time config loading issues)
   - Calls `get_connection(settings.db_path)`
   - Yields the connection
   - Closes the connection in a `finally` block

5. **`DbDep` type alias** — `Annotated[sqlite3.Connection, Depends(get_db)]` for use in route function signatures.

   These are defined in `db.py` (not `main.py`) to avoid circular imports between `main.py` and `routes.py`. Both `main.py` and `routes.py` import from `db.py`.

**Step 1: Create the file with the above functions**

**Step 2: Verify the module imports**

Run: `python -c "from pipeline.registry_api.db import init_db, get_connection, make_delivery_id, get_db, DbDep; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/pipeline/registry_api/db.py
git commit -m "feat: add db module with schema init and connection management"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Tests for schema init and delivery_id generation

**Verifies:** qa-registry.AC3.4

**Files:**
- Create: `tests/registry_api/test_db.py`

**Testing:**

Tests must verify:
- **qa-registry.AC3.4:** `make_delivery_id` produces deterministic SHA-256 hex digest — same input always produces same output, different inputs produce different outputs

Additional tests for schema init:
- `init_db` creates the `deliveries` table with all expected columns
- `init_db` is idempotent (calling twice doesn't error)
- WAL mode is enabled after `init_db`

Use `:memory:` SQLite databases for all tests (create fresh connection per test via a pytest fixture in this file or conftest).

**Verification:**

Run: `pytest tests/registry_api/test_db.py -v`
Expected: All tests pass

**Commit:** `test: add schema init and delivery_id tests`
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-4) -->
<!-- START_TASK_3 -->
### Task 3: Implement upsert_delivery

**Files:**
- Modify: `src/pipeline/registry_api/db.py`

**Implementation:**

Add `upsert_delivery(conn: sqlite3.Connection, data: dict) -> dict`:

The function should:
1. Compute `delivery_id` from `data["source_path"]` using `make_delivery_id`
2. Get current timestamp as ISO 8601 string for `first_seen_at`
3. Execute an `INSERT ... ON CONFLICT(delivery_id) DO UPDATE` statement that:
   - On insert: sets all fields including `first_seen_at` to current timestamp
   - On conflict: updates all mutable fields BUT:
     - Preserves `first_seen_at` via `COALESCE(deliveries.first_seen_at, excluded.first_seen_at)`
     - Updates `last_updated_at` conditionally: only when `excluded.fingerprint != deliveries.fingerprint` (use a CASE expression)
4. Return the full row as a dict by querying `SELECT * FROM deliveries WHERE delivery_id = ?`

The CASE expression for `last_updated_at`:
```sql
last_updated_at = CASE
    WHEN excluded.fingerprint != deliveries.fingerprint THEN excluded.last_updated_at
    ELSE deliveries.last_updated_at
END
```

Where `excluded.last_updated_at` is the current timestamp passed in the INSERT values.

**Step 1: Add the function to db.py**

**Step 2: Verify it imports**

Run: `python -c "from pipeline.registry_api.db import upsert_delivery; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/pipeline/registry_api/db.py
git commit -m "feat: add upsert_delivery with fingerprint-based change detection"
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Tests for upsert_delivery

**Verifies:** qa-registry.AC2.1, qa-registry.AC2.2, qa-registry.AC2.3, qa-registry.AC2.4

**Files:**
- Modify: `tests/registry_api/test_db.py`

**Testing:**

Tests must verify each AC:
- **qa-registry.AC2.1:** Upsert creates delivery with all metadata fields populated — insert a delivery, verify all fields are present and correct in the returned dict
- **qa-registry.AC2.2:** Upsert preserves `first_seen_at` when re-inserting existing delivery — insert, note `first_seen_at`, upsert same `source_path` with different data, verify `first_seen_at` unchanged
- **qa-registry.AC2.3:** Upsert bumps `last_updated_at` when fingerprint changes — insert with fingerprint "aaa", upsert with fingerprint "bbb", verify `last_updated_at` is updated
- **qa-registry.AC2.4:** Upsert does NOT bump `last_updated_at` when fingerprint is unchanged — insert with fingerprint "aaa", upsert with same fingerprint "aaa", verify `last_updated_at` is unchanged

For AC2.3 and AC2.4 tests, you may need a small `time.sleep(0.01)` or explicitly pass different timestamps to distinguish "changed" from "unchanged" values. Prefer explicit timestamps if the implementation supports it, otherwise use sleep.

**Verification:**

Run: `pytest tests/registry_api/test_db.py -v`
Expected: All tests pass

**Commit:** `test: add upsert_delivery tests for create, preserve, and fingerprint detection`
<!-- END_TASK_4 -->
<!-- END_SUBCOMPONENT_B -->

<!-- START_SUBCOMPONENT_C (tasks 5-6) -->
<!-- START_TASK_5 -->
### Task 5: Implement get_delivery, list_deliveries, get_actionable, update_delivery

**Files:**
- Modify: `src/pipeline/registry_api/db.py`

**Implementation:**

Add four functions:

1. **`get_delivery(conn, delivery_id: str) -> dict | None`** — `SELECT * FROM deliveries WHERE delivery_id = ?`. Return dict or None.

2. **`list_deliveries(conn, filters: dict) -> list[dict]`** — Build a dynamic WHERE clause from the filters dict. Supported filter keys:
   - `dp_id`, `project`, `request_type`, `workplan_id`, `request_id`, `qa_status`, `scan_root` — exact match with `=`
   - `converted` — boolean: if `True`, `parquet_converted_at IS NOT NULL`; if `False`, `parquet_converted_at IS NULL`
   - `version` — if `"latest"`, use a subquery: `version = (SELECT MAX(d2.version) FROM deliveries d2 WHERE d2.dp_id = deliveries.dp_id AND d2.workplan_id = deliveries.workplan_id)`; otherwise exact match
   
   All filters combine with AND. Empty filters dict returns all rows.

3. **`get_actionable(conn) -> list[dict]`** — `SELECT * FROM deliveries WHERE qa_status = 'passed' AND parquet_converted_at IS NULL`

4. **`update_delivery(conn, delivery_id: str, updates: dict) -> dict | None`** — Build a dynamic `UPDATE deliveries SET ... WHERE delivery_id = ?` from the updates dict. Only update keys that are present. Return the updated row or None if delivery_id not found. Allowed update keys: `parquet_converted_at`, `output_path`, `qa_status`, `qa_passed_at`. **If `updates` is empty, skip the UPDATE statement entirely** (an empty SET clause is invalid SQL) — just query and return the current row via SELECT, or None if the delivery_id doesn't exist.

All functions should use parameterized queries to prevent SQL injection.

**Step 1: Add the four functions to db.py**

**Step 2: Verify imports**

Run: `python -c "from pipeline.registry_api.db import get_delivery, list_deliveries, get_actionable, update_delivery; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/pipeline/registry_api/db.py
git commit -m "feat: add get, list, actionable, and update query functions"
```
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Tests for query functions

**Verifies:** qa-registry.AC2.5, qa-registry.AC2.6, qa-registry.AC2.7, qa-registry.AC2.8

**Files:**
- Modify: `tests/registry_api/test_db.py`

**Testing:**

Tests must verify each AC:
- **qa-registry.AC2.5:** `list_deliveries` filters by each supported query param — insert multiple deliveries with different `dp_id`, `project`, `request_type`, `workplan_id`, `request_id`, `qa_status`, `scan_root`, `converted` values. For each filter param, call `list_deliveries` with just that filter and verify correct subset returned. Pay special attention to the `converted` boolean filter which uses `IS NULL`/`IS NOT NULL` SQL (not `=`): test `converted=True` returns only deliveries where `parquet_converted_at` is set, and `converted=False` returns only those where it is NULL.
- **qa-registry.AC2.6:** `version=latest` returns highest version per `(dp_id, workplan_id)` — insert deliveries for same `(dp_id, workplan_id)` with versions `v01`, `v02`, `v03`. Filter with `version="latest"`, verify only `v03` returned.
- **qa-registry.AC2.7:** Multiple filters combine with AND semantics — filter with two params simultaneously, verify only rows matching BOTH are returned.
- **qa-registry.AC2.8:** Empty filter set returns all deliveries — insert 3 deliveries, call `list_deliveries({})`, verify all 3 returned.

Additional tests:
- `get_delivery` returns correct row for existing delivery_id
- `get_delivery` returns None for nonexistent delivery_id
- `get_actionable` returns only deliveries with `qa_status='passed'` and `parquet_converted_at IS NULL`
- `get_actionable` excludes deliveries with `qa_status='pending'`
- `get_actionable` excludes deliveries already converted
- `update_delivery` updates only specified fields
- `update_delivery` returns None for nonexistent delivery_id
- `update_delivery` with empty dict is a no-op (returns the unchanged row)

Create a helper function or fixture that inserts a delivery with sensible defaults, accepting overrides for specific fields. This avoids repeating the full delivery dict in every test.

**Verification:**

Run: `pytest tests/registry_api/test_db.py -v`
Expected: All tests pass

**Commit:** `test: add query function tests for list, get, actionable, and update`
<!-- END_TASK_6 -->
<!-- END_SUBCOMPONENT_C -->
