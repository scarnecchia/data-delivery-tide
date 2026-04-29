# Phase 1: Cleanup-path DEBUG logging (Category A)

**Goal:** Log suppressed exceptions in cleanup code (writer.close, tmp.unlink) at DEBUG level so filesystem/writer failures are visible without changing error-propagation semantics.

**Architecture:** Three sites in two files (`convert.py` x2, `daemon.py` x1) inside `BaseException` cleanup blocks. Each cleanup block already swallows its own inner exception; we only add a `logger.debug(..., exc_info=True)` call. The outer `raise` is preserved.

**Tech Stack:** stdlib `logging`, project's `pipeline.json_logging.get_logger`.

**Scope:** 1 of 5 phases (issue #23, slug `GH23`).

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH23.AC1: Cleanup exceptions are logged at DEBUG
- **GH23.AC1.1 Success:** `convert.py` writer.close cleanup logs `"writer close failed during cleanup"` at DEBUG with `exc_info=True` when writer.close raises.
- **GH23.AC1.2 Success:** `convert.py` tmp.unlink cleanup logs `"tmp file unlink failed during cleanup"` at DEBUG with `exc_info=True` when unlink raises.
- **GH23.AC1.3 Success:** `daemon.py` persist_last_seq tmp.unlink cleanup logs at DEBUG with `exc_info=True` when unlink raises.
- **GH23.AC1.4 Success:** Exceptions in all three cleanup sites are still suppressed (not re-raised); only logging is added.

### GH23.AC6 (partial): Test coverage for logged exceptions
- **GH23.AC6.1 Success:** Tests for convert.py cleanup path verify DEBUG log emitted when writer.close or unlink raises; verify exception is not re-raised from convert_sas_to_parquet.

---

## Codebase verification findings

- ✓ `src/pipeline/converter/convert.py` exists; cleanup block at lines 177–188 matches design. Lines 178–182 wrap `writer.close()`; lines 183–187 wrap `tmp_path.unlink()`. Outer `raise` at line 188 preserved.
- ✗ Design says `convert.py` "Requires adding a module-level logger". Confirmed: `convert.py` has NO `import logging` and NO module-level logger. Must add `import logging` and `logger = logging.getLogger(__name__)`.
- ✓ `src/pipeline/converter/daemon.py` `persist_last_seq` at lines 29–55. Cleanup block at lines 49–55; `tmp.unlink()` is at line 52, swallowed by `except OSError: pass` at lines 53–54.
- ✗ Design says daemon.py "use the `get_logger` call from existing imports or add a module-level fallback". `get_logger` is imported at line 61 (AFTER `persist_last_seq` at line 29). Must add a module-level `import logging` + `logger = logging.getLogger(__name__)` near the top of the file (near `import asyncio` at line 3) so `persist_last_seq` can use it. Do NOT use the project's `get_logger` for `persist_last_seq` — it requires a config-resolved log directory and fights the Functional Core ordering.
- ✓ `pipeline.json_logging.JsonFormatter` honours `exc_info=True`: `JsonFormatter.format` calls `self.formatException(record.exc_info)` and embeds it as `exception` in the JSON record.
- ✓ Test file `tests/converter/test_convert.py` exists. Project uses `pytest` + `caplog` for log assertions (verified in `tests/test_json_logging.py`).

**No external dependency research needed:** Phase 1 only uses stdlib `logging`.

---

<!-- START_TASK_1 -->
### Task 1: Add module-level logger and DEBUG cleanup logs to convert.py

**Verifies:** GH23.AC1.1, GH23.AC1.2, GH23.AC1.4

**Files:**
- Modify: `src/pipeline/converter/convert.py` (add import + logger; modify cleanup block at lines 177–188)
- Test: `tests/converter/test_convert.py` (add cleanup-path log tests)

**Implementation:**

1. Add `import logging` to the imports block at the top of `src/pipeline/converter/convert.py`. Place alphabetically with the existing stdlib imports (after `import os` at line 4).

2. Add a module-level logger immediately after the imports, before the `from pipeline.converter.classify import SchemaDriftError` line at line 16. Insert a blank line above and below for readability:

```python
logger = logging.getLogger(__name__)
```

3. Modify the cleanup block. Current block (lines 177–188):

```python
    except BaseException:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
```

Replace with:

```python
    except BaseException:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                logger.debug("writer close failed during cleanup", exc_info=True)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                logger.debug("tmp file unlink failed during cleanup", exc_info=True)
        raise
```

The `pass` is replaced by the `logger.debug(...)` call. Control flow is unchanged: the inner exception is suppressed; the outer `raise` re-raises the original `BaseException`.

**Testing:**

Add two tests to `tests/converter/test_convert.py`. Tests must verify each AC:

- **GH23.AC1.1:** When `writer.close()` raises during the BaseException cleanup, a DEBUG record with message `"writer close failed during cleanup"` is emitted by logger `pipeline.converter.convert`, and the record has populated `exc_info`. The original outer exception still propagates from `convert_sas_to_parquet`.
- **GH23.AC1.2:** When `tmp_path.unlink()` raises `OSError` during cleanup, a DEBUG record with message `"tmp file unlink failed during cleanup"` is emitted, with `exc_info` populated. The original outer exception still propagates.
- **GH23.AC1.4:** Both cleanup tests assert the inner exception was swallowed (not visible to the caller); only the outer (original) exception is observed by `pytest.raises`.

Use `caplog.set_level(logging.DEBUG, logger="pipeline.converter.convert")` to capture DEBUG records. Use `monkeypatch` or `unittest.mock.patch` to force `pyarrow.parquet.ParquetWriter.close` and `pathlib.Path.unlink` to raise. Trigger the outer `BaseException` by making `pyreadstat.read_file_in_chunks` (or equivalent chunk iterator) raise after a writer is created.

Existing test patterns in `test_convert.py` already drive `convert_sas_to_parquet` end-to-end with real fixture SAS files; reuse that machinery and inject failures via `monkeypatch`.

**Verification:**

Run: `uv run pytest tests/converter/test_convert.py -v`
Expected: all existing tests pass; new cleanup-path tests pass.

**Commit:** `feat(converter): log convert.py cleanup-path exceptions at DEBUG`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add module-level logger and DEBUG cleanup log to daemon.py persist_last_seq

**Verifies:** GH23.AC1.3, GH23.AC1.4

**Files:**
- Modify: `src/pipeline/converter/daemon.py` (add import + logger; modify cleanup block at lines 49–55)
- Test: `tests/converter/test_daemon.py` (add cleanup-path log test)

**Implementation:**

1. Add `import logging` to the imports block at the top of `src/pipeline/converter/daemon.py`. Insert it alphabetically with existing stdlib imports (after `import json` at line 4).

2. Add a module-level logger immediately after the stdlib imports block (after `from pathlib import Path` at line 8, before the existing blank line at line 9):

```python
logger = logging.getLogger(__name__)
```

This logger MUST be defined ABOVE the `persist_last_seq` function (line 29) so the function can reference it. Do NOT replace it with the existing `from pipeline.json_logging import get_logger` at line 61 — `persist_last_seq` is a Functional-Core helper that runs before `DaemonRunner` initialises configuration; using `logging.getLogger(__name__)` keeps it config-free.

3. Modify the cleanup block. Current block (lines 49–55):

```python
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
```

Replace with:

```python
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                logger.debug("tmp file unlink failed during cleanup", exc_info=True)
        raise
```

The `pass` is replaced by `logger.debug(...)`. Outer `raise` preserved.

**Testing:**

Add one test to `tests/converter/test_daemon.py`. Test must verify:

- **GH23.AC1.3:** When `tmp.unlink()` raises `OSError` during the BaseException cleanup of `persist_last_seq`, a DEBUG record with message `"tmp file unlink failed during cleanup"` is emitted by logger `pipeline.converter.daemon`, with `exc_info` populated.
- **GH23.AC1.4:** The original outer exception (e.g., the one that caused entry into the BaseException block) propagates; the inner OSError is suppressed.

Use `caplog.set_level(logging.DEBUG, logger="pipeline.converter.daemon")`. Trigger the outer exception by making `os.replace` raise (this is the last line in the `try` block at line 48). Force `Path.unlink` to raise OSError via `monkeypatch`. Confirm the outer exception bubbles out.

**Verification:**

Run: `uv run pytest tests/converter/test_daemon.py -v`
Expected: all existing tests pass; new cleanup-path test passes.

**Commit:** `feat(converter): log daemon.py persist_last_seq cleanup-path exception at DEBUG`
<!-- END_TASK_2 -->

---

## Done when

- Tasks 1 and 2 committed.
- `uv run pytest` passes (no regressions).
- All four AC1.* and AC6.1 cases verified by new tests in `tests/converter/`.
