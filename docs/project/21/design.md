# Issue #21 Design: Replace `unittest.mock.patch` with Dependency Injection

## Summary

Seven test files import `unittest.mock` to patch module-level globals or inject fake HTTP behaviour. This violates the project's Python Programming Standards §3.2 (no `unittest.mock.patch`). The fix is to make each piece of production code accept its collaborators as parameters, then pass fakes directly in tests. The converter's `engine.py` is already the reference model for this pattern — it accepts `http_module` and `convert_fn` as parameters. All seven files can be brought to that standard with surgical changes to source and test code, no architectural rewrites required.

## Definition of Done

- Zero imports of `unittest.mock` across all test files
- Production source code exposes DI seams where it does not already have them
- All existing tests continue to pass and cover the same behaviour as before
- No test behaviour removed; only the injection mechanism changes
- `AsyncMock` usages that test `ConnectionManager` directly are replaced with standalone Protocol-conforming fakes
- The one `AsyncMock` usage in `test_routes.py` that simulates a WS client session (not testing `ConnectionManager` itself) is documented as acceptable and kept with a comment explaining why

## Acceptance Criteria

### di.AC1: `tests/test_auth_cli.py`
- **di.AC1.1 Success:** `test_add_user_token_is_urlsafe` verifies token generation without `patch`
- **di.AC1.2 Success:** `cmd_add_user` accepts a `token_generator` parameter (default `secrets.token_urlsafe`) that tests can substitute with a deterministic callable

### di.AC2: `tests/converter/test_http.py`
- **di.AC2.1 Success:** All `TestGetDelivery`, `TestPatchDelivery`, `TestListUnconverted`, `TestEmitEvent` tests pass with a fake transport object instead of `patch("urllib.request.urlopen")`
- **di.AC2.2 Success:** `_request_with_retry` (or a renamed equivalent) accepts an `urlopen` parameter that defaults to `urllib.request.urlopen`
- **di.AC2.3 Success:** Retry/backoff tests inject a fake `sleep` alongside the fake `urlopen`

### di.AC3: `tests/crawler/test_http.py`
- **di.AC3.1 Success:** All `TestPostDeliverySuccess`, `TestPostDeliveryFailure`, `TestPostDeliveryBackoff` tests pass with injected fakes instead of `patch`
- **di.AC3.2 Success:** `post_delivery` accepts `urlopen` and `sleep` parameters (defaults to `urllib.request.urlopen` and `time.sleep`)

### di.AC4: `tests/crawler/test_main.py`
- **di.AC4.1 Success:** All `TestCrawl`, `TestLexiconSystemAC5Integration`, `TestCrawlAuth`, `TestSubDeliveryDiscovery` tests pass with `post_fn` injected into `crawl()` instead of `@patch("pipeline.crawler.main.post_delivery")`
- **di.AC4.2 Success:** `crawl()` accepts a `post_fn` parameter (default `post_delivery`) and calls it instead of calling `post_delivery` directly
- **di.AC4.3 Success:** `TestMain` class patches on `settings` and `get_logger` are replaced by accepting config/logger parameters (both already accepted by `crawl()`); `main()` test is refactored to test only the integration wiring or is moved to an integration test
- **di.AC4.4 Success:** All `MagicMock()` usages for `logger` remain acceptable (logger is already a parameter on `walk_roots` and `crawl()`)

### di.AC5: `tests/registry_api/test_routes.py`
- **di.AC5.1 Success:** `TestWebSocketBroadcast.test_ws_client_receives_delivery_created_event` uses a standalone fake `WebSocket` class instead of `AsyncMock()` for `mock_ws`
- **di.AC5.2 Success:** The fake `WebSocket` implements `send_json(data)` and records calls without `AsyncMock`

### di.AC6: `tests/registry_api/test_events.py`
- **di.AC6.1 Success:** `TestConnectionManager` tests use a standalone fake `WebSocket` class instead of `AsyncMock()` for each `mock_ws`
- **di.AC6.2 Success:** The fake records `send_json` calls and can be configured to raise on demand (for dead-connection tests)
- **di.AC6.3 Success:** `TestWebSocketEndpoint` integration tests (using the real `client` fixture) are untouched — they use real WebSocket connections

