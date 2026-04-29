# GH20 Phase 5: Registry API — callers of the db layer

**Goal:** Update `routes.py` and `auth.py` to consume the `DeliveryRecord` / `TokenRecord` / `EventRow` dataclasses from Phase 4. Replace every `DeliveryResponse(**dict)` with `DeliveryResponse.model_validate(dataclasses.asdict(record))`, every `token_row["X"]` with `token_row.X`, and every `old["X"]` with `old.X`.

**Architecture:** Phase 4 turned `db.py` into the dataclass boundary; Phase 5 makes the consumers conform. Pydantic `model_validate` accepts a plain dict (from `dataclasses.asdict`) and runs validators just like the old `**dict` constructor did. The wire shape (JSON over HTTP, JSON over WebSocket) is identical because `model_dump()` is unchanged and the dataclass fields exactly mirror the SQLite columns.

**Tech Stack:** Python 3.10+ stdlib `dataclasses`, FastAPI/Pydantic v2; no new dependencies.

**Scope:** 5 of 5 phases of GH20. Touches `src/pipeline/registry_api/routes.py` and `src/pipeline/registry_api/auth.py`. Hard-depends on Phase 4 (records.py and updated db.py return types must exist). Closes the GH20 issue.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH20.AC4: Registry API db layer returns typed dataclasses (consumer side)
- **GH20.AC4.5 Success:** Routes call `DeliveryResponse.model_validate(dataclasses.asdict(record))` instead of passing the raw dict.
- **GH20.AC4.6 Success:** `auth.py` uses `TokenRecord` attribute access for `.username`, `.role`, `.revoked_at`.
- **GH20.AC4.7 Failure:** `tests/registry_api/test_routes.py`, `test_auth.py`, `test_events.py` pass without modification (these tests inspect HTTP responses and `sqlite3.Row` rows directly — neither shape changes).

### GH20.AC5: Cross-cutting — no serialization regression
- **GH20.AC5.1 Success:** JSON responses from all GET endpoints byte-for-byte equivalent before and after the migration.
- **GH20.AC5.2 Success:** WebSocket broadcast payloads unchanged.
- **GH20.AC5.4 Failure:** Dataclass field access on a missing key fails loudly at construction time (any DB row missing a column raises `KeyError` inside `_record_from_row`, not silently returning `None` later).

---

## Codebase verification findings

- `src/pipeline/registry_api/routes.py:21-29` — currently imports `EventRecord` from `models.py` (the Pydantic class). Phase 5 must NOT also import `EventRecord` from the new `records.py`. Phase 4 named the db dataclass `EventRow` precisely to avoid this collision. No changes to the import block other than (optional) adding `import dataclasses` for the `asdict()` calls.

- `src/pipeline/registry_api/routes.py:106-114` — `result = upsert_delivery(db, db_data)` then `response = DeliveryResponse(**result)`. After Phase 4, `result` is a `DeliveryRecord` dataclass. Migration: `response = DeliveryResponse.model_validate(dataclasses.asdict(result))`.

  Then `return result` at line 116 returns a `DeliveryRecord` to FastAPI. FastAPI's `response_model=DeliveryResponse` uses Pydantic to serialise the return; with a dataclass, FastAPI's serialisation will fail at runtime because Pydantic `model_validate` is called on the dataclass instance and tries to use `.model_validate(record)` rather than `.model_validate(asdict(record))`. The fix: return `dataclasses.asdict(result)` instead of `result`, OR construct the Pydantic response explicitly and return it.

  **Decision:** return `dataclasses.asdict(result)` from each route. This is the simpler change (one-line per route) and matches the existing flow where FastAPI receives a dict and serialises it. The alternative (constructing the Pydantic instance) requires the route to know about `DeliveryResponse`; the dict path is more decoupled.

