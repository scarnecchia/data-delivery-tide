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
    reason: str | None = None  # "already_converted", "errored", "excluded_dp_id", "no_sas_file", or None


def _build_parquet_dir(source_path: str) -> Path:
    return Path(source_path) / "parquet"


def _find_sas_files(source_path: Path) -> list[Path]:
    return sorted(
        p for p in source_path.iterdir()
        if p.is_file() and p.suffix.lower() == ".sas7bdat"
    )


def convert_one(
    delivery_id: str,
    api_url: str,
    *,
    converter_version: str,
    chunk_size: int,
    compression: str,
    dp_id_exclusions: set[str] | None = None,
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

    # Skip guard 0: dp_id is in the exclusion set.
    if dp_id_exclusions and delivery.get("dp_id") in dp_id_exclusions:
        logger.info(
            "skipped excluded dp_id",
            extra={
                "delivery_id": delivery_id,
                "dp_id": delivery.get("dp_id"),
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "excluded_dp_id",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="excluded_dp_id")

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

    if sas_file is None:
        try:
            dir_contents = [
                {"name": p.name, "is_file": p.is_file(), "suffix": p.suffix}
                for p in source_path.iterdir()
            ]
        except OSError:
            dir_contents = "unreadable"
        logger.info(
            "skipped no sas file",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "no_sas_file",
                "dir_contents": dir_contents,
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="no_sas_file")

    try:
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

    try:
        http_module.patch_delivery(
            api_url, delivery_id, {"metadata": {"conversion_error": error_dict}}
        )
    except Exception:
        logger.warning(
            "failed to PATCH conversion_error to registry",
            extra={"delivery_id": delivery_id, "source_path": source_path},
        )

    event_payload = {
        "delivery_id": delivery_id,
        "error_class": error_class,
        "error_message": error_message,
        "at": now,
    }
    try:
        http_module.emit_event(api_url, "conversion.failed", delivery_id, event_payload)
    except Exception:
        logger.warning(
            "failed to emit conversion.failed event",
            extra={"delivery_id": delivery_id, "source_path": source_path},
        )

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
