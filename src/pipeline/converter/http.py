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


def patch_delivery(
    api_url: str,
    delivery_id: str,
    updates: dict,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict:
    """
    PATCH /deliveries/{delivery_id} with the given partial update dict.

    Accepts any subset of DeliveryUpdate fields. Returns the full updated row.
    """
    url = f"{api_url.rstrip('/')}/deliveries/{delivery_id}"
    data = json.dumps(updates).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    return _request_with_retry(request, urlopen=urlopen, sleep=sleep)


def list_unconverted(
    api_url: str,
    after: str = "",
    limit: int = 200,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> list[dict]:
    """
    GET /deliveries?converted=false&after=&limit= — returns a page of delivery dicts.

    Empty `after` is treated as "start from the beginning" (the registry
    pagination builds a `delivery_id > after` condition; empty string
    sorts before all hex digests).
    """
    params = f"converted=false&after={after}&limit={limit}"
    url = f"{api_url.rstrip('/')}/deliveries?{params}"
    request = urllib.request.Request(url, method="GET")
    return _request_with_retry(request, urlopen=urlopen, sleep=sleep)


def emit_event(
    api_url: str,
    event_type: str,
    delivery_id: str,
    payload: dict,
    *,
    urlopen=urllib.request.urlopen,
    sleep=time.sleep,
) -> dict:
    """
    POST /events with the given EventCreate body — returns the inserted EventRecord.

    event_type must be one of "conversion.completed" or "conversion.failed";
    the registry rejects other values with 422.
    """
    url = f"{api_url.rstrip('/')}/events"
    body = json.dumps({
        "event_type": event_type,
        "delivery_id": delivery_id,
        "payload": payload,
    }).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _request_with_retry(request, urlopen=urlopen, sleep=sleep)
