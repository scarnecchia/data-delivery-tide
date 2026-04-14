# pattern: Functional Core
import re
from dataclasses import dataclass, replace
from itertools import groupby


@dataclass(frozen=True)
class ParsedDelivery:
    request_id: str
    project: str
    request_type: str
    workplan_id: str
    dp_id: str
    version: str
    status: str
    source_path: str
    scan_root: str


@dataclass(frozen=True)
class ParseError:
    raw_path: str
    scan_root: str
    reason: str


# Matches _<dp_id>_v<digits> at the end of a version directory name.
# dp_id is 3-8 alphanumeric characters. Version is v followed by 1+ digits.
_VERSION_DIR_PATTERN = re.compile(r"^(.+)_([a-zA-Z0-9]{3,8})_(v\d+)$")


def parse_path(
    path: str,
    scan_root: str,
    exclusions: set[str],
    dir_map: dict[str, str],
) -> ParsedDelivery | ParseError | None:
    """Parse a delivery directory path into structured metadata.

    Returns:
        ParsedDelivery on success,
        None if dp_id is in the exclusion set (expected, not an error),
        ParseError if the path cannot be parsed.
    """
    # Determine status from terminal directory using dir_map
    parts = path.rstrip("/").split("/")
    if len(parts) < 2:
        return ParseError(
            raw_path=path,
            scan_root=scan_root,
            reason="path too short to contain version directory",
        )

    terminal_dir = parts[-1]
    if terminal_dir not in dir_map:
        return ParseError(
            raw_path=path,
            scan_root=scan_root,
            reason=f"terminal directory '{terminal_dir}' not in dir_map",
        )
    status = dir_map[terminal_dir]

    # Walk up to the version directory (parent of msoc/msoc_new)
    # path: .../soc_qar_wp001_mkscnr_v01/msoc
    # version_dir_name: soc_qar_wp001_mkscnr_v01

    version_dir_name = parts[-2]

    match = _VERSION_DIR_PATTERN.match(version_dir_name)
    if match is None:
        return ParseError(
            raw_path=path,
            scan_root=scan_root,
            reason=f"could not extract version segment from directory name: {version_dir_name}",
        )

    request_id = match.group(1)
    dp_id = match.group(2)
    version = match.group(3)

    # Check exclusion AFTER successful parse — excluded dp_ids return None, not error
    if dp_id in exclusions:
        return None

    # Split request_id to extract project, request_type, workplan_id
    # request_id format: <project>_<request_type>_<workplan_id>
    # e.g. "soc_qar_wp001" -> project="soc", request_type="qar", workplan_id="wp001"
    # For longer request_ids like "soc_qar_wp001_extra", still works:
    # first segment is project, second is request_type, rest joined is workplan_id
    id_parts = request_id.split("_")
    if len(id_parts) < 3:
        return ParseError(
            raw_path=path,
            scan_root=scan_root,
            reason=f"request_id has fewer than 3 segments: {request_id}",
        )

    project = id_parts[0]
    request_type = id_parts[1]
    workplan_id = "_".join(id_parts[2:])

    return ParsedDelivery(
        request_id=request_id,
        project=project,
        request_type=request_type,
        workplan_id=workplan_id,
        dp_id=dp_id,
        version=version,
        status=status,
        source_path=path,
        scan_root=scan_root,
    )


def _group_key(delivery: ParsedDelivery) -> tuple[str, str]:
    """Extract grouping key from delivery: (workplan_id, dp_id)."""
    return (delivery.workplan_id, delivery.dp_id)


def _version_sort_key(delivery: ParsedDelivery) -> str:
    """Extract version for descending sort."""
    return delivery.version


def derive_statuses(
    deliveries: list[ParsedDelivery],
    lexicon,
) -> list[ParsedDelivery]:
    """Apply lexicon derivation hook if defined.

    If lexicon.derive_hook is set, delegates to the hook function.
    If lexicon.derive_hook is None, applies the inline QA supersession
    logic (pending non-highest versions → failed). This inline logic
    will be removed in Phase 6 when the hook module is created.

    Returns a new list — does not mutate the input.
    """
    if lexicon.derive_hook is not None:
        return lexicon.derive_hook(deliveries, lexicon)

    # Inline fallback: QA supersession logic (kept until Phase 6 extracts it)
    if not deliveries:
        return []

    result = []
    sorted_deliveries = sorted(deliveries, key=_group_key)

    for _key, group in groupby(sorted_deliveries, key=_group_key):
        group_list = list(group)
        if len(group_list) == 1:
            result.append(group_list[0])
            continue

        # Sort by version descending to find the highest
        by_version = sorted(group_list, key=_version_sort_key, reverse=True)
        highest_version = by_version[0].version

        for delivery in group_list:
            if delivery.status == "pending" and delivery.version != highest_version:
                result.append(replace(delivery, status="failed"))
            else:
                result.append(delivery)

    return result
