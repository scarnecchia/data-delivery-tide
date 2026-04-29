# SAS-to-Parquet Converter — Phase 3: Engine + registry client

**Goal:** Imperative-shell orchestration: fetch a delivery from the registry, check skip guards, call the Phase 2 conversion core, PATCH the registry row with results (success or failure), and emit a lifecycle event via the Phase 1 `POST /events` endpoint.

**Architecture:** Three new files in `src/pipeline/converter/`:
- `http.py` — stdlib urllib client mirroring `crawler/http.py` shape (GET delivery, PATCH delivery, POST event). Exponential backoff on 5xx; immediate raise on 4xx.
- `engine.py` — `convert_one(delivery_id, http_client) -> ConversionResult` orchestration with structured logging.
- Plus extended `pipeline.config.PipelineConfig` for new `converter_*` fields.

**Tech Stack:** stdlib urllib, pytest + unittest.mock (matching crawler test pattern), JsonFormatter for structured logging.

**Scope:** Phase 3 of 6 from design plan `docs/design-plans/2026-04-16-sas-to-parquet-converter.md`.

**Codebase verified:** 2026-04-16.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### sas-to-parquet-converter.AC5: Engine orchestration and skip guards
- **sas-to-parquet-converter.AC5.1 Success:** Given a delivery with null `parquet_converted_at` and no `conversion_error`, engine converts and PATCHes `output_path` + `parquet_converted_at`, emits `conversion.completed`
- **sas-to-parquet-converter.AC5.2 Success:** Delivery with non-null `parquet_converted_at` and existing file is skipped (no work, no events)
- **sas-to-parquet-converter.AC5.3 Success:** Delivery with `metadata.conversion_error` set is skipped (no work, no events)
- **sas-to-parquet-converter.AC5.4 Failure:** Classified exception from core results in a PATCH writing `metadata.conversion_error = {class, message, at, converter_version}` and emitting `conversion.failed`
- **sas-to-parquet-converter.AC5.5 Failure:** No automatic retry occurs after a classified exception
- **sas-to-parquet-converter.AC5.6 Success:** Structured log line emitted per conversion attempt (success or failure) via `JsonFormatter`

### sas-to-parquet-converter.AC6: Event payload shapes (engine-produced)
- **sas-to-parquet-converter.AC6.2 Success:** `conversion.completed` payload contains `delivery_id`, `output_path`, `row_count`, `bytes_written`, `wrote_at`
- **sas-to-parquet-converter.AC6.3 Success:** `conversion.failed` payload contains `delivery_id`, `error_class`, `error_message`, `at`

---

## Engineer Briefing

**Prerequisites completed:**
- Phase 1 landed: `POST /events` endpoint accepts `conversion.completed` and `conversion.failed` with arbitrary payload dicts. Deep-merge PATCH of `metadata` is in place. Pagination is supported on `GET /deliveries`.
- Phase 2 landed: `convert_sas_to_parquet`, `ConversionMetadata`, `SchemaDriftError`, `classify_exception`, `ErrorClass` are all importable from `pipeline.converter.convert` and `pipeline.converter.classify`.

**Library facts (confirmed):**

- Crawler `http.py` at `src/pipeline/crawler/http.py:1-69` is the template. Copy its shape verbatim:
  - Module-level `_BACKOFF_SECONDS = (2, 4, 8)` (4 total attempts).
  - Free functions, not a class.
  - `RegistryUnreachableError` raised after retries exhausted.
  - `RegistryClientError(status_code, body)` raised immediately on 4xx.
  - 5xx and `(urllib.error.URLError, OSError)` → retry with `time.sleep(_BACKOFF_SECONDS[attempt])`.
  - JSON via stdlib `json`.
- Crawler test pattern at `tests/crawler/test_http.py` mocks `urllib.request.urlopen` (NOT a real HTTP server). Retry tests patch `time.sleep` to avoid wall-clock waits. Use the same pattern here.

**Configuration facts:**

- `PipelineConfig` is a `@dataclass` at `src/pipeline/config.py:18-30`. New fields added to the dataclass AND to the return statement in `load_config` (lines 72-84).
- `pipeline/config.json` holds defaults; the `load_config` helper uses `.get(field, default)` so config.json need not include every new field — but for documentation and production predictability, this phase adds all six converter fields to config.json.

**Design invariants to preserve:**

