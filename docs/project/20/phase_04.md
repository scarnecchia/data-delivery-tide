# GH20 Phase 4: Registry API — `db.py` return types

**Goal:** Define `DeliveryRecord`, `TokenRecord`, and `EventRow` frozen dataclasses (in a new `registry_api/records.py`) and update every read function in `db.py` to return them instead of `dict` / `list[dict]`. `upsert_delivery` keeps a `dict` *input* (its callers pass `model_dump()` output) but its *return* becomes `DeliveryRecord | None`.

**Architecture:** The data flow `sqlite3.Row → dict(row) → Pydantic model` becomes `sqlite3.Row → dict(row) → DeliveryRecord → DeliveryResponse.model_validate(dataclasses.asdict(record))`. `db.py` becomes the dataclass boundary; Phase 5 updates `routes.py` and `auth.py` to consume the new return types.

**Tech Stack:** Python 3.10+ stdlib `dataclasses`, sqlite3, json; no new dependencies.

**Scope:** 4 of 5 phases of GH20. Touches `src/pipeline/registry_api/db.py` (modified) and `src/pipeline/registry_api/records.py` (new). Hard blocker for Phase 5. Independent of Phases 1-3.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH20.AC4: Registry API db layer returns typed dataclasses
- **GH20.AC4.1 Success:** `DeliveryRecord`, `TokenRecord`, `EventRow` frozen dataclasses defined in `registry_api/records.py`.
- **GH20.AC4.2 Success:** `get_delivery` returns `DeliveryRecord | None`; `list_deliveries` returns `tuple[list[DeliveryRecord], int]`.
- **GH20.AC4.3 Success:** `get_token_by_hash` returns `TokenRecord | None`.
- **GH20.AC4.4 Success:** `insert_event` and `get_events_after` return `EventRow` / `list[EventRow]`.
- **GH20.AC4.8 Edge:** `upsert_delivery` still accepts a plain `dict` input; return type becomes `DeliveryRecord | None`.
- **GH20.AC4.7 Failure:** `tests/registry_api/test_db.py` passes (with the access-syntax updates documented below — see "Note on test modification" in this file).

### GH20.AC5: Cross-cutting — no serialization regression
- **GH20.AC5.1, AC5.2 Success:** Phase 5 (routes + auth) finishes the JSON-equivalence work. Phase 4 sets up the dataclass boundary.

---

## Codebase verification findings

- `src/pipeline/registry_api/db.py:213-225` — `_deserialize_metadata(row_dict)` mutates a dict in-place. After migration, this helper either:
  - (a) is removed, with metadata deserialisation inlined into each query function; or
  - (b) is renamed `_record_from_row` and refactored to take a `sqlite3.Row` and return a `DeliveryRecord`.

  Approach (b) keeps the per-query logic clean and centralises the JSON-decoding edge case (lines 220-224 currently swallow `JSONDecodeError` / `TypeError` and default to `{}`). Phase 4 implements (b).

- `src/pipeline/registry_api/db.py:228-333` — `upsert_delivery(conn, data)` returns `dict | None`. Input remains `dict`. Migration: at line 332-333, replace `return _deserialize_metadata(row_dict)` / `return None` with `return _record_from_row(row) if row else None`.

- `src/pipeline/registry_api/db.py:336-353` — `get_delivery(conn, delivery_id)` returns `dict | None`. Migration: same as `upsert_delivery`.

- `src/pipeline/registry_api/db.py:356-422` — `list_deliveries(conn, filters)` returns `tuple[list[dict], int]`. Migration: `tuple[list[DeliveryRecord], int]`. The list comprehension at line 422 becomes `[_record_from_row(row) for row in rows]`.

- `src/pipeline/registry_api/db.py:425-460` — `get_actionable(conn, lexicon_actionable)` returns `list[dict]`. Migration: `list[DeliveryRecord]`.

- `src/pipeline/registry_api/db.py:463-525` — `update_delivery(conn, delivery_id, updates)` returns `dict | None`. Migration: `DeliveryRecord | None`. Three return sites (lines 487, 500, 524) all become `_record_from_row(row) if row else None`.

- `src/pipeline/registry_api/db.py:528-538` — `get_token_by_hash(conn, token_hash)` returns `dict | None`. Migration: `TokenRecord | None`. Returns `_token_record_from_row(row) if row else None`.

