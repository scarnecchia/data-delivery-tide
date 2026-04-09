# Crawler Service Implementation Plan

**Goal:** Build the filesystem crawler intake layer for the healthcare data pipeline

**Architecture:** Functional Core / Imperative Shell. Pure functions handle parsing, fingerprinting, and manifest construction. Thin imperative shell handles filesystem I/O, manifest writing, and HTTP calls.

**Tech Stack:** Python 3.10+, stdlib only (no new runtime deps), pytest + httpx for testing

**Scope:** 5 phases from original design (phases 1-5)

**Codebase verified:** 2026-04-09

---

## Acceptance Criteria Coverage

This phase implements and tests:

### crawler.AC5: Retry and Abort
- **crawler.AC5.1 Success:** Successful POST on first attempt returns response and continues
- **crawler.AC5.2 Success:** Transient 5xx triggers retry with backoff (2s, 4s, 8s), succeeds on later attempt
- **crawler.AC5.3 Failure:** All 3 retries exhausted raises RegistryUnreachableError
- **crawler.AC5.4 Failure:** Crawler exits non-zero when RegistryUnreachableError is raised
- **crawler.AC5.5 Edge:** 4xx response is NOT retried (immediate failure)

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Create http.py with post_delivery() and RegistryUnreachableError

**Verifies:** crawler.AC5.1, crawler.AC5.2, crawler.AC5.3, crawler.AC5.5

**Files:**
- Create: `src/pipeline/crawler/http.py`
- Create: `tests/crawler/test_http.py`

**Implementation:**

`http.py` is Imperative Shell — it performs HTTP I/O. Uses stdlib `urllib.request` to POST JSON to the registry API. Retries on connection errors and 5xx responses with exponential backoff (2s, 4s, 8s). Does NOT retry 4xx. Raises `RegistryUnreachableError` after exhausting all retries.

The registry API's `POST /deliveries` endpoint returns HTTP 200 with a `DeliveryResponse` JSON body on success.

```python
# pattern: Imperative Shell
import json
import time
import urllib.error
import urllib.request


class RegistryUnreachableError(Exception):
    """Raised when all retry attempts to the registry API are exhausted."""


class RegistryClientError(Exception):
    """Raised on 4xx responses (client errors that should not be retried)."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"registry returned {status_code}: {body}")


_BACKOFF_SECONDS = (2, 4, 8)


def post_delivery(api_url: str, payload: dict) -> dict:
    """POST a delivery payload to the registry API.

    Args:
        api_url: Base URL of the registry API (e.g. "http://localhost:8000")
        payload: Dict matching the DeliveryCreate schema

    Returns:
        Response body dict (DeliveryResponse)

    Raises:
        RegistryUnreachableError: All retry attempts exhausted
        RegistryClientError: 4xx response (not retried)
    """
    url = f"{api_url.rstrip('/')}/deliveries"
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last_error: Exception | None = None

    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        try:
            with urllib.request.urlopen(request) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                body = exc.read().decode()
                raise RegistryClientError(exc.code, body) from exc
            # 5xx — retry
            last_error = exc
        except (urllib.error.URLError, OSError) as exc:
            # Connection refused, timeout, DNS failure — retry
            last_error = exc

        if attempt < len(_BACKOFF_SECONDS):
            time.sleep(_BACKOFF_SECONDS[attempt])

    raise RegistryUnreachableError(
        f"registry API unreachable after {len(_BACKOFF_SECONDS) + 1} attempts: {last_error}"
    )
```

**Testing:**

Tests must mock `urllib.request.urlopen` to simulate various HTTP scenarios. Follow project conventions: class-based grouping.

- **crawler.AC5.1:** Mock urlopen to return 200 with JSON body on first call. Assert response dict returned, urlopen called exactly once.
- **crawler.AC5.2:** Mock urlopen to raise HTTPError(500) on first two calls, return 200 on third. Assert response returned. Use `unittest.mock.patch` on `time.sleep` to avoid real delays.
- **crawler.AC5.3:** Mock urlopen to always raise URLError (connection refused). Assert RegistryUnreachableError raised after 4 total attempts (1 initial + 3 retries).
- **crawler.AC5.5:** Mock urlopen to raise HTTPError(422). Assert RegistryClientError raised immediately, urlopen called exactly once, no retries.

Additional tests:
- Verify backoff sleep durations are 2, 4, 8 seconds (via mocked time.sleep call args)
- Verify request has correct URL construction, Content-Type header, and JSON body

Test file structure:

```python
class TestPostDeliverySuccess:
    # AC5.1, AC5.2

class TestPostDeliveryFailure:
    # AC5.3, AC5.5

class TestPostDeliveryBackoff:
    # Backoff timing verification
```

**Verification:**

Run: `uv run pytest tests/crawler/test_http.py -v`
Expected: All tests pass

**Commit:** `feat(crawler): implement HTTP client with retry and backoff`
<!-- END_TASK_1 -->

<!-- END_SUBCOMPONENT_A -->

**Note:** crawler.AC5.4 (non-zero exit on RegistryUnreachableError) is verified in Phase 5 when the orchestrator catches this exception and calls `sys.exit(1)`.
