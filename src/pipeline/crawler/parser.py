# pattern: Functional Core
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedDelivery:
    request_id: str
    project: str
    request_type: str
    workplan_id: str
    dp_id: str
    version: str
    qa_status: str
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
) -> ParsedDelivery | ParseError | None:
    """Parse a delivery directory path into structured metadata.

    Returns:
        ParsedDelivery on success,
        None if dp_id is in the exclusion set (expected, not an error),
        ParseError if the path cannot be parsed.
    """
    # Determine QA status from terminal directory
    if path.endswith("/msoc"):
        qa_status = "passed"
    elif path.endswith("/msoc_new"):
        qa_status = "pending"
    else:
        return ParseError(
            raw_path=path,
            scan_root=scan_root,
            reason="path does not end with msoc or msoc_new",
        )

    # Walk up to the version directory (parent of msoc/msoc_new)
    # path: .../soc_qar_wp001_mkscnr_v01/msoc
    # version_dir_name: soc_qar_wp001_mkscnr_v01
    parts = path.rstrip("/").split("/")
    # terminal is msoc or msoc_new, version dir is one level up
    if len(parts) < 2:
        return ParseError(
            raw_path=path,
            scan_root=scan_root,
            reason="path too short to contain version directory",
        )

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
        qa_status=qa_status,
        source_path=path,
        scan_root=scan_root,
    )
