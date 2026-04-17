# SAS-to-Parquet Converter — Phase 4: Backfill CLI

**Goal:** A one-shot walker that pages through unconverted deliveries via `GET /deliveries?converted=false` and calls `engine.convert_one` on each until the backlog drains, then exits.

**Architecture:** One new file (`src/pipeline/converter/cli.py`) and one `pyproject.toml` entry-point registration. The CLI is the thinnest possible wrapper around Phase 3's engine plus a paging loop over Phase 1's paginated `GET /deliveries`. No per-CLI retry logic — if the registry is unreachable, urllib raises `RegistryUnreachableError` from the converter HTTP client and the CLI exits non-zero.

**Tech Stack:** stdlib argparse, stdlib urllib (via converter.http), logger.

**Scope:** Phase 4 of 6. Depends on Phase 3 (engine + http client) and Phase 1 (pagination).

**Codebase verified:** 2026-04-16.

---

## Acceptance Criteria Coverage

### sas-to-parquet-converter.AC8: Backfill CLI
- **sas-to-parquet-converter.AC8.1 Success:** `registry-convert` with empty backlog exits 0 immediately
- **sas-to-parquet-converter.AC8.2 Success:** `registry-convert` with N unconverted deliveries processes all N and exits
- **sas-to-parquet-converter.AC8.3 Success:** `--limit M` processes at most M deliveries and exits
- **sas-to-parquet-converter.AC8.4 Success:** `--shard I/N` only processes deliveries whose `delivery_id` falls into shard `I` of `N`
- **sas-to-parquet-converter.AC8.5 Success:** `--include-failed` re-attempts deliveries with `conversion_error` set (clears it on success)
- **sas-to-parquet-converter.AC8.6 Failure:** Registry unreachable results in non-zero exit code and no partial work

---

## Engineer Briefing

**Shard semantics:** `--shard I/N` means "process delivery_ids where `int(delivery_id[:8], 16) % N == I`." `delivery_id` is a 64-char hex SHA-256, so using the first 8 hex chars (32 bits) gives plenty of distribution for typical N up to a few hundred. The modulo approach lets multiple CLI instances divide work without coordination.

**Include-failed semantics:** With `--include-failed`, the CLI first clears `metadata.conversion_error` on each matching delivery by PATCHing `{"metadata": {"conversion_error": null}}` (Phase 1 AC7.3), then lets the engine process it. If conversion succeeds, the cleared field persists. If it fails again, the engine writes a fresh `conversion_error`. Without `--include-failed`, the engine's skip-guard (AC5.3) treats any non-null `conversion_error` as "skip."

**Why the clear has to happen in the CLI and not the engine:** The engine is status-blind and does not mutate `conversion_error` except to set it on failure. "Re-attempt a failed delivery" is an operator-initiated action, not an engine behaviour. The CLI handles it as an explicit pre-pass.

**Paging contract (Phase 1 provided):**
- `GET /deliveries?converted=false&after={id}&limit={N}` returns up to N rows with `delivery_id > id`, ordered by `delivery_id` ascending.
- Empty response list means "no more rows past this cursor."
- Use `converter_cli_batch_size` from config as the default page size; `--limit` caps total deliveries, not page size.

**Signal handling (basic):** Catch `KeyboardInterrupt` in the main loop — finish the current delivery (engine already handles Ctrl+C mid-delivery by re-raising), then exit 130 (standard SIGINT exit code). No `--daemonize` in this phase; the daemon is Phase 5.

**Exit codes:**
- 0 — backlog drained (or `--limit` reached) cleanly.
- 1 — registry unreachable, or unexpected unhandled exception.
- 130 — SIGINT (Ctrl+C).

**Testing:** Follow the crawler CLI test pattern (see `tests/crawler/test_main.py`). Stub both `http_module` and `convert_fn` passed through the engine call. Test argument parsing independently with `argparse` parser introspection.

---

<!-- START_SUBCOMPONENT_A (tasks 1-3) -->

<!-- START_TASK_1 -->
### Task 1: CLI argument parsing and shard filter helper (pure)

**Verifies:** Prerequisite for AC8.3, AC8.4.

**Files:**
- Create: `src/pipeline/converter/cli.py` (argparse and `_in_shard` helper)
- Create: `tests/converter/test_cli.py`

**Implementation:**

Start `src/pipeline/converter/cli.py`:

