# Test Requirements — GH23 (log swallowed exceptions)

Maps every acceptance criterion in `docs/project/23/design.md` to an automated test. No criterion in this issue requires human verification — all six exception-handling sites are deterministically triggerable in unit tests via `monkeypatch` / fakes, and structured log output is asserted via pytest's `caplog`.

All tests must run under `uv run pytest`.

---

## AC1: Cleanup exceptions are logged at DEBUG (Phase 1)

| AC | Test type | Test file | Test name (suggested) | Verification |
|----|-----------|-----------|------------------------|--------------|
| GH23.AC1.1 | unit | `tests/converter/test_convert.py` | `test_convert_logs_writer_close_failure_at_debug` | Force `ParquetWriter.close` to raise during the `BaseException` cleanup. Assert `caplog` contains a record with `levelno == logging.DEBUG`, `name == "pipeline.converter.convert"`, `message == "writer close failed during cleanup"`, and `record.exc_info` populated. |
| GH23.AC1.2 | unit | `tests/converter/test_convert.py` | `test_convert_logs_tmp_unlink_failure_at_debug` | Force `Path.unlink` to raise `OSError` during cleanup. Assert DEBUG record with message `"tmp file unlink failed during cleanup"` and populated `exc_info`. |
| GH23.AC1.3 | unit | `tests/converter/test_daemon.py` | `test_persist_last_seq_logs_tmp_unlink_failure_at_debug` | Force `os.replace` to raise inside `persist_last_seq`'s `try`, force `Path.unlink` to raise `OSError`. Assert DEBUG record from `pipeline.converter.daemon` with message `"tmp file unlink failed during cleanup"` and populated `exc_info`. |
| GH23.AC1.4 | unit | both files above | each cleanup test | In every cleanup test above, wrap the call in `pytest.raises(<original outer exception type>)`. The inner suppressed exception (writer.close / unlink) must NOT be the one observed by `pytest.raises`. |

## AC2: engine.py warnings include exception details (Phase 2)

| AC | Test type | Test file | Test name (suggested) | Verification |
|----|-----------|-----------|------------------------|--------------|
| GH23.AC2.1 | unit | `tests/converter/test_engine.py` | `test_engine_patch_failure_warning_includes_exc_info` | Drive engine into the total-failure path (all SAS files fail). Monkeypatch `http_module.patch_delivery` to raise `RuntimeError("boom")`. Assert WARNING record with message `"failed to PATCH conversion_error to registry"` and `record.exc_info[0] is RuntimeError`. |
| GH23.AC2.2 | unit | `tests/converter/test_engine.py` | `test_engine_emit_failure_warning_includes_exc_info` | Same setup; monkeypatch `http_module.emit_event` to raise `RuntimeError("boom")`. Assert WARNING record with message `"failed to emit conversion.failed event"` and `record.exc_info[0] is RuntimeError`. |
| GH23.AC2.3 | unit | both tests above | (assertions in same tests) | In both tests, additionally assert `record.exc_info` is a 3-tuple (`type`, `value`, `traceback`) and that `traceback` is not `None` — confirming traceback is reachable for structured log output. |

## AC3: consumer.py narrows exception clauses (Phase 3)

| AC | Test type | Test file | Test name (suggested) | Verification |
|----|-----------|-----------|------------------------|--------------|
| GH23.AC3.1 | unit | `tests/events/test_consumer.py` | `test_session_silent_on_buffer_task_cancelled_error` | Drive `_session` so `buffer_task` ends with `asyncio.CancelledError` (cancel a task that is sleeping/iterating). Assert no records from `pipeline.events.consumer` are captured at DEBUG or higher. |
| GH23.AC3.1 | unit | `tests/events/test_consumer.py` | `test_session_silent_on_buffer_task_connection_closed` | Make `_buffer_ws` raise `ConnectionClosed`. Assert no DEBUG records from `pipeline.events.consumer`. |
| GH23.AC3.2 | unit | `tests/events/test_consumer.py` | `test_session_logs_unexpected_buffer_task_exception_at_debug` | Make `_buffer_ws` raise `RuntimeError("boom")`. Assert one DEBUG record with message `"buffer task raised unexpected exception"` and `record.exc_info[0] is RuntimeError`. |
| GH23.AC3.3 | unit | `tests/events/test_consumer.py` | `test_session_finally_block_applies_same_split` | Make `await self._catch_up()` raise so the `finally` clause runs. Repeat AC3.1 and AC3.2 sub-cases against this path. Confirm same logging behaviour. |
| GH23.AC3.4 | unit | `tests/events/test_consumer.py` | `test_buffer_ws_still_reraises_cancelled_and_connection_closed` | Drive `_buffer_ws` directly. With `CancelledError`, assert `pytest.raises(asyncio.CancelledError)` propagates from awaiting the task. With `ConnectionClosed`, assert `pytest.raises(ConnectionClosed)` propagates. Confirms `_buffer_ws` is unchanged. |

## AC4: registry_api/events.py logs dead connection exceptions (Phase 4)

