# GH20 Phase 3: Converter engine accumulation types

**Goal:** Replace the bare `list[tuple[str, int, int]]` and `dict[str, dict]` accumulators in `converter/engine.py` with frozen dataclasses (`FileConversionSuccess` and `FileConversionFailure`). Use attribute access for aggregations and `dataclasses.asdict()` when building the PATCH body and event payload.

**Architecture:** Pure type-layer substitution inside the converter's Imperative Shell. The HTTP wire shape (PATCH body, POST /events payload) is unchanged because `dataclasses.asdict(failure)` produces the same dict shape as the previous dict-literal construction. No new modules; new types live alongside `ConversionResult` at the top of `engine.py`.

**Tech Stack:** Python 3.10+ stdlib `dataclasses`; no new dependencies.

**Scope:** 3 of 5 phases of GH20. Touches `src/pipeline/converter/engine.py`. Independent of all other phases — `engine.py` has no import from Phases 1-2 modules and is not imported by Phases 4-5.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH20.AC3: Converter engine accumulation types are dataclasses
- **GH20.AC3.1 Success:** `successes` list holds `FileConversionSuccess` instances with `.filename`, `.row_count`, `.bytes_written` fields.
- **GH20.AC3.2 Success:** `failures` dict values are `FileConversionFailure` instances with `.error_class`, `.message`, `.at`, `.converter_version` fields.
- **GH20.AC3.3 Success:** `total_rows`, `total_bytes`, and `converted_files` aggregations use attribute access on `FileConversionSuccess`.
- **GH20.AC3.4 Success:** The `patch_body` and `event_payload` dicts built from `failures` serialise identically to the current output (use `dataclasses.asdict()`).
- **GH20.AC3.5 Failure:** Existing `test_engine.py` assertions on patch body shapes pass without modification (the on-the-wire dict shape is preserved).

---

## Codebase verification findings

- `src/pipeline/converter/engine.py:14-18` — `ConversionResult` already exists as a frozen dataclass. The new types follow the same pattern.
- `src/pipeline/converter/engine.py:108-109` — `successes: list[tuple[str, int, int]]` and `failures: dict[str, dict]`. The accumulators are local to `convert_one`. All reads of `successes` happen inside `convert_one` (lines 209-211); all reads of `failures` happen inside `convert_one` (lines 168-194, 220-221).
- `src/pipeline/converter/engine.py:127-132` — failures dict literal: `{"class": error_class, "message": str(exc)[:500], "at": now, "converter_version": converter_version}`. The "class" key collides with Python's builtin in attribute form, so the dataclass field is named `error_class` (per the design AC3.2). The wire-shape mapping is `{"class": failure.error_class, ...}` — done explicitly when building the patch body, not via `asdict()`.

  **Subtlety:** `dataclasses.asdict(FileConversionFailure(error_class='X', ...))` produces `{'error_class': 'X', ...}`, which **does not** match the existing wire shape (`{'class': 'X', ...}`). The fix is to use a custom translation when constructing `patch_body` and `event_payload` rather than a bare `asdict()` call. Two acceptable implementations:

  - **Option A (preferred for explicitness):** build the dict by hand with the right keys:

    ```python
    failure_dict = {
        "class": failure.error_class,
        "message": failure.message,
        "at": failure.at,
        "converter_version": failure.converter_version,
    }
    ```

  - **Option B:** post-process `asdict()` to rename the key:

    ```python
    failure_dict = dataclasses.asdict(failure)
    failure_dict["class"] = failure_dict.pop("error_class")
    ```

  Option A is preferred because it documents the wire shape inline at the construction site. The design's AC3.4 says "use `dataclasses.asdict()`" but its intent is "preserve wire shape" — reading the design literally would change the wire shape, which AC3.5 forbids. This phase implements Option A and notes the deviation explicitly.

- `src/pipeline/converter/engine.py:127-132` (failures dict, again) — the **dict key** in `failures[sas_file.name]` is the SAS filename. That's the *outer* dict; its value type changes from `dict` to `FileConversionFailure`. Iterating `failures.items()` to build the wire-shape dict translates each value via Option A.

- `src/pipeline/converter/engine.py:162-167` — total-failure branch builds `error_dict` (a separate single dict, not the per-file `failures`). It currently uses key "class" with value "multi_file_failure". The simplest path is to keep `error_dict` as a plain dict literal — it is constructed once and used immediately in `patch_body` and `event_payload` — and **not** promote it to a dataclass. The design's AC3.2 names only the per-file `failures` dict values, so this is in scope.

  Documented decision: `error_dict` stays a plain dict literal; only the per-file `failures` migrate.

- `src/pipeline/converter/engine.py:168-173` — `patch_body` for the total-failure branch contains `"conversion_errors": failures`. After migration, `failures` is a `dict[str, FileConversionFailure]`; the assignment must become `"conversion_errors": {name: option_a_dict(failure) for name, failure in failures.items()}` (using a small local helper or inline comprehension; see Task 1 implementation).