- `src/pipeline/registry_api/CLAUDE.md` says the converter must not import from `registry_api`. That's correct for shared Python imports. BUT the converter SHOULD import `DeliveryResponse` / `EventCreate` / `EventRecord` from `pipeline.registry_api.models` — models are the wire contract and sharing them is how we keep the shapes aligned. This is common Python; the CLAUDE.md "boundary" means no imports from `db.py`, `routes.py`, or internal state. Confirm with the registry_api CLAUDE.md "no imports from crawler, converter, or events consumer" — it goes one way: registry doesn't import from the converter. Converter importing the models package (pure Pydantic) is fine.
- FCIS pattern: `http.py` and `engine.py` both get `# pattern: Imperative Shell` on line 1.

**Skip-guard semantics:**

- `metadata.conversion_error` being a dict (any content) counts as "errored, skip." A `None` or missing key means "no error, process." This is the contract — the operator PATCHes `{"metadata": {"conversion_error": null}}` to clear via the Phase 1 deep-merge semantic and the next engine call processes the delivery.
- "File exists" check for AC5.2: the engine inspects `output_path` from the delivery row; if `parquet_converted_at` is not null AND the file at `output_path` exists on disk, skip. If `parquet_converted_at` is non-null but the file has been deleted, DO re-convert (treat the file on disk as authoritative). This is the documented semantic per design's "skip if `parquet_converted_at` is set and file exists."

**Logging contract:**

- One log line per conversion attempt, emitted via `get_logger("converter", log_dir=...)`.
- Extra fields on every log line: `delivery_id`, `source_path`, `outcome` ("success"|"failure"|"skipped"), and on failure: `error_class`, `error_message`.
- Do NOT log the full Pydantic delivery dict — that bloats log files.

**Test fixture reuse:**

- Use the `sas_fixture_factory` from `tests/converter/conftest.py` (created in Phase 2) for any test that needs a real SAS file.
- For engine-level tests that don't need real bytes, pass a stub `http_client` with configurable return values — the engine is dependency-injected via function parameters.

**Run tests:** `uv run pytest`. Phase 3 adds `tests/converter/test_http.py` and `tests/converter/test_engine.py`.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Add `converter_*` config fields to `PipelineConfig` and `config.json`

**Verifies:** Infrastructure precondition for AC5.

**Files:**
- Modify: `src/pipeline/config.py:18-30` (add six fields to the `PipelineConfig` dataclass)
- Modify: `src/pipeline/config.py:72-84` (load the fields with defaults in `load_config`)
- Modify: `pipeline/config.json` (add the six fields with production defaults)
- Modify: `tests/test_config.py` (add assertions for new fields)

**Implementation:**

Step 1 — Extend `PipelineConfig`:

```python
@dataclass
class PipelineConfig:
    scan_roots: list[ScanRoot]
    registry_api_url: str
    output_root: str
    schema_path: str
    overrides_path: str
    log_dir: str
    db_path: str
    dp_id_exclusions: list[str]
    crawl_manifest_dir: str
    crawler_version: str
    lexicons_dir: str
    converter_version: str
    converter_chunk_size: int
    converter_compression: str
    converter_state_path: str
    converter_cli_batch_size: int
    converter_cli_sleep_empty_secs: int
```

Step 2 — Extend the `load_config` return with defaults:

```python
return PipelineConfig(
    # ... existing fields ...
    lexicons_dir=lexicons_dir,
    converter_version=data.get("converter_version", "0.1.0"),
    converter_chunk_size=data.get("converter_chunk_size", 100_000),
    converter_compression=data.get("converter_compression", "zstd"),
    converter_state_path=data.get("converter_state_path", "pipeline/.converter_state.json"),
    converter_cli_batch_size=data.get("converter_cli_batch_size", 200),
    converter_cli_sleep_empty_secs=data.get("converter_cli_sleep_empty_secs", 0),
)
```

Step 3 — Extend `pipeline/config.json` (leave existing keys intact):

```json
{
  "lexicons_dir": "lexicons",
  "scan_roots": [ ... unchanged ... ],
  "registry_api_url": "http://localhost:8000",
  "output_root": "/output",
  "schema_path": "/pipeline/schema.json",
  "overrides_path": "/pipeline/overrides.json",
  "log_dir": "/pipeline/logs",
  "db_path": "pipeline/registry.db",
  "dp_id_exclusions": ["nsdp"],
  "crawl_manifest_dir": "pipeline/crawl_manifests",
  "crawler_version": "1.0.0",
  "converter_version": "0.1.0",
  "converter_chunk_size": 100000,
  "converter_compression": "zstd",
  "converter_state_path": "pipeline/.converter_state.json",
  "converter_cli_batch_size": 200,
  "converter_cli_sleep_empty_secs": 0
}
```

