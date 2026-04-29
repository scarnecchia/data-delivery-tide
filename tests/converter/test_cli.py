# pattern: test file

import argparse
import hashlib

import pytest

from pipeline.converter.cli import _build_parser, _in_shard, _iter_unconverted, _parse_shard, _run
from pipeline.converter.http import RegistryUnreachableError


class TestParseShard:
    def test_none_returns_none(self):
        assert _parse_shard(None) is None

    def test_valid_zero_of_one(self):
        assert _parse_shard("0/1") == (0, 1)

    def test_valid_three_of_four(self):
        assert _parse_shard("3/4") == (3, 4)

    @pytest.mark.parametrize(
        "bad", ["", "/", "0", "1/2/3", "a/b", "-1/4", "4/4", "5/4", "0/0", "0/-1"]
    )
    def test_malformed_raises(self, bad):
        with pytest.raises(ValueError):
            _parse_shard(bad)


class TestInShard:
    def test_no_shard_always_true(self):
        assert _in_shard("abc123" + "0" * 58, None) is True

    def test_deterministic_bucket_assignment(self):
        # Two different delivery_ids; each goes to one and only one shard out of N.
        d1 = "00000000" + "0" * 56  # bucket 0 mod any N
        d2 = "ffffffff" + "0" * 56  # bucket (2**32 - 1) mod N

        n = 4
        shards_hit_d1 = [i for i in range(n) if _in_shard(d1, (i, n))]
        shards_hit_d2 = [i for i in range(n) if _in_shard(d2, (i, n))]

        assert len(shards_hit_d1) == 1
        assert len(shards_hit_d2) == 1

    def test_distribution_across_shards(self):
        # 100 random-ish delivery_ids distributed across 4 shards -> each shard sees some.
        ids = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(100)]
        counts = [sum(1 for d in ids if _in_shard(d, (i, 4))) for i in range(4)]
        # Each of the 4 shards gets at least one id; total = 100.
        assert sum(counts) == 100
        assert all(c > 0 for c in counts)


class TestBuildParser:
    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.limit is None
        assert args.shard is None
        assert args.include_failed is False

    def test_all_flags(self):
        parser = _build_parser()
        args = parser.parse_args(["--limit", "10", "--shard", "1/2", "--include-failed"])
        assert args.limit == 10
        assert args.shard == "1/2"
        assert args.include_failed is True


class _StubCliHttp:
    """Stub for the CLI's http_module — list_unconverted + patch_delivery only."""

    def __init__(self, pages: list[list[dict]]):
        # pages is a list of pages; each page is a list of delivery dicts.
        # Last element should be [] to terminate pagination.
        self.pages = list(pages)  # Make a copy since we'll pop
        self.patches: list[tuple[str, dict]] = []
        self.call_count = 0
        self.RegistryUnreachableError = RegistryUnreachableError

    def list_unconverted(self, api_url, after, limit):
        self.call_count += 1
        if not self.pages:
            return []
        return self.pages.pop(0)

    def patch_delivery(self, api_url, delivery_id, updates):
        self.patches.append((delivery_id, updates))
        return {}


def _fake_args(*, limit=None, shard=None, include_failed=False):
    return argparse.Namespace(limit=limit, shard=shard, include_failed=include_failed)


class TestIterUnconverted:
    def test_stops_on_empty_page(self):
        http = _StubCliHttp(
            pages=[
                [{"delivery_id": "a" * 64}, {"delivery_id": "b" * 64}],
                [],
            ]
        )
        result = list(_iter_unconverted("http://x", page_size=2, http_module=http))
        assert [d["delivery_id"] for d in result] == ["a" * 64, "b" * 64]
        assert http.call_count == 2

    def test_pages_multiple_times(self):
        http = _StubCliHttp(
            pages=[
                [{"delivery_id": "a" * 64}, {"delivery_id": "b" * 64}],
                [{"delivery_id": "c" * 64}],
                [],
            ]
        )
        result = list(_iter_unconverted("http://x", page_size=2, http_module=http))
        assert len(result) == 3
        assert http.call_count == 3


