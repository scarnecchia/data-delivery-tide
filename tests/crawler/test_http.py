# pattern: test file
import json
import urllib.error
from unittest.mock import MagicMock, patch, call

import pytest

from pipeline.crawler.http import (
    post_delivery,
    RegistryUnreachableError,
    RegistryClientError,
)


class TestPostDeliverySuccess:
    """AC5.1, AC5.2 — Successful requests and retry scenarios."""

    def test_successful_post_first_attempt(self):
        """AC5.1: Successful POST on first attempt returns response and continues."""
        payload = {"source_path": "/data/test", "version": "v01"}
        response_body = {"delivery_id": "abc123", "status": "pending"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(response_body).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = post_delivery("http://localhost:8000", payload)

            assert result == response_body
            assert mock_urlopen.call_count == 1

    def test_retry_on_500_succeeds_third_attempt(self):
        """AC5.2: 5xx triggers retry with backoff, succeeds on later attempt."""
        payload = {"source_path": "/data/test", "version": "v01"}
        response_body = {"delivery_id": "abc123", "status": "pending"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            with patch("time.sleep") as mock_sleep:
                # First two calls raise 500, third succeeds
                mock_response = MagicMock()
                mock_response.read.return_value = json.dumps(response_body).encode()

                mock_urlopen.side_effect = [
                    urllib.error.HTTPError(
                        "http://localhost:8000/deliveries",
                        500,
                        "Internal Server Error",
                        {},
                        None,
                    ),
                    urllib.error.HTTPError(
                        "http://localhost:8000/deliveries",
                        500,
                        "Internal Server Error",
                        {},
                        None,
                    ),
                    MagicMock(
                        __enter__=MagicMock(return_value=mock_response),
                        __exit__=MagicMock(return_value=False),
                    ),
                ]

                result = post_delivery("http://localhost:8000", payload)

                assert result == response_body
                # 1 initial + 2 retries = 3 calls
                assert mock_urlopen.call_count == 3
                # Verify backoff sleep durations
                mock_sleep.assert_has_calls([call(2), call(4)])

    def test_retry_on_connection_error_succeeds(self):
        """AC5.2: Connection error triggers retry, succeeds on later attempt."""
        payload = {"source_path": "/data/test", "version": "v01"}
        response_body = {"delivery_id": "abc123", "status": "pending"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            with patch("time.sleep"):
                mock_response = MagicMock()
                mock_response.read.return_value = json.dumps(response_body).encode()

                mock_urlopen.side_effect = [
                    urllib.error.URLError("Connection refused"),
                    MagicMock(
                        __enter__=MagicMock(return_value=mock_response),
                        __exit__=MagicMock(return_value=False),
                    ),
                ]

                result = post_delivery("http://localhost:8000", payload)

                assert result == response_body
                assert mock_urlopen.call_count == 2


class TestPostDeliveryFailure:
    """AC5.3, AC5.5 — Exhausted retries and 4xx errors."""

    def test_all_retries_exhausted_raises_error(self):
        """AC5.3: All 3 retries exhausted raises RegistryUnreachableError."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            with patch("time.sleep") as mock_sleep:
                # Always raise URLError (connection refused)
                mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

                with pytest.raises(RegistryUnreachableError):
                    post_delivery("http://localhost:8000", payload)

                # 1 initial + 3 retries = 4 total attempts
                assert mock_urlopen.call_count == 4
                # 3 sleep calls for backoff between attempts
                mock_sleep.assert_has_calls([call(2), call(4), call(8)])

    def test_four_hundred_error_not_retried(self):
        """AC5.5: 4xx response is NOT retried (immediate failure)."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            error_response = MagicMock()
            error_response.read.return_value = b'{"error": "Unprocessable Entity"}'

            exc = urllib.error.HTTPError(
                "http://localhost:8000/deliveries",
                422,
                "Unprocessable Entity",
                {},
                error_response,
            )
            mock_urlopen.side_effect = exc

            with pytest.raises(RegistryClientError) as exc_info:
                post_delivery("http://localhost:8000", payload)

            # Verify called exactly once, no retries
            assert mock_urlopen.call_count == 1
            assert exc_info.value.status_code == 422
            assert exc_info.value.body == '{"error": "Unprocessable Entity"}'


class TestPostDeliveryBackoff:
    """Verify backoff timing and request construction."""

    def test_backoff_sleep_durations(self):
        """Verify backoff sleep durations are 2, 4, 8 seconds."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.urlopen") as mock_urlopen:
            with patch("time.sleep") as mock_sleep:
                mock_urlopen.side_effect = [
                    urllib.error.URLError("fail"),
                    urllib.error.URLError("fail"),
                    urllib.error.URLError("fail"),
                    urllib.error.URLError("fail"),
                ]

                with pytest.raises(RegistryUnreachableError):
                    post_delivery("http://localhost:8000", payload)

                # Should have exactly 3 sleep calls with correct durations
                mock_sleep.assert_has_calls([call(2), call(4), call(8)])
                assert mock_sleep.call_count == 3

    def test_request_url_construction(self):
        """Verify request has correct URL construction."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.Request") as mock_request:
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b'{"delivery_id": "test"}'
                mock_urlopen.return_value.__enter__.return_value = mock_response

                post_delivery("http://localhost:8000", payload)

                # Verify Request was called with correct URL
                args, kwargs = mock_request.call_args
                assert args[0] == "http://localhost:8000/deliveries"

    def test_request_headers_and_body(self):
        """Verify request has correct Content-Type header and JSON body."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.Request") as mock_request:
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b'{"delivery_id": "test"}'
                mock_urlopen.return_value.__enter__.return_value = mock_response

                post_delivery("http://localhost:8000", payload)

                # Verify Request was called with correct parameters
                args, kwargs = mock_request.call_args
                assert kwargs["data"] == json.dumps(payload).encode()
                assert kwargs["headers"]["Content-Type"] == "application/json"
                assert kwargs["method"] == "POST"

    def test_auth_header_included_when_token_provided(self):
        """Authorization header is set when a token is provided."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.Request") as mock_request:
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b'{"delivery_id": "test"}'
                mock_urlopen.return_value.__enter__.return_value = mock_response

                post_delivery("http://localhost:8000", payload, token="secret-token")

                args, kwargs = mock_request.call_args
                assert kwargs["headers"]["Authorization"] == "Bearer secret-token"

    def test_no_auth_header_when_token_is_none(self):
        """No Authorization header when token is None."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.Request") as mock_request:
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b'{"delivery_id": "test"}'
                mock_urlopen.return_value.__enter__.return_value = mock_response

                post_delivery("http://localhost:8000", payload)

                args, kwargs = mock_request.call_args
                assert "Authorization" not in kwargs["headers"]

    def test_url_trailing_slash_stripped(self):
        """Verify trailing slash in api_url is handled correctly."""
        payload = {"source_path": "/data/test", "version": "v01"}

        with patch("urllib.request.Request") as mock_request:
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b'{"delivery_id": "test"}'
                mock_urlopen.return_value.__enter__.return_value = mock_response

                post_delivery("http://localhost:8000/", payload)

                # Verify Request was called with correct URL (slash removed)
                args, kwargs = mock_request.call_args
                assert args[0] == "http://localhost:8000/deliveries"