**Testing:**

In `tests/test_config.py`, extend the existing tests that build a `PipelineConfig` dict to include the new keys, and add:

- `test_loads_converter_version_with_default` — config file missing the key uses `"0.1.0"`.
- `test_loads_converter_chunk_size_with_default` — missing key → `100_000`.
- `test_loads_converter_compression_with_default` — missing key → `"zstd"`.
- `test_loads_converter_state_path_with_default` — missing key → `"pipeline/.converter_state.json"`.
- `test_loads_converter_cli_batch_size_with_default` — missing key → `200`.
- `test_loads_converter_cli_sleep_empty_secs_with_default` — missing key → `0`.
- `test_explicit_converter_version_overrides_default` — config with `"converter_version": "1.2.3"` loads that value.

**Verification:**

Run: `uv run pytest tests/test_config.py -v`
Expected: New tests pass; existing tests still pass (none required construction from all-keys-present config).

Run: `uv run pytest`
Expected: Full suite green. Registry API still starts with `uv run registry-api`.

**Commit:** `feat(config): add converter_* configuration fields`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Converter HTTP client (`src/pipeline/converter/http.py`)

**Verifies:** Infrastructure precondition for AC5.

**Files:**
- Create: `src/pipeline/converter/http.py`
- Create: `tests/converter/test_http.py`

**Implementation:**

Mirror `src/pipeline/crawler/http.py` exactly in shape. Three free functions for the three HTTP operations the engine needs.

Contents of `src/pipeline/converter/http.py`:

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


def _request_with_retry(request: urllib.request.Request) -> dict:
    """Execute a urllib Request with exponential backoff on 5xx/network errors."""
    last_error: Exception | None = None

    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        try:
            with urllib.request.urlopen(request) as response:
                body = response.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise RegistryClientError(exc.code, exc.read().decode()) from exc
            last_error = exc
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc

        if attempt < len(_BACKOFF_SECONDS):
            time.sleep(_BACKOFF_SECONDS[attempt])

    raise RegistryUnreachableError(
        f"registry API unreachable after {len(_BACKOFF_SECONDS) + 1} attempts: {last_error}"
    )


def get_delivery(api_url: str, delivery_id: str) -> dict:
    """
    GET /deliveries/{delivery_id} — returns the DeliveryResponse dict.

    Raises RegistryClientError(404) if the delivery does not exist.
    """
    url = f"{api_url.rstrip('/')}/deliveries/{delivery_id}"
    request = urllib.request.Request(url, method="GET")
    return _request_with_retry(request)


def patch_delivery(api_url: str, delivery_id: str, updates: dict) -> dict:
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
    return _request_with_retry(request)


def emit_event(api_url: str, event_type: str, delivery_id: str, payload: dict) -> dict:
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
    return _request_with_retry(request)
```

**Testing:**

Contents of `tests/converter/test_http.py`. Copy the mocking pattern from `tests/crawler/test_http.py` verbatim.

```python
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
```

**Verification:**

Run: `uv run pytest tests/converter/test_http.py -v`
Expected: All HTTP tests pass.

**Commit:** `feat(converter): add HTTP client for registry interactions`
<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 3-5) -->

<!-- START_TASK_3 -->
### Task 3: Engine orchestration — skip guards + happy path (`engine.py`)

**Verifies:** sas-to-parquet-converter.AC5.1, AC5.2, AC5.3, AC5.6, AC6.2

**Files:**
- Create: `src/pipeline/converter/engine.py`
- Create: `tests/converter/test_engine.py` (this file grows across Tasks 3–5)

**Implementation:**

Contents of `src/pipeline/converter/engine.py`:

```python
# pattern: Imperative Shell

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pipeline.converter import http as converter_http
from pipeline.converter.classify import classify_exception
from pipeline.converter.convert import convert_sas_to_parquet
from pipeline.json_logging import get_logger


@dataclass(frozen=True)
class ConversionResult:
    outcome: Literal["success", "failure", "skipped"]
    delivery_id: str
    reason: str | None = None  # "already_converted", "errored", or None


def _build_output_path(source_path: str) -> Path:
    """
    Derive the Parquet output path: {source_path}/parquet/{stem}.parquet.

    The stem is the last directory name of source_path — i.e., the delivery's
    terminal directory. Example:
      source_path = /scan/dpid/packages/req/ver/msoc
      output_path = /scan/dpid/packages/req/ver/msoc/parquet/msoc.parquet
    """
    src = Path(source_path)
    return src / "parquet" / f"{src.name}.parquet"