- `src/pipeline/registry_api/routes.py:130-140` — `list_all_deliveries` returns `PaginatedDeliveryResponse(items=items, total=total, ...)`. After Phase 4, `items` is `list[DeliveryRecord]`. Pydantic v2's `PaginatedDeliveryResponse(items=...)` constructor will not accept dataclass items via the model. Migration: convert to dicts before constructing the response:

  ```python
  items_data = [dataclasses.asdict(item) for item in items]
  return PaginatedDeliveryResponse(
      items=items_data, total=total, limit=filters.limit, offset=filters.offset,
  )
  ```

- `src/pipeline/registry_api/routes.py:143-157` — `get_actionable_deliveries` returns `get_actionable(db, lexicon_actionable)` which is now `list[DeliveryRecord]`. Migration: `return [dataclasses.asdict(d) for d in get_actionable(db, lexicon_actionable)]`.

- `src/pipeline/registry_api/routes.py:160-170` — `get_single_delivery`. Migration: `return dataclasses.asdict(result)` if result else 404.

- `src/pipeline/registry_api/routes.py:173-256` — `update_single_delivery`:
  - Line 193: `old = get_delivery(db, delivery_id)` — `old` is now `DeliveryRecord | None`.
  - Line 198: `lexicon = lexicons.get(old["lexicon_id"])` → `lexicon = lexicons.get(old.lexicon_id)`.
  - Line 201: `old_status = old["status"]` → `old_status = old.status`.
  - Line 206: `f"unknown lexicon_id: {old['lexicon_id']}"` → `f"unknown lexicon_id: {old.lexicon_id}"`.
  - Line 210: `f"... not valid for lexicon '{old['lexicon_id']}'"` → `f"... not valid for lexicon '{old.lexicon_id}'"`.
  - Line 216: same.
  - Lines 220-221: `metadata_val = old.get("metadata", {})` — `old` is a dataclass, no `.get()`. Replace with `metadata_val = old.metadata` (always a dict, no fallback needed because `_parse_metadata` always returns `{}`). Then drop the `isinstance(metadata_val, dict)` guard (it is unconditionally a dict from the dataclass).

    Concretely:
    ```python
    existing_metadata = dict(old.metadata)  # copy to avoid mutating the dataclass-held dict
    if "metadata" in updates and isinstance(updates["metadata"], dict):
        existing_metadata = {**existing_metadata, **updates["metadata"]}
    ```
  - Lines 237-244: same pattern in the `elif "metadata" in updates:` branch.
  - Line 246: `result = update_delivery(db, delivery_id, updates)` — result is now `DeliveryRecord | None`.
  - Line 250: `actual_new_status = result["status"]` → `actual_new_status = result.status`.
  - Line 252: `response = DeliveryResponse(**result)` → `response = DeliveryResponse.model_validate(dataclasses.asdict(result))`.
  - Line 256: `return result` → `return dataclasses.asdict(result)`.

- `src/pipeline/registry_api/routes.py:259-270` — `get_events`:
  - Return is `list[EventRow]`. Migration: `return [dataclasses.asdict(e) for e in get_events_after(db, after, limit)]`.

- `src/pipeline/registry_api/routes.py:273-288` — `emit_event`:
  - Line 286: `event = insert_event(...)` — result is now `EventRow`.
  - Line 287: `await manager.broadcast(event)` — broadcast accepts a dict shape per `events.py`. Migration: `event_dict = dataclasses.asdict(event); await manager.broadcast(event_dict)`. Then `return event_dict`.

  The previous `insert_event` returned a dict directly to `manager.broadcast`; now we serialise. Wire shape preserved.

- `src/pipeline/registry_api/routes.py:113-114` (delivery.created broadcast):
  - `event = insert_event(db, "delivery.created", delivery_id, response.model_dump(), username=token.username)` returns `EventRow` after Phase 4.
  - `await manager.broadcast(event)` — same fix as above. Migration:

    ```python
    event = insert_event(db, "delivery.created", delivery_id, response.model_dump(), username=token.username)
    await manager.broadcast(dataclasses.asdict(event))
    ```