- `src/pipeline/registry_api/db.py:541-584` — `insert_event(...)` returns a manually-constructed dict (lines 577-584). Migration: return `EventRow(seq=..., event_type=..., delivery_id=..., payload=..., username=..., created_at=...)`.

- `src/pipeline/registry_api/db.py:587-616` — `get_events_after(...)` returns `list[dict]`. Migration: `list[EventRow]`. The for-loop at lines 611-615 becomes a list-comp constructing `EventRow` instances with `payload=json.loads(row["payload"])`.

- `src/pipeline/registry_api/db.py:619-632` — `delivery_exists(...)` returns `bool`. Unchanged.

- `tests/registry_api/test_db.py` — uses subscript access on every read result (`result["delivery_id"]`, `result["status"]`, `result["metadata"]`, etc.). Migration: every subscript becomes attribute access. The `sample_delivery` fixture returns the `upsert_delivery` result — `sample_delivery["delivery_id"]` (lines 974, 998, 999) becomes `sample_delivery.delivery_id`. `result["seq"]` (line 1114) becomes `result.seq`. The TestInsertEvent and TestGetEventsAfter classes (lines 1008-1198) currently do `result["payload"] == payload` — this works on the `EventRow` dataclass via attribute access: `result.payload == payload`.

  An exception: line 1118 reads `row["delivery_id"]` where `row` is a `sqlite3.Row` from a direct `cursor.fetchone()` (the test bypasses the API and queries the table directly). This stays as subscript — `sqlite3.Row` supports both index and key access regardless.

- `tests/registry_api/test_auth.py:129-130` — reads `row["token_hash"]` from a direct `cursor.execute("SELECT token_hash FROM tokens ...")`. This is a `sqlite3.Row`, not a `TokenRecord`; subscript access stays.

## External dependency findings

N/A — `dataclasses` is stdlib. sqlite3 is stdlib. No external research required.

## Note on test modification

The design's AC4.7 says `test_db.py` and `test_routes.py` "pass without modification". The "Additional Considerations" section of the design contradicts this for `test_db.py`: *"any test using `result["field"]` rather than `result.field` will fail."*

This phase modifies `test_db.py` to use attribute access. No test names are added or removed; no behavioural assertions change. This is the minimum necessary change to support the dataclass return-type migration. `test_routes.py` is unaffected because it operates on `response.json()` (a dict serialised over the wire by FastAPI) — those subscript reads remain valid.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Create `src/pipeline/registry_api/records.py` with the three dataclass types

**Verifies:** GH20.AC4.1.

**Files:**
- Create: `src/pipeline/registry_api/records.py`.

**Implementation:**

```python
# pattern: Functional Core
"""Frozen dataclass records returned by db.py query functions.

These are the typed shapes the database layer hands back to routes.py
and auth.py. They mirror the SQLite column shapes one-for-one, with
metadata pre-deserialised from JSON to dict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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
    metadata: dict
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
    payload: dict
    username: str | None
    created_at: str
```

Notes:
- `from __future__ import annotations` keeps the `Literal[...]` evaluation lazy and matches the project's Python 3.10+ baseline; consistent with other registry_api modules.
- `metadata: dict` (not `dict | None`) because `_record_from_row` always defaults to `{}` if SQLite returns NULL or unparseable JSON. This matches the existing `_deserialize_metadata` semantics (lines 220-224 of `db.py`).
- `EventRow` is the chosen name (not `EventRecord`) per design's Additional Considerations: avoiding name collision with the Pydantic `EventRecord` in `models.py` when both are imported from the same module (Phase 5's `routes.py`).

**Verification:**

