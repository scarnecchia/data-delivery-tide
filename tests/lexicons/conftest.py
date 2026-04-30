# pattern: test file
import json
from pathlib import Path

import pytest


@pytest.fixture
def lexicons_dir(tmp_path):
    """Create a temp lexicons directory and return its path.

    Tests copy fixture files into subdirectories of this path to
    build whatever lexicon layout they need.
    """
    return tmp_path / "lexicons"


@pytest.fixture
def make_lexicon_file(lexicons_dir):
    """Factory fixture: write a lexicon JSON file into the temp lexicons dir.

    Usage:
        make_lexicon_file("soc/_base.json", {"statuses": ["pending", "passed"]})
    """

    def _make(relative_path: str, data: dict) -> Path:
        file_path = lexicons_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(data, f)
        return file_path

    return _make