def _find_sas_file(source_path: Path) -> Path | None:
    """
    Locate the single .sas7bdat file in the delivery's source directory.

    Convention from crawler: deliveries have exactly one SAS file at the root
    of source_path (sub-deliveries live in their own source_path). If zero or
    multiple SAS files are found, this returns None and the caller raises —
    caller wraps as FileNotFoundError to route to source_missing classification.
    """
    candidates = sorted(source_path.glob("*.sas7bdat"))
    if len(candidates) == 1:
        return candidates[0]
    return None


def convert_one(
    delivery_id: str,
    api_url: str,
    *,
    converter_version: str,
    chunk_size: int,
    compression: str,
    log_dir: str | None = None,
    http_module=converter_http,
    convert_fn=convert_sas_to_parquet,
) -> ConversionResult:
    """
    Convert a single delivery end-to-end.

    1. GET the delivery from the registry.
    2. Apply skip guards.
    3. Locate the SAS file inside source_path.
    4. Call convert_sas_to_parquet.
    5. On success: PATCH {output_path, parquet_converted_at}, emit conversion.completed.
    6. On failure: classify, PATCH {metadata.conversion_error}, emit conversion.failed.

    Args:
        delivery_id: Registry delivery ID.
        api_url: Registry API base URL.
        converter_version, chunk_size, compression: forwarded to core.
        log_dir: Directory for JSON log file (stderr-only if None).
        http_module: Injected for tests (defaults to converter.http).
        convert_fn: Injected for tests (defaults to the real conversion core).

    Returns:
        ConversionResult describing the outcome.

    Contract: Does NOT retry on failure. A classified error is recorded and
    the caller moves to the next delivery.
    """
    logger = get_logger("converter", log_dir=log_dir)

    delivery = http_module.get_delivery(api_url, delivery_id)
    source_path_str = delivery["source_path"]
    output_path = _build_output_path(source_path_str)

    # Skip guard 1: already converted and file still exists.
    if delivery.get("parquet_converted_at") and output_path.exists():
        logger.info(
            "skipped already converted",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "already_converted",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="already_converted")

    # Skip guard 2: conversion_error present.
    metadata = delivery.get("metadata") or {}
    if metadata.get("conversion_error"):
        logger.info(
            "skipped errored delivery",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "errored",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="errored")

    # Locate source file.
    source_path = Path(source_path_str)
    sas_file = _find_sas_file(source_path)

    try:
        if sas_file is None:
            raise FileNotFoundError(f"no single .sas7bdat file found under {source_path}")

        conv_meta = convert_fn(
            sas_file,
            output_path,
            chunk_size=chunk_size,
            compression=compression,
            converter_version=converter_version,
        )
    except BaseException as exc:
        return _handle_failure(
            exc, delivery_id, source_path_str, api_url, converter_version, logger, http_module
        )

    # Success path.
    patch_body = {
        "output_path": str(output_path),
        "parquet_converted_at": conv_meta.wrote_at.isoformat(),
    }
    http_module.patch_delivery(api_url, delivery_id, patch_body)

    event_payload = {
        "delivery_id": delivery_id,
        "output_path": str(output_path),
        "row_count": conv_meta.row_count,
        "bytes_written": conv_meta.bytes_written,
        "wrote_at": conv_meta.wrote_at.isoformat(),
    }
    http_module.emit_event(api_url, "conversion.completed", delivery_id, event_payload)

    logger.info(
        "converted",
        extra={
            "delivery_id": delivery_id,
            "source_path": source_path_str,
            "outcome": "success",
            "row_count": conv_meta.row_count,
            "bytes_written": conv_meta.bytes_written,
        },
    )
    return ConversionResult(outcome="success", delivery_id=delivery_id)


