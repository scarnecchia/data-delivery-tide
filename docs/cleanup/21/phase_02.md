# GH21 Phase 2: HTTP DI for crawler/http and converter/http

**Goal:** Replace every `unittest.mock.patch("...urlopen")` and `patch("...time.sleep")` in `tests/crawler/test_http.py` and `tests/converter/test_http.py` with injected fakes by adding `urlopen` and `sleep` keyword parameters to the production HTTP functions.

**Architecture:** Same DI pattern as `engine.convert_one`. Public functions in both `crawler/http.py` and `converter/http.py` accept `urlopen` and `sleep` as keyword-only parameters defaulting to `urllib.request.urlopen` and `time.sleep`. The converter module's private helper `_request_with_retry` accepts the same parameters and the public functions thread them through. Tests build small `FakeUrlopen` and `FakeSleep` classes co-located with their tests (no shared `tests/fakes.py` — neither file imports from the other and the design explicitly defers extraction).

**Tech Stack:** Python stdlib `urllib.request`, `urllib.error`, `time`; pytest. No new dependencies.

**Scope:** 2 of 5 phases of GH21. Touches `src/pipeline/crawler/http.py`, `src/pipeline/converter/http.py`, `tests/crawler/test_http.py`, `tests/converter/test_http.py`. Independent of phases 1, 3, 4, 5.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH21.AC2: `tests/converter/test_http.py`
- **GH21.AC2.1 Success:** All `TestGetDelivery`, `TestPatchDelivery`, `TestListUnconverted`, `TestEmitEvent` tests pass with a fake transport object instead of `patch("urllib.request.urlopen")`
- **GH21.AC2.2 Success:** `_request_with_retry` (or a renamed equivalent) accepts an `urlopen` parameter that defaults to `urllib.request.urlopen`
- **GH21.AC2.3 Success:** Retry/backoff tests inject a fake `sleep` alongside the fake `urlopen`

### GH21.AC3: `tests/crawler/test_http.py`
- **GH21.AC3.1 Success:** All `TestPostDeliverySuccess`, `TestPostDeliveryFailure`, `TestPostDeliveryBackoff` tests pass with injected fakes instead of `patch`
- **GH21.AC3.2 Success:** `post_delivery` accepts `urlopen` and `sleep` parameters (defaults to `urllib.request.urlopen` and `time.sleep`)

---

## Codebase verification findings

- ✓ `src/pipeline/crawler/http.py:24` — `post_delivery(api_url: str, payload: dict, token: str | None = None) -> dict` exists; calls `urllib.request.urlopen` at line 55 and `time.sleep` at line 68.
- ✓ `src/pipeline/converter/http.py:24` — `_request_with_retry(request) -> dict` exists; calls `urllib.request.urlopen` at line 30 and `time.sleep` at line 41.
- ✓ `src/pipeline/converter/http.py` public callers of `_request_with_retry`: `get_delivery` (line 48), `patch_delivery` (line 59), `list_unconverted` (line 76), `emit_event` (line 94). Each receives only an `api_url` (and call-specific arguments) and passes a constructed `Request` to `_request_with_retry`.
- ✓ `tests/crawler/test_http.py:3` — `from unittest.mock import MagicMock, patch, call` — all three of these need to be removed by the end of this phase. Note: `call` is imported but not used by any test that the design says to convert; the executor must verify with grep before removing the symbol.
- ✓ `tests/converter/test_http.py:1` — already labelled `# pattern: test file` (Phase 2 only modifies test bodies, not line 1).
- ✓ `tests/converter/test_http.py:4` — `from unittest.mock import patch, MagicMock`. Both are used for `patch("...urlopen")` and `MagicMock` builders for response context managers.
- ✓ `tests/crawler/test_http.py` lines 22, 37-38, 73-74, 97-98, 114, 143-144, 163-164, 179-180, 197-198, 212-213, 227-228 use `with patch(...)` blocks. The decorators on `tests/converter/test_http.py` (lines 28, 34, 48, 64, 72, 84, 108-109, 123-124, 132-133, 143-144) are class-method `@patch` decorators that pass mock objects as method parameters.
- ✓ `crawler/http.py` uses **bare** `urllib.request.urlopen` (calls the module function), so production callers will not pass `urlopen=`. `converter/http.py` is the same.
- ⚠ `tests/converter/test_http.py:108` and similar lines have **two stacked decorators** (`@patch("...time.sleep")` outermost, `@patch("...urllib.request.urlopen")` innermost). After conversion, both fakes are passed via the new kwargs in a single call — no decorator stacking needed.

