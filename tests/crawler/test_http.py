# pattern: test file
import json
import urllib.error
import urllib.request

import pytest

from pipeline.crawler.http import (
    RegistryClientError,
    RegistryUnreachableError,
    post_delivery,
)


class _FakeResponse:
    def __init__(self, body, status=200):
        self._body = json.dumps(body).encode()
        self._status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._body

    @property
    def status(self):
        return self._status


class FakeUrlopen:
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
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds):
        self.calls.append(seconds)


class _ErrBody:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def close(self):
        pass


class TestPostDeliverySuccess:
    """AC5.1, AC5.2 — Successful requests and retry scenarios."""

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

    def test_retry_on_500_succeeds_third_attempt(self):
        """AC5.2: 5xx triggers retry with backoff, succeeds on later attempt."""
        payload = {"source_path": "/data/test", "version": "v01"}
        response_body = {"delivery_id": "abc123", "status": "pending"}

        err = urllib.error.HTTPError(
            "http://localhost:8000/deliveries",
            500,
            "Internal Server Error",
            {},
            None,
        )
        fake = FakeUrlopen([err, err, response_body])
        sleep = FakeSleep()

        result = post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        assert result == response_body
        assert len(fake.calls) == 3
        assert sleep.calls == [2, 4]

    def test_retry_on_connection_error_succeeds(self):
        """AC5.2: Connection error triggers retry, succeeds on later attempt."""
        payload = {"source_path": "/data/test", "version": "v01"}
        response_body = {"delivery_id": "abc123", "status": "pending"}

        fake = FakeUrlopen(
            [
                urllib.error.URLError("Connection refused"),
                response_body,
            ]
        )
        sleep = FakeSleep()

        result = post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        assert result == response_body
        assert len(fake.calls) == 2


class TestPostDeliveryFailure:
    """AC5.3, AC5.5 — Exhausted retries and 4xx errors."""

    def test_all_retries_exhausted_raises_error(self):
        """AC5.3: All 3 retries exhausted raises RegistryUnreachableError."""
        payload = {"source_path": "/data/test", "version": "v01"}

        fake = FakeUrlopen([urllib.error.URLError("Connection refused")] * 4)
        sleep = FakeSleep()

        with pytest.raises(RegistryUnreachableError):
            post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        assert len(fake.calls) == 4
        assert sleep.calls == [2, 4, 8]

    def test_four_hundred_error_not_retried(self):
        """AC5.5: 4xx response is NOT retried (immediate failure)."""
        payload = {"source_path": "/data/test", "version": "v01"}

        err = urllib.error.HTTPError(
            "http://localhost:8000/deliveries",
            422,
            "Unprocessable Entity",
            {},
            _ErrBody(b'{"error": "Unprocessable Entity"}'),
        )
        fake = FakeUrlopen([err])
        sleep = FakeSleep()

        with pytest.raises(RegistryClientError) as exc_info:
            post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        assert len(fake.calls) == 1
        assert exc_info.value.status_code == 422
        assert exc_info.value.body == '{"error": "Unprocessable Entity"}'


class TestPostDeliveryBackoff:
    """Verify backoff timing and request construction."""

    def test_backoff_sleep_durations(self):
        """Verify backoff sleep durations are 2, 4, 8 seconds."""
        payload = {"source_path": "/data/test", "version": "v01"}

        fake = FakeUrlopen([urllib.error.URLError("fail")] * 4)
        sleep = FakeSleep()

        with pytest.raises(RegistryUnreachableError):
            post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        assert sleep.calls == [2, 4, 8]

    def test_request_url_construction(self):
        """Verify request has correct URL construction."""
        payload = {"source_path": "/data/test", "version": "v01"}
        fake = FakeUrlopen([{"delivery_id": "test"}])
        sleep = FakeSleep()

        post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        assert fake.calls[0].get_full_url() == "http://localhost:8000/deliveries"

    def test_request_headers_and_body(self):
        """Verify request has correct Content-Type header and JSON body."""
        payload = {"source_path": "/data/test", "version": "v01"}
        fake = FakeUrlopen([{"delivery_id": "test"}])
        sleep = FakeSleep()

        post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        request = fake.calls[0]
        assert request.data == json.dumps(payload).encode()
        assert request.get_header("Content-type") == "application/json"
        assert request.method == "POST"

    def test_auth_header_included_when_token_provided(self):
        """Authorization header is set when a token is provided."""
        payload = {"source_path": "/data/test", "version": "v01"}
        fake = FakeUrlopen([{"delivery_id": "test"}])
        sleep = FakeSleep()

        post_delivery(
            "http://localhost:8000",
            payload,
            token="secret-token",
            urlopen=fake,
            sleep=sleep,
        )

        assert fake.calls[0].get_header("Authorization") == "Bearer secret-token"

    def test_no_auth_header_when_token_is_none(self):
        """No Authorization header when token is None."""
        payload = {"source_path": "/data/test", "version": "v01"}
        fake = FakeUrlopen([{"delivery_id": "test"}])
        sleep = FakeSleep()

        post_delivery("http://localhost:8000", payload, urlopen=fake, sleep=sleep)

        assert fake.calls[0].get_header("Authorization") is None

    def test_url_trailing_slash_stripped(self):
        """Verify trailing slash in api_url is handled correctly."""
        payload = {"source_path": "/data/test", "version": "v01"}
        fake = FakeUrlopen([{"delivery_id": "test"}])
        sleep = FakeSleep()

        post_delivery("http://localhost:8000/", payload, urlopen=fake, sleep=sleep)

        assert fake.calls[0].get_full_url() == "http://localhost:8000/deliveries"
