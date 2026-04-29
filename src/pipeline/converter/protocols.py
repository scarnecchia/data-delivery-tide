# pattern: Functional Core
"""Structural Protocol types for converter dependency-injected callables.

These define the shape of test seams (`http_module`, `convert_one_fn`,
`consumer_factory`) used by the engine, CLI, and daemon. Production code
satisfies them implicitly via duck typing; tests can inject fakes that match
the shape without inheriting from any concrete class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from pipeline.converter.convert import ConversionMetadata
    from pipeline.converter.engine import ConversionResult
    from pipeline.events.consumer import EventConsumer


class HttpModuleProtocol(Protocol):
    """Shape of `pipeline.converter.http` as consumed by engine + cli."""

    def get_delivery(self, api_url: str, delivery_id: str) -> dict: ...

    def patch_delivery(self, api_url: str, delivery_id: str, updates: dict) -> dict: ...

    def list_unconverted(self, api_url: str, after: str = "", limit: int = 200) -> list[dict]: ...

    def emit_event(
        self, api_url: str, event_type: str, delivery_id: str, payload: dict
    ) -> dict: ...


class ConvertOneFnProtocol(Protocol):
    """Shape of `engine.convert_one` for callers that inject it."""

    def __call__(
        self,
        delivery_id: str,
        api_url: str,
        *,
        converter_version: str,
        chunk_size: int,
        compression: str,
        dp_id_exclusions: set[str] | None = ...,
        log_dir: str | None = ...,
    ) -> ConversionResult: ...


class ConvertSasToParquetFnProtocol(Protocol):
    """Shape of `convert.convert_sas_to_parquet` for engine dependency injection."""

    def __call__(
        self,
        source_path: Path,
        output_path: Path,
        *,
        chunk_size: int = ...,
        compression: str = ...,
        converter_version: str = ...,
    ) -> ConversionMetadata: ...


class ConsumerFactoryProtocol(Protocol):
    """Shape of `EventConsumer.__init__` for daemon dependency injection."""

    def __call__(
        self,
        api_url: str,
        on_event: object,
    ) -> EventConsumer: ...