```python
# pattern: Imperative Shell

import argparse
import sys

from pipeline.converter import http as converter_http
from pipeline.converter.engine import convert_one


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="registry-convert",
        description="Drain unconverted deliveries from the registry to Parquet.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most this many deliveries total. Default: no limit.",
    )
    parser.add_argument(
        "--shard", type=str, default=None, metavar="I/N",
        help="Only process deliveries in shard I of N (0-indexed). "
             "Example: --shard 0/4 picks up ~1/4 of the backlog.",
    )
    parser.add_argument(
        "--include-failed", action="store_true",
        help="Also re-attempt deliveries with conversion_error set "
             "(clears the error first).",
    )
    return parser


def _parse_shard(shard_arg: str | None) -> tuple[int, int] | None:
    """
    Parse '--shard I/N' into (I, N). Returns None if argument is None.

    Raises ValueError for malformed input, negative I, N <= 0, or I >= N.
    """
    if shard_arg is None:
        return None
    parts = shard_arg.split("/")
    if len(parts) != 2:
        raise ValueError(f"--shard must be formatted as I/N, got: {shard_arg}")
    i = int(parts[0])
    n = int(parts[1])
    if n <= 0:
        raise ValueError(f"--shard N must be > 0, got: {n}")
    if i < 0 or i >= n:
        raise ValueError(f"--shard I must satisfy 0 <= I < N, got I={i}, N={n}")
    return i, n


def _in_shard(delivery_id: str, shard: tuple[int, int] | None) -> bool:
    """
    Test whether a delivery_id falls into the given shard.

    Uses the first 8 hex chars of the SHA-256 delivery_id as a 32-bit int
    and takes modulo N. Returns True when shard is None (no filter).
    """
    if shard is None:
        return True
    i, n = shard
    bucket = int(delivery_id[:8], 16) % n
    return bucket == i
```

**Testing in `tests/converter/test_cli.py`:**

```python
# pattern: test file

import pytest

from pipeline.converter.cli import _build_parser, _parse_shard, _in_shard


class TestParseShard:
    def test_none_returns_none(self):
        assert _parse_shard(None) is None

    def test_valid_zero_of_one(self):
        assert _parse_shard("0/1") == (0, 1)

    def test_valid_three_of_four(self):
        assert _parse_shard("3/4") == (3, 4)

    @pytest.mark.parametrize("bad", ["", "/", "0", "1/2/3", "a/b", "-1/4", "4/4", "5/4", "0/0", "0/-1"])
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
        import hashlib
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
```

**Verification:**

Run: `uv run pytest tests/converter/test_cli.py -v`
Expected: All tests pass.

**Commit:** `feat(converter): add CLI argument parsing and shard helper`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: List-unconverted paging generator + main loop

**Verifies:** sas-to-parquet-converter.AC8.1, AC8.2, AC8.3, AC8.4, AC8.6

**Files:**
- Modify: `src/pipeline/converter/cli.py` (add paging helper + main() function)
- Modify: `src/pipeline/converter/http.py` (add `list_unconverted` function)
- Modify: `tests/converter/test_http.py` (cover new HTTP function)
- Modify: `tests/converter/test_cli.py` (cover main loop)

**Implementation:**

Step 1 — Add to `converter/http.py`:

```python
def list_unconverted(
    api_url: str,
    after: str = "",
    limit: int = 200,
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
    return _request_with_retry(request)
```

Note: the registry's `after: str | None = None` Pydantic default means an empty string gets passed as-is. Confirmed by Phase 1 Task 4 — empty string works as a "start from the beginning" sentinel because every hex delivery_id is strictly greater than `""` lexically.

**Update test_http.py** with a `TestListUnconverted` class:

```python
class TestListUnconverted:
    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_returns_list_of_delivery_dicts(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_response([
            {"delivery_id": "aaa"}, {"delivery_id": "bbb"}
        ])
        result = list_unconverted("http://localhost:8000", after="", limit=200)
        assert result == [{"delivery_id": "aaa"}, {"delivery_id": "bbb"}]

    @patch("pipeline.converter.http.urllib.request.urlopen")
    def test_builds_correct_query_string(self, mock_urlopen):
        mock_urlopen.return_value = _make_urlopen_response([])
        list_unconverted("http://localhost:8000", after="cursor123", limit=50)
        request = mock_urlopen.call_args[0][0]
        url = request.get_full_url()
        assert "converted=false" in url
        assert "after=cursor123" in url
        assert "limit=50" in url
```

Add the import to the top of test_http.py: `from pipeline.converter.http import list_unconverted`.

Step 2 — Add paging + main to `cli.py`:

