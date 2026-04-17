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
