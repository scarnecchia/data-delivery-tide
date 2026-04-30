# GH21 Test Requirements

This document maps each GH21 acceptance criterion to a specific test (or set of tests) and identifies the file the test lives in. Generated from `docs/project/21/design.md` and `phase_0{1..5}.md`.

Every criterion maps to an automated test. None of GH21's criteria require human verification — every change is internal-API-shape and observable via Python introspection plus pytest assertions.

## Coverage matrix

| AC | Spec (verbatim from design, scoped to GH21) | Test file | Test name (existing or kept) | Test type | Phase |
|----|----------------------------------------------|-----------|-------------------------------|-----------|-------|
| GH21.AC1.1 | `test_add_user_token_is_urlsafe` verifies token generation without `patch` | `tests/test_auth_cli.py` | `test_add_user_token_is_urlsafe` (rewritten body, name preserved) | unit | 1 |
| GH21.AC1.2 | `cmd_add_user` accepts a `token_generator` parameter (default `secrets.token_urlsafe`) | `tests/test_auth_cli.py` (signature) + Phase 1 Task 1 verification snippet | introspection assertion in Phase 1 Task 1 verification block; the rewritten `test_add_user_token_is_urlsafe` exercises the parameter end-to-end | unit | 1 |
| GH21.AC2.1 | All `TestGetDelivery`, `TestPatchDelivery`, `TestListUnconverted`, `TestEmitEvent` pass with a fake transport | `tests/converter/test_http.py` | All methods in `TestGetDelivery`, `TestPatchDelivery`, `TestListUnconverted`, `TestEmitEvent` | unit | 2 |
| GH21.AC2.2 | `_request_with_retry` accepts an `urlopen` parameter that defaults to `urllib.request.urlopen` | `tests/converter/test_http.py` (signature) + Phase 2 Task 2 verification snippet | introspection assertion verifying `inspect.signature(_request_with_retry).parameters['urlopen'].default is urllib.request.urlopen`; behavioural coverage via `TestGetDelivery` etc. | unit | 2 |
| GH21.AC2.3 | Retry/backoff tests inject a fake `sleep` alongside the fake `urlopen` | `tests/converter/test_http.py` | All methods in `TestRetryBehaviour` | unit | 2 |
| GH21.AC3.1 | All `TestPostDeliverySuccess`, `TestPostDeliveryFailure`, `TestPostDeliveryBackoff` tests pass with injected fakes | `tests/crawler/test_http.py` | All methods in those three classes (11 tests total) | unit | 2 |
| GH21.AC3.2 | `post_delivery` accepts `urlopen` and `sleep` parameters with stdlib defaults | `tests/crawler/test_http.py` (signature) + Phase 2 Task 1 verification snippet | introspection assertion + behavioural coverage in `TestPostDeliverySuccess`/`TestPostDeliveryBackoff` | unit | 2 |
| GH21.AC4.1 | All `TestCrawl`, `TestLexiconSystemAC5Integration`, `TestCrawlAuth`, `TestSubDeliveryDiscovery` tests pass with `post_fn` injected | `tests/crawler/test_main.py` | All 15 affected test methods across those four classes | unit | 3 |
| GH21.AC4.2 | `crawl()` accepts a `post_fn` parameter (default `post_delivery`) | `tests/crawler/test_main.py` (signature) + Phase 3 Task 1 verification snippet | introspection assertion verifying `post_fn` is keyword-only with default `None` (resolved to `post_delivery` at call time); behavioural coverage in `TestCrawl` | unit | 3 |
| GH21.AC4.3 | `TestMain` patches on `settings` and `get_logger` are replaced by `monkeypatch.setattr` | `tests/crawler/test_main.py` | `TestMain.test_ac5_4_registry_unreachable_exits_nonzero` (rewritten with `monkeypatch.setattr`) | unit | 3 |
| GH21.AC4.4 | `MagicMock()` usages for `logger` remain acceptable | `tests/crawler/test_main.py` | All tests using `MagicMock(spec=logging.Logger)` and bare `MagicMock()` for `logger` (e.g. `test_ac3_1_warning_when_target_missing`, `test_ac3_2_no_warning_when_target_exists`) — these continue to pass; legitimacy is documented in Phase 3 Task 3 | unit | 3 |
| GH21.AC5.1 | `TestWebSocketBroadcast.test_ws_client_receives_delivery_created_event` uses a standalone fake `WebSocket` class | `tests/registry_api/test_routes.py` | `test_ws_client_receives_delivery_created_event` (rewritten to use `FakeWebSocket`) | unit | 4 |
| GH21.AC5.2 | The fake `WebSocket` implements `send_json(data)` and records calls without `AsyncMock` | `tests/registry_api/test_routes.py` | The same test as AC5.1 (assertions inspect `fake_ws.sent`) | unit | 4 |
| GH21.AC6.1 | `TestConnectionManager` tests use a standalone fake `WebSocket` class | `tests/registry_api/test_events.py` | All 12 methods of `TestConnectionManager` (rewritten to use `FakeWebSocket`) | unit | 4 |
| GH21.AC6.2 | The fake records `send_json` calls and can be configured to raise on demand | `tests/registry_api/test_events.py` | `test_broadcast_removes_dead_connection`, `test_broadcast_with_multiple_dead_connections` (use `FakeWebSocket(fail_on_send=True)`) | unit | 4 |
| GH21.AC6.3 | `TestWebSocketEndpoint` integration tests are untouched | `tests/registry_api/test_events.py:172-247` | All methods of `TestWebSocketEndpoint` (`test_websocket_connect_accepted`, `test_websocket_disconnect_removes_connection`, `test_broadcast_to_single_client`, `test_dead_connection_cleanup_ac33`) — verified by `git diff` showing zero changes in this range | integration | 4 |
| GH21.AC7.1 | All eleven tests pass without `patch("...httpx.AsyncClient", ...)` | `tests/events/test_consumer.py` | All 11 tests in the file (rewritten where needed; 5 of them were the affected `_catch_up` tests, others were already free of the prohibited patch) | unit | 5 |
| GH21.AC7.2 | `EventConsumer._catch_up` accepts an `http_client_factory` parameter | `tests/events/test_consumer.py` (signature) + Phase 5 Task 1 verification snippet | introspection assertion verifying `inspect.signature(_catch_up).parameters['http_client_factory'].default is httpx.AsyncClient`; behavioural coverage in `test_catch_up_single_page` etc. | unit | 5 |
| GH21.AC7.3 | `test_session_receives_ws_events` and `test_reconnection_after_disconnect` use `patch.object` on the consumer instance | `tests/events/test_consumer.py` | `test_session_receives_ws_events` (lines 286-287), `test_reconnection_after_disconnect` (line 337); their `patch.object`/`patch("...connect")` calls are preserved per design line 307-309 | unit | 5 |