```bash
uv run python -c "
from dataclasses import is_dataclass, fields
from pipeline.registry_api.records import DeliveryRecord, TokenRecord, EventRow

for cls in (DeliveryRecord, TokenRecord, EventRow):
    assert is_dataclass(cls), f'{cls.__name__} must be a dataclass'
    assert cls.__dataclass_params__.frozen, f'{cls.__name__} must be frozen'

drec_fields = {f.name for f in fields(DeliveryRecord)}
expected_drec = {
    'delivery_id', 'request_id', 'project', 'request_type', 'workplan_id', 'dp_id',
    'version', 'scan_root', 'lexicon_id', 'status', 'metadata', 'first_seen_at',
    'parquet_converted_at', 'file_count', 'total_bytes', 'source_path', 'output_path',
    'fingerprint', 'last_updated_at',
}
assert drec_fields == expected_drec, drec_fields ^ expected_drec

trec_fields = {f.name for f in fields(TokenRecord)}
assert trec_fields == {'token_hash', 'username', 'role', 'created_at', 'revoked_at'}

erow_fields = {f.name for f in fields(EventRow)}
assert erow_fields == {'seq', 'event_type', 'delivery_id', 'payload', 'username', 'created_at'}
print('OK')
"
```

Expected: `OK`.

**Commit:** deferred to Task 3.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Refactor `db.py` query functions to return dataclasses; introduce `_record_from_row` and `_token_record_from_row` helpers

**Verifies:** GH20.AC4.2, GH20.AC4.3, GH20.AC4.4, GH20.AC4.8.

**Files:**
- Modify: `src/pipeline/registry_api/db.py`.

**Implementation:**

Add the records imports near the top of `db.py` (after the stdlib block):

```python
from pipeline.registry_api.records import DeliveryRecord, TokenRecord, EventRow
```

Replace `_deserialize_metadata` (lines 213-225) with two row-to-dataclass helpers:

```python
def _parse_metadata(raw: object) -> dict:
    """Decode a metadata column value to a dict.

    Falls back to {} on NULL or invalid JSON, matching the previous
    in-place mutation behaviour of _deserialize_metadata.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw  # already deserialised (defensive)
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _record_from_row(row: sqlite3.Row) -> DeliveryRecord:
    """Convert a deliveries-table row to a DeliveryRecord."""
    return DeliveryRecord(
        delivery_id=row["delivery_id"],
        request_id=row["request_id"],
        project=row["project"],
        request_type=row["request_type"],
        workplan_id=row["workplan_id"],
        dp_id=row["dp_id"],
        version=row["version"],
        scan_root=row["scan_root"],
        lexicon_id=row["lexicon_id"],
        status=row["status"],
        metadata=_parse_metadata(row["metadata"]),
        first_seen_at=row["first_seen_at"],
        parquet_converted_at=row["parquet_converted_at"],
        file_count=row["file_count"],
        total_bytes=row["total_bytes"],
        source_path=row["source_path"],
        output_path=row["output_path"],
        fingerprint=row["fingerprint"],
        last_updated_at=row["last_updated_at"],
    )


def _token_record_from_row(row: sqlite3.Row) -> TokenRecord:
    """Convert a tokens-table row to a TokenRecord."""
    return TokenRecord(
        token_hash=row["token_hash"],
        username=row["username"],
        role=row["role"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
    )
```

Update each query function:

**`upsert_delivery` (line 228):**
- Change return annotation `-> dict` to `-> DeliveryRecord | None`.
- Replace lines 330-333:

  ```python
  if row:
      return _record_from_row(row)
  return None
  ```

**`get_delivery` (line 336):**
- Change return annotation `-> dict | None` to `-> DeliveryRecord | None`.
- Replace lines 350-353:

  ```python
  if row:
      return _record_from_row(row)
  return None
  ```

**`list_deliveries` (line 356):**
- Change return annotation `-> tuple[list[dict], int]` to `-> tuple[list[DeliveryRecord], int]`.
- Replace line 422:

  ```python
  return [_record_from_row(row) for row in rows], total
  ```

**`get_actionable` (line 425):**
- Change return annotation `-> list[dict]` to `-> list[DeliveryRecord]`.
- Replace line 460:

  ```python
  return [_record_from_row(row) for row in rows]
  ```

**`update_delivery` (line 463):**
- Change return annotation `-> dict | None` to `-> DeliveryRecord | None`.
- Replace lines 484-487, 498-501, 521-525 (three sites that fetch and return). Each becomes:

  ```python
  if row:
      return _record_from_row(row)
  return None
  ```

**`get_token_by_hash` (line 528):**
- Change return annotation `-> dict | None` to `-> TokenRecord | None`.
- Replace line 538:

  ```python
  return _token_record_from_row(row) if row else None
  ```