class TestRunMainLoop:
    def test_empty_backlog_exits_zero(self, monkeypatch):
        # AC8.1
        monkeypatch.setattr("pipeline.converter.cli.settings.log_dir", None)
        monkeypatch.setattr(
            "pipeline.converter.cli.settings.registry_api_url", "http://localhost:8000"
        )
        monkeypatch.setattr("pipeline.converter.cli.settings.converter_cli_batch_size", 200)
        http = _StubCliHttp(pages=[[]])
        calls = []

        def convert_one_fn(*args, **kwargs):
            calls.append((args, kwargs))

        rc = _run(_fake_args(), shard=None, http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        assert calls == []

    def test_processes_all_deliveries(self, monkeypatch):
        # AC8.2
        monkeypatch.setattr("pipeline.converter.cli.settings.log_dir", None)
        monkeypatch.setattr(
            "pipeline.converter.cli.settings.registry_api_url", "http://localhost:8000"
        )
        monkeypatch.setattr("pipeline.converter.cli.settings.converter_cli_batch_size", 200)
        http = _StubCliHttp(
            pages=[
                [
                    {"delivery_id": "a" * 64, "metadata": {}},
                    {"delivery_id": "b" * 64, "metadata": {}},
                ],
                [],
            ]
        )
        calls = []

        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)

        rc = _run(_fake_args(), shard=None, http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        assert calls == ["a" * 64, "b" * 64]

    def test_limit_caps_processing(self, monkeypatch):
        # AC8.3
        monkeypatch.setattr("pipeline.converter.cli.settings.log_dir", None)
        monkeypatch.setattr(
            "pipeline.converter.cli.settings.registry_api_url", "http://localhost:8000"
        )
        monkeypatch.setattr("pipeline.converter.cli.settings.converter_cli_batch_size", 200)
        http = _StubCliHttp(
            pages=[
                [{"delivery_id": f"{i:064x}", "metadata": {}} for i in range(5)],
                [],
            ]
        )
        calls = []

        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)

        rc = _run(_fake_args(limit=3), shard=None, http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        assert len(calls) == 3

    def test_shard_filter_skips_out_of_shard(self, monkeypatch):
        # AC8.4
        monkeypatch.setattr("pipeline.converter.cli.settings.log_dir", None)
        monkeypatch.setattr(
            "pipeline.converter.cli.settings.registry_api_url", "http://localhost:8000"
        )
        monkeypatch.setattr("pipeline.converter.cli.settings.converter_cli_batch_size", 200)
        # Hand-picked hex prefixes that deterministically land in shard 0 and 1 of 2:
        # int("00000000", 16) % 2 == 0  (shard 0)
        # int("00000001", 16) % 2 == 1  (shard 1)
        # int("00000002", 16) % 2 == 0  (shard 0)
        # int("00000003", 16) % 2 == 1  (shard 1)
        shard_0_id = "00000000" + "0" * 56
        shard_1_id = "00000001" + "0" * 56
        shard_0_id_b = "00000002" + "0" * 56
        shard_1_id_b = "00000003" + "0" * 56

        ids_in_order = [shard_0_id, shard_1_id, shard_0_id_b, shard_1_id_b]
        http = _StubCliHttp(pages=[[{"delivery_id": d, "metadata": {}} for d in ids_in_order], []])
        calls = []

        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)

        rc = _run(
            _fake_args(shard=None), shard=(0, 2), http_module=http, convert_one_fn=convert_one_fn
        )
        assert rc == 0
        # Exact expected shard-0 processing.
        assert calls == [shard_0_id, shard_0_id_b]

    def test_include_failed_clears_conversion_error_first(self, monkeypatch):
        # AC8.5
        monkeypatch.setattr("pipeline.converter.cli.settings.log_dir", None)
        monkeypatch.setattr(
            "pipeline.converter.cli.settings.registry_api_url", "http://localhost:8000"
        )
        monkeypatch.setattr("pipeline.converter.cli.settings.converter_cli_batch_size", 200)
        errored = {
            "delivery_id": "a" * 64,
            "metadata": {"conversion_error": {"class": "parse_error"}},
        }
        http = _StubCliHttp(pages=[[errored], []])
        calls = []

        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)

        rc = _run(
            _fake_args(include_failed=True),
            shard=None,
            http_module=http,
            convert_one_fn=convert_one_fn,
        )
        assert rc == 0
        # PATCH must have been issued to clear the error before the engine call.
        assert http.patches == [("a" * 64, {"metadata": {"conversion_error": None}})]
        assert calls == ["a" * 64]

    def test_without_include_failed_skips_errored(self, monkeypatch):
        # AC8.5 (negative case)
        monkeypatch.setattr("pipeline.converter.cli.settings.log_dir", None)
        monkeypatch.setattr(
            "pipeline.converter.cli.settings.registry_api_url", "http://localhost:8000"
        )
        monkeypatch.setattr("pipeline.converter.cli.settings.converter_cli_batch_size", 200)
        # Without --include-failed, errored deliveries are returned by the
        # registry (they ARE unconverted) — but we rely on the engine's skip
        # guard (Phase 3 AC5.3) to filter them. The CLI just doesn't pre-clear.
        # Verify: no clearing PATCH is issued.
        errored = {
            "delivery_id": "a" * 64,
            "metadata": {"conversion_error": {"class": "parse_error"}},
        }
        http = _StubCliHttp(pages=[[errored], []])
        calls = []

        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)  # engine would skip, but we still stub it

        rc = _run(
            _fake_args(include_failed=False),
            shard=None,
            http_module=http,
            convert_one_fn=convert_one_fn,
        )
        assert rc == 0
        assert http.patches == []  # no clearing PATCH


class TestMainEntryPoint:
    def test_help_exits_cleanly(self, capsys):
        from pipeline.converter.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "registry-convert" in out
        assert "--shard" in out
        assert "--include-failed" in out

    def test_invalid_shard_returns_two(self, capsys):
        from pipeline.converter.cli import main

        rc = main(["--shard", "notvalid"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "error" in err.lower()


class TestRegistryUnreachable:
    def test_exits_nonzero_on_unreachable(self, monkeypatch):
        # AC8.6
        monkeypatch.setattr("pipeline.converter.cli.settings.log_dir", None)
        monkeypatch.setattr(
            "pipeline.converter.cli.settings.registry_api_url", "http://localhost:8000"
        )
        monkeypatch.setattr("pipeline.converter.cli.settings.converter_cli_batch_size", 200)

        class _FailingHttp:
            RegistryUnreachableError = RegistryUnreachableError

            def list_unconverted(self, *args, **kwargs):
                raise RegistryUnreachableError("cannot connect")

            def patch_delivery(self, *args, **kwargs):
                raise AssertionError("should not be called")

        def convert_one_fn(*args, **kwargs):
            raise AssertionError("should not be called")

        rc = _run(
            _fake_args(), shard=None, http_module=_FailingHttp(), convert_one_fn=convert_one_fn
        )
        assert rc == 1