- `src/pipeline/registry_api/routes.py:253-254` (delivery.status_changed broadcast) — same pattern.

- `src/pipeline/registry_api/auth.py:30-55` — `require_auth`:
  - Line 47: `token_row = get_token_by_hash(db, token_hash)` — now `TokenRecord | None`.
  - Line 49: `if token_row is None:` — unchanged (the `is None` check works on a dataclass-or-None).
  - Line 52: `if token_row["revoked_at"] is not None:` → `if token_row.revoked_at is not None:`.
  - Line 55: `return TokenInfo(username=token_row["username"], role=token_row["role"])` → `return TokenInfo(username=token_row.username, role=token_row.role)`.

- `src/pipeline/registry_api/main.py` — does not consume the changed return types directly (only calls `init_db` and uses `DbDep`); no edits required. Verify with grep.

- `tests/registry_api/test_routes.py` — operates on `response.json()` (JSON dict over HTTP). The `event = events[0]` pattern reads from the `get_events(db)` test helper at line 33, which serialises `sqlite3.Row` to dict via `{**dict(row), "payload": json.loads(...)}` — that helper is unchanged and still returns dicts. No edits required to `test_routes.py` for Phase 5.

- `tests/registry_api/test_auth.py` — line 47 (`token_row = get_token_by_hash(db, token_hash)`) is in production code. The test reads at lines 126-130 query the `tokens` table directly via `cursor.execute(...)`, returning `sqlite3.Row` instances. Subscript stays. No edits required.

- `tests/registry_api/test_events.py` — operates on the `manager` (ConnectionManager) and on response.json(); does not consume db return types directly. No edits required.

## External dependency findings

N/A. FastAPI's `response_model` machinery supports both dicts and Pydantic-model returns from route handlers. Returning a dict is the prior pattern; this phase preserves it.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Update `src/pipeline/registry_api/auth.py` to use `TokenRecord` attribute access

**Verifies:** GH20.AC4.6.

**Files:**
- Modify: `src/pipeline/registry_api/auth.py`.

**Implementation:**

Two edits at lines 52 and 55:

```python
# was:
if token_row["revoked_at"] is not None:
    raise HTTPException(status_code=401, detail="Token has been revoked")

return TokenInfo(username=token_row["username"], role=token_row["role"])

# becomes:
if token_row.revoked_at is not None:
    raise HTTPException(status_code=401, detail="Token has been revoked")

return TokenInfo(username=token_row.username, role=token_row.role)
```

No other changes; the `is None` check at line 49 is unchanged (None vs. dataclass works identically to None vs. dict).

**Verification:**

```bash
uv run pytest tests/registry_api/test_auth.py -v
```

Expected: all `test_auth.py` tests pass.

```bash
grep -nE "token_row\[" src/pipeline/registry_api/auth.py
```

Expected: zero matches.

**Commit:** deferred to Task 3.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update `src/pipeline/registry_api/routes.py` to consume dataclasses via `dataclasses.asdict()` and attribute access

**Verifies:** GH20.AC4.5, GH20.AC5.1, GH20.AC5.2.

**Files:**
- Modify: `src/pipeline/registry_api/routes.py`.

**Implementation:**

Add `import dataclasses` to the stdlib import block at the top of the file.

Apply the edits enumerated in "Codebase verification findings" above. The full per-route edit list:

1. **`create_delivery` (lines 70-116):**
   - Line 112-113:
     ```python
     response = DeliveryResponse.model_validate(dataclasses.asdict(result))
     event = insert_event(db, "delivery.created", delivery_id, response.model_dump(), username=token.username)
     await manager.broadcast(dataclasses.asdict(event))
     ```
   - Line 116: `return dataclasses.asdict(result)`.