## External dependency findings

N/A — `urllib.request` and `time` are stdlib; their contracts (`urlopen(request)` returns a context manager whose `__enter__` returns an object with a `read()` method and `status` attribute; `urlopen` raises `urllib.error.HTTPError`/`URLError`/`OSError`; `time.sleep(seconds)` returns None) are stable across Python 3.10-3.13.

---

<!-- START_TASK_1 -->
### Task 1: Add `urlopen` and `sleep` kwargs to `crawler/http.post_delivery`

**Verifies:** GH21.AC3.2 (signature change only — tests come in Task 4)

**Files:**
- Modify: `src/pipeline/crawler/http.py:24-72` — change `post_delivery` signature and the two call sites (`urllib.request.urlopen` on line 55, `time.sleep` on line 68).

**Implementation:**

```python
def post_delivery(
    api_url: str,
    payload: dict,
    token: str | None = None,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict:
    """POST a delivery payload to the registry API.

    The `urlopen` and `sleep` keyword-only parameters exist for testability —
    production callers leave them at their defaults; tests pass fakes.
    """
    url = f"{api_url.rstrip('/')}/deliveries"
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST",
    )

    last_error: Exception | None = None

    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        try:
            with urlopen(request) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                body = exc.read().decode()
                raise RegistryClientError(exc.code, body) from exc
            last_error = exc
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc

        if attempt < len(_BACKOFF_SECONDS):
            sleep(_BACKOFF_SECONDS[attempt])

    raise RegistryUnreachableError(
        f"registry API unreachable after {len(_BACKOFF_SECONDS) + 1} attempts: {last_error}"
    )
```