- `src/pipeline/converter/engine.py:209-211` — aggregations `total_rows`, `total_bytes`, `converted_files` currently destructure tuple values: `sum(r for _, r, _ in successes)`. Migration: `sum(s.row_count for s in successes)`, `sum(s.bytes_written for s in successes)`, `[s.filename for s in successes]`.

- `src/pipeline/converter/engine.py:213-221` — partial-success `patch_body` builds `"converted_files": converted_files` (already a list of strings) and `"conversion_errors": failures` (the dict). Same translation as the total-failure branch for `failures`.

- `tests/converter/test_engine.py:398-450` — the test that asserts `errors = patch["metadata"]["conversion_errors"]` — `patch` is captured from the HTTP module's PATCH call; the test reads it as a plain dict with key `"class"`. AC3.5 requires this assertion to pass unchanged. With Option A above, the wire shape is preserved.

- `tests/converter/test_engine.py:677` — analogous assertion in the partial-success path. Same expectation.

## External dependency findings

N/A — `dataclasses` is stdlib. `pyreadstat`, `pyarrow`, `pandas` are unaffected by this phase (they live in `convert.py`, not `engine.py`).

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Define `FileConversionSuccess` and `FileConversionFailure`; rewrite `convert_one`

**Verifies:** GH20.AC3.1, GH20.AC3.2, GH20.AC3.3, GH20.AC3.4.

**Files:**
- Modify: `src/pipeline/converter/engine.py`.

**Implementation:**

Add the dataclasses near the top of the file, alongside `ConversionResult`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ConversionResult:  # already exists; unchanged
    outcome: Literal["success", "failure", "skipped"]
    delivery_id: str
    reason: str | None = None


@dataclass(frozen=True)
class FileConversionSuccess:
    filename: str
    row_count: int
    bytes_written: int


@dataclass(frozen=True)
class FileConversionFailure:
    error_class: str
    message: str
    at: str
    converter_version: str
```

Add the import for `dataclasses` (used for `asdict` if Option B is taken; not strictly required under Option A but conventional alongside the dataclass decorator). The file already imports `from dataclasses import dataclass`, so the bare-module import only adds:

```python
import dataclasses  # add this near the top, in stdlib import block
```

(Option A does not call `dataclasses.asdict()` in the `engine.py` rewrite below, so the bare-module import is unnecessary if Option A is used uniformly. Add it only if a future executor switches to Option B. For now, omit it.)

Rewrite the local accumulators:

```python
successes: list[FileConversionSuccess] = []
failures: dict[str, FileConversionFailure] = {}
```

Rewrite the failure-record construction inside the except block (replacing lines 127-132):

```python
except BaseException as exc:
    error_class = classify_exception(exc)
    now = datetime.now(timezone.utc).isoformat()
    failures[sas_file.name] = FileConversionFailure(
        error_class=error_class,
        message=str(exc)[:500],
        at=now,
        converter_version=converter_version,
    )
    logger.warning(
        "file conversion failed",
        extra={
            "delivery_id": delivery_id,
            "source_path": source_path_str,
            "sas_filename": sas_file.name,
            "outcome": "failure",
            "error_class": error_class,
        },
    )
    continue
```

Rewrite the success-record construction (line 145):

```python
successes.append(
    FileConversionSuccess(
        filename=f"{sas_file.stem}.parquet",
        row_count=conv_meta.row_count,
        bytes_written=conv_meta.bytes_written,
    )
)
```

Define a local helper for the wire-shape translation (Option A), placed just before the total-failure branch:

```python
def _failure_to_wire(failure: FileConversionFailure) -> dict:
    """Translate FileConversionFailure to its wire-shape dict.

    The on-the-wire dict uses key 'class' (a Python builtin), whereas
    the dataclass field is named 'error_class'. asdict() alone would
    not produce the right key, so we build the dict explicitly.
    """
    return {
        "class": failure.error_class,
        "message": failure.message,
        "at": failure.at,
        "converter_version": failure.converter_version,
    }