def _handle_failure(
    exc: BaseException,
    delivery_id: str,
    source_path: str,
    api_url: str,
    converter_version: str,
    logger,
    http_module,
) -> ConversionResult:
    """
    Classify the exception, PATCH the registry with conversion_error, emit
    conversion.failed, and log. Re-raises BaseException subclasses that
    indicate operator intent (KeyboardInterrupt, SystemExit) without writing
    to the registry — those mean "stop now," not "this delivery failed."
    """
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        raise exc

    error_class = classify_exception(exc)
    now = datetime.now(timezone.utc).isoformat()
    error_message = str(exc)[:500]  # cap — real exceptions can be huge tracebacks

    error_dict = {
        "class": error_class,
        "message": error_message,
        "at": now,
        "converter_version": converter_version,
    }

    # Best-effort: if the PATCH itself fails we still log and re-raise — the
    # operator will see the conversion.failed entry never landed in events,
    # and the crawler's next delivery.created re-run will clear the field.
    http_module.patch_delivery(
        api_url, delivery_id, {"metadata": {"conversion_error": error_dict}}
    )

    event_payload = {
        "delivery_id": delivery_id,
        "error_class": error_class,
        "error_message": error_message,
        "at": now,
    }
    http_module.emit_event(api_url, "conversion.failed", delivery_id, event_payload)

    logger.error(
        "conversion failed",
        extra={
            "delivery_id": delivery_id,
            "source_path": source_path,
            "outcome": "failure",
            "error_class": error_class,
            "error_message": error_message,
        },
    )
    return ConversionResult(outcome="failure", delivery_id=delivery_id)
```

**Why injected `http_module` and `convert_fn`:** Tests stub these to assert PATCH shapes without real HTTP and without real SAS files. Production defaults bind to the real modules.

**Why `source_path` + `parquet/{stem}.parquet` naming:** `Path(source_path).name` is the terminal directory (e.g., `msoc`, `scdm_snapshot`). Parent and sub-deliveries both use `{source_path}/parquet/{stem}.parquet`, giving a uniform layout (per AC2.4). This matches the design exactly.

**Why cap error_message at 500 chars:** Avoids giant tracebacks turning the metadata JSON into a megabyte row. Truncated message is still searchable in logs where the full stack is captured.

**Testing (Task 3 covers AC5.1/AC5.2/AC5.3/AC5.6/AC6.2 — happy path and skip guards):**

Contents of `tests/converter/test_engine.py`:

```python
# pattern: test file

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.converter.convert import ConversionMetadata
from pipeline.converter.engine import convert_one, ConversionResult, _build_output_path


class _StubHttp:
    """Stub http module recording PATCH/emit calls and returning configured delivery dicts."""

    def __init__(self, delivery: dict):
        self.delivery = delivery
        self.patches: list[tuple[str, dict]] = []
        self.events: list[tuple[str, str, dict]] = []

    def get_delivery(self, api_url, delivery_id):
        return self.delivery

    def patch_delivery(self, api_url, delivery_id, updates):
        self.patches.append((delivery_id, updates))
        return self.delivery

    def emit_event(self, api_url, event_type, delivery_id, payload):
        self.events.append((event_type, delivery_id, payload))
        return {"seq": 1, "event_type": event_type, "delivery_id": delivery_id, "payload": payload}


def _make_delivery(source_path: str, parquet_converted_at=None, metadata=None):
    return {
        "delivery_id": "d1",
        "source_path": source_path,
        "parquet_converted_at": parquet_converted_at,
        "metadata": metadata or {},
        "output_path": None,
    }


class TestConvertOneHappyPath:
    def test_success_patches_and_emits(self, tmp_path):
        # AC5.1, AC6.2
        source_dir = tmp_path / "dpid" / "packages" / "req" / "v1" / "msoc"
        source_dir.mkdir(parents=True)
        (source_dir / "msoc.sas7bdat").write_bytes(b"unused by stub")

        http = _StubHttp(_make_delivery(str(source_dir)))
        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"pq")
            return ConversionMetadata(
                row_count=123,
                column_count=4,
                column_labels={},
                value_labels={},
                sas_encoding="UTF-8",
                bytes_written=2,
                wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1",
            "http://registry",
            converter_version="0.1.0",
            chunk_size=100,
            compression="zstd",
            http_module=http,
            convert_fn=fake_convert,
        )

        assert result.outcome == "success"

        # PATCH: AC5.1
        assert len(http.patches) == 1
        delivery_id, patch = http.patches[0]
        assert delivery_id == "d1"
        assert patch["output_path"] == str(source_dir / "parquet" / "msoc.parquet")
        assert patch["parquet_converted_at"] == fake_wrote_at.isoformat()

        # Event: AC6.2
        assert len(http.events) == 1
        event_type, event_delivery_id, payload = http.events[0]
        assert event_type == "conversion.completed"
        assert event_delivery_id == "d1"
        assert set(payload.keys()) == {"delivery_id", "output_path", "row_count", "bytes_written", "wrote_at"}
        assert payload["row_count"] == 123
        assert payload["bytes_written"] == 2
        assert payload["wrote_at"] == fake_wrote_at.isoformat()

    def test_build_output_path_parent_delivery(self):
        # AC2.4 (shared semantic with Phase 2): parquet/{stem}.parquet under source.
        src = "/data/dpid/packages/req/v1/msoc"
        out = _build_output_path(src)
        assert out == Path("/data/dpid/packages/req/v1/msoc/parquet/msoc.parquet")

    def test_build_output_path_sub_delivery(self):
        # AC10.2 (shared semantic): sub-delivery gets its own parquet dir.
        src = "/data/dpid/packages/req/v1/msoc/scdm_snapshot"
        out = _build_output_path(src)
        assert out == Path("/data/dpid/packages/req/v1/msoc/scdm_snapshot/parquet/scdm_snapshot.parquet")


