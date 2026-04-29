# pattern: Imperative Shell

import argparse
import sys
from collections.abc import Generator

from pipeline.config import settings
from pipeline.converter import http as converter_http
from pipeline.converter.engine import convert_one
from pipeline.converter.protocols import ConvertOneFnProtocol, HttpModuleProtocol
from pipeline.json_logging import get_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="registry-convert",
        description="Drain unconverted deliveries from the registry to Parquet.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most this many deliveries total. Default: no limit.",
    )
    parser.add_argument(
        "--shard",
        type=str,
        default=None,
        metavar="I/N",
        help="Only process deliveries in shard I of N (0-indexed). "
        "Example: --shard 0/4 picks up ~1/4 of the backlog.",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Also re-attempt deliveries with conversion_error set (clears the error first).",
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


def _iter_unconverted(
    api_url: str,
    page_size: int,
    http_module: HttpModuleProtocol = converter_http,  # type: ignore[assignment]
) -> Generator[dict, None, None]:
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

    return _run(
        args,
        shard,
        http_module=converter_http,
        convert_one_fn=convert_one,
        dp_id_exclusions=set(settings.dp_id_exclusions),
    )


def _run(
    args: argparse.Namespace,
    shard: tuple[int, int] | None,
    *,
    http_module: HttpModuleProtocol,
    convert_one_fn: ConvertOneFnProtocol,
    dp_id_exclusions: set[str] | None = None,
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
                        api_url,
                        delivery_id,
                        {"metadata": {"conversion_error": None}},
                    )

            convert_one_fn(
                delivery_id,
                api_url,
                converter_version=settings.converter_version,
                chunk_size=settings.converter_chunk_size,
                compression=settings.converter_compression,
                dp_id_exclusions=dp_id_exclusions,
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
