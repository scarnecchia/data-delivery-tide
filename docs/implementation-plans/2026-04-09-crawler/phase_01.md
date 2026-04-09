# Crawler Service Implementation Plan

**Goal:** Build the filesystem crawler intake layer for the healthcare data pipeline

**Architecture:** Functional Core / Imperative Shell. Pure functions handle parsing, fingerprinting, and manifest construction. Thin imperative shell handles filesystem I/O, manifest writing, and HTTP calls.

**Tech Stack:** Python 3.10+, stdlib only (no new runtime deps), pytest + httpx for testing

**Scope:** 5 phases from original design (phases 1-5)

**Codebase verified:** 2026-04-09

---

## Acceptance Criteria Coverage

This phase implements and tests:

### crawler.AC1: Path Parser
- **crawler.AC1.1 Success:** Standard path `/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc` returns correct metadata (request_id=`soc_qar_wp001`, project=`soc`, request_type=`qar`, workplan_id=`wp001`, dp_id=`mkscnr`, version=`v01`, qa_status=`passed`)
- **crawler.AC1.2 Success:** Path with `msoc_new` terminal directory returns qa_status=`pending`
- **crawler.AC1.3 Success:** dp_id at boundary lengths (3 and 8 characters) parses correctly
- **crawler.AC1.4 Success:** Version variants (`v01`, `v1`, `v10`) parse correctly
- **crawler.AC1.5 Success:** Paths from different scan_roots parse correctly with correct scan_root in result
- **crawler.AC1.6 Failure:** dp_id shorter than 3 or longer than 8 characters returns parse error
- **crawler.AC1.7 Failure:** Missing version segment returns parse error with descriptive reason
- **crawler.AC1.8 Failure:** Path not ending in `msoc` or `msoc_new` returns parse error
- **crawler.AC1.9 Edge:** Excluded dp_id (e.g., `nsdp`) returns `None` (not an error)
- **crawler.AC1.10 Edge:** Request ID with more than 3 underscore-separated segments parses correctly (everything before dp_id+version match is request_id)

### crawler.AC8: Tests (partial)
- **crawler.AC8.1 Success:** Parser unit tests cover all AC1 cases with zero I/O

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->

<!-- START_TASK_1 -->
### Task 1: Add dp_id_exclusions to PipelineConfig and config.json

**Verifies:** None (infrastructure — config plumbing for crawler.AC1.9)

**Files:**
- Modify: `src/pipeline/config.py:15-22` (PipelineConfig dataclass)
- Modify: `src/pipeline/config.py:40-48` (load_config function)
- Modify: `pipeline/config.json` (add new field)
- Modify: `tests/test_config.py` (add test for new field)

**Implementation:**

Add `dp_id_exclusions: list[str]` field to `PipelineConfig` dataclass. Update `load_config()` to read it from the JSON config with a default of `[]` if absent. Add `"dp_id_exclusions": ["nsdp"]` to `pipeline/config.json`.

In `config.py`, the dataclass gains one field:

```python
@dataclass
class PipelineConfig:
    scan_roots: list[ScanRoot]
    registry_api_url: str
    output_root: str
    schema_path: str
    overrides_path: str
    log_dir: str
    db_path: str
    dp_id_exclusions: list[str]
```

In `load_config()`, add to the return:

```python
dp_id_exclusions=data.get("dp_id_exclusions", []),
```

**Verification:**

Run: `uv run pytest tests/test_config.py -v`
Expected: All existing config tests still pass, new test passes

**Commit:** `feat(crawler): add dp_id_exclusions to pipeline config`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create parser.py with parse_path() and result dataclasses

**Verifies:** crawler.AC1.1, crawler.AC1.2, crawler.AC1.3, crawler.AC1.4, crawler.AC1.5, crawler.AC1.6, crawler.AC1.7, crawler.AC1.8, crawler.AC1.9, crawler.AC1.10, crawler.AC8.1

**Files:**
- Create: `src/pipeline/crawler/parser.py`
- Create: `tests/crawler/__init__.py`
- Create: `tests/crawler/test_parser.py`

**Implementation:**

`parser.py` is Functional Core — zero I/O. It defines three dataclasses and one function:

```python
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
```

**Testing:**

Tests must verify each AC listed above. Follow project conventions: class-based grouping, docstrings citing AC numbers.

- **crawler.AC1.1:** Parse standard path, assert all 9 fields match expected values
- **crawler.AC1.2:** Path ending in `/msoc_new` returns qa_status=`"pending"`
- **crawler.AC1.3:** dp_id with exactly 3 chars (`"abc"`) and exactly 8 chars (`"abcdefgh"`) both parse successfully
- **crawler.AC1.4:** Version strings `v01`, `v1`, `v10` all parse correctly
- **crawler.AC1.5:** Same relative path under different scan_roots returns correct scan_root in each result
- **crawler.AC1.6:** dp_id with 2 chars and 9 chars both return ParseError
- **crawler.AC1.7:** Directory name missing `_v\d+` suffix returns ParseError with reason containing "version"
- **crawler.AC1.8:** Path ending in neither `msoc` nor `msoc_new` (e.g., `/data`) returns ParseError with reason containing "msoc"
- **crawler.AC1.9:** dp_id in exclusions set returns `None` (not ParseError)
- **crawler.AC1.10:** Request ID `"soc_qar_wp001_extra"` parses with workplan_id=`"wp001_extra"`

Test file structure:

```python
class TestParsePathSuccess:
    # AC1.1, AC1.2, AC1.3, AC1.4, AC1.5, AC1.10

class TestParsePathFailure:
    # AC1.6, AC1.7, AC1.8

class TestParsePathEdgeCases:
    # AC1.9
```

**Verification:**

Run: `uv run pytest tests/crawler/test_parser.py -v`
Expected: All tests pass

**Commit:** `feat(crawler): implement path parser with result dataclasses`
<!-- END_TASK_2 -->

<!-- END_SUBCOMPONENT_A -->