```

This helper is module-private (single underscore) and lives next to `convert_one`. It replaces all three sites that previously embedded `failures` directly in a wire dict:

1. **Total-failure branch — `patch_body`:**

   ```python
   patch_body: dict = {
       "metadata": {
           "conversion_error": error_dict,
           "conversion_errors": {name: _failure_to_wire(f) for name, f in failures.items()},
       },
   }
   ```

2. **Partial/full-success branch — `patch_body["metadata"]["conversion_errors"]`:**

   ```python
   if failures:
       patch_body["metadata"]["conversion_errors"] = {
           name: _failure_to_wire(f) for name, f in failures.items()
       }
   ```

3. **`error_dict` for total-failure (separate, unchanged):** keeps the plain-dict shape with key `"class": "multi_file_failure"`. No edit needed.

Rewrite the aggregations (lines 209-211):

```python
total_rows = sum(s.row_count for s in successes)
total_bytes = sum(s.bytes_written for s in successes)
converted_files = [s.filename for s in successes]
```

The `len(successes)` call at line 228 (`"file_count": len(successes)`) is unchanged — `len()` works the same on the new list of dataclass instances.

The `len(failures)` calls at lines 165, 202-203, 231 are unchanged — `len()` works the same on the new dict of dataclass values.

**Verification:**

```bash
uv run python -c "
from dataclasses import is_dataclass
from pipeline.converter.engine import FileConversionSuccess, FileConversionFailure

for cls in (FileConversionSuccess, FileConversionFailure):
    assert is_dataclass(cls), f'{cls.__name__} must be a dataclass'
    assert cls.__dataclass_params__.frozen, f'{cls.__name__} must be frozen'

assert {f.name for f in FileConversionSuccess.__dataclass_fields__.values()} == {
    'filename', 'row_count', 'bytes_written',
}
assert {f.name for f in FileConversionFailure.__dataclass_fields__.values()} == {
    'error_class', 'message', 'at', 'converter_version',
}
print('OK')
"
```

Expected: `OK`.

**Commit:** deferred to Task 2.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Run `tests/converter/test_engine.py` and full converter suite, commit

**Verifies:** GH20.AC3.5 (existing assertions on patch-body shapes pass without modification).

**Files:** none changed in this task.

**Implementation:**

Run:

```bash
uv run pytest tests/converter/test_engine.py -v
```

Expected: all tests pass with the same count as before. The assertions at `test_engine.py:433` and `test_engine.py:677` (which inspect `patch["metadata"]["conversion_errors"][filename]["class"]`) pass because `_failure_to_wire` preserves the `"class"` key.

If any assertion fails on a key that no longer exists (e.g., `error_class` instead of `class`), revisit Task 1 — the `_failure_to_wire` translation must keep the `"class"` key.

Run the full converter suite to surface any indirect callers of the accumulator types:

```bash
uv run pytest tests/converter/ -v
```

Expected: all converter tests pass.

**Commit:**

```bash
git add src/pipeline/converter/engine.py
git commit -m "refactor(converter): replace bare tuples and dicts with frozen dataclasses (GH20 phase 3)"
```
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

---

## Phase 3 Done When

- `FileConversionSuccess` and `FileConversionFailure` are `@dataclass(frozen=True)` in `converter/engine.py`.
- The `successes` accumulator is `list[FileConversionSuccess]`; the `failures` accumulator is `dict[str, FileConversionFailure]`.
- All aggregations (`total_rows`, `total_bytes`, `converted_files`) read via attribute access.
- The `_failure_to_wire` helper translates `FileConversionFailure` to the wire-shape dict (with key `"class"` preserved).
- `tests/converter/test_engine.py` and `tests/converter/` overall pass with the same number of tests as before; no test names added or removed.

## Notes for executor

- **Wire-shape preservation is the load-bearing invariant.** AC3.5 says the existing patch-body assertions pass without modification. The `_failure_to_wire` helper is the bridge that makes this work. Do not skip it and do not call `dataclasses.asdict(failure)` directly in the patch body — that would rename `"class"` to `"error_class"` and break `test_engine.py:433`, the daemon's downstream payload, and any consumer reading the registry's `metadata.conversion_errors[*].class` field.
- **Independence:** Phase 3 commits independently of Phases 1-2 and 4-5. No coordination required at the commit level. Run before/after the registry_api work in any order.
- **`error_dict` (singular) stays a plain dict.** It is constructed once in the total-failure branch and serialised immediately. Promoting it to a dataclass would be scope creep with no observable benefit and would require a parallel `_error_to_wire` helper. The design's AC3.2 only names the per-file failures dict.
- **Conflict surface:**
  - **GH17** (ruff) — formatting only; if GH17 has not landed, run `uv run ruff format src/pipeline/converter/engine.py` after the rewrite.
  - **GH19** (annotations) — may have already added return-type annotations elsewhere in `engine.py`. The Phase 3 edits leave those alone.
  - **GH23** (exception logging) — touches the same `except BaseException` block at lines 124-143. If GH23 has merged, the block has additional `logger.warning(..., exc_info=True)` invocations. Reapply the failures-dataclass migration on top of the GH23 edits; the structural shape is identical, only the construction call (`failures[name] = FileConversionFailure(...)`) replaces the dict literal.
  - **GH24** (structured logging extra) — does not touch `engine.py`'s exception block (per the DAG's "conflict hotspots" table, which lists `engine.py` in the GH24 hotspot via log calls in success branches; verify post-merge).