The two changes versus the current line 55 and 68 are exactly: `urllib.request.urlopen(request)` → `urlopen(request)` and `time.sleep(_BACKOFF_SECONDS[attempt])` → `sleep(_BACKOFF_SECONDS[attempt])`. Everything else in the function body stays as-is, including the existing `urllib.request.Request(…)` call which is not an external collaborator (it builds an in-memory object, doesn't perform I/O).

**Verification:**

```bash
uv run python -c "
import inspect, time, urllib.request
from pipeline.crawler.http import post_delivery
sig = inspect.signature(post_delivery)
assert sig.parameters['urlopen'].kind is inspect.Parameter.KEYWORD_ONLY
assert sig.parameters['urlopen'].default is urllib.request.urlopen
assert sig.parameters['sleep'].kind is inspect.Parameter.KEYWORD_ONLY
assert sig.parameters['sleep'].default is time.sleep
print('OK')
"
```

Expected: `OK`.

**Commit:** deferred to Task 4 (single commit for the phase).
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Add `urlopen` and `sleep` kwargs to `converter/http._request_with_retry` and the four public callers

**Verifies:** GH21.AC2.2 (private helper accepts `urlopen` parameter; tests in Task 5).

**Files:**
- Modify: `src/pipeline/converter/http.py:24-45` — change `_request_with_retry` signature, replace `urllib.request.urlopen` (line 30) and `time.sleep` (line 41).
- Modify: `src/pipeline/converter/http.py:48-56` (`get_delivery`), `:59-73` (`patch_delivery`), `:76-91` (`list_unconverted`), `:94-113` (`emit_event`) — each public function gains the same two kwargs and threads them through to `_request_with_retry`.

**Implementation:**

`_request_with_retry`:

```python
def _request_with_retry(
    request: urllib.request.Request,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict:
    """Execute a urllib Request with exponential backoff on 5xx/network errors."""
    last_error: Exception | None = None

    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        try:
            with urlopen(request) as response:
                body = response.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RegistryClientError(exc.code, exc.read().decode()) from exc
            last_error = exc
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc

        if attempt < len(_BACKOFF_SECONDS):
            sleep(_BACKOFF_SECONDS[attempt])

    raise RegistryUnreachableError(
        f"registry API unreachable after {len(_BACKOFF_SECONDS) + 1} attempts: {last_error}"
    )
```

Each of the four public functions gains the identical kwargs and threads them through. For example `get_delivery`:

```python
def get_delivery(
    api_url: str,
    delivery_id: str,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict:
    """
    GET /deliveries/{delivery_id} — returns the DeliveryResponse dict.

    Raises RegistryClientError(404) if the delivery does not exist.
    """
    url = f"{api_url.rstrip('/')}/deliveries/{delivery_id}"
    request = urllib.request.Request(url, method="GET")
    return _request_with_retry(request, urlopen=urlopen, sleep=sleep)
```

Apply the same shape to `patch_delivery`, `list_unconverted`, and `emit_event`. The bodies are unchanged except for the trailing `return _request_with_retry(request, urlopen=urlopen, sleep=sleep)`.

**Why thread through every public function:** The design Section "Target State" lists `_request_with_retry` as the seam, but the converter test classes (`TestGetDelivery`, `TestPatchDelivery`, `TestListUnconverted`, `TestEmitEvent`) call the public functions, not `_request_with_retry` directly. To avoid having tests reach into the private helper, the public functions must accept and forward the kwargs.

**Verification:**

```bash
uv run python -c "
import inspect, time, urllib.request
from pipeline.converter.http import (
    _request_with_retry, get_delivery, patch_delivery, list_unconverted, emit_event,
)
for fn in (_request_with_retry, get_delivery, patch_delivery, list_unconverted, emit_event):
    sig = inspect.signature(fn)
    assert sig.parameters['urlopen'].kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__
    assert sig.parameters['urlopen'].default is urllib.request.urlopen, fn.__name__
    assert sig.parameters['sleep'].kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__
    assert sig.parameters['sleep'].default is time.sleep, fn.__name__
print('OK')
"
```

Expected: `OK`.

**Commit:** deferred to Task 5.
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Define `FakeUrlopen`, `_FakeResponse`, `FakeSleep` helpers in each test module

**Verifies:** Setup for AC3.1 and AC2.1 (no test code rewritten yet — that comes in Task 4 and 5).

**Files:**
- Modify: `tests/crawler/test_http.py` — add helpers near the top of the file, after imports, before the first `class Test...`.
- Modify: `tests/converter/test_http.py` — add the same helpers in the same position.

**Implementation:**

The helpers are intentionally small and duplicated between the two test modules per the design's "Shared fakes" section. If they later grow past ~20 lines or land in a third file, the design says to extract to `tests/fakes.py`; that is out of scope here.

```python
import json
import urllib.request
import urllib.error


class _FakeResponse:
    """Stand-in for the object returned by urllib.request.urlopen as a context manager.

    Implements the subset of the response protocol used by the production code:
    `__enter__`/`__exit__`, `read()`, and `status`.
    """

    def __init__(self, body: dict | list, status: int = 200):
        self._body = json.dumps(body).encode()
        self._status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return self._body

    @property
    def status(self) -> int:
        return self._status


class FakeUrlopen:
    """Fake replacement for urllib.request.urlopen.

    Constructed with a sequence of responses where each item is either a body
    dict/list (returned wrapped in _FakeResponse) or a BaseException (raised on
    that call). Records each Request object passed in `self.calls` for assertion.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[urllib.request.Request] = []

    def __call__(self, request):
        self.calls.append(request)
        if not self._responses:
            raise AssertionError("FakeUrlopen called more times than configured")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return _FakeResponse(item)


class FakeSleep:
    """Fake replacement for time.sleep — records seconds without actually sleeping."""

    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
```

The constructor accepts a list and pops from the front so test ordering is FIFO and obvious; raising `AssertionError` on overrun catches misconfigured tests immediately rather than yielding silent stale data.

For `tests/crawler/test_http.py`, the existing top-of-file imports are:

```python
import json
import urllib.error
from unittest.mock import MagicMock, patch, call

import pytest

from pipeline.crawler.http import (
    post_delivery,
    RegistryUnreachableError,
    RegistryClientError,
)
```

Replace with:

```python
# pattern: test file
import json
import urllib.error
import urllib.request

import pytest

from pipeline.crawler.http import (
    post_delivery,
    RegistryUnreachableError,
    RegistryClientError,
)
```

Note: prepend `# pattern: test file` if (and only if) GH27 has not already added it before this branch lands. GH27 plan modifies this exact file's line 1; check `head -1 tests/crawler/test_http.py` first. If the label is already present, leave it. The Edit tool will fail noisily on duplicate prepend.

**GH27 coordination:** GH27 (Tier 0) adds `# pattern: test file` to line 1 before this task runs. The Edit's old_string must include the existing `# pattern: test file` line as the first line to match correctly. Do NOT prepend a duplicate label.

For `tests/converter/test_http.py`, the existing top has `# pattern: test file` (verified) plus:

```python
import json
from unittest.mock import patch, MagicMock
import urllib.error

import pytest
```

Replace with:

```python
# pattern: test file

import json
import urllib.error
import urllib.request

import pytest
```

Note: `urllib.request` is a new import for both files because `FakeUrlopen.calls` is type-annotated `list[urllib.request.Request]`. The existing import `urllib.error` is preserved because the tests still construct `urllib.error.HTTPError` and `urllib.error.URLError` instances to feed into `FakeUrlopen`.

The `_make_urlopen_response` helper currently in `tests/converter/test_http.py:19-24` becomes redundant once `_FakeResponse` is in place — delete it, since `FakeUrlopen([{...}])` returns a `_FakeResponse` directly.

**Verification:**

```bash
grep -n "unittest.mock\|MagicMock\b" tests/crawler/test_http.py tests/converter/test_http.py
```

After Task 5, expect zero matches in either file. (After Task 3 alone, the import lines are gone but the test bodies still need rewriting — so this verification is final-state, not Task-3-only.)

**Commit:** deferred to Task 5.
<!-- END_TASK_3 -->

<!-- START_SUBCOMPONENT_B (tasks 4-5) -->
<!-- START_TASK_4 -->
### Task 4: Rewrite `tests/crawler/test_http.py` test bodies to inject `FakeUrlopen`/`FakeSleep`

**Verifies:** GH21.AC3.1

**Files:**
- Modify: `tests/crawler/test_http.py` — every existing test method.

**Implementation:**

The mapping from the existing tests to the new shape is mechanical. Every `with patch("urllib.request.urlopen") as mock_urlopen:` block becomes a `fake = FakeUrlopen([...])` construction at the top of the test, followed by `post_delivery(..., urlopen=fake)`. Every `with patch("time.sleep") as mock_sleep:` becomes `sleep = FakeSleep()` plus `post_delivery(..., urlopen=fake, sleep=sleep)`.

The tests inspect `fake.calls[i]` (a `urllib.request.Request`) where they currently inspect `mock_urlopen.call_args[0][0]`. Both expose the same `Request` object — assertions on `request.method`, `request.get_full_url()`, `request.data`, `request.headers` work without change.

For the four `TestPostDeliveryBackoff` tests at lines 159-237 that currently `patch("urllib.request.Request")`: do **not** patch the `Request` constructor with a fake. Instead, construct `FakeUrlopen([{"delivery_id": "test"}])` and call `post_delivery(...)`, then assert against `fake.calls[0]` for URL/headers/method/body. Patching `Request` was always a workaround to avoid building a response; with the fake transport that workaround is no longer needed.

Concrete example for `test_successful_post_first_attempt` (lines 17-30):

```python
def test_successful_post_first_attempt(self):
    """AC5.1: Successful POST on first attempt returns response and continues."""
    payload = {"source_path": "/data/test", "version": "v01"}
    response_body = {"delivery_id": "abc123", "status": "pending"}

    fake = FakeUrlopen([response_body])
    sleep = FakeSleep()

    result = post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

    assert result == response_body
    assert len(fake.calls) == 1
    assert sleep.calls == []
```

For `test_retry_on_500_succeeds_third_attempt` (lines 32-67):

```python
def test_retry_on_500_succeeds_third_attempt(self):
    """AC5.2: 5xx triggers retry with backoff, succeeds on later attempt."""
    payload = {"source_path": "/data/test", "version": "v01"}
    response_body = {"delivery_id": "abc123", "status": "pending"}

    err = urllib.error.HTTPError(
        "http://localhost:8000/deliveries", 500, "Internal Server Error", {}, None,
    )
    fake = FakeUrlopen([err, err, response_body])
    sleep = FakeSleep()

    result = post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

    assert result == response_body
    assert len(fake.calls) == 3
    assert sleep.calls == [2, 4]
```

For `test_four_hundred_error_not_retried` (lines 110-133), the `HTTPError` instance must have a `.read()` method that returns the JSON body. The constructor's `fp` argument is treated as a file-like body source — pass a `MagicMock`-free shim:

```python
class _ErrBody:
    def read(self):
        return b'{"error": "Unprocessable Entity"}'

err = urllib.error.HTTPError(
    "http://localhost:8000/deliveries", 422, "Unprocessable Entity", {}, _ErrBody(),
)
fake = FakeUrlopen([err])
sleep = FakeSleep()

with pytest.raises(RegistryClientError) as exc_info:
    post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

assert len(fake.calls) == 1
assert exc_info.value.status_code == 422
assert exc_info.value.body == '{"error": "Unprocessable Entity"}'
```

This replaces the original `MagicMock` that supplied `error_response.read.return_value`. Production code (line 59 in `crawler/http.py`) calls `exc.read()` on the HTTPError — supplying a real object with a `.read()` method makes the test pass without any mock library.

**Special note on `test_request_url_construction`, `test_request_headers_and_body`, `test_auth_header_included_when_token_provided`, `test_no_auth_header_when_token_is_none`, `test_url_trailing_slash_stripped`** (lines 159-237):

These currently use `with patch("urllib.request.Request")` to capture constructor arguments. Rewrite them to inspect the `Request` object captured by `FakeUrlopen.calls[0]`:

```python
def test_request_url_construction(self):
    payload = {"source_path": "/data/test", "version": "v01"}
    fake = FakeUrlopen([{"delivery_id": "test"}])
    sleep = FakeSleep()

    post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

    assert fake.calls[0].get_full_url() == "http://localhost:8000/deliveries"


def test_request_headers_and_body(self):
    payload = {"source_path": "/data/test", "version": "v01"}
    fake = FakeUrlopen([{"delivery_id": "test"}])
    sleep = FakeSleep()

    post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

    request = fake.calls[0]
    assert request.data == json.dumps(payload).encode()
    assert request.headers["Content-type"] == "application/json"
    assert request.method == "POST"
```

Note the header capitalisation: `urllib.request.Request` normalises header names to title-case during `__init__`, so `headers["Content-Type"]` becomes `headers["Content-type"]` when read back. Assert against the capitalised form, or use `request.get_header("Content-type")` which is case-insensitive on the read side. The original test asserted on `kwargs["headers"]["Content-Type"]` because it intercepted the constructor arguments before normalisation; the new test inspects the constructed object after normalisation, so the assertion key changes. This is the only behavioural-shape change in the rewrite.

**Testing:**

Tests must verify each AC listed above:
- GH21.AC3.1: Existing test names (`test_successful_post_first_attempt`, `test_retry_on_500_succeeds_third_attempt`, `test_retry_on_connection_error_succeeds`, `test_all_retries_exhausted_raises_error`, `test_four_hundred_error_not_retried`, `test_backoff_sleep_durations`, `test_request_url_construction`, `test_request_headers_and_body`, `test_auth_header_included_when_token_provided`, `test_no_auth_header_when_token_is_none`, `test_url_trailing_slash_stripped`) all pass with the new fake-injection shape.

Test-implementor generates final test code at execution time using the shapes above. No tests are added or removed.

**Verification:**

```bash
grep -n "unittest.mock\|MagicMock\b\| patch(" tests/crawler/test_http.py
```

Expected: zero matches.

```bash
uv run pytest tests/crawler/test_http.py -v
```

Expected: same number of tests as before, all passing.

**Commit:** deferred to Task 5.
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Rewrite `tests/converter/test_http.py` test bodies, run full converter+crawler tests, commit phase

**Verifies:** GH21.AC2.1, GH21.AC2.3

**Files:**
- Modify: `tests/converter/test_http.py` — every test method in `TestGetDelivery`, `TestPatchDelivery`, `TestListUnconverted`, `TestEmitEvent`, `TestRetryBehaviour`.

**Implementation:**

The class-method decorator pattern (e.g. `@patch("pipeline.converter.http.urllib.request.urlopen")` on line 28) becomes inline `FakeUrlopen` injection. The two-decorator stack (`@patch("...time.sleep")` outermost + `@patch("...urlopen")` innermost) on `TestRetryBehaviour` methods (lines 108-152) collapses to a single call site that passes both `urlopen=` and `sleep=`.

`test_200_returns_body_as_dict` (lines 28-32) becomes:

```python
def test_200_returns_body_as_dict(self):
    fake = FakeUrlopen([{"delivery_id": "abc"}])
    sleep = FakeSleep()
    result = get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)
    assert result == {"delivery_id": "abc"}
```

`test_404_raises_registry_client_error` (lines 34-44) — the existing `http_err.read = lambda: b'{"detail":"Delivery not found"}'` works against a real `HTTPError`, but the constructor's `fp` argument is preferred. Use a `_ErrBody` shim as in Task 4, or keep the `read` override (Python's `urllib.error.HTTPError` permits attribute assignment):

