# pattern: test file
"""Test that hardcoded QA status references don't exist in the codebase.

This test acts as a static analysis gate to prevent hardcoded qa_status and
qa_passed_at references from being reintroduced. QA status must always be
managed through the lexicon system, not hardcoded in application code.
"""

import re
import subprocess
from pathlib import Path


def test_no_hardcoded_qa_references() -> None:
    """Assert zero matches for hardcoded qa_status and qa_passed_at in src/pipeline/.

    Uses grep to search all .py files for the forbidden strings, excluding
    __pycache__ and .pyc files.
    """
    pipeline_dir = Path(__file__).parent.parent / "src" / "pipeline"
    assert pipeline_dir.exists(), f"Pipeline directory not found: {pipeline_dir}"

    forbidden_patterns = ["qa_status", "qa_passed_at"]
    found_references = []

    for py_file in pipeline_dir.rglob("*.py"):
        # Skip __pycache__ directories and .pyc files
        if "__pycache__" in py_file.parts:
            continue

        content = py_file.read_text(encoding="utf-8")

        for pattern in forbidden_patterns:
            if re.search(rf"\b{re.escape(pattern)}\b", content):
                found_references.append((str(py_file), pattern))

    assert not found_references, (
        f"Found hardcoded QA references that must use lexicon system:\n"
        + "\n".join(f"  {path}: {pattern}" for path, pattern in found_references)
    )


def test_no_hardcoded_qa_references_via_grep() -> None:
    """Verify the static analysis gate using grep as an alternate method.

    This provides defense-in-depth validation of the hardcoded QA check.
    """
    pipeline_dir = Path(__file__).parent.parent / "src" / "pipeline"
    assert pipeline_dir.exists(), f"Pipeline directory not found: {pipeline_dir}"

    # Search using grep with word boundaries
    result = subprocess.run(
        [
            "grep",
            "-r",
            "--include=*.py",
            "--exclude-dir=__pycache__",
            r"\b\(qa_status\|qa_passed_at\)\b",
            str(pipeline_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, f"Found hardcoded QA references:\n{result.stdout}"
