# pattern: test file

import json
import urllib.error
import urllib.request

import pytest

from pipeline.converter.http import (
    RegistryClientError,
    RegistryUnreachableError,
    emit_event,
    get_delivery,
    list_unconverted,
    patch_delivery,
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


class TestGetDelivery:
    def test_200_returns_body_as_dict(self):
        fake = FakeUrlopen([{"delivery_id": "abc"}])
        sleep = FakeSleep()
        result = get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)
        assert result == {"delivery_id": "abc"}

    def test_404_raises_registry_client_error(self):
        err = urllib.error.HTTPError(
            url="",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        err.read = lambda: b'{"detail":"delivery not found"}'
        fake = FakeUrlopen([err])
        sleep = FakeSleep()

        with pytest.raises(RegistryClientError) as exc_info:
            get_delivery("http://localhost:8000", "missing", urlopen=fake, sleep=sleep)
        assert exc_info.value.status_code == 404


class TestPatchDelivery:
    def test_sends_json_body_and_returns_updated_row(self):
        fake = FakeUrlopen([{"delivery_id": "abc", "output_path": "/p/x.parquet"}])
        sleep = FakeSleep()

        result = patch_delivery(
            "http://localhost:8000",
            "abc",
            {"output_path": "/p/x.parquet"},
            urlopen=fake,
            sleep=sleep,
        )
        assert result["output_path"] == "/p/x.parquet"

        request = fake.calls[0]
        assert request.method == "PATCH"
        assert request.get_full_url().endswith("/deliveries/abc")
        assert json.loads(request.data) == {"output_path": "/p/x.parquet"}


class TestListUnconverted:
    def test_returns_list_of_delivery_dicts(self):
        paginated = {
            "items": [{"delivery_id": "aaa"}, {"delivery_id": "bbb"}],
            "total": 2,
            "limit": 200,
            "offset": 0,
        }
        fake = FakeUrlopen([paginated])
        sleep = FakeSleep()
        result = list_unconverted(
            "http://localhost:8000",
            after="",
            limit=200,
            urlopen=fake,
            sleep=sleep,
        )
        assert result == [{"delivery_id": "aaa"}, {"delivery_id": "bbb"}]

    def test_empty_items_returns_empty_list(self):
        paginated = {"items": [], "total": 0, "limit": 200, "offset": 0}
        fake = FakeUrlopen([paginated])
        sleep = FakeSleep()
        result = list_unconverted(
            "http://localhost:8000",
            after="",
            limit=200,
            urlopen=fake,
            sleep=sleep,
        )
        assert result == []

    def test_builds_correct_query_string(self):
        paginated = {"items": [], "total": 0, "limit": 50, "offset": 0}
        fake = FakeUrlopen([paginated])
        sleep = FakeSleep()
        list_unconverted(
            "http://localhost:8000",
            after="cursor123",
            limit=50,
            urlopen=fake,
            sleep=sleep,
        )
        url = fake.calls[0].get_full_url()
        assert "converted=false" in url
        assert "after=cursor123" in url
        assert "limit=50" in url


class TestEmitEvent:
    def test_posts_correct_shape(self):
        fake = FakeUrlopen([{"seq": 5, "event_type": "conversion.completed", "delivery_id": "abc"}])
        sleep = FakeSleep()
        result = emit_event(
            "http://localhost:8000",
            "conversion.completed",
            "abc",
            {"row_count": 10},
            urlopen=fake,
            sleep=sleep,
        )
        assert result["seq"] == 5

        request = fake.calls[0]
        assert request.method == "POST"
        body = json.loads(request.data)
        assert body == {
            "event_type": "conversion.completed",
            "delivery_id": "abc",
            "payload": {"row_count": 10},
        }


class TestAuthentication:
    def test_token_sets_authorization_header(self):
        fake = FakeUrlopen([{"delivery_id": "abc"}])
        sleep = FakeSleep()
        get_delivery("http://localhost:8000", "abc", token="secret-token", urlopen=fake, sleep=sleep)
        request = fake.calls[0]
        assert request.get_header("Authorization") == "Bearer secret-token"

    def test_no_token_omits_authorization_header(self):
        fake = FakeUrlopen([{"delivery_id": "abc"}])
        sleep = FakeSleep()
        get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)
        request = fake.calls[0]
        assert request.get_header("Authorization") is None

    def test_patch_sends_token(self):
        fake = FakeUrlopen([{"delivery_id": "abc"}])
        sleep = FakeSleep()
        patch_delivery("http://localhost:8000", "abc", {"k": "v"}, token="tok", urlopen=fake, sleep=sleep)
        assert fake.calls[0].get_header("Authorization") == "Bearer tok"

    def test_emit_event_sends_token(self):
        fake = FakeUrlopen([{"seq": 1}])
        sleep = FakeSleep()
        emit_event("http://localhost:8000", "conversion.completed", "abc", {}, token="tok", urlopen=fake, sleep=sleep)
        assert fake.calls[0].get_header("Authorization") == "Bearer tok"


class TestRetryBehaviour:
    def test_5xx_retried_then_succeeds(self):
        err = urllib.error.HTTPError(url="", code=500, msg="x", hdrs=None, fp=None)
        fake = FakeUrlopen([err, err, {"delivery_id": "abc"}])
        sleep = FakeSleep()

        result = get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)

        assert result == {"delivery_id": "abc"}
        assert len(fake.calls) == 3
        assert 2 in sleep.calls
        assert 4 in sleep.calls

    def test_all_attempts_exhausted_raises_unreachable(self):
        err = urllib.error.HTTPError(url="", code=500, msg="x", hdrs=None, fp=None)
        fake = FakeUrlopen([err, err, err, err])
        sleep = FakeSleep()
        with pytest.raises(RegistryUnreachableError):
            get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)
        assert len(fake.calls) == 4

    def test_4xx_not_retried(self):
        err = urllib.error.HTTPError(url="", code=422, msg="x", hdrs=None, fp=None)
        err.read = lambda: b'{"detail":"bad"}'
        fake = FakeUrlopen([err])
        sleep = FakeSleep()
        with pytest.raises(RegistryClientError):
            patch_delivery(
                "http://localhost:8000",
                "abc",
                {"k": "v"},
                urlopen=fake,
                sleep=sleep,
            )
        assert len(fake.calls) == 1
        assert sleep.calls == []

    def test_network_error_retried(self):
        fake = FakeUrlopen(
            [
                urllib.error.URLError("connection refused"),
                {"delivery_id": "abc"},
            ]
        )
        sleep = FakeSleep()
        result = get_delivery("http://localhost:8000", "abc", urlopen=fake, sleep=sleep)
        assert result == {"delivery_id": "abc"}
