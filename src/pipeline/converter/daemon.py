# pattern: Imperative Shell

import asyncio
import contextlib
import json
import logging
import os
import signal
import uuid
from pathlib import Path

from pipeline.config import settings
from pipeline.converter.engine import convert_one
from pipeline.converter.protocols import ConsumerFactoryProtocol, ConvertOneFnProtocol
from pipeline.events.consumer import EventConsumer
from pipeline.json_logging import get_logger

logger = logging.getLogger(__name__)


def load_last_seq(state_path: Path) -> int:
    """
    Read last_seq from state file. Returns 0 if the file is missing or invalid.

    Invalid content (malformed JSON, missing key, non-int value) is tolerated
    — we return 0 and start from scratch rather than crash on startup. The
    worst case is re-processing a handful of events, which is idempotent
    thanks to the engine's skip guards.
    """
    try:
        with open(state_path) as f:
            data = json.load(f)
        seq = data.get("last_seq", 0)
        return int(seq) if isinstance(seq, (int, float)) else 0
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return 0


def persist_last_seq(state_path: Path, seq: int) -> None:
    """
    Atomically write last_seq to state_path.

    Uses tmp-file-plus-os.replace for atomicity, with fsync of the tmp file
    to survive power loss between the write and the rename. Does NOT fsync
    the parent directory (see Phase 5 briefing for rationale).

    Creates parent directories if missing.
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # uuid-based tmp name matches the pattern used in convert.py; safe under
    # any concurrency even though the daemon processes events serially.
    tmp = state_path.with_name(f".{state_path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with open(tmp, "w") as f:
            json.dump({"last_seq": seq}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, state_path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                logger.debug("tmp file unlink failed during cleanup", exc_info=True)
        raise


class DaemonRunner:
    """
    Event-driven daemon orchestrator.

    Lifecycle:
      1. __init__ resolves config and sets up state.
      2. run_async() wires EventConsumer with an on_event callback, registers
         signal handlers on the event loop, and awaits the consumer task.
      3. On SIGTERM/SIGINT: sets _stopping, cancels the consumer task after
         any in-flight on_event completes, persists last_seq, returns.
    """

    def __init__(
        self,
        *,
        api_url: str,
        state_path: Path,
        converter_version: str,
        chunk_size: int,
        compression: str,
        dp_id_exclusions: set[str] | None = None,
        log_dir: str | None,
        consumer_factory: ConsumerFactoryProtocol = EventConsumer,  # type: ignore[assignment]
        convert_one_fn: ConvertOneFnProtocol = convert_one,  # type: ignore[assignment]
    ) -> None:
        self.api_url = api_url
        self.state_path = Path(state_path)
        self.converter_version = converter_version
        self.chunk_size = chunk_size
        self.compression = compression
        self.dp_id_exclusions = dp_id_exclusions
        self.log_dir = log_dir
        self._consumer_factory = consumer_factory
        self._convert_one_fn = convert_one_fn
        self._stopping = False
        self._logger = get_logger("converter-daemon", log_dir=log_dir)

    async def run_async(self) -> int:
        """
        Main coroutine. Returns an exit code.
        """
        last_seq = load_last_seq(self.state_path)
        self._logger.info(
            "daemon starting",
            extra={"last_seq": last_seq, "state_path": str(self.state_path)},
        )

        consumer = self._consumer_factory(self.api_url, self._on_event)
        consumer._last_seq = last_seq  # intentional private-attr set; see briefing

        loop = asyncio.get_running_loop()
        consumer_task = asyncio.create_task(consumer.run())
        self._consumer = consumer  # for signal handler to advance last_seq

        def _request_shutdown() -> None:
            if self._stopping:
                return
            self._stopping = True
            self._logger.info("shutdown requested; finishing in-flight work")
            # Cancelling schedules a CancelledError at the next await point.
            # Any in-flight asyncio.to_thread call returns first (threads can't
            # be cancelled), then the on_event coroutine resumes, persists,
            # and returns — after which the consumer loop sees cancellation.
            consumer_task.cancel()

        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                # Windows test environments. Not a target platform.
                loop.add_signal_handler(sig, _request_shutdown)

        try:
            await consumer_task
        except asyncio.CancelledError:
            self._logger.info("consumer task cancelled")
        except Exception as exc:
            self._logger.error(
                "consumer task raised unhandled exception",
                extra={"error_message": str(exc)},
            )
            return 1

        # State persistence is owned by `_on_event`: both the success path
        # and the cancellation path persist the event's seq before returning
        # or re-raising. Do NOT add a tail persist here:
        #   - On clean exit, the last processed event already has its seq
        #     on disk.
        #   - `consumer._last_seq` is updated by the reference consumer AFTER
        #     `on_event` returns (src/pipeline/events/consumer.py:81-82,
        #     87-88, 122-123), so it does not necessarily reflect an event
        #     that was mid-processing when we started shutting down.
        #   - A hypothetical unhandled Exception from the consumer task
        #     won't have a well-defined `_last_seq` to persist either.
        # The engine's skip-guards (converted=true; conversion_error set)
        # make replay of any unpersisted seq idempotent on restart.
        self._logger.info(
            "daemon stopped",
            extra={"last_seq": consumer._last_seq},
        )
        return 0

    async def _on_event(self, event: dict) -> None:
        """
        Per-event callback: dispatch delivery.created to the engine off the
        event loop; skip other event types.

        Persistence correctness:
          - Engine success → persist seq at the bottom of this method.
          - Engine raises `Exception` (classified failure) → engine has
            already PATCHed + emitted conversion.failed. Persist seq anyway
            so we don't re-dispatch the same failed delivery (whose next
            attempt would be skipped by the engine's conversion_error
            skip-guard regardless).
          - `CancelledError` (SIGTERM during `asyncio.to_thread`) →
            CancelledError is a BaseException, NOT an Exception subclass, so
            the `except Exception` below does not catch it. We explicitly
            catch it, persist the seq we just completed (the thread ran to
            completion before cancel fired — threads are not cancellable),
            and re-raise so the consumer task unwinds cleanly.
        """
        seq = event.get("seq", 0)
        event_type = event.get("event_type", "")
        delivery_id = event.get("delivery_id")

        if event_type == "delivery.created" and delivery_id:
            try:
                # Offload blocking work to a thread so the WebSocket keeps
                # pumping pings. Concurrency remains 1 — we await this before
                # accepting the next event.
                await asyncio.to_thread(
                    self._convert_one_fn,
                    delivery_id,
                    self.api_url,
                    converter_version=self.converter_version,
                    chunk_size=self.chunk_size,
                    compression=self.compression,
                    dp_id_exclusions=self.dp_id_exclusions,
                    log_dir=self.log_dir,
                )
            except asyncio.CancelledError:
                # SIGTERM/SIGINT fired while we were awaiting to_thread. The
                # underlying thread ran to completion (Python can't cancel
                # a running thread); the engine's PATCH + event emission
                # finished. Persist the seq so we don't replay on restart,
                # then re-raise to let the consumer task shut down.
                persist_last_seq(self.state_path, seq)
                raise
            except Exception as exc:
                # Engine already PATCHed + emitted conversion.failed. Log and
                # advance anyway — the skip guard handles replay.
                self._logger.error(
                    "engine raised during convert_one",
                    extra={"delivery_id": delivery_id, "error_message": str(exc)},
                )

        # Persist regardless of event_type — AC9.4 + AC9.7.
        persist_last_seq(self.state_path, seq)


def main() -> int:
    """Entry point for registry-convert-daemon."""
    runner = DaemonRunner(
        api_url=settings.registry_api_url,
        state_path=Path(settings.converter_state_path),
        converter_version=settings.converter_version,
        chunk_size=settings.converter_chunk_size,
        compression=settings.converter_compression,
        dp_id_exclusions=set(settings.dp_id_exclusions),
        log_dir=settings.log_dir,
    )
    return asyncio.run(runner.run_async())
