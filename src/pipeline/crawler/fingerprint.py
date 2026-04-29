# pattern: Functional Core
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FileEntry:
    filename: str
    size_bytes: int
    modified_at: str


def compute_fingerprint(files: list[FileEntry]) -> str:
    """Compute a deterministic fingerprint from a file inventory.

    Sorts by filename to ensure ordering invariance, then hashes the
    concatenated filename:size_bytes:modified_at strings.

    Returns "sha256:<hex>" or "sha256:empty" if no files.
    """
    if not files:
        return "sha256:" + hashlib.sha256(b"").hexdigest()

    sorted_files = sorted(files, key=lambda f: f.filename)
    content = "\n".join(
        f"{f.filename}:{f.size_bytes}:{f.modified_at}" for f in sorted_files
    )
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()
