# Phase 2: engine.py exc_info addition (Category B)

**Goal:** Add `exc_info=True` to two existing WARNING logs in `engine.py` so PATCH and event-emit failures expose exception type and traceback in structured output.

**Architecture:** Two mechanical edits to existing `logger.warning(...)` calls. No new imports, no new variables. Logger and `extra=` payloads already exist.

**Tech Stack:** stdlib `logging`, `pipeline.json_logging.get_logger`.

**Scope:** 2 of 5 phases (issue #23, slug `GH23`).

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH23.AC2: engine.py warnings include exception details
- **GH23.AC2.1 Success:** The `"failed to PATCH conversion_error to registry"` warning log includes `exc_info=True`.
- **GH23.AC2.2 Success:** The `"failed to emit conversion.failed event"` warning log includes `exc_info=True`.
- **GH23.AC2.3 Edge:** Exception type and traceback appear in structured log output (not just the message string).

### GH23.AC6 (partial): Test coverage for logged exceptions
- **GH23.AC6.2 Success:** Tests for engine.py verify `exc_info` present in captured log records for PATCH and emit failures.

---

## Codebase verification findings

- ✓ `src/pipeline/converter/engine.py` lines 174–194 contain the two warning calls. Line 177–180: `logger.warning("failed to PATCH conversion_error to registry", extra={...})`. Line 191–194: `logger.warning("failed to emit conversion.failed event", extra={...})`.
- ✓ Both calls already pass `extra=` dicts; both are inside `except Exception:` blocks where `exc_info=True` will pick up the active exception.
- ✓ Logger imported via `pipeline.json_logging.get_logger`; `JsonFormatter` honours `exc_info=True` and serialises the formatted exception under the `exception` JSON key.
- ✓ Test file `tests/converter/test_engine.py` exists. `JsonFormatter` exposes `record.exc_info` on the LogRecord, so `caplog` records expose `exc_info` directly.

**No external dependency research needed.**

---

<!-- START_TASK_1 -->
### Task 1: Add exc_info=True to both engine.py WARNING calls

**Verifies:** GH23.AC2.1, GH23.AC2.2, GH23.AC2.3

**Files:**
- Modify: `src/pipeline/converter/engine.py` (lines 177–180 and 191–194)
- Test: `tests/converter/test_engine.py` (add log-record assertions)

**Implementation:**

1. Modify the PATCH-failure warning at lines 174–180. Current code:

```python
        try:
            http_module.patch_delivery(api_url, delivery_id, patch_body)
        except Exception:
            logger.warning(
                "failed to PATCH conversion_error to registry",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
            )
```

Replace with:

```python
        try:
            http_module.patch_delivery(api_url, delivery_id, patch_body)
        except Exception:
            logger.warning(
                "failed to PATCH conversion_error to registry",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
                exc_info=True,
            )
```

2. Modify the emit-failure warning at lines 188–194. Current code:

```python
        try:
            http_module.emit_event(api_url, "conversion.failed", delivery_id, event_payload)
        except Exception:
            logger.warning(
                "failed to emit conversion.failed event",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
            )
```

Replace with:

```python
        try:
            http_module.emit_event(api_url, "conversion.failed", delivery_id, event_payload)
        except Exception:
            logger.warning(
                "failed to emit conversion.failed event",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
                exc_info=True,
            )
```

**Testing:**

Add tests (or extend existing ones) in `tests/converter/test_engine.py` so that two scenarios are covered:

- **GH23.AC2.1, AC2.3:** When the engine handles total conversion failure and `http_module.patch_delivery` raises (e.g., `monkeypatch` it to raise `RuntimeError("boom")`), a captured WARNING record with message `"failed to PATCH conversion_error to registry"` has `record.exc_info` populated and `record.exc_info[0] is RuntimeError`.
- **GH23.AC2.2, AC2.3:** When `http_module.emit_event` raises (similar monkeypatch), a WARNING record with message `"failed to emit conversion.failed event"` has `record.exc_info` populated.

Use `caplog.set_level(logging.WARNING, logger="pipeline.converter.engine")`. Drive the engine into the total-failure path by ensuring all SAS files fail conversion (mock `convert_fn` test seam to raise on every call).

**Verification:**

Run: `uv run pytest tests/converter/test_engine.py -v`
Expected: all tests pass.

**Commit:** `feat(converter): include exc_info in engine.py warning logs for PATCH and emit failures`
<!-- END_TASK_1 -->

---

## Done when

- Task 1 committed.
- `uv run pytest` passes.
- AC2.1, AC2.2, AC2.3, AC6.2 verified.