class TestConvertOneSkipGuards:
    def test_skip_when_already_converted_and_file_exists(self, tmp_path):
        # AC5.2
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        output_file = source_dir / "parquet" / "msoc.parquet"
        output_file.parent.mkdir()
        output_file.write_bytes(b"existing")

        http = _StubHttp(_make_delivery(
            str(source_dir), parquet_converted_at="2026-04-15T00:00:00+00:00"
        ))

        def should_not_be_called(src, out, **kwargs):
            raise AssertionError("convert_fn should not be invoked on skipped delivery")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=should_not_be_called,
        )

        assert result.outcome == "skipped"
        assert result.reason == "already_converted"
        assert http.patches == []
        assert http.events == []

    def test_reconvert_when_file_deleted_despite_flag(self, tmp_path):
        # Edge: parquet_converted_at set but file missing -> re-convert.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(
            str(source_dir), parquet_converted_at="2026-04-15T00:00:00+00:00"
        ))

        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"new")
            return ConversionMetadata(
                row_count=1, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=3, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )
        assert result.outcome == "success"

    def test_skip_when_conversion_error_set(self, tmp_path):
        # AC5.3
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(
            str(source_dir),
            metadata={"conversion_error": {"class": "parse_error", "message": "x"}},
        ))

        def should_not_be_called(src, out, **kwargs):
            raise AssertionError("convert_fn should not be invoked on errored delivery")

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=should_not_be_called,
        )
        assert result.outcome == "skipped"
        assert result.reason == "errored"
        assert http.patches == []
        assert http.events == []

    def test_null_conversion_error_does_not_skip(self, tmp_path):
        # AC7.3 interaction: {"conversion_error": null} means processable.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")

        http = _StubHttp(_make_delivery(
            str(source_dir),
            metadata={"conversion_error": None, "other_key": "preserved"},
        ))

        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"")
            return ConversionMetadata(
                row_count=0, column_count=0, column_labels={}, value_labels={},
                sas_encoding="", bytes_written=0, wrote_at=fake_wrote_at,
            )

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=fake_convert,
        )
        assert result.outcome == "success"
```

**Verification:**

Run: `uv run pytest tests/converter/test_engine.py::TestConvertOneHappyPath tests/converter/test_engine.py::TestConvertOneSkipGuards -v`
Expected: All happy-path and skip-guard tests pass.

**Commit:** `feat(converter): add engine with skip guards and happy-path orchestration`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Engine failure path — classified errors, no retry

**Verifies:** sas-to-parquet-converter.AC5.4, AC5.5, AC6.3

**Context:** Exercise each exception class path through the engine. Use `convert_fn` stub to raise; assert PATCH shape and event shape.

**Files:**
- Modify: `tests/converter/test_engine.py` (add `TestConvertOneFailure` class)

**Implementation:**

```python
from pyreadstat import ReadstatError
import pyarrow as pa

from pipeline.converter.classify import SchemaDriftError


