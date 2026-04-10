from pipeline.crawler.fingerprint import FileEntry, compute_fingerprint


class TestComputeFingerprint:
    """AC8.2 — Fingerprint computation (determinism, ordering invariance, change detection)."""

    def test_determinism_same_file_list_produces_same_fingerprint(self):
        """AC8.2: Repeated calls with same files produce identical fingerprint."""
        files: list[FileEntry] = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
            {"filename": "file2.sas7bdat", "size_bytes": 2048, "modified_at": "2026-04-01T11:00:00Z"},
        ]

        fp1 = compute_fingerprint(files)
        fp2 = compute_fingerprint(files)

        assert fp1 == fp2

    def test_ordering_invariance_different_order_same_fingerprint(self):
        """AC8.2: Files in different order produce identical fingerprint."""
        files_ordered = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
            {"filename": "file2.sas7bdat", "size_bytes": 2048, "modified_at": "2026-04-01T11:00:00Z"},
        ]
        files_reversed = [
            {"filename": "file2.sas7bdat", "size_bytes": 2048, "modified_at": "2026-04-01T11:00:00Z"},
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
        ]

        fp_ordered = compute_fingerprint(files_ordered)
        fp_reversed = compute_fingerprint(files_reversed)

        assert fp_ordered == fp_reversed

    def test_change_detection_different_filename(self):
        """AC8.2: Different filename produces different fingerprint."""
        files_original = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
        ]
        files_changed = [
            {"filename": "file1_modified.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
        ]

        fp_original = compute_fingerprint(files_original)
        fp_changed = compute_fingerprint(files_changed)

        assert fp_original != fp_changed

    def test_change_detection_different_size(self):
        """AC8.2: Different size_bytes produces different fingerprint."""
        files_original = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
        ]
        files_changed = [
            {"filename": "file1.sas7bdat", "size_bytes": 2048, "modified_at": "2026-04-01T10:00:00Z"},
        ]

        fp_original = compute_fingerprint(files_original)
        fp_changed = compute_fingerprint(files_changed)

        assert fp_original != fp_changed

    def test_change_detection_different_modified_at(self):
        """AC8.2: Different modified_at produces different fingerprint."""
        files_original = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
        ]
        files_changed = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T11:00:00Z"},
        ]

        fp_original = compute_fingerprint(files_original)
        fp_changed = compute_fingerprint(files_changed)

        assert fp_original != fp_changed

    def test_empty_file_list(self):
        """Additional: Empty file list produces consistent fingerprint."""
        files: list[FileEntry] = []

        fp1 = compute_fingerprint(files)
        fp2 = compute_fingerprint(files)

        assert fp1 == fp2
        assert fp1.startswith("sha256:")

    def test_single_file(self):
        """Additional: Single file works correctly."""
        files: list[FileEntry] = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
        ]

        fp = compute_fingerprint(files)

        assert fp.startswith("sha256:")
        assert len(fp) > 7  # "sha256:" prefix + hex digest

    def test_fingerprint_format(self):
        """Additional: Fingerprint has correct format sha256:<hex>."""
        files: list[FileEntry] = [
            {"filename": "file1.sas7bdat", "size_bytes": 1024, "modified_at": "2026-04-01T10:00:00Z"},
        ]

        fp = compute_fingerprint(files)

        assert fp.startswith("sha256:")
        hex_part = fp[7:]  # Remove "sha256:" prefix
        assert len(hex_part) == 64  # SHA-256 produces 64 hex characters
        assert all(c in "0123456789abcdef" for c in hex_part)
