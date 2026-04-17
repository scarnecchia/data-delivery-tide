# pattern: test file

import json
from unittest.mock import patch, MagicMock
import urllib.error

import pytest

from pipeline.converter.http import (
    RegistryUnreachableError,
    RegistryClientError,
    get_delivery,
    patch_delivery,
    emit_event,
)


def _make_urlopen_response(body: dict, status: int = 200):
    """Build a context-manager mock matching urllib.request.urlopen's contract."""
    mock = MagicMock()
    mock.__enter__.return_value.read.return_value = json.dumps(body).encode()
    mock.__enter__.return_value.status = status
    return mock


class TestGetDelivery:
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_200_returns_body_as_dict(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_response({"delivery_id": "abc"})
        result = get_delivery("http://localhost:8000", "abc")
        assert result == {"delivery_id": "abc"}

    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_404_raises_registry_client_error(self, mock_urlopen):
        http_err = urllib.error.HTTPError(
            url="", code=404, msg="Not Found", hdrs=None, fp=None
        )
        http_err.read = lambda: b'{"detail":"Delivery not found"}'
        mock_urlopen.side_effect = http_err

        with pytest.raises(RegistryClientError) as exc_info:
            get_delivery("http://localhost:8000", "missing")
        assert exc_info.value.status_code == 404


class TestPatchDelivery:
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_sends_json_body_and_returns_updated_row(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_response(
            {"delivery_id": "abc", "output_path": "/p/x.parquet"}
        )
        result = patch_delivery("http://localhost:8000", "abc", {"output_path": "/p/x.parquet"})
        assert result["output_path"] == "/p/x.parquet"

        # Inspect the Request object passed to urlopen.
        request = mock_urlopen.call_args[0][0]
        assert request.method == "PATCH"
        assert request.get_full_url().endswith("/deliveries/abc")
        assert json.loads(request.data) == {"output_path": "/p/x.parquet"}


class TestEmitEvent:
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_posts_correct_shape(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_response(
            {"seq": 5, "event_type": "conversion.completed", "delivery_id": "abc"}
        )
        result = emit_event(
            "http://localhost:8000",
            "conversion.completed",
            "abc",
            {"row_count": 10},
        )
        assert result["seq"] == 5

        request = mock_urlopen.call_args[0][0]
        assert request.method == "POST"
        body = json.loads(request.data)
        assert body == {
            "event_type": "conversion.completed",
            "delivery_id": "abc",
            "payload": {"row_count": 10},
        }


class TestRetryBehaviour:
    @patch("pipeline.converter.http.time.sleep")
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_5xx_retried_then_succeeds(self, mock_urlopen, mock_sleep):
        err = urllib.error.HTTPError(url="", code=500, msg="x", hdrs=None, fp=None)
        mock_urlopen.side_effect = [
            err,
            err,
            _make_urlopen_response({"delivery_id": "abc"}),
        ]
        result = get_delivery("http://localhost:8000", "abc")
        assert result == {"delivery_id": "abc"}
        assert mock_urlopen.call_count == 3
        mock_sleep.assert_any_call(2)
        mock_sleep.assert_any_call(4)

    @patch("pipeline.converter.http.time.sleep")
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_all_attempts_exhausted_raises_unreachable(self, mock_urlopen, mock_sleep):
        err = urllib.error.HTTPError(url="", code=500, msg="x", hdrs=None, fp=None)
        mock_urlopen.side_effect = [err, err, err, err]
        with pytest.raises(RegistryUnreachableError):
            get_delivery("http://localhost:8000", "abc")
        assert mock_urlopen.call_count == 4

    @patch("pipeline.converter.http.time.sleep")
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_4xx_not_retried(self, mock_urlopen, mock_sleep):
        err = urllib.error.HTTPError(url="", code=422, msg="x", hdrs=None, fp=None)
        err.read = lambda: b'{"detail":"bad"}'
        mock_urlopen.side_effect = err
        with pytest.raises(RegistryClientError):
            patch_delivery("http://localhost:8000", "abc", {"k": "v"})
        assert mock_urlopen.call_count == 1
        mock_sleep.assert_not_called()

    @patch("pipeline.converter.http.time.sleep")
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_network_error_retried(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            urllib.error.URLError("connection refused"),
            _make_urlopen_response({"delivery_id": "abc"}),
        ]
        result = get_delivery("http://localhost:8000", "abc")
        assert result == {"delivery_id": "abc"}
