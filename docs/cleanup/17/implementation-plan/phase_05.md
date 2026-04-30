# GH17 Phase 5 — Generic type arguments and type-narrowing fixes

**Goal:** Resolve `[type-arg]`, `[dict-item]`, `[union-attr]`, `[arg-type]`, `[return-value]`, and `[no-any-return]` errors. These are real type bugs surfaced by strict mode — fixing them tightens correctness, doesn't just silence noise.

**Architecture:** Each error fixed at the smallest correct scope. Most are bare `dict`/`list` annotations that need parameterising. A handful are genuine logic gaps (e.g., `union-attr` on `Any | None` patterns from pyreadstat metadata) that require a guard or `cast()`.

**Tech Stack:** Python typing, mypy 1.10+.

**Scope:** 5 of 6 phases.

**Codebase verified:** 2026-04-29 — concrete error inventory from `uv run --with mypy mypy --strict src/pipeline/` at planning time:

- ✓ **42 `[type-arg]`** errors — bare `dict` and `list` parameter/return types. Primary locations:
  - `db.py:425, 463, 528, 545, 547, 591` (bare `dict` returns/params on db helpers — but verified at planning time these are already `dict | None`/`dict[str, Any]` partly; mypy may flag the bare `dict` keyword form)
  - `convert.py:24, 48` (bare `dict` in `ConversionMetadata` field)
  - `engine.py:109, 168` (bare `dict` in local var annotations)
  - `routes.py:36` (bare `list` parameter in `_validate_source_path`)
  - `daemon.py:166` (bare `dict` parameter in `_on_event(event: dict)`)
  - `auth_cli.py` (bare `dict` in row helpers)
  - Plus ~30 more across the codebase
- ✓ **5 `[dict-item]`** errors at `engine.py:228-232` — the `event_payload` dict has mixed value types (`str | int | None`). Need to type the dict explicitly.
- ✓ **2 `[union-attr]`** errors at `convert.py:192, 206` — `getattr(file_metadata_obj, "column_labels", None)` returns `Any | None`, then code accesses `.names` on the result. Needs a guard or `cast()`.
- ✓ **1 `[arg-type]`** at `routes.py:136` — `PaginatedDeliveryResponse(items=items, ...)` where `items` is `list[dict[Any, Any]]` but the field expects `list[DeliveryResponse]`. The fix: explicit construction of `DeliveryResponse` instances OR Pydantic validator handles the conversion (need to verify).
- ✓ **2 `[return-value]`** errors in crawler/manifest area — `manifest.py` shape mismatches.
- ✓ **2 `[no-any-return]`** errors — functions return `Any` from `getattr`-style chains; explicit `cast()` or guard.
- ✓ **2 `[assignment]`** errors in crawler — `CrawlManifest` vs `dict[Any, Any]` shape mismatches indicate `manifest.py` needs proper TypedDict declaration.

---

## Acceptance Criteria Coverage

- **GH17.AC5.1 (type-arg cleared):** `uv run mypy src/pipeline/ 2>&1 | grep -c "type-arg"` returns 0.
- **GH17.AC5.2 (dict-item cleared):** Same for `dict-item`.
- **GH17.AC5.3 (union-attr cleared):** Same for `union-attr`.
- **GH17.AC5.4 (arg-type cleared):** Same for `arg-type`.
- **GH17.AC5.5 (return-value cleared):** Same for `return-value`.
- **GH17.AC5.6 (no-any-return cleared):** Same for `no-any-return`.
- **GH17.AC5.7 (Other assignment errors cleared):** Same for `assignment` errors not addressed by Phase 4.
- **GH17.AC5.8 (No regressions):** `uv run pytest` exits 0.

---

<!-- START_TASK_1 -->
### Task 1: Fix `[type-arg]` — parameterise bare `dict` and `list`

**Verifies:** GH17.AC5.1

**Files:** Every file flagged by `uv run mypy src/pipeline/ 2>&1 | grep "type-arg"`. Concentrate on `db.py`, `convert.py`, `engine.py`, `routes.py`, `daemon.py`, `auth_cli.py`, and any others.

**Implementation:**

**Step 1: Inventory**