2. **`list_all_deliveries` (lines 119-140):**
   ```python
   filter_dict = filters.model_dump(exclude_none=True)
   items, total = list_deliveries(db, filter_dict)
   return PaginatedDeliveryResponse(
       items=[dataclasses.asdict(item) for item in items],
       total=total,
       limit=filters.limit,
       offset=filters.offset,
   )
   ```

3. **`get_actionable_deliveries` (lines 143-157):**
   ```python
   return [dataclasses.asdict(d) for d in get_actionable(db, lexicon_actionable)]
   ```

4. **`get_single_delivery` (lines 160-170):**
   ```python
   result = get_delivery(db, delivery_id)
   if result is None:
       raise HTTPException(status_code=404, detail="Delivery not found")
   return dataclasses.asdict(result)
   ```

5. **`update_single_delivery` (lines 173-256):** the longest patch — replace every dict subscript on `old` and `result` with attribute access. Detailed edits (cite line in pre-migration `routes.py`):
   - Line 198: `lexicon = lexicons.get(old.lexicon_id)`
   - Line 201: `old_status = old.status`
   - Line 206: `f"unknown lexicon_id: {old.lexicon_id}"`
   - Line 210: `f"status '{new_status}' not valid for lexicon '{old.lexicon_id}'"`
   - Line 216: `f"transition from '{old_status}' to '{new_status}' not allowed for lexicon '{old.lexicon_id}'"`
   - Lines 220-221:
     ```python
     existing_metadata = dict(old.metadata)
     ```
   - Drop the `isinstance(metadata_val, dict) else json.loads(metadata_val or "{}")` guard — `old.metadata` is always a dict from Phase 4.
   - Line 224 (inside the `if new_status is not None` branch):
     ```python
     if "metadata" in updates and isinstance(updates["metadata"], dict):
         existing_metadata = {**existing_metadata, **updates["metadata"]}
     ```
     (No change here from pre-migration code; the only change above is `existing_metadata = dict(old.metadata)`.)
   - Lines 237-244 (the `elif "metadata" in updates:` branch):
     ```python
     elif "metadata" in updates:
         existing_metadata = dict(old.metadata)
         merged = {**existing_metadata, **updates["metadata"]}
         updates["metadata"] = json.dumps(merged)
     ```
   - Line 250: `actual_new_status = result.status`
   - Lines 252-254:
     ```python
     response = DeliveryResponse.model_validate(dataclasses.asdict(result))
     event = insert_event(db, "delivery.status_changed", delivery_id, response.model_dump(), username=token.username)
     await manager.broadcast(dataclasses.asdict(event))
     ```
   - Line 256: `return dataclasses.asdict(result)`

6. **`get_events` (lines 259-270):**
   ```python
   return [dataclasses.asdict(e) for e in get_events_after(db, after, limit)]
   ```

7. **`emit_event` (lines 273-288):**
   ```python
   if get_delivery(db, data.delivery_id) is None:
       raise HTTPException(status_code=404, detail="Delivery not found")
   event = insert_event(db, data.event_type, data.delivery_id, data.payload, username=token.username)
   event_dict = dataclasses.asdict(event)
   await manager.broadcast(event_dict)
   return event_dict
   ```

**Verification:**

```bash
uv run pytest tests/registry_api/test_routes.py tests/registry_api/test_events.py -v
```

Expected: all tests pass.

```bash
grep -nE 'old\["|result\["|token_row\["' src/pipeline/registry_api/routes.py
```

Expected: zero matches.

