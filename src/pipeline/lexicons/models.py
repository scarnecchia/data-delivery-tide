# pattern: Functional Core
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.crawler.parser import ParsedDelivery


@dataclass(frozen=True)
class MetadataField:
    type: str
    set_on: str | None = None


@dataclass(frozen=True)
class Lexicon:
    id: str
    statuses: tuple[str, ...]
    transitions: dict[str, tuple[str, ...]]
    dir_map: dict[str, str]
    actionable_statuses: tuple[str, ...]
    metadata_fields: dict[str, MetadataField]
    derive_hook: Callable[[list["ParsedDelivery"], "Lexicon"], list["ParsedDelivery"]] | None = None
    sub_dirs: dict[str, str] = field(default_factory=dict)