```bash
uv run mypy src/pipeline/ 2>&1 | grep "type-arg" > /tmp/gh17-type-arg.txt
wc -l /tmp/gh17-type-arg.txt
```

**Step 2: For each location, parameterise the bare type.**

Decision rules (apply in order):

1. **If the value's structure is known** (e.g., `dict[str, str]`, `list[FileEntry]`), use the precise type.
2. **If the value is a JSON payload** with mixed shapes, use `dict[str, Any]` (and import `from typing import Any` at the top of the file).
3. **If the value is row data from sqlite3.Row converted to dict**, use `dict[str, Any]` — sqlite3 row factory yields heterogeneous values.
4. **If a function returns a dict that is reused via `**kwargs`-like patterns**, `dict[str, Any]` is the honest annotation.

**Specific known fixes (verified at planning time):**

- `routes.py:36` — `def _validate_source_path(source_path: str, scan_roots: list) -> None:` → change `list` to `list[ScanRoot]`. Add `from pipeline.config import ScanRoot` (TYPE_CHECKING guard if needed). **Wait — `routes.py` already imports from `pipeline.registry_api.*`; check that GH19 Phase 2 Task 5 didn't already touch this signature.** If GH19 has annotated this function, this fix may already be in.
- `daemon.py:166` — `async def _on_event(self, event: dict) -> None:` → change `dict` to `dict[str, Any]`.
- `convert.py:24` — `column_labels: dict` field on `ConversionMetadata` dataclass → `dict[str, str]` (verified by inspecting how it's built at `convert.py:43`).
- `convert.py:48` — `value_labels: dict` → `dict[str, dict[Any, str]]` (verify shape from pyreadstat docs; if uncertain, `dict[str, dict[Any, Any]]` is the honest fallback).
- `engine.py:109` — `failures: dict` local → `dict[str, dict[str, Any]]` (per `engine.py:127-132` where each value is a 4-key dict).
- `engine.py:168` — `patch_body: dict` local → `dict[str, Any]`.
- `db.py:425, 463, etc.` — most are `dict` return types; change to `dict[str, Any]`.
- `auth_cli.py` row-handling helpers — `dict[str, Any]`.

For each of the ~42 hits, apply the appropriate annotation.

**Step 3: Verify**

```bash
uv run mypy src/pipeline/ 2>&1 | grep -c "type-arg"
```

Expected: 0.

**Step 4: Tests**

```bash
uv run pytest
```

Expected: zero failures.

**Commit:**

```bash
git add src/pipeline/
git commit -m "feat: parameterise bare dict and list types under mypy strict (#17)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Fix `engine.py:228-232` `[dict-item]` errors

**Verifies:** GH17.AC5.2

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/engine.py:225-234`

**Implementation:**

Read the current `event_payload` construction at `engine.py:225-234` (verified at planning time):

```python
    event_payload = {
        "delivery_id": delivery_id,
        "output_path": str(parquet_dir),
        "file_count": len(successes),
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "failed_count": len(failures),
        "wrote_at": wrote_at,
    }
    http_module.emit_event(api_url, "conversion.completed", delivery_id, event_payload)
```

Mypy infers the dict's value type from the FIRST entry (`str`), then complains that subsequent `int` values don't match. The fix: declare the dict's value type explicitly.

Replace with:

```python
    event_payload: dict[str, Any] = {
        "delivery_id": delivery_id,
        "output_path": str(parquet_dir),
        "file_count": len(successes),
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "failed_count": len(failures),
        "wrote_at": wrote_at,
    }
    http_module.emit_event(api_url, "conversion.completed", delivery_id, event_payload)
```

(Add `from typing import Any` to engine.py imports if not already present — verify against current file state. GH19's Phase 3 Task 1 may have added it.)

**Step 1: Apply the edit**

**Step 2: Verify**

```bash
uv run mypy src/pipeline/converter/engine.py 2>&1 | grep "dict-item"
```

Expected: no output.

**Step 3: Tests**

```bash
uv run pytest tests/converter/test_engine.py
```

Expected: zero failures.

**Commit:**

```bash
git add src/pipeline/converter/engine.py
git commit -m "fix: type event_payload dict explicitly (#17)"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Fix `convert.py:192, 206` `[union-attr]` errors

**Verifies:** GH17.AC5.3

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/convert.py:185-210` (the trailing `ConversionMetadata` construction)

**Implementation:**

Read `convert.py:185-212`. The relevant lines:

```python
    column_labels_out = _build_column_labels(
        list(locked_schema.names),
        getattr(file_metadata_obj, "column_labels", None) if file_metadata_obj else None,
    )
    value_labels_out = (
        getattr(file_metadata_obj, "variable_value_labels", {}) or {}
        if file_metadata_obj else {}
    )
    sas_encoding_out = (
        getattr(file_metadata_obj, "file_encoding", "") or ""
        if file_metadata_obj else ""
    )
```

Wait — re-read more carefully. The `union-attr` errors at lines 192 and 206 likely come from `locked_schema.names` access where `locked_schema` is `pa.Schema | None`. After the `if writer is None:` empty-file handling, `locked_schema` is set to a non-None schema, but mypy can't trace that across the control flow.

**Step 1: Confirm the exact error**

```bash
uv run mypy src/pipeline/converter/convert.py 2>&1 | grep "union-attr"
```

Expected output should look like:

```
src/pipeline/converter/convert.py:192: error: Item "None" of "pa.Schema | None" has no attribute "names"  [union-attr]
```

**Step 2: Apply the appropriate guard**

The clean fix is an `assert` (which mypy honours for narrowing):

```python
    assert locked_schema is not None  # set in either branch above
    column_labels_out = _build_column_labels(
        list(locked_schema.names),
        getattr(file_metadata_obj, "column_labels", None) if file_metadata_obj else None,
    )
```

Add the `assert` after the existing control-flow that establishes `locked_schema` as non-None (after the `if writer is None:` block resolves). The runtime cost is one boolean check; the mypy benefit is full narrowing for the rest of the function.

If the actual error is different (e.g., on `file_metadata_obj.names` instead of `locked_schema.names`), apply an analogous guard at the appropriate location.

**Step 3: Verify**

```bash
uv run mypy src/pipeline/converter/convert.py 2>&1 | grep "union-attr"
```

Expected: no output.

**Step 4: Tests**

```bash
uv run pytest tests/converter/test_convert.py
```

Expected: zero failures. (The `assert` cannot fire — every path to that point sets `locked_schema`.)

**Commit:**

```bash
git add src/pipeline/converter/convert.py
git commit -m "fix: narrow locked_schema type with assert in convert_sas_to_parquet (#17)"
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Fix `routes.py:136` `[arg-type]` error

**Verifies:** GH17.AC5.4

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:119-140`

**Implementation:**

Read the `list_all_deliveries` handler at `routes.py:119-140`:

```python
@protected_router.get("/deliveries", response_model=PaginatedDeliveryResponse)
async def list_all_deliveries(
    db: DbDep, filters: DeliveryFilters = Depends()
) -> PaginatedDeliveryResponse:
    filter_dict = filters.model_dump(exclude_none=True)
    items, total = list_deliveries(db, filter_dict)
    return PaginatedDeliveryResponse(
        items=items,
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )
```

`items` is `list[dict[Any, Any]]` (from `list_deliveries`), but `PaginatedDeliveryResponse.items` is `list[DeliveryResponse]`. Pydantic v2 will validate-and-construct the dicts into `DeliveryResponse` instances at runtime, but mypy can't see through that because the `BaseModel.__init__` signature is typed strictly.

**The fix:** explicitly construct the `DeliveryResponse` list:

```python
@protected_router.get("/deliveries", response_model=PaginatedDeliveryResponse)
async def list_all_deliveries(
    db: DbDep, filters: DeliveryFilters = Depends()  # noqa: B008
) -> PaginatedDeliveryResponse:
    filter_dict = filters.model_dump(exclude_none=True)
    items, total = list_deliveries(db, filter_dict)
    return PaginatedDeliveryResponse(
        items=[DeliveryResponse.model_validate(item) for item in items],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )
```

`DeliveryResponse.model_validate(item)` is the Pydantic v2 idiom for "construct from a dict". Mypy will see the list comprehension's type as `list[DeliveryResponse]` and accept it.

**Caveat:** if `DeliveryResponse` is already imported in `routes.py` (it is — verified at line 24 in current file), no new import needed.

**Upstream note:** GH20 Phase 5 will rewrite this expression again when deliveries become frozen dataclasses. This edit is correct for the post-GH19 codebase state; the GH20 executor will rebuild it on top of dataclass returns.

**Step 1: Apply the edit**

**Step 2: Verify**

```bash
uv run mypy src/pipeline/registry_api/routes.py 2>&1 | grep "arg-type"
```

Expected: no output.

**Step 3: Tests**

```bash
uv run pytest tests/registry_api/test_routes.py
```

Expected: zero failures. The wire response is identical (Pydantic produces the same JSON either way).

**Commit:**

```bash
git add src/pipeline/registry_api/routes.py
git commit -m "fix: explicit DeliveryResponse construction in list_all_deliveries (#17)"
```
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Fix remaining `[return-value]`, `[no-any-return]`, and `[assignment]` errors

**Verifies:** GH17.AC5.5, GH17.AC5.6, GH17.AC5.7

**Files:** Whatever mypy flags. Per planning-time data, concentrated in `crawler/manifest.py`, `crawler/main.py`, `lexicons/loader.py` (post-GH19).

**Implementation:**

**Step 1: Inventory**

```bash
uv run mypy src/pipeline/ 2>&1 | grep -E "\[(return-value|no-any-return|assignment)\]" > /tmp/gh17-misc-errors.txt
cat /tmp/gh17-misc-errors.txt
```

**Step 2: For each error, apply the smallest correct fix.** Common patterns:

- **`[return-value]` on `manifest.py`** functions returning shape mismatches: usually fixed by typing the local var with the correct `TypedDict` (e.g., `CrawlManifest`) at construction, so the return path matches. Read the function, identify what kind of dict it builds, declare a `TypedDict` matching that shape if one doesn't exist.
- **`[no-any-return]`** on functions that return values from `Any`-typed expressions (e.g., `getattr(meta, "x", default)`): use `cast(ReturnType, expression)` from `typing`, or restructure to avoid the `Any`-typed step.
- **`[assignment]`** mismatches: usually a local var was declared with a wrong type early; correct the declaration.

**Step 3: Verify**

```bash
uv run mypy src/pipeline/ 2>&1 | grep -cE "\[(return-value|no-any-return|assignment)\]"
```

Expected: 0.

**Step 4: Final mypy check**

```bash
uv run mypy src/pipeline/ 2>&1 | tail -5
```

Expected: only `[import-untyped]` errors remain (Phase 6's responsibility).

**Step 5: Tests**

```bash
uv run pytest
```

Expected: zero failures.

**Commit:**

```bash
git add src/pipeline/
git commit -m "fix: resolve return-value, no-any-return, and assignment errors (#17)"
```
<!-- END_TASK_5 -->

---

## Phase Done When

- `uv run mypy src/pipeline/ 2>&1 | grep -cE "\[(type-arg|dict-item|union-attr|arg-type|return-value|no-any-return|assignment)\]"` returns 0.
- The only remaining mypy errors are `[import-untyped]` (Phase 6).
- `uv run pytest` exits 0.
- `uv run ruff check src/ tests/` exits 0.

## Out of Scope

- `[import-untyped]` for pandas/pyarrow/pyreadstat — Phase 6.
- Adding new `TypedDict` declarations beyond what's strictly necessary to clear errors — out of scope unless the current dict-shaped types make the fixes obscure.

## Notes for the implementor

- Phase 5 is the highest-risk phase in GH17. `[union-attr]` and `[no-any-return]` errors can mask real null-deref or type-laundering bugs. Read the surrounding control flow before adding a `cast()` — if the cast is wrong, mypy stays green but the bug ships.
- `[dict-item]` and `[arg-type]` fixes via explicit annotations (`dict[str, Any]`) shift the precision burden onto the caller. That's correct here — the dicts are wire-format payloads where `Any` is honest.
- If `[return-value]` errors in crawler/manifest area are extensive (>3), it suggests `manifest.py` needs a `TypedDict` declaration. Consult the user before introducing one — a `TypedDict` is a non-trivial API surface.
- Phase 5 sets up Phase 6: only `[import-untyped]` should remain after Task 5 commits.