JSON-equivalence sanity check (compare a sample response shape before/after — only meaningful if you have a `git stash` of the pre-migration code; otherwise the test suite's `response.json()` assertions cover this):

```bash
uv run pytest tests/registry_api/test_routes.py::TestGetSingleDelivery -v
uv run pytest tests/registry_api/test_routes.py::TestPatchDelivery -v
```

Expected: pass.

**Commit:** deferred to Task 3.
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (task 3) -->
<!-- START_TASK_3 -->
### Task 3: Run the full test suite, commit Phase 5

**Verifies:** GH20.AC5.1, GH20.AC5.2 (suite-wide regression check).

**Files:** none changed in this task.

**Implementation:**

```bash
uv run pytest -x
```

Expected: all tests pass. The full suite includes crawler, converter, registry_api, events, lexicons. Phases 1-4 should already pass; Phase 5 closes the loop on routes/auth.

If `test_routes.py` reports any test failure with `'DeliveryRecord' object is not subscriptable`, the offending site in `routes.py` was missed — return to Task 2's edit list.

If `test_routes.py` reports `TypeError: argument after ** must be a mapping`, a `DeliveryResponse(**result)` call was missed — return to Task 2.

If `test_events.py` (consumer-side WebSocket fan-out) reports any payload mismatch, inspect `manager.broadcast(...)` arguments — both call sites must pass `dataclasses.asdict(event)` not `event`.

**Commit:**

```bash
git add src/pipeline/registry_api/routes.py src/pipeline/registry_api/auth.py
git commit -m "refactor(registry_api): consume db dataclasses via asdict + attribute access (GH20 phase 5)"
```
<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_B -->

---

## Phase 5 Done When

- `auth.py:require_auth` reads `token_row.revoked_at`, `token_row.username`, `token_row.role` via attribute access.
- Every route handler in `routes.py` returns `dataclasses.asdict(record)` (or `[dataclasses.asdict(r) for r in records]` for list routes).
- `DeliveryResponse(**result)` is replaced everywhere by `DeliveryResponse.model_validate(dataclasses.asdict(result))`.
- `manager.broadcast(...)` always receives a dict (`dataclasses.asdict(event)`).
- `tests/registry_api/test_routes.py`, `test_auth.py`, `test_events.py` pass with the same number of tests as before; no test names added or removed.
- `uv run pytest -x` passes the full suite.

## Notes for executor

- **Commit cadence:** Phase 5 is the final commit of the GH20 series. Phases 1+2 commit together; Phase 3 commits independently; Phase 4 commits independently; Phase 5 commits independently. Total: 4 commits on the security-hardening branch.
- **Wire-shape invariant:** the JSON shape of every response is unchanged. The dataclass→dict bridge happens at the route boundary, not at the Pydantic model boundary. Pydantic still produces the same JSON because `dataclasses.asdict(record)` produces the same dict that `dict(sqlite3.Row)` + `_deserialize_metadata` produced before.
- **`update_single_delivery` is the largest patch.** Take the time to walk every `old["X"]` and `result["X"]` reference and confirm replacement. The `existing_metadata = dict(old.metadata)` copy guard is important: `old.metadata` is the dataclass-held dict; mutating it would mutate the frozen dataclass's internal state (not raise, but pollute future reads in the same request scope).
- **Conflict surface:**
  - **GH22** (lowercase error messages) touches the same `routes.py` error strings (lines 95, 100, 206, 210, 216 of pre-migration). If GH22 has merged, the lowercased strings are already there — the Phase 5 edits replace the dict subscripts but leave the f-string casing alone.
  - **GH17** (ruff) — formatting; if not yet landed, run `uv run ruff format src/pipeline/registry_api/routes.py src/pipeline/registry_api/auth.py` after the rewrite.
  - **GH19** (annotations) — already merged at Tier 1; routes.py signatures are already annotated. Phase 5 doesn't change them.
- **`response_model=DeliveryResponse` keeps working with dict returns** — FastAPI passes the dict through Pydantic's validation/serialisation. This is the prior behaviour; Phase 5 preserves it.
- **Why not return the Pydantic model directly?** Returning `DeliveryResponse.model_validate(dataclasses.asdict(result))` from the route would also work, and is equally valid. The choice to return the dict matches the prior code's "FastAPI sees a dict, runs response_model serialisation" pattern. Either is acceptable; the implementation chose the smaller-diff option.