### di.AC7: `tests/events/test_consumer.py`
- **di.AC7.1 Success:** All eleven tests pass without `patch("pipeline.events.consumer.httpx.AsyncClient", ...)`
- **di.AC7.2 Success:** `EventConsumer._catch_up` accepts an `http_client_factory` parameter (default `httpx.AsyncClient`) that tests inject with a factory returning a fake async context manager
- **di.AC7.3 Success:** `test_session_receives_ws_events` and `test_reconnection_after_disconnect` use `patch.object` on the consumer instance (not on a module import) — these are acceptable as they test integration between `_session` and its sub-methods on the same object; they do not patch external module symbols

## Glossary

- **DI (Dependency Injection):** Passing collaborators as function/constructor parameters rather than importing and calling them directly, enabling callers (including test code) to supply alternatives.
- **Protocol:** A Python `typing.Protocol` class that defines the minimal interface a collaborator must implement; no inheritance required. Used here to type-annotate DI parameters without coupling to a concrete implementation.
- **Transport fake:** A plain Python class that implements only the methods called by the system under test, recording calls for later assertion. No magic attributes, no `unittest.mock` machinery.
- **AsyncMock:** `unittest.mock.AsyncMock` — creates objects whose methods are automatically awaitable. Used here as a shorthand for async objects; the issue asks us to replace these with standalone fakes where they are the primary test double for a public interface.
- **Imperative Shell:** The outer layer of the Functional Core / Imperative Shell pattern used in this codebase. It owns I/O and side effects. The shell is the right place for DI seams because it is the only layer that reaches out to external systems.

---

## Architecture

### Current State

The seven files use `patch` in four distinct modes:

| Mode | Files | Problem |
|---|---|---|
| Patch module-level `urllib.request.urlopen` | `converter/test_http.py`, `crawler/test_http.py` | Global state mutation; couples tests to import paths |
| Patch `post_delivery` at the call site inside `main.py` | `crawler/test_main.py` | Same; also prevents testing the post-delivery logic path |
| Patch `secrets.token_urlsafe` | `test_auth_cli.py` | Trivially replaceable with a parameter default |
| `AsyncMock` as a standalone fake WebSocket | `registry_api/test_events.py`, `registry_api/test_routes.py` | Tests `ConnectionManager` interface via mock rather than a real fake |
| Patch `httpx.AsyncClient` constructor | `events/test_consumer.py` | Patches an import; fake should be injected instead |

The converter's `engine.py` already demonstrates the target pattern:

```python
def convert_one(
    delivery_id: str,
    api_url: str,
    *,
    http_module=converter_http,     # injected in tests
    convert_fn=convert_sas_to_parquet,  # injected in tests
) -> ConversionResult:
```

Every other module with external collaborators should follow this same convention.

### Target State

After the changes, each module will accept its external collaborators as keyword arguments with production defaults:

| Module | New parameter(s) | Default(s) |
|---|---|---|
| `auth_cli.cmd_add_user` | `token_generator` | `secrets.token_urlsafe` |
| `crawler/http.post_delivery` | `urlopen`, `sleep` | `urllib.request.urlopen`, `time.sleep` |
| `converter/http._request_with_retry` | `urlopen`, `sleep` | `urllib.request.urlopen`, `time.sleep` |
| `crawler/main.crawl` | `post_fn` | `post_delivery` |
| `events/consumer.EventConsumer._catch_up` | `http_client_factory` | `httpx.AsyncClient` |

The `ConnectionManager` interface (`send_json`, `accept`) will be captured in a Protocol so standalone fakes can be type-checked. No change to the `ConnectionManager` source is needed; the Protocol lives alongside the tests.

---

## Existing Patterns Followed

- `engine.py` parameter-default DI is the direct precedent for all `urllib`/`httpx` injection.
- `crawl(config, logger)` already accepts both config and logger as parameters — `post_fn` is the same pattern.
- `walk_roots(scan_roots, ..., logger=None)` accepts an optional logger — the same convention applies to optional injectable collaborators.
- `monkeypatch.setattr` is used in `cli_db` fixture already — it is the sanctioned alternative to `patch` for settings objects.

---

## Implementation Phases

### Phase 1 — Low-risk, zero structural change (auth_cli)

**`auth_cli.py` + `tests/test_auth_cli.py`**

The single `patch` call in `test_add_user_token_is_urlsafe` verifies that `secrets.token_urlsafe(32)` is called. The fix is to add `token_generator=secrets.token_urlsafe` as a parameter to `cmd_add_user` and call `token_generator(32)` internally. The test then passes a deterministic lambda instead of patching.

Source change in `auth_cli.py`:

```python
def cmd_add_user(args: argparse.Namespace, token_generator=secrets.token_urlsafe) -> int:
    ...
    raw_token = token_generator(32)
```

Test rewrite:

```python
def test_add_user_token_is_urlsafe(self, cli_db, capsys):
    calls = []
    def fake_generator(n):
        calls.append(n)
        return "mocked-token-value"

    args = argparse.Namespace(username="urlsafe_user", role="read")
    cmd_add_user(args, token_generator=fake_generator)

    assert calls == [32]
```

`cmd_rotate_token` uses `secrets.token_urlsafe` in the same way and should receive the same parameter for consistency, even though no current test patches it.

### Phase 2 — HTTP fakes for `crawler/http.py` and `converter/http.py`

Both modules contain the same pattern: a `_request_with_retry`-style loop that calls `urllib.request.urlopen` and `time.sleep`. The cleanest DI approach mirrors `engine.py`: pass the collaborators as keyword arguments to the public functions.

**`crawler/http.post_delivery`:**

```python
def post_delivery(
    api_url: str,
    payload: dict,
    token: str | None = None,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict:
```

**`converter/http._request_with_retry`** (private, only called from the same module's public functions):

```python
def _request_with_retry(
    request: urllib.request.Request,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict:
```

Each public function in `converter/http.py` (`get_delivery`, `patch_delivery`, `list_unconverted`, `emit_event`) will pass `urlopen` and `sleep` through to `_request_with_retry`. They all need corresponding parameters added.

**Fake transport for tests:**

A single `FakeUrlopen` class in each test module (or a shared `tests/fakes.py`) replaces `MagicMock` + `patch`:

```python
class FakeUrlopen:
    def __init__(self, responses):
        """responses: list of (body_dict | Exception)"""
        self._responses = iter(responses)
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        resp = next(self._responses)
        if isinstance(resp, BaseException):
            raise resp
        return _FakeResponse(resp)

class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return self._body

    @property
    def status(self):
        return 200
```

Tests that currently call `mock_urlopen.call_args[0][0]` to inspect the `Request` object will instead read `fake_urlopen.calls[0]` — the semantics are identical, no behaviour is removed.

The retry/backoff tests currently patch `time.sleep` alongside `urlopen`. With the DI approach, they pass a `FakeSleep` that records call arguments:

```python
class FakeSleep:
    def __init__(self):
        self.calls = []
    def __call__(self, seconds):
        self.calls.append(seconds)
```

### Phase 3 — `crawl()` post_fn injection

**`crawler/main.py`:**

```python
from pipeline.crawler.http import post_delivery as _post_delivery

def crawl(config, logger, token: str | None = None, *, post_fn=None) -> int:
    if post_fn is None:
        post_fn = _post_delivery
    ...
    post_fn(config.registry_api_url, payload, token=token)
```

All `@patch("pipeline.crawler.main.post_delivery")` decorators in `test_main.py` are removed. Tests construct a `FakePostDelivery` recorder and pass it:

```python
class FakePostDelivery:
    def __init__(self):
        self.calls = []
    def __call__(self, api_url, payload, *, token=None):
        self.calls.append({"api_url": api_url, "payload": payload, "token": token})
        return {}
```

Tests then inspect `fake_post.calls` where they currently inspect `mock_post.call_args_list`. The shape of the assertions is unchanged; only the fixture mechanism differs.

The `TestMain` class (three `@patch` decorators on `settings`, `get_logger`, `crawl`) presents a special case. These patch module-level globals in `main.py`, not collaborators passed as parameters. The cleanest resolution is to note that `main()` is a thin entry-point that reads `settings` and calls `crawl()` — its logic is already fully tested through `crawl()`. The `test_ac5_4_registry_unreachable_exits_nonzero` test can be rewritten by calling `crawl()` with a `post_fn` that raises `RegistryUnreachableError`, then verifying the exit code by calling `main()` with that config via `monkeypatch.setattr` on `pipeline.crawler.main.settings` (which is `monkeypatch.setattr`, not `patch`).

### Phase 4 — WebSocket fakes for `ConnectionManager` tests

**`tests/registry_api/test_events.py`:**

Replace all `AsyncMock()` instances that simulate WebSocket connections with a `FakeWebSocket` class. The `ConnectionManager` only calls `websocket.accept()` and `websocket.send_json(data)`, so:

```python
class FakeWebSocket:
    def __init__(self, fail_on_send=False):
        self._fail_on_send = fail_on_send
        self.accepted = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        if self._fail_on_send:
            raise RuntimeError("Connection closed")
        self.sent.append(data)
```

All assertions that currently call `mock_ws.send_json.assert_called_once_with(...)` become `assert fake_ws.sent == [...]`. All assertions that check the websocket was removed from `active_connections` are unchanged.

**`tests/registry_api/test_routes.py` — `TestWebSocketBroadcast`:**

This test creates a `mock_ws = AsyncMock()` and adds it directly to `manager.active_connections` to simulate a connected client, then makes an HTTP request and checks whether `mock_ws.send_json` was called. The same `FakeWebSocket` class from `test_events.py` applies here.

Note: `test_ws_client_receives_delivery_created_event` is an `@pytest.mark.asyncio` test that mixes the synchronous `client` (TestClient) with an async task. The test structure is already somewhat unusual (asyncio.sleep for timing). The fake WebSocket resolves the `AsyncMock` dependency without changing the test's timing structure, which is acceptable.

### Phase 5 — EventConsumer HTTP injection

**`events/consumer.py`:**

`_catch_up` constructs `httpx.AsyncClient()` directly. Adding a factory parameter follows the same pattern as all previous phases:

```python
async def _catch_up(self, *, http_client_factory=httpx.AsyncClient) -> None:
    async with http_client_factory() as client:
        while True:
            resp = await client.get(...)
```

**Tests in `tests/events/test_consumer.py`:**

The current pattern already builds a `mock_client` object manually (not relying on `MagicMock` auto-spec) and the `patch` only replaces the constructor. All tests become:

```python
await consumer._catch_up(http_client_factory=lambda: mock_client)
```

The `mock_client` is already a manually constructed object with `mock_client.get = mock_get`, so the test logic itself needs no change — only the injection mechanism.

The `test_session_receives_ws_events`, `test_reconnection_after_disconnect`, and `test_deduplication_by_seq` tests use `patch.object(consumer, "_buffer_ws", ...)` and `patch.object(consumer, "_session", ...)`. These are patching methods **on the specific consumer instance under test**, not patching a module-level symbol. This is the grey area mentioned in the issue. The assessment here is: these are testing integration between `_session` and its internal sub-methods; the consumer is the unit, and the patch.object calls isolate specific internal paths within that unit without polluting external namespaces. They are **acceptable as-is** and require no change.

Similarly, `patch("pipeline.events.consumer.connect")` in `test_reconnection_after_disconnect` patches the `websockets.connect` function inside the consumer module. This is a module-level symbol patch and should ideally be replaced with a `connect_fn` parameter on `EventConsumer.__init__` or `run()`. However, given the complexity of the async iterator protocol for `websockets.connect` (it yields websockets in a `async for` loop for reconnection), this is deferred — the `_session`-level patch.object approach already removes the need to exercise the full reconnect loop in most tests. Phase 5 targets only the `httpx.AsyncClient` injection.

---

## Additional Considerations

### What is not changing

- `MagicMock(spec=logging.Logger)` usages in `test_main.py` are fine. `logger` is already a parameter on `walk_roots` and `crawl()` — the logger duck-typed with `MagicMock(spec=...)` is legitimate DI, not patching.
- `conftest.py` fixtures that use `monkeypatch.setattr` (e.g., `cli_db` patching `pipeline.auth_cli.settings`) are already compliant.
- The `test_routes.py` and `test_events.py` integration tests using the real `client` fixture (Starlette TestClient + real WebSocket connections) are untouched.
- `patch.object` on consumer instance methods (`_buffer_ws`, `_session`, `_catch_up`) is acceptable and not in scope.

### Shared fakes

`FakeWebSocket`, `FakeUrlopen`, `FakePostDelivery`, and `FakeSleep` are simple enough to define inline in each test module. If they drift toward 20+ lines or are needed by more than two test files, a `tests/fakes.py` module is the natural home. For this issue, keep them co-located with their tests.

### Protocol definitions

Type annotations for injected parameters are useful but optional. If added, they belong in the source module alongside the function:

```python
from typing import Protocol

class UrlOpenProtocol(Protocol):
    def __call__(self, request: urllib.request.Request): ...
```

This is a quality-of-life improvement, not required for the issue. Add if the reviewer asks; skip if not.

### Ordering

Phases 1–3 are independent and can be done in any order or in parallel branches. Phase 4 and Phase 5 are also independent of each other and of 1–3. Suggested order: 1 → 2 → 3 → 4 → 5, working file by file, running `uv run pytest` after each phase.

### Risk

All changes are purely additive (new keyword parameters with defaults). No call site outside tests is affected. The production behaviour is identical. The only risk is accidentally changing an assertion — running the full test suite after each phase catches this immediately.
