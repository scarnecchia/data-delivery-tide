# pattern: Imperative Shell (orchestration + side effects), with helper pure functions

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pipeline.converter import http as converter_http
from pipeline.converter.classify import classify_exception
from pipeline.converter.convert import convert_sas_to_parquet
from pipeline.converter.protocols import (
    ConvertSasToParquetFnProtocol,
    HttpModuleProtocol,
)
from pipeline.json_logging import get_logger


@dataclass(frozen=True)
class ConversionResult:
    outcome: Literal["success", "failure", "skipped"]
    delivery_id: str
    reason: str | None = (
        None  # "already_converted", "errored", "excluded_dp_id", "no_sas_file", or None
    )


@dataclass(frozen=True)
class FileConversionSuccess:
    filename: str
    row_count: int
    bytes_written: int


@dataclass(frozen=True)
class FileConversionFailure:
    error_class: str
    message: str
    at: str
    converter_version: str


def _failure_to_wire(failure: FileConversionFailure) -> dict[str, Any]:
    """Translate FileConversionFailure to its wire-shape dict.

    The on-the-wire dict uses key 'class' (a Python builtin); the dataclass
    field is named 'error_class' to avoid the collision. asdict() alone would
    not produce the right key, so we build the dict explicitly.
    """
    return {
        "class": failure.error_class,
        "message": failure.message,
        "at": failure.at,
        "converter_version": failure.converter_version,
    }


def _build_parquet_dir(source_path: str) -> Path:
    return Path(source_path) / "parquet"


def _find_sas_files(source_path: Path) -> list[Path]:
    return sorted(
        p for p in source_path.iterdir() if p.is_file() and p.suffix.lower() == ".sas7bdat"
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
    http_module: HttpModuleProtocol = converter_http,
    convert_fn: ConvertSasToParquetFnProtocol = convert_sas_to_parquet,
) -> ConversionResult:
    logger = get_logger("converter", log_dir=log_dir)

    delivery = http_module.get_delivery(api_url, delivery_id)
    source_path_str = delivery["source_path"]

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

    # Skip guard 1: already converted (trust the flag only).
    if delivery.get("parquet_converted_at"):
        logger.info(
            "skipped already converted",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "already_converted",
            },
        )
        return ConversionResult(
            outcome="skipped", delivery_id=delivery_id, reason="already_converted"
        )

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

    # Discover SAS files.
    source_path = Path(source_path_str)
    sas_files = _find_sas_files(source_path)

    if not sas_files:
        logger.info(
            "skipped no sas file",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "skipped",
                "reason": "no_sas_file",
            },
        )
        return ConversionResult(outcome="skipped", delivery_id=delivery_id, reason="no_sas_file")

    # Convert each SAS file.
    parquet_dir = _build_parquet_dir(source_path_str)
    successes: list[FileConversionSuccess] = []
    failures: dict[str, FileConversionFailure] = {}
    wrote_at: str | None = None

    for sas_file in sas_files:
        output = parquet_dir / f"{sas_file.stem}.parquet"
        try:
            conv_meta = convert_fn(
                sas_file,
                output,
                chunk_size=chunk_size,
                compression=compression,
                converter_version=converter_version,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            error_class = classify_exception(exc)
            now = datetime.now(UTC).isoformat()
            failures[sas_file.name] = FileConversionFailure(
                error_class=error_class,
                message=str(exc)[:500],
                at=now,
                converter_version=converter_version,
            )
            logger.warning(
                "file conversion failed",
                extra={
                    "delivery_id": delivery_id,
                    "source_path": source_path_str,
                    "sas_filename": sas_file.name,
                    "outcome": "failure",
                    "error_class": error_class,
                },
            )
            continue

        successes.append(
            FileConversionSuccess(
                filename=f"{sas_file.stem}.parquet",
                row_count=conv_meta.row_count,
                bytes_written=conv_meta.bytes_written,
            )
        )
        wrote_at = conv_meta.wrote_at.isoformat()
        logger.info(
            "file converted",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "sas_filename": sas_file.name,
                "outcome": "success",
                "row_count": conv_meta.row_count,
                "bytes_written": conv_meta.bytes_written,
            },
        )

    # Total failure.
    if not successes:
        now = datetime.now(UTC).isoformat()
        error_dict = {
            "class": "multi_file_failure",
            "message": f"all {len(failures)} files failed conversion",
            "at": now,
            "converter_version": converter_version,
        }
        patch_body: dict[str, Any] = {
            "metadata": {
                "conversion_error": error_dict,
                "conversion_errors": {name: _failure_to_wire(f) for name, f in failures.items()},
            },
        }
        try:
            http_module.patch_delivery(api_url, delivery_id, patch_body)
        except Exception:
            logger.warning(
                "failed to PATCH conversion_error to registry",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
                exc_info=True,
            )

        event_payload: dict[str, Any] = {
            "delivery_id": delivery_id,
            "error_class": "multi_file_failure",
            "error_message": error_dict["message"],
            "at": now,
        }
        try:
            http_module.emit_event(api_url, "conversion.failed", delivery_id, event_payload)
        except Exception:
            logger.warning(
                "failed to emit conversion.failed event",
                extra={"delivery_id": delivery_id, "source_path": source_path_str},
                exc_info=True,
            )

        logger.error(
            "conversion failed",
            extra={
                "delivery_id": delivery_id,
                "source_path": source_path_str,
                "outcome": "failure",
                "file_count": len(failures),
                "failed_count": len(failures),
            },
        )
        return ConversionResult(outcome="failure", delivery_id=delivery_id)

    # At least one success.
    total_rows = sum(s.row_count for s in successes)
    total_bytes = sum(s.bytes_written for s in successes)
    converted_files = [s.filename for s in successes]

    patch_body = {
        "output_path": str(parquet_dir),
        "parquet_converted_at": wrote_at,
        "metadata": {
            "converted_files": converted_files,
        },
    }
    if failures:
        patch_body["metadata"]["conversion_errors"] = {
            name: _failure_to_wire(f) for name, f in failures.items()
        }

    http_module.patch_delivery(api_url, delivery_id, patch_body)

    completion_payload: dict[str, Any] = {
        "delivery_id": delivery_id,
        "output_path": str(parquet_dir),
        "file_count": len(successes),
        "total_rows": total_rows,
        "total_bytes": total_bytes,
        "failed_count": len(failures),
        "wrote_at": wrote_at,
    }
    http_module.emit_event(api_url, "conversion.completed", delivery_id, completion_payload)

    logger.info(
        "converted",
        extra={
            "delivery_id": delivery_id,
            "source_path": source_path_str,
            "outcome": "success",
            "file_count": len(successes),
            "total_rows": total_rows,
            "total_bytes": total_bytes,
            "failed_count": len(failures),
        },
    )
    return ConversionResult(outcome="success", delivery_id=delivery_id)
