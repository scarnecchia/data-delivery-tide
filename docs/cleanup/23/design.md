# Log or Re-raise Swallowed Exceptions Design

## Summary

Six locations across the pipeline swallow exceptions without logging them, violating Python Programming Standards §4.3. This design classifies each site by its context (cleanup code, expected transient errors, or genuine surprises), specifies the minimal fix, and defines done criteria. No architectural changes are needed — all fixes are additive log calls or minor narrowing of exception types.

The fixes divide cleanly into two effort tiers: mechanical (add `exc_info=True` or a `logger.debug` call) and considered (narrow broad `except` clauses in `consumer.py` where expected vs unexpected exceptions must be distinguished).

## Definition of Done

- All six exception-handling sites emit log output when an unexpected exception is caught.
- Cleanup-path exceptions are logged at `DEBUG` level with `exc_info=True`.
- Warning-level logs that previously omitted exception details include `exc_info=True`.
- `consumer.py` no longer uses bare `except Exception` as a catch-all alongside expected transient types (`CancelledError`, `ConnectionClosed`).
- `registry_api/events.py` logs the exception before appending to the dead connection list.
- `crawler/main.py` logs a warning with the path before each `continue`.
- All existing tests continue to pass.
- New tests verify that each fixed site logs at the expected level when an exception occurs.

## Acceptance Criteria

### swallowed-exceptions.AC1: Cleanup exceptions are logged at DEBUG

- **swallowed-exceptions.AC1.1 Success:** `convert.py` writer.close cleanup logs `"writer close failed during cleanup"` at DEBUG with `exc_info=True` when writer.close raises.
- **swallowed-exceptions.AC1.2 Success:** `convert.py` tmp.unlink cleanup logs `"tmp file unlink failed during cleanup"` at DEBUG with `exc_info=True` when unlink raises.
- **swallowed-exceptions.AC1.3 Success:** `daemon.py` persist_last_seq tmp.unlink cleanup logs at DEBUG with `exc_info=True` when unlink raises.
- **swallowed-exceptions.AC1.4 Success:** Exceptions in all three cleanup sites are still suppressed (not re-raised); only logging is added.

### swallowed-exceptions.AC2: engine.py warnings include exception details

- **swallowed-exceptions.AC2.1 Success:** The `"failed to PATCH conversion_error to registry"` warning log includes `exc_info=True`.
- **swallowed-exceptions.AC2.2 Success:** The `"failed to emit conversion.failed event"` warning log includes `exc_info=True`.
- **swallowed-exceptions.AC2.3 Edge:** Exception type and traceback appear in structured log output (not just the message string).

### swallowed-exceptions.AC3: consumer.py narrows exception clauses

- **swallowed-exceptions.AC3.1 Success:** After buffer_task.cancel(), `CancelledError` and `ConnectionClosed` are caught and suppressed silently (expected transient).
- **swallowed-exceptions.AC3.2 Success:** Any other exception (bare `Exception`) from buffer_task is logged at DEBUG with `exc_info=True` before being suppressed.
- **swallowed-exceptions.AC3.3 Success:** The `finally` block in `_session` applies the same split: silent for `CancelledError`/`ConnectionClosed`, logged DEBUG for other exceptions.
- **swallowed-exceptions.AC3.4 Edge:** `_buffer_ws` continues to explicitly re-raise `CancelledError` and `ConnectionClosed` unchanged.

### swallowed-exceptions.AC4: registry_api/events.py logs dead connection exceptions

- **swallowed-exceptions.AC4.1 Success:** When `connection.send_json` raises, the exception is logged at DEBUG with `exc_info=True` before the connection is added to the dead list.
- **swallowed-exceptions.AC4.2 Success:** The existing warning log `"Removed dead WebSocket connection during broadcast"` is retained.
- **swallowed-exceptions.AC4.3 Edge:** The exception type is visible in structured log output (not just the "Removed dead…" message).

### swallowed-exceptions.AC5: crawler/main.py logs before continuing

- **swallowed-exceptions.AC5.1 Success:** Each of the four `except OSError: continue` sites logs a warning with the relevant path before continuing.
- **swallowed-exceptions.AC5.2 Success:** Each warning includes `exc_info=True` so the specific OS error is visible.
- **swallowed-exceptions.AC5.3 Edge:** Crawl continues processing remaining directories after logging (continue semantics preserved).

### swallowed-exceptions.AC6: Test coverage for logged exceptions

- **swallowed-exceptions.AC6.1 Success:** Tests for convert.py cleanup path verify DEBUG log emitted when writer.close or unlink raises; verify exception is not re-raised from convert_sas_to_parquet.
- **swallowed-exceptions.AC6.2 Success:** Tests for engine.py verify `exc_info` present in captured log records for PATCH and emit failures.
- **swallowed-exceptions.AC6.3 Success:** Tests for consumer.py verify that unexpected exceptions from buffer_task are logged at DEBUG; verify CancelledError and ConnectionClosed are not logged.
- **swallowed-exceptions.AC6.4 Success:** Tests for events.py broadcast verify DEBUG log emitted when send_json raises; verify dead connection is still collected.
- **swallowed-exceptions.AC6.5 Success:** Tests for crawler walk_roots verify warning logged with path when scandir raises OSError.