```python
def test_404_raises_registry_client_error(self):
    err = urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=None, fp=None,
    )
    err.read = lambda: b'{"detail":"delivery not found"}'
    fake = FakeUrlopen([err])
    sleep = FakeSleep()

    with pytest.raises(RegistryClientError) as exc_info:
        get_delivery("http://localhost:8000", "missing", urlopen=fake, sleep=sleep)
    assert exc_info.value.status_code == 404
```

`test_sends_json_body_and_returns_updated_row` (lines 48-60) becomes:

```python
def test_sends_json_body_and_returns_updated_row(self):
    fake = FakeUrlopen([{"delivery_id": "abc", "output_path": "/p/x.parquet"}])
    sleep = FakeSleep()

    result = patch_delivery(
        "http://localhost:8000", "abc", {"output_path": "/p/x.parquet"},
        urlopen=fake, sleep=sleep,
    )
    assert result["output_path"] == "/p/x.parquet"

    request = fake.calls[0]
    assert request.method == "PATCH"
    assert request.get_full_url().endswith("/deliveries/abc")
    assert json.loads(request.data) == {"output_path": "/p/x.parquet"}
```

`TestListUnconverted` and `TestEmitEvent` follow the same shape — replace `mock_urlopen.return_value = _make_urlopen_response(...)` with `fake = FakeUrlopen([...])`, and replace `request = mock_urlopen.call_args[0][0]` with `request = fake.calls[0]`.