**`insert_event` (line 541):**
- Change return annotation `-> dict` to `-> EventRow`.
- Replace lines 576-584:

  ```python
  seq = cursor.lastrowid
  return EventRow(
      seq=seq,
      event_type=event_type,
      delivery_id=delivery_id,
      payload=payload,
      username=username,
      created_at=now,
  )
  ```

  Note: the literal type of `event_type: str` argument is broader than `EventRow.event_type: Literal[...]`. The `EventRow` constructor accepts the str at runtime (frozen dataclass does no Literal validation); the typing layer is satisfied because `db.insert_event`'s string argument is constrained at the call sites (routes.py uses literal strings). If mypy strict (GH17) flags this, narrow at the call site or `cast` inside `insert_event`.

**`get_events_after` (line 587):**
- Change return annotation `-> list[dict]` to `-> list[EventRow]`.
- Replace lines 611-615:

  ```python
  result = []
  for row in rows:
      result.append(
          EventRow(
              seq=row["seq"],
              event_type=row["event_type"],
              delivery_id=row["delivery_id"],
              payload=json.loads(row["payload"]),
              username=row["username"],
              created_at=row["created_at"],
          )
      )
  return result
  ```

**`delivery_exists`** — unchanged.

Remove the now-unused `_deserialize_metadata` function entirely.

**Verification:**

```bash
uv run python -c "
import inspect
from pipeline.registry_api.db import (
    upsert_delivery, get_delivery, list_deliveries, get_actionable,
    update_delivery, get_token_by_hash, insert_event, get_events_after,
)
from pipeline.registry_api.records import DeliveryRecord, TokenRecord, EventRow

ann = {
    'upsert_delivery': 'DeliveryRecord | None',
    'get_delivery': 'DeliveryRecord | None',
    'list_deliveries': 'tuple[list[DeliveryRecord], int]',
    'get_actionable': 'list[DeliveryRecord]',
    'update_delivery': 'DeliveryRecord | None',
    'get_token_by_hash': 'TokenRecord | None',
    'insert_event': 'EventRow',
    'get_events_after': 'list[EventRow]',
}

for name, expected in ann.items():
    fn = locals().get(name)
    sig = inspect.signature(fn)
    print(f'{name}: {sig.return_annotation}')
print('OK')
"
```

Expected: each function reports the new annotation; `OK`.

**Commit:** deferred to Task 3.
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (task 3) -->
<!-- START_TASK_3 -->
### Task 3: Update `tests/registry_api/test_db.py` for attribute access; run, commit (db only)

**Verifies:** GH20.AC4.7 (test_db.py passes after the documented access-syntax updates).

**Files:**
- Modify: `tests/registry_api/test_db.py`.

**Implementation:**

Three categories of edits:

1. **Top-level subscript reads on db return values.** Every `result["X"]`, `delivery["X"]`, `sample_delivery["X"]`, `upsert_result["X"]`, `fetched["X"]` becomes `result.X` / `sample_delivery.X` / etc. The named `result`, `delivery`, etc. are the dataclass-typed return values of the db functions under test.

   Run:

   ```bash
   grep -nE 'result\["|delivery\["|sample_delivery\["|upsert_result\["|fetched\["' tests/registry_api/test_db.py
   ```

   to enumerate every site. Flagged sites already include lines 398-470, 643-644, 974, 985-1005, 1029-1118, 1270-1300 (per codebase verification).

2. **Sites where the variable is a `sqlite3.Row` (not a dataclass).** Line 1114 (`cursor.execute("SELECT * FROM events ...")` then `row = cursor.fetchone()`) and line 1118 (`assert row["delivery_id"] == "id-1"`). These stay as subscript — `sqlite3.Row` supports key access. Verify each subscript site to confirm whether the variable is a dataclass return or a `sqlite3.Row`. Heuristic: if the variable is captured from `upsert_delivery(...)`, `get_delivery(...)`, etc., it is a dataclass; if from `cursor.fetchone()`, it is a `sqlite3.Row`.

3. **`metadata` field equality assertions.** Line 986 reads `assert result["metadata"] == {"passed_at": "..."}`. After migration: `assert result.metadata == {"passed_at": "..."}`. The dataclass `metadata: dict` is identical structurally; the `==` works on dicts the same way.

4. **`EventRow.payload` reads.** Line 1031, 1067 read `result["payload"]`; migration: `result.payload`. Equality still works (`dict == dict`).

