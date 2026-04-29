# pattern: Functional Core
from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

from pipeline.lexicons.models import Lexicon, MetadataField

MAX_INHERITANCE_DEPTH = 3


class LexiconLoadError(Exception):
    """Raised when one or more lexicon files fail validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} lexicon error(s):\n" + "\n".join(errors))


def _discover_lexicon_files(lexicons_dir: Path) -> dict[str, Path]:
    """Walk lexicons_dir, return mapping of lexicon_id -> file path."""
    result: dict[str, Path] = {}
    for json_file in sorted(lexicons_dir.rglob("*.json")):
        if json_file.name.endswith(".schema.json"):
            continue
        relative = json_file.relative_to(lexicons_dir)
        lexicon_id = str(relative.with_suffix("")).replace("/", ".").replace("\\", ".")
        result[lexicon_id] = json_file
    return result


def _resolve_inheritance_order(
    raw_lexicons: dict[str, dict],
) -> list[str]:
    """Return lexicon IDs in topological order (bases before children).

    Raises LexiconLoadError on circular extends or missing base references.
    """
    errors: list[str] = []
    sorter: TopologicalSorter[str] = TopologicalSorter()

    for lid, data in raw_lexicons.items():
        extends = data.get("extends")
        if extends:
            if extends not in raw_lexicons:
                errors.append(f"{lid}: extends unknown lexicon '{extends}'")
            else:
                sorter.add(lid, extends)
        else:
            sorter.add(lid)

    if errors:
        raise LexiconLoadError(errors)

    try:
        return list(sorter.static_order())
    except CycleError as exc:
        raise LexiconLoadError([f"circular extends chain: {exc.args[1]}"]) from exc


def _check_inheritance_depth(
    raw_lexicons: dict[str, dict],
) -> list[str]:
    """Check that no inheritance chain exceeds MAX_INHERITANCE_DEPTH."""
    errors: list[str] = []
    for lid, data in raw_lexicons.items():
        depth = 0
        current = lid
        while raw_lexicons.get(current, {}).get("extends"):
            depth += 1
            current = raw_lexicons[current]["extends"]
            if depth > MAX_INHERITANCE_DEPTH:
                errors.append(f"{lid}: inheritance depth exceeds {MAX_INHERITANCE_DEPTH}")
                break
    return errors


def _deep_merge(base: dict, child: dict) -> dict:
    """Merge child into base. Child keys win. Nested dicts merged recursively."""
    result = dict(base)
    for key, value in child.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_single(
    lid: str,
    raw_lexicons: dict[str, dict],
    resolved: dict[str, dict],
) -> dict:
    """Resolve a single lexicon, merging with its base if extends is set."""
    data = raw_lexicons[lid]
    extends = data.get("extends")
    if extends and extends in resolved:
        base = resolved[extends]
        merged = _deep_merge(base, data)
        merged["id"] = lid
        merged.pop("extends", None)
        return merged
    data = dict(data)
    data["id"] = lid
    data.pop("extends", None)
    return data


def _import_hook(hook_path: str) -> Callable[..., Any]:
    """Import a hook from a dotted path like 'pipeline.lexicons.soc.qa:derive'.

    Returns a callable matching the ``derive_hook`` shape:
    ``(list[ParsedDelivery], Lexicon) -> list[ParsedDelivery]``. Typed as
    ``Callable[..., Any]`` (per design #19 AC4.2) because importing
    ``ParsedDelivery`` here would violate the lexicons -> crawler boundary.
    The actual hook signature is enforced by ``Lexicon.derive_hook``.
    """
    module_path, _, attr_name = hook_path.rpartition(":")
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def _validate_sub_dirs(lexicons: dict[str, Lexicon]) -> list[str]:
    """Validate sub_dirs references across all loaded lexicons."""
    errors: list[str] = []
    for lid, lex in lexicons.items():
        for dir_name, sub_lexicon_id in lex.sub_dirs.items():
            if sub_lexicon_id not in lexicons:
                errors.append(
                    f"{lid}: sub_dirs['{dir_name}'] references unknown lexicon '{sub_lexicon_id}'"
                )
            elif lexicons[sub_lexicon_id].sub_dirs:
                errors.append(
                    f"{lid}: sub_dirs['{dir_name}'] references lexicon "
                    f"'{sub_lexicon_id}' which itself has sub_dirs "
                    f"(recursive nesting not allowed)"
                )
    return errors


def _validate_lexicon(lid: str, data: dict) -> list[str]:
    """Validate a single resolved lexicon dict. Return list of error strings."""
    errors: list[str] = []
    statuses = set(data.get("statuses", []))

    if not statuses:
        errors.append(f"{lid}: 'statuses' is empty or missing")

    for from_status, targets in data.get("transitions", {}).items():
        if from_status not in statuses:
            errors.append(f"{lid}: transitions key '{from_status}' not in statuses")
        for target in targets:
            if target not in statuses:
                errors.append(
                    f"{lid}: transitions['{from_status}'] references unknown status '{target}'"
                )

    for dir_name, status in data.get("dir_map", {}).items():
        if status not in statuses:
            errors.append(f"{lid}: dir_map['{dir_name}'] references unknown status '{status}'")

    for action_status in data.get("actionable_statuses", []):
        if action_status not in statuses:
            errors.append(f"{lid}: actionable_statuses references unknown status '{action_status}'")

    for field_name, field_def in data.get("metadata_fields", {}).items():
        set_on = field_def.get("set_on") if isinstance(field_def, dict) else None
        if set_on and set_on not in statuses:
            errors.append(
                f"{lid}: metadata_fields['{field_name}'].set_on references "
                f"unknown status '{set_on}'"
            )

    return errors


def _build_lexicon(data: dict, hook: Callable[..., Any] | None) -> Lexicon:
    """Convert a validated dict to a frozen Lexicon dataclass."""
    metadata_fields = {}
    for name, field_def in data.get("metadata_fields", {}).items():
        metadata_fields[name] = MetadataField(
            type=field_def["type"],
            set_on=field_def.get("set_on"),
        )

    sub_dirs = dict(data.get("sub_dirs", {}))

    return Lexicon(
        id=data["id"],
        statuses=tuple(data.get("statuses", ())),
        transitions={k: tuple(v) for k, v in data.get("transitions", {}).items()},
        dir_map=dict(data.get("dir_map", {})),
        actionable_statuses=tuple(data.get("actionable_statuses", ())),
        metadata_fields=metadata_fields,
        derive_hook=hook,
        sub_dirs=sub_dirs,
    )


def load_all_lexicons(lexicons_dir: str | Path) -> dict[str, Lexicon]:
    """Load, resolve, validate, and return all lexicons from a directory.

    Raises LexiconLoadError if any validation errors are found.
    All errors are collected and reported in a single batch.
    """
    lexicons_path = Path(lexicons_dir)
    if not lexicons_path.is_dir():
        raise LexiconLoadError([f"lexicons_dir does not exist: {lexicons_dir}"])

    file_map = _discover_lexicon_files(lexicons_path)
    if not file_map:
        raise LexiconLoadError([f"no lexicon files found in {lexicons_dir}"])

    raw: dict[str, dict] = {}
    parse_errors: list[str] = []
    for lid, path in file_map.items():
        try:
            with open(path) as f:
                data = json.load(f)
            data.pop("$schema", None)
            raw[lid] = data
        except (json.JSONDecodeError, OSError) as exc:
            parse_errors.append(f"{lid}: failed to read {path}: {exc}")

    if parse_errors:
        raise LexiconLoadError(parse_errors)

    all_errors: list[str] = []

    # Resolve inheritance order first — catches circular extends chains
    # before depth check (so circulars report as cycles, not depth violations)
    order = _resolve_inheritance_order(raw)

    all_errors.extend(_check_inheritance_depth(raw))

    resolved: dict[str, dict] = {}
    for lid in order:
        resolved[lid] = _resolve_single(lid, raw, resolved)

    for lid, data in resolved.items():
        all_errors.extend(_validate_lexicon(lid, data))

    hook_map: dict[str, object | None] = {}
    for lid, data in resolved.items():
        hook_path = data.get("derive_hook")
        if hook_path:
            try:
                hook_map[lid] = _import_hook(hook_path)
            except (ImportError, AttributeError) as exc:
                all_errors.append(f"{lid}: cannot import derive_hook '{hook_path}': {exc}")
        else:
            hook_map[lid] = None

    if all_errors:
        raise LexiconLoadError(all_errors)

    result: dict[str, Lexicon] = {}
    for lid, data in resolved.items():
        result[lid] = _build_lexicon(data, hook_map.get(lid))

    # Validate sub_dirs references (must happen after all lexicons are built)
    sub_dir_errors = _validate_sub_dirs(result)
    if sub_dir_errors:
        raise LexiconLoadError(sub_dir_errors)

    return result


def load_lexicon(lexicon_id: str, lexicons_dir: str | Path) -> Lexicon:
    """Load a single lexicon by ID. Convenience wrapper around load_all_lexicons."""
    all_lexicons = load_all_lexicons(lexicons_dir)
    if lexicon_id not in all_lexicons:
        raise LexiconLoadError([f"lexicon '{lexicon_id}' not found"])
    return all_lexicons[lexicon_id]