class TestConvertOneFailure:
    def _setup_failing(self, tmp_path, exc):
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        def raises(src, out, **kwargs):
            raise exc

        return http, raises

    def test_parse_error_patches_and_emits_failed(self, tmp_path):
        # AC5.4, AC6.3
        http, raises = self._setup_failing(tmp_path, ReadstatError("bad sas"))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )

        assert result.outcome == "failure"

        # PATCH shape (AC5.4)
        assert len(http.patches) == 1
        _, patch = http.patches[0]
        assert "metadata" in patch
        err = patch["metadata"]["conversion_error"]
        assert err["class"] == "parse_error"
        assert "bad sas" in err["message"]
        assert err["converter_version"] == "0.1.0"
        assert "at" in err

        # Event shape (AC6.3)
        assert len(http.events) == 1
        event_type, _, payload = http.events[0]
        assert event_type == "conversion.failed"
        assert set(payload.keys()) == {"delivery_id", "error_class", "error_message", "at"}
        assert payload["error_class"] == "parse_error"

    def test_schema_drift_classifies_correctly(self, tmp_path):
        http, raises = self._setup_failing(tmp_path, SchemaDriftError("chunk mismatch"))
        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )
        assert result.outcome == "failure"
        assert http.patches[0][1]["metadata"]["conversion_error"]["class"] == "schema_drift"

    @pytest.mark.parametrize("exc,expected_class", [
        (FileNotFoundError("missing"),            "source_missing"),
        (PermissionError("nope"),                 "source_permission"),
        (OSError("generic io"),                   "source_io"),
        (UnicodeDecodeError("utf-8", b"", 0, 1, "x"), "encoding_mismatch"),
        (MemoryError("boom"),                     "oom"),
        (pa.lib.ArrowTypeError("arrow"),          "arrow_error"),
        (ValueError("unrelated"),                 "unknown"),
    ])
    def test_each_exception_classifies_on_failure_path(self, tmp_path, exc, expected_class):
        http, raises = self._setup_failing(tmp_path, exc)
        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises,
        )
        assert result.outcome == "failure"
        assert http.patches[0][1]["metadata"]["conversion_error"]["class"] == expected_class
        assert http.events[0][2]["error_class"] == expected_class

    def test_no_retry_after_failure(self, tmp_path):
        # AC5.5: convert_fn is called exactly once.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        call_count = {"n": 0}

        def counting_raise(src, out, **kwargs):
            call_count["n"] += 1
            raise RuntimeError("one shot")

        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=counting_raise,
        )
        assert call_count["n"] == 1

    def test_missing_sas_file_classifies_source_missing(self, tmp_path):
        # source_path has no .sas7bdat file at all.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        http = _StubHttp(_make_delivery(str(source_dir)))

        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=lambda *a, **k: pytest.fail("should not be called"),
        )
        assert result.outcome == "failure"
        assert http.patches[0][1]["metadata"]["conversion_error"]["class"] == "source_missing"

    def test_error_message_truncated_to_500_chars(self, tmp_path):
        # Guards the _handle_failure 500-char cap on message length.
        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        huge_message = "x" * 10_000

        def raises_huge(src, out, **kwargs):
            raise ValueError(huge_message)

        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http, convert_fn=raises_huge,
        )

        patched = http.patches[0][1]
        assert len(patched["metadata"]["conversion_error"]["message"]) == 500
        # Event payload is built from the same truncated value.
        assert len(http.events[0][2]["error_message"]) == 500

    def test_keyboard_interrupt_re_raised_no_registry_write(self, tmp_path):
        # Operator interruption must not be recorded as a conversion failure.
        http, raises = self._setup_failing(tmp_path, KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            convert_one(
                "d1", "http://registry",
                converter_version="0.1.0", chunk_size=100, compression="zstd",
                http_module=http, convert_fn=raises,
            )
        assert http.patches == []
        assert http.events == []
```

**Verification:**

Run: `uv run pytest tests/converter/test_engine.py -v`
Expected: All engine tests pass, including new failure tests.

**Commit:** `feat(converter): classify and record conversion failures without retry`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Integration-level engine test against real SAS + real converter

**Verifies:** sas-to-parquet-converter.AC5.1 (integration confidence), AC5.6

**Context:** The previous engine tests stub both `convert_fn` and `http_module`. This test stubs only `http_module` — the real `convert_sas_to_parquet` runs against a real SAS fixture, producing a real Parquet file, and the engine's PATCH/event shapes reflect real `ConversionMetadata`. This catches any glue-layer bugs between Phase 2 and Phase 3.

**Files:**
- Modify: `tests/converter/test_engine.py` (add `TestConvertOneIntegration` class)

**Implementation:**

```python
import pyarrow.parquet as pq
import pandas as pd


class TestConvertOneLogging:
    """
    Verify AC5.6: a structured log line is emitted per conversion attempt
    (success or failure) via the project JsonFormatter.

    Note on caplog + JsonFormatter: pytest's caplog captures records on the
    root logger hierarchy by default. `get_logger("converter", ...)` returns
    a named child logger; caplog sees its records as long as propagation is
    on (default) or we use `caplog.set_level(..., logger="converter")`.
    """
    def test_success_emits_structured_log(self, tmp_path, caplog):
        import logging

        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        fake_wrote_at = datetime(2026, 4, 16, tzinfo=timezone.utc)

        def fake_convert(src, out, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"x")
            return ConversionMetadata(
                row_count=5, column_count=1, column_labels={}, value_labels={},
                sas_encoding="UTF-8", bytes_written=1, wrote_at=fake_wrote_at,
            )

        caplog.set_level(logging.INFO, logger="converter")
        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,  # stderr-only; caplog still captures via propagation
            http_module=http, convert_fn=fake_convert,
        )

        success_records = [r for r in caplog.records if getattr(r, "outcome", None) == "success"]
        assert len(success_records) >= 1, f"no success log records found in {caplog.records}"
        record = success_records[0]
        assert record.delivery_id == "d1"
        assert record.source_path == str(source_dir)
        assert record.row_count == 5

    def test_failure_emits_structured_log(self, tmp_path, caplog):
        import logging

        source_dir = tmp_path / "msoc"
        source_dir.mkdir()
        (source_dir / "msoc.sas7bdat").write_bytes(b"")
        http = _StubHttp(_make_delivery(str(source_dir)))

        def fake_raises(src, out, **kwargs):
            raise ValueError("boom")

        caplog.set_level(logging.ERROR, logger="converter")
        convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            log_dir=None,
            http_module=http, convert_fn=fake_raises,
        )

        failure_records = [r for r in caplog.records if getattr(r, "outcome", None) == "failure"]
        assert len(failure_records) >= 1
        record = failure_records[0]
        assert record.delivery_id == "d1"
        assert record.error_class == "unknown"
        assert "boom" in record.error_message