`TestRetryBehaviour` tests inject both fakes:

```python
def test_5xx_retried_then_succeeds(self):
    err = urllib.error.HTTPError(url="", code=500, msg="x", hdrs=None, fp=None)
    fake = FakeUrlopen([err, err, {"delivery_id": "abc"}])
    sleep = FakeSleep()

    result = get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)

    assert result == {"delivery_id": "abc"}
    assert len(fake.calls) == 3
    assert 2 in sleep.calls
    assert 4 in sleep.calls
```

`test_all_attempts_exhausted_raises_unreachable` (lines 123-130):

```python
def test_all_attempts_exhausted_raises_unreachable(self):
    err = urllib.error.HTTPError(url="", code=500, msg="x", hdrs=None, fp=None)
    fake = FakeUrlopen([err, err, err, err])
    sleep = FakeSleep()
    with pytest.raises(RegistryUnreachableError):
        get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)
    assert len(fake.calls) == 4
```

`test_4xx_not_retried` (lines 132-141) — same pattern, with `_ErrBody` shim if you prefer real attributes over `read = lambda` mutation:

```python
def test_4xx_not_retried(self):
    err = urllib.error.HTTPError(url="", code=422, msg="x", hdrs=None, fp=None)
    err.read = lambda: b'{"detail":"bad"}'
    fake = FakeUrlopen([err])
    sleep = FakeSleep()
    with pytest.raises(RegistryClientError):
        patch_delivery("http://localhost:8000", "abc", {"k": "v"}, urlopen=fake, sleep=sleep)
    assert len(fake.calls) == 1
    assert sleep.calls == []
```