```python
from pipeline.config import settings
from pipeline.json_logging import get_logger


def _iter_unconverted(
    api_url: str,
    page_size: int,
    http_module=converter_http,
):
    """
    Generator yielding delivery dicts one at a time, paging under the covers.

    Stops when a page returns empty. Does not retry — the underlying
    http_module handles transient failures; exhaustion raises RegistryUnreachableError
    and propagates to main().
    """
    cursor = ""
    while True:
        page = http_module.list_unconverted(api_url, after=cursor, limit=page_size)
        if not page:
            return
        for delivery in page:
            yield delivery
        cursor = page[-1]["delivery_id"]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        shard = _parse_shard(args.shard)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return _run(args, shard, http_module=converter_http, convert_one_fn=convert_one)


def _run(
    args,
    shard: tuple[int, int] | None,
    *,
    http_module,
    convert_one_fn,
) -> int:
    """
    Orchestrate the paged walk + per-delivery engine call. Pure shell.

    Tests can inject http_module and convert_one_fn to avoid touching HTTP
    or running the real converter.
    """
    logger = get_logger("converter-cli", log_dir=settings.log_dir)

    api_url = settings.registry_api_url
    processed = 0

    try:
        for delivery in _iter_unconverted(
            api_url, settings.converter_cli_batch_size, http_module=http_module
        ):
            delivery_id = delivery["delivery_id"]

            if not _in_shard(delivery_id, shard):
                continue

            if args.include_failed:
                metadata = delivery.get("metadata") or {}
                if metadata.get("conversion_error"):
                    http_module.patch_delivery(
                        api_url, delivery_id,
                        {"metadata": {"conversion_error": None}},
                    )

            convert_one_fn(
                delivery_id,
                api_url,
                converter_version=settings.converter_version,
                chunk_size=settings.converter_chunk_size,
                compression=settings.converter_compression,
                log_dir=settings.log_dir,
            )

            processed += 1
            if args.limit is not None and processed >= args.limit:
                break

    except converter_http.RegistryUnreachableError as exc:
        logger.error(
            "registry unreachable, exiting",
            extra={"error_message": str(exc)},
        )
        return 1
    except KeyboardInterrupt:
        logger.warning("interrupted by user", extra={"processed": processed})
        return 130

    logger.info("backfill complete", extra={"processed": processed})
    return 0
```

**Step 3 — Register the entry point in `pyproject.toml`:**

```toml
[project.scripts]
registry-api = "pipeline.registry_api.main:run"
registry-convert = "pipeline.converter.cli:main"
```

Reinstall so the console script picks up: `uv pip install -e ".[registry,dev]"` (on the target machine; the worktree will already have it after `pip install -e .`).

**Testing in test_cli.py:**

```python
import argparse
from pipeline.converter.cli import _iter_unconverted, _run


class _StubCliHttp:
    """Stub for the CLI's http_module — list_unconverted + patch_delivery only."""

    def __init__(self, pages: list[list[dict]]):
        # pages is a list of pages; each page is a list of delivery dicts.
        # Last element should be [] to terminate pagination.
        self.pages = pages
        self.patches: list[tuple[str, dict]] = []
        self.call_count = 0
        self.RegistryUnreachableError = RuntimeError  # sentinel; overridden per test

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
        http = _StubCliHttp(pages=[
            [{"delivery_id": "a" * 64}, {"delivery_id": "b" * 64}],
            [],
        ])
        result = list(_iter_unconverted("http://x", page_size=2, http_module=http))
        assert [d["delivery_id"] for d in result] == ["a" * 64, "b" * 64]
        assert http.call_count == 2

    def test_pages_multiple_times(self):
        http = _StubCliHttp(pages=[
            [{"delivery_id": "a" * 64}, {"delivery_id": "b" * 64}],
            [{"delivery_id": "c" * 64}],
            [],
        ])
        result = list(_iter_unconverted("http://x", page_size=2, http_module=http))
        assert len(result) == 3
        assert http.call_count == 3


class TestRunMainLoop:
    def test_empty_backlog_exits_zero(self):
        # AC8.1
        http = _StubCliHttp(pages=[[]])
        calls = []
        def convert_one_fn(*args, **kwargs):
            calls.append((args, kwargs))

        rc = _run(_fake_args(), shard=None, http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        assert calls == []

    def test_processes_all_deliveries(self):
        # AC8.2
        http = _StubCliHttp(pages=[
            [{"delivery_id": "a" * 64, "metadata": {}},
             {"delivery_id": "b" * 64, "metadata": {}}],
            [],
        ])
        calls = []
        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)

        rc = _run(_fake_args(), shard=None, http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        assert calls == ["a" * 64, "b" * 64]

    def test_limit_caps_processing(self):
        # AC8.3
        http = _StubCliHttp(pages=[
            [{"delivery_id": f"{i:064x}", "metadata": {}} for i in range(5)],
            [],
        ])
        calls = []
        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)

        rc = _run(_fake_args(limit=3), shard=None, http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        assert len(calls) == 3

    def test_shard_filter_skips_out_of_shard(self):
        # AC8.4
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

        rc = _run(_fake_args(shard=None), shard=(0, 2), http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        # Exact expected shard-0 processing.
        assert calls == [shard_0_id, shard_0_id_b]

    def test_include_failed_clears_conversion_error_first(self):
        # AC8.5
        errored = {
            "delivery_id": "a" * 64,
            "metadata": {"conversion_error": {"class": "parse_error"}},
        }
        http = _StubCliHttp(pages=[[errored], []])
        calls = []
        def convert_one_fn(delivery_id, api_url, **kwargs):
            calls.append(delivery_id)

        rc = _run(_fake_args(include_failed=True), shard=None,
                  http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        # PATCH must have been issued to clear the error before the engine call.
        assert http.patches == [("a" * 64, {"metadata": {"conversion_error": None}})]
        assert calls == ["a" * 64]

    def test_without_include_failed_skips_errored(self):
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

        rc = _run(_fake_args(include_failed=False), shard=None,
                  http_module=http, convert_one_fn=convert_one_fn)
        assert rc == 0
        assert http.patches == []  # no clearing PATCH


class TestRegistryUnreachable:
    def test_exits_nonzero_on_unreachable(self):
        # AC8.6
        from pipeline.converter.http import RegistryUnreachableError

        class _FailingHttp:
            def list_unconverted(self, *args, **kwargs):
                raise RegistryUnreachableError("cannot connect")
            def patch_delivery(self, *args, **kwargs):
                raise AssertionError("should not be called")

        def convert_one_fn(*args, **kwargs):
            raise AssertionError("should not be called")

        rc = _run(_fake_args(), shard=None, http_module=_FailingHttp(),
                  convert_one_fn=convert_one_fn)
        assert rc == 1
```

