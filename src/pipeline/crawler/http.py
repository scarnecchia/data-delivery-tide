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