`test_network_error_retried` (lines 143-151):

```python
def test_network_error_retried(self):
    fake = FakeUrlopen([
        urllib.error.URLError("connection refused"),
        {"delivery_id": "abc"},
    ])
    sleep = FakeSleep()
    result = get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)
    assert result == {"delivery_id": "abc"}
```

**Testing:**

Tests must verify each AC listed above:
- GH21.AC2.1: `TestGetDelivery`, `TestPatchDelivery`, `TestListUnconverted`, `TestEmitEvent` pass without `patch`.
- GH21.AC2.3: `TestRetryBehaviour` injects `FakeSleep()` alongside `FakeUrlopen([...])` and asserts on `sleep.calls` for backoff verification.

**Verification:**

```bash
grep -n "unittest.mock\|MagicMock\b\|@patch\| patch(" tests/converter/test_http.py
```

Expected: zero matches.

```bash
uv run pytest tests/converter/test_http.py tests/crawler/test_http.py -v
```

Expected: all tests in both files pass with the same count as before this phase.

**Commit:**

```bash
git add src/pipeline/crawler/http.py \
        src/pipeline/converter/http.py \
        tests/crawler/test_http.py \
        tests/converter/test_http.py
git commit -m "refactor(http): inject urlopen and sleep instead of patching (GH21 phase 2)"
```
<!-- END_TASK_5 -->
<!-- END_SUBCOMPONENT_B -->

---

## Phase 2 Done When

- `crawler/http.post_delivery` and the four converter `http` public functions plus `_request_with_retry` accept `urlopen` and `sleep` keyword-only parameters with their respective stdlib defaults.
- `tests/crawler/test_http.py` and `tests/converter/test_http.py` import nothing from `unittest.mock` and use no `MagicMock` or `@patch`.
- All retry/backoff tests inject `FakeSleep` and assert on `sleep.calls`.
- `uv run pytest tests/converter/test_http.py tests/crawler/test_http.py` passes with the same test count as before this phase.

## Notes for executor

- **Phase ordering:** independent of phases 1, 3, 4, 5.
- **Conflict surface:** `crawler/http.py` and `converter/http.py` are not modified by any other GH issue currently in flight (verified against the DAG at `docs/project/DAG.md`).
- **GH27 interaction:** `tests/crawler/test_http.py` is on GH27's add-label list. If GH27 lands first, `head -1` of that file is already `# pattern: test file` and Task 3's edit must preserve it. If GH21 lands first, GH27 prepends the label as planned. The Edit tool's exact-match behaviour will surface any drift loudly.