**Note on the `_FailingHttp.RegistryUnreachableError` hack:** `_run` imports `converter_http` at module level and catches `converter_http.RegistryUnreachableError`. The test's `_FailingHttp` raises the real `RegistryUnreachableError` from `pipeline.converter.http` — that matches the `except` clause. No need to monkeypatch the except-class attribute.

**Verification:**

Run: `uv run pytest tests/converter/test_cli.py -v`
Expected: All CLI tests pass.

Run: `uv run pytest tests/converter/test_http.py::TestListUnconverted -v`
Expected: HTTP paging test passes.

Run: `uv run pytest`
Expected: Full suite green.

**Commit:** `feat(converter): backfill CLI (registry-convert) with pagination and sharding`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Entry-point registration and end-to-end CLI smoke test

**Verifies:** AC8.2 (integration).

**Files:**
- Confirm `pyproject.toml:29-31` has the new entry point.
- Modify: `tests/converter/test_cli.py` (add a smoke test that runs `main()` with real argparse against a stubbed http).

**Implementation:**

Verify entry point registration took effect:

```bash
uv pip install -e ".[registry,dev]"
which registry-convert  # should resolve to the venv bin
registry-convert --help  # should print help text
```

Add a smoke test that exercises `main()`'s argparse path:

```python
from unittest.mock import patch


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
```

**Verification:**

Run: `uv run pytest tests/converter/test_cli.py::TestMainEntryPoint -v`
Expected: Both tests pass.

Run: `which registry-convert && registry-convert --help`
Expected: Entry point resolves; help text printed.

**Commit:** `feat(converter): register registry-convert entry point in pyproject.toml`
<!-- END_TASK_3 -->

<!-- END_SUBCOMPONENT_A -->

---

## Phase completion checklist

- [ ] Three tasks committed separately.
- [ ] `uv run pytest` full suite green.
- [ ] `registry-convert --help` prints usage.
- [ ] `src/pipeline/converter/cli.py` starts with `# pattern: Imperative Shell` on line 1.
- [ ] Manual smoke test against a real running registry: start `uv run registry-api`, POST one or more deliveries pointing at real SAS fixtures, run `registry-convert`, verify rows are PATCHed with `parquet_converted_at` and Parquet files exist on disk.
- [ ] `registry-convert --limit 0` behaviour: documented in argparse help; processes zero and exits 0. (Not a required AC but common-sense sanity.)
- [ ] Phase 5 (daemon) can import `convert_one`, `list_unconverted`, and `_in_shard` without circular dependencies (it won't re-use `_in_shard` — the daemon filters based on event stream, not hex modulo).