## Glossary

- **exc_info=True**: Keyword argument to Python logger calls that attaches the current exception's type, value, and traceback to the log record. Required by §4.3 to make caught exceptions diagnosable.
- **Cleanup path**: An `except` block whose only purpose is to avoid resource leaks during exception unwinding (e.g., close a file writer, unlink a tmp file). The original exception is re-raised after cleanup; the cleanup exception itself is suppressed but should be logged.
- **Swallowed exception**: An exception that is caught, neither re-raised nor logged, and therefore invisible to operators and monitoring.
- **CancelledError**: `asyncio.CancelledError` — a `BaseException` subclass signalling task cancellation in asyncio. Expected in shutdown paths; should not be treated as an error.
- **ConnectionClosed**: `websockets.exceptions.ConnectionClosed` — expected when the remote WebSocket peer disconnects. Part of normal reconnect lifecycle; should not be treated as an error.
- **Dead connection**: A WebSocket connection that raises on send, indicating the client has disconnected without a clean close. Collected and removed silently by `ConnectionManager.broadcast`; the consumer's reconnect loop handles recovery.
- **FCIS**: Functional Core / Imperative Shell — the project's architectural pattern separating pure logic (Functional Core) from side effects (Imperative Shell).
- **WAL mode**: SQLite Write-Ahead Logging — enables concurrent reads during writes; used by the registry API's SQLite backing store.

## Architecture

Seven distinct exception-handling sites require fixes. They group into four categories:

**Category A — Cleanup code (suppress, add DEBUG log):**
Two sites in `convert.py` (`writer.close`, `tmp.unlink`) and one in `daemon.py` (`persist_last_seq` tmp.unlink) are inside `except BaseException` / `except OSError` cleanup blocks whose sole purpose is resource release before re-raising the original exception. These must never re-raise; they only need a `logger.debug(..., exc_info=True)` call.

**Category B — Warning without details (add exc_info=True):**
Two sites in `engine.py` (`failed to PATCH conversion_error`, `failed to emit conversion.failed event`) already log at WARNING but omit `exc_info=True`, so the exception type and traceback are invisible.

**Category C — Broad clause mixing expected and unexpected types (narrow + add DEBUG for unexpected):**
Two sites in `consumer.py` (`_session` lines 74-77 and 92-95) use `except (CancelledError, ConnectionClosed, Exception): pass` after `buffer_task.cancel()`. `CancelledError` and `ConnectionClosed` are expected transients; bare `Exception` is not. The fix splits the clause: silent for the expected pair, DEBUG-logged for everything else.

**Category D — Silent continue in loop (add WARNING log with path):**
Four `except OSError: continue` blocks in `crawler/main.py` (`walk_roots` at the dpid, request, version, and terminal scan levels) suppress filesystem errors with no log output. Each needs a `logger.warning(...)` with `exc_info=True` before the `continue`.

**Category E — Exception swallowed before dead-list append (add DEBUG log):**
One site in `registry_api/events.py` (`ConnectionManager.broadcast`) catches `Exception` and appends the connection to a dead list, then logs a warning about the removal — but never logs the exception itself. Add `logger.debug(..., exc_info=True)` before the dead list append.

No changes to calling conventions, return types, or module boundaries are required. All fixes are confined to the catch clauses themselves.

## Existing Patterns

The project uses `pipeline.json_logging.get_logger` (in converter and crawler modules) and the standard `logging.getLogger(__name__)` (in consumer.py and registry_api/events.py). Both produce structured JSON output via `JsonFormatter`. `exc_info=True` on any logger call causes the formatter to include exception details in the structured record.

Investigation confirmed:

- `daemon.py` and `engine.py` already call `logger.error(...)` and `logger.warning(...)` with structured `extra=` dicts — the pattern for adding `exc_info=True` is already demonstrated in those files.
- `registry_api/events.py` already uses `logger.warning(...)` — DEBUG logging with `exc_info` is a simple addition at the same logger.
- `consumer.py` already re-raises `CancelledError` in `_buffer_ws` (line 103), demonstrating the project's intent to treat cancellation as a non-error — the `_session` cleanup clauses should follow the same pattern.
- `crawler/main.py` already logs warnings with `extra=` structured fields (e.g., the missing target-directory warning at line 76) — the OSError sites should match that style.

No new patterns are introduced. All fixes follow existing conventions.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Cleanup-path DEBUG logging (Category A)

**Goal:** Log suppressed exceptions in cleanup code so filesystem/writer failures are visible at DEBUG level without changing error-propagation semantics.

