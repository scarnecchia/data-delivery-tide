# pattern: Functional Core
from dataclasses import dataclass
from typing import Callable


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
    derive_hook: Callable | None = None