5. **Insert helper construction in TestInsertEvent / TestGetEventsAfter.** No changes needed to the call sites of `insert_event(...)`; only the assertions on the returned `EventRow` change (from subscript to attribute).

**Verification:**

```bash
uv run pytest tests/registry_api/test_db.py -v
```

Expected: all tests pass with the same count as before. No test names added or removed.

If any test fails with `TypeError: 'DeliveryRecord' object is not subscriptable`, return to step 1 and convert the offending subscript.

If any test fails with `AttributeError: 'sqlite3.Row' object has no attribute 'X'`, return to step 2 — the subscript was correct and should not have been converted.

**Commit:**

```bash
git add src/pipeline/registry_api/records.py \
        src/pipeline/registry_api/db.py \
        tests/registry_api/test_db.py
git commit -m "refactor(registry_api): db.py returns frozen dataclasses (GH20 phase 4)"
```

Phase 5 will follow with the `routes.py` and `auth.py` consumer updates as a separate commit.
<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_B -->

---

## Phase 4 Done When

- `src/pipeline/registry_api/records.py` exists and exports `DeliveryRecord`, `TokenRecord`, `EventRow` as `@dataclass(frozen=True)`.
- Every read function in `db.py` (`upsert_delivery`, `get_delivery`, `list_deliveries`, `get_actionable`, `update_delivery`, `get_token_by_hash`, `insert_event`, `get_events_after`) returns the appropriate dataclass.
- `_deserialize_metadata` is gone; `_record_from_row`, `_token_record_from_row`, `_parse_metadata` replace it.
- `tests/registry_api/test_db.py` passes with the same number of tests as before; subscript access on db returns is replaced with attribute access; subscript on `sqlite3.Row` rows is preserved.
- `routes.py`, `auth.py`, `main.py` (registry_api) — **NOT YET UPDATED**. Their callers will fail until Phase 5 lands. **Phase 4 + Phase 5 must commit in sequence on the same branch**: do not push Phase 4 to a long-lived branch without Phase 5 immediately following, because intermediate state breaks `test_routes.py` and `test_auth.py`.

## Notes for executor

- **Commit cadence:** Phase 4 commits separately from Phases 1-2-3 and from Phase 5. Both commits land before merging to main; the GH20 PR is one PR with multiple commits, but the WIP must not push Phase 4 alone to main.
- **Intermediate-state breakage:** Between Phase 4 and Phase 5 commits, `routes.py` will fail at `DeliveryResponse(**result)` (line 112) because `result` is a `DeliveryRecord` and `**result` raises `TypeError: argument after ** must be a mapping`. Phase 5 fixes this by switching to `DeliveryResponse.model_validate(dataclasses.asdict(result))`. Tests `test_routes.py` and `test_auth.py` will fail in this intermediate window — that is expected and documented.
- **`TokenInfo` construction in `auth.py`:** Phase 5 will switch `TokenInfo(username=token_row["username"], role=token_row["role"])` (line 55 of `auth.py`) to attribute access. Phase 4 leaves `auth.py` unchanged; the test failures are isolated to Phase 5's scope.
- **Conflict surface:**
  - **GH17** (ruff) — formatting; if not yet landed, run `uv run ruff format src/pipeline/registry_api/records.py src/pipeline/registry_api/db.py` after the rewrite.
  - **GH19** (annotations) — `db.py` already has return annotations; the migration replaces them. If GH19 has merged, the function signatures may already use slightly different forms (e.g. `Optional[dict]` vs `dict | None`); reconcile in favour of `| None`.
  - **GH22** (lowercase error messages) — does not touch `db.py` (per the DAG).
  - **GH23** (exception logging) — does not touch `db.py` (per the DAG).
- **`metadata` parsing edge case:** `_parse_metadata` returns `{}` for `None`, invalid JSON, or non-dict JSON values. This matches the previous `_deserialize_metadata` behaviour. The defensive `isinstance(value, dict)` guard is new — the prior code would have stored a non-dict JSON value (e.g., a list or scalar) in the row's metadata field, which would have broken downstream consumers. The new guard normalises to `{}` in that case. The change is an improvement and is unlikely to be observed in tests because the upsert path always serialises a dict.