| AC | Test type | Test file | Test name (suggested) | Verification |
|----|-----------|-----------|------------------------|--------------|
| GH23.AC4.1 | unit | `tests/registry_api/test_events.py` | `test_broadcast_logs_send_failure_at_debug` | Construct `ConnectionManager` with one fake `WebSocket` whose `send_json` is an `AsyncMock` raising `RuntimeError("boom")`. `await manager.broadcast({...})`. Assert DEBUG record with message `"WebSocket send failed, marking connection dead"` and `record.exc_info[0] is RuntimeError`. |
| GH23.AC4.2 | unit | `tests/registry_api/test_events.py` | `test_broadcast_retains_warning_for_dead_connection` | Same scenario. Assert WARNING record with message `"Removed dead WebSocket connection during broadcast"` is also present. |
| GH23.AC4.3 | unit | (same AC4.1 test) | additional assertions | Assert `record.exc_info` is a 3-tuple, `record.exc_info[0] is RuntimeError`, and `traceback` element is not `None`. |
| GH23.AC6.4 | unit | `tests/registry_api/test_events.py` | `test_broadcast_removes_dead_connection_after_logging` | After the failed broadcast, assert the failing websocket has been removed from `manager.active_connections`. Combine with healthy-connection control case to assert no log records on the happy path. |

## AC5: crawler/main.py logs before continuing (Phase 5)

For each of the four scandir sites, repeat the same test pattern with site-specific fixtures.

| AC | Test type | Test file | Test name (suggested) | Verification |
|----|-----------|-----------|------------------------|--------------|
| GH23.AC5.1 + AC5.2 (site 1: dpid) | unit | `tests/crawler/test_main.py` | `test_walk_roots_logs_dpid_scandir_oserror` | Set up `tmp_path` scan root. Monkeypatch `os.scandir` to raise `OSError` on the root path; otherwise delegate. Call `walk_roots(scan_roots, valid_terminals, logger=test_logger)`. Assert WARNING record with message `"scandir failed, skipping"`, `record.path == <root path>`, `record.exc_info[0] is OSError`. |
| GH23.AC5.1 + AC5.2 (site 2: request) | unit | `tests/crawler/test_main.py` | `test_walk_roots_logs_request_scandir_oserror` | Build fixture with one dpid + target dir; raise OSError on `scandir(target_path)`. Assert WARNING with `record.path == <target_path>`. |
| GH23.AC5.1 + AC5.2 (site 3: version) | unit | `tests/crawler/test_main.py` | `test_walk_roots_logs_version_scandir_oserror` | Build fixture down through request_id; raise OSError on `scandir(<request path>)`. Assert WARNING with `record.path == <request path>`. |
| GH23.AC5.1 + AC5.2 (site 4: terminal) | unit | `tests/crawler/test_main.py` | `test_walk_roots_logs_terminal_scandir_oserror` | Build fixture down through version; raise OSError on `scandir(<version path>)`. Assert WARNING with `record.path == <version path>`. |
| GH23.AC5.3 (continue semantics) | unit | `tests/crawler/test_main.py` | `test_walk_roots_continues_after_oserror` | Build a fixture with two siblings at the failing level: scandir raises OSError for sibling A but succeeds for sibling B (which contains a discoverable terminal). Assert `walk_roots` returns the terminal under sibling B — confirming the `continue` is preserved at every site. Run once per site. |
| GH23.AC6.5 + logger=None branch | unit | `tests/crawler/test_main.py` | `test_walk_roots_oserror_with_no_logger_does_not_raise` | Pick one site (e.g., site 1). Run with `logger=None`. Assert no exception is raised and no records are captured. Confirms the `if logger:` guard. |

---

## Test infrastructure notes

- **Capture DEBUG records:** Use `caplog.set_level(logging.DEBUG, logger="<module logger name>")` for AC1, AC3, AC4.
- **Capture WARNING records:** Default `caplog` level captures WARNING for AC2, AC5.
- **`exc_info` shape:** `record.exc_info` from a logger called with `exc_info=True` is `(type, value, traceback)`. Tests should assert on `record.exc_info[0]` (type) and check `record.exc_info[2] is not None` (traceback present).
- **No mocked databases.** All five phases test in-memory or `tmp_path` fixtures; nothing requires SQLite or a real registry process.
- **Async tests:** Phases 3 and 4 use `pytest.mark.asyncio`. Project already depends on `pytest-asyncio` (per CLAUDE.md).

## Coverage summary

| AC | Phase | Status |
|----|-------|--------|
| GH23.AC1.1 | 1 | covered |
| GH23.AC1.2 | 1 | covered |
| GH23.AC1.3 | 1 | covered |
| GH23.AC1.4 | 1 | covered |
| GH23.AC2.1 | 2 | covered |
| GH23.AC2.2 | 2 | covered |
| GH23.AC2.3 | 2 | covered |
| GH23.AC3.1 | 3 | covered |
| GH23.AC3.2 | 3 | covered |
| GH23.AC3.3 | 3 | covered |
| GH23.AC3.4 | 3 | covered |
| GH23.AC4.1 | 4 | covered |
| GH23.AC4.2 | 4 | covered |
| GH23.AC4.3 | 4 | covered |
| GH23.AC5.1 | 5 | covered (4 sites) |
| GH23.AC5.2 | 5 | covered (4 sites) |
| GH23.AC5.3 | 5 | covered (4 sites) |
| GH23.AC6.1 | 1 | covered |
| GH23.AC6.2 | 2 | covered |
| GH23.AC6.3 | 3 | covered |
| GH23.AC6.4 | 4 | covered |
| GH23.AC6.5 | 5 | covered |

All criteria automated; no human verification required.