## Phase rollups

| Phase | Test files touched | Tests rewritten | Test count delta |
|-------|---------------------|------------------|-------------------|
| 1 | `tests/test_auth_cli.py` | 1 (`test_add_user_token_is_urlsafe`) | 0 |
| 2 | `tests/converter/test_http.py`, `tests/crawler/test_http.py` | All `TestGetDelivery` + `TestPatchDelivery` + `TestListUnconverted` + `TestEmitEvent` + `TestRetryBehaviour` (~13) and all `TestPostDeliverySuccess` + `TestPostDeliveryFailure` + `TestPostDeliveryBackoff` (~11) | 0 |
| 3 | `tests/crawler/test_main.py` | All 15 `@patch`-decorated methods + `TestMain.test_ac5_4_registry_unreachable_exits_nonzero` | 0 |
| 4 | `tests/registry_api/test_events.py`, `tests/registry_api/test_routes.py` | All 12 methods of `TestConnectionManager` and `test_ws_client_receives_delivery_created_event` (1) | 0 |
| 5 | `tests/events/test_consumer.py` | 5 `_catch_up` tests | 0 |

**Net test count change across the entire issue: 0.** Every existing test name is preserved; every existing assertion shape is preserved; only the injection mechanism changes. This is what AC4.1, AC2.1, AC3.1, AC6.1, AC7.1 mean by "All ... tests pass with [the new mechanism]" — same behaviour, different scaffolding.

## Verification gate (final)

Before considering GH21 done, the following commands must all return zero exit codes:

```bash
# No `unittest.mock.patch` anywhere in tests except the documented exceptions in test_consumer.py:
grep -rn "from unittest.mock import\|unittest.mock.patch" tests/ \
    | grep -v "tests/events/test_consumer.py:.*from unittest.mock import AsyncMock, patch" \
    | grep -v "tests/crawler/test_main.py:.*from unittest.mock import MagicMock"

# No @patch decorators or with patch( blocks anywhere except test_consumer.py's documented patch.object usages:
grep -rnE "@patch\(|with patch\(" tests/ \
    | grep -v "tests/events/test_consumer.py:.*patch\.object" \
    | grep -v "tests/events/test_consumer.py:.*patch\(.pipeline\.events\.consumer\.connect"

# No AsyncMock used as a WebSocket simulation in registry_api tests:
grep -rn "AsyncMock\b" tests/registry_api/

# Full test suite passes:
uv run pytest
```

Each command's expected output is empty (or, for the test suite, "all tests pass with same count as before GH21 began").

## Human verification: none required

Every criterion is verifiable via Python introspection + pytest. No UI, no side effects on external systems, no behaviour change visible to consumers of the registry API. The pipeline's HTTP wire shape, WebSocket protocol, exit codes, and database state are all unchanged — this issue is a pure test-quality refactor.