**Components:**
- `src/pipeline/converter/convert.py` — add `logger.debug("writer close failed during cleanup", exc_info=True)` inside `except Exception` at ~L181; add `logger.debug("tmp file unlink failed during cleanup", exc_info=True)` inside `except OSError` at ~L186. Requires adding a module-level logger (`logger = logging.getLogger(__name__)`).
- `src/pipeline/converter/daemon.py` — add `logger.debug("tmp file unlink failed during cleanup", exc_info=True)` inside `except OSError` at ~L53 in `persist_last_seq`. Module-level logger already absent from `persist_last_seq`'s scope; use the `get_logger` call from existing imports or add a module-level fallback.

**Dependencies:** None.

**Done when:** swallowed-exceptions.AC1.1, AC1.2, AC1.3, AC1.4 pass. Tests inject a failing writer/unlink, assert DEBUG log emitted, assert original exception still propagates from the outer call.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: engine.py exc_info addition (Category B)

**Goal:** Add `exc_info=True` to existing warning logs in `engine.py` so PATCH and event-emit failures expose exception type and traceback.

**Components:**
- `src/pipeline/converter/engine.py` — add `exc_info=True` to the `logger.warning("failed to PATCH conversion_error to registry", ...)` call at ~L177; add `exc_info=True` to the `logger.warning("failed to emit conversion.failed event", ...)` call at ~L191.

**Dependencies:** None (mechanical addition to existing log calls).

**Done when:** swallowed-exceptions.AC2.1, AC2.2, AC2.3 pass. Tests mock `http_module.patch_delivery` and `http_module.emit_event` to raise, capture log records, assert `exc_info` field is populated.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: consumer.py exception clause narrowing (Category C)

**Goal:** Replace the broad `except (CancelledError, ConnectionClosed, Exception): pass` clauses with split handling: silent for expected transients, DEBUG-logged for anything else.

**Components:**
- `src/pipeline/events/consumer.py` — refactor the two `except (asyncio.CancelledError, ConnectionClosed, Exception): pass` blocks (lines 74-77 and 92-95) in `_session`. Replace each with:
  ```
  except (asyncio.CancelledError, ConnectionClosed):
      pass
  except Exception:
      logger.debug("buffer task raised unexpected exception", exc_info=True)
  ```

**Dependencies:** None. `logger` is already defined at module level.

**Done when:** swallowed-exceptions.AC3.1, AC3.2, AC3.3, AC3.4 pass. Tests verify CancelledError and ConnectionClosed from buffer_task produce no log output; verify that a RuntimeError from buffer_task is logged at DEBUG.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: registry_api/events.py broadcast DEBUG logging (Category E)

**Goal:** Log the send_json exception at DEBUG before collecting the dead connection, so failed-send details are available for diagnosis.

**Components:**
- `src/pipeline/registry_api/events.py` — add `logger.debug("WebSocket send failed, marking connection dead", exc_info=True)` inside `except Exception` before the `dead.append(connection)` call at ~L36.

**Dependencies:** None. `logger` is already defined at module level.

**Done when:** swallowed-exceptions.AC4.1, AC4.2, AC4.3 pass. Tests mock `connection.send_json` to raise, assert DEBUG log emitted, assert connection appears in dead list, assert existing warning log still emitted.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: crawler/main.py OSError logging (Category D)

**Goal:** Log a warning with path and exc_info at each of the four silent `except OSError: continue` sites in `walk_roots`.

**Components:**
- `src/pipeline/crawler/main.py` — add `logger.warning("scandir failed, skipping", extra={"path": <relevant_path>}, exc_info=True)` before `continue` at the four OSError catch sites: dpid-level scandir (~L62), request-level scandir (~L84), version-level scandir (~L93), terminal-level scandir (~L101). The `logger` parameter is already threaded into `walk_roots`.

**Dependencies:** None.

**Done when:** swallowed-exceptions.AC5.1, AC5.2, AC5.3 pass. Tests mock `os.scandir` to raise OSError for a specific path, assert warning logged with that path, assert remaining directories are still processed.
<!-- END_PHASE_5 -->

## Additional Considerations

**Test verification approach:** The standard approach for asserting log output in pytest is `caplog` (pytest's built-in log capture fixture). Tests should assert on `record.levelname`, `record.message`, and the presence of `record.exc_info` for the `exc_info=True` cases. `caplog.set_level(logging.DEBUG)` is required to capture DEBUG-level records in phases 1, 3, and 4.

**Effort estimate:** Phases 1, 2, 4, and 5 are mechanical (1–2 lines per site). Phase 3 requires judgment on exception clause design and slightly more test surface (verifying the split behaviour). Total estimated effort: 2–3 hours including tests.

**No behavioural regressions:** All fixes are additive log calls or clause splits. No return values, exception propagation semantics, or calling conventions change.