class TestConvertOneIntegration:
    def test_real_sas_real_parquet_stubbed_http(self, tmp_path, sas_fixture_factory):
        source_dir = tmp_path / "dpid" / "packages" / "req" / "v1" / "msoc"
        source_dir.mkdir(parents=True)
        # Write a real SAS file inside the source directory using the fixture factory.
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        # Factory uses its own tmp_path — redirect by writing directly here.
        import pyreadstat
        sas_path = source_dir / "msoc.sas7bdat"
        pyreadstat.write_sas7bdat(df, str(sas_path))

        http = _StubHttp(_make_delivery(str(source_dir)))
        result = convert_one(
            "d1", "http://registry",
            converter_version="0.1.0", chunk_size=100, compression="zstd",
            http_module=http,
        )

        assert result.outcome == "success"

        # Parquet file was produced at the expected path.
        out = source_dir / "parquet" / "msoc.parquet"
        assert out.exists()
        table = pq.read_table(out)
        assert table.num_rows == 3

        # Engine PATCHed with the same output_path and a well-formed timestamp.
        _, patch = http.patches[0]
        assert patch["output_path"] == str(out)
        assert "T" in patch["parquet_converted_at"]  # ISO 8601

        # Event payload has real row_count / bytes_written.
        _, _, payload = http.events[0]
        assert payload["row_count"] == 3
        assert payload["bytes_written"] > 0
```

**Verification:**

Run: `uv run pytest tests/converter/test_engine.py::TestConvertOneIntegration -v`
Expected: Passes. This is the end-to-end integration at Phase-3 scope (engine + core, no registry API process).

Run: `uv run pytest`
Expected: Full suite green (324 existing + all Phase 1/2/3 new tests).

**Commit:** `test(converter): engine integration test with real SAS and Parquet`
<!-- END_TASK_5 -->

<!-- END_SUBCOMPONENT_B -->

---

## Phase completion checklist

- [ ] Five tasks committed separately.
- [ ] `uv run pytest` full suite green.
- [ ] `src/pipeline/converter/http.py` and `engine.py` both start with `# pattern: Imperative Shell` on line 1.
- [ ] New `converter_*` config fields present in `config.json` and `PipelineConfig` with defaults.
- [ ] `convert_one` has no imports from `pipeline.registry_api` except `models` (contract sharing is allowed; db/routes/events are forbidden).
- [ ] Phase 4 (CLI) can import `convert_one`, `ConversionResult`, `converter_http.get_delivery`, `converter_http.patch_delivery` without circular dependencies.
- [ ] A quick manual end-to-end smoke test: start `uv run registry-api`, POST a delivery with `source_path` pointing to a real SAS fixture, call `convert_one(delivery_id, "http://localhost:8000", ...)` from a Python REPL; verify registry row updated and event emitted.
