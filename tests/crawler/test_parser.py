import pytest

from pipeline.crawler.parser import ParsedDelivery, ParseError, parse_path, derive_qa_statuses


class TestParsePathSuccess:
    """AC1.1, AC1.2, AC1.3, AC1.4, AC1.5, AC1.10 — Successful parsing with correct metadata."""

    def test_standard_path_with_msoc_status_passed(self):
        """AC1.1: Standard path returns correct metadata with qa_status=passed."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.request_id == "soc_qar_wp001"
        assert result.project == "soc"
        assert result.request_type == "qar"
        assert result.workplan_id == "wp001"
        assert result.dp_id == "mkscnr"
        assert result.version == "v01"
        assert result.qa_status == "passed"
        assert result.source_path == path
        assert result.scan_root == "/requests/qa"

    def test_path_with_msoc_new_status_pending(self):
        """AC1.2: Path ending in msoc_new returns qa_status=pending."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.qa_status == "pending"

    def test_dp_id_at_minimum_boundary_3_chars(self):
        """AC1.3: dp_id with exactly 3 characters parses successfully."""
        path = "/requests/qa/abc/packages/soc_qar_wp001/soc_qar_wp001_abc_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.dp_id == "abc"

    def test_dp_id_at_maximum_boundary_8_chars(self):
        """AC1.3: dp_id with exactly 8 characters parses successfully."""
        path = "/requests/qa/abcdefgh/packages/soc_qar_wp001/soc_qar_wp001_abcdefgh_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.dp_id == "abcdefgh"

    def test_version_v01_format(self):
        """AC1.4: Version string v01 parses correctly."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.version == "v01"

    def test_version_v1_format(self):
        """AC1.4: Version string v1 parses correctly."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v1/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.version == "v1"

    def test_version_v10_format(self):
        """AC1.4: Version string v10 parses correctly."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v10/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.version == "v10"

    def test_different_scan_root_one(self):
        """AC1.5: Same relative path under different scan_root returns correct scan_root."""
        path = "/requests/qm/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc"
        result = parse_path(path, scan_root="/requests/qm", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.scan_root == "/requests/qm"

    def test_different_scan_root_two(self):
        """AC1.5: Same relative path under another scan_root returns correct scan_root."""
        path = "/requests/qad/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc"
        result = parse_path(path, scan_root="/requests/qad", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.scan_root == "/requests/qad"

    def test_request_id_with_more_than_3_segments(self):
        """AC1.10: Request ID with >3 segments parses with remaining parts in workplan_id."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001_extra/soc_qar_wp001_extra_mkscnr_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParsedDelivery)
        assert result.request_id == "soc_qar_wp001_extra"
        assert result.project == "soc"
        assert result.request_type == "qar"
        assert result.workplan_id == "wp001_extra"


class TestParsePathFailure:
    """AC1.6, AC1.7, AC1.8 — Parse errors with descriptive reasons."""

    def test_dp_id_too_short_2_chars(self):
        """AC1.6: dp_id with 2 characters returns ParseError."""
        path = "/requests/qa/ab/packages/soc_qar_wp001/soc_qar_wp001_ab_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParseError)
        assert result.raw_path == path
        assert result.scan_root == "/requests/qa"

    def test_dp_id_too_long_9_chars(self):
        """AC1.6: dp_id with 9 characters returns ParseError."""
        path = "/requests/qa/abcdefghi/packages/soc_qar_wp001/soc_qar_wp001_abcdefghi_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParseError)
        assert result.raw_path == path
        assert result.scan_root == "/requests/qa"

    def test_missing_version_segment(self):
        """AC1.7: Directory name missing _v<digits> suffix returns ParseError with 'version' in reason."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParseError)
        assert "version" in result.reason.lower()
        assert result.raw_path == path

    def test_path_ending_in_neither_msoc_nor_msoc_new(self):
        """AC1.8: Path not ending in msoc or msoc_new returns ParseError with 'msoc' in reason."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/data"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParseError)
        assert "msoc" in result.reason.lower()
        assert result.raw_path == path

    def test_path_too_short_missing_version_dir(self):
        """Edge case: Path too short to contain version directory."""
        path = "/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions=set())

        assert isinstance(result, ParseError)
        assert result.raw_path == path


class TestParsePathEdgeCases:
    """AC1.9 — Excluded dp_id returns None (not error)."""

    def test_excluded_dp_id_returns_none(self):
        """AC1.9: dp_id in exclusion set returns None (expected, not error)."""
        path = "/requests/qa/nsdp/packages/soc_qar_wp001/soc_qar_wp001_nsdp_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions={"nsdp"})

        assert result is None

    def test_excluded_dp_id_among_multiple_exclusions(self):
        """AC1.9: Excluded dp_id returns None even with multiple exclusions."""
        path = "/requests/qa/nsdp/packages/soc_qar_wp001/soc_qar_wp001_nsdp_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions={"nsdp", "other", "excluded"})

        assert result is None

    def test_non_excluded_dp_id_with_exclusions_set(self):
        """AC1.9: Non-excluded dp_id parses successfully even with exclusions set."""
        path = "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc"
        result = parse_path(path, scan_root="/requests/qa", exclusions={"nsdp", "other"})

        assert isinstance(result, ParsedDelivery)
        assert result.dp_id == "mkscnr"


class TestDeriveQaStatuses:
    """AC2.7, AC2.8, AC2.9 — Derive failed status for superseded deliveries."""

    def test_ac2_7_pending_superseded_by_newer_version(self):
        """AC2.7: Pending delivery superseded by newer version is marked failed."""
        v1 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            qa_status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new",
            scan_root="/requests/qa",
        )
        v2 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v02",
            qa_status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new",
            scan_root="/requests/qa",
        )

        result = derive_qa_statuses([v1, v2])

        assert len(result) == 2
        # v1 should be marked failed
        v1_result = next(d for d in result if d.version == "v01")
        assert v1_result.qa_status == "failed"
        # v2 should remain pending
        v2_result = next(d for d in result if d.version == "v02")
        assert v2_result.qa_status == "pending"

    def test_ac2_8_pending_without_newer_version_stays_pending(self):
        """AC2.8: Single pending delivery (no newer version) remains pending."""
        v1 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            qa_status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new",
            scan_root="/requests/qa",
        )

        result = derive_qa_statuses([v1])

        assert len(result) == 1
        assert result[0].qa_status == "pending"

    def test_ac2_9_passed_delivery_never_changed(self):
        """AC2.9: Passed delivery is never marked failed, even with newer pending."""
        v1_passed = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            qa_status="passed",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc",
            scan_root="/requests/qa",
        )
        v2_pending = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v02",
            qa_status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new",
            scan_root="/requests/qa",
        )

        result = derive_qa_statuses([v1_passed, v2_pending])

        assert len(result) == 2
        # v1 (passed) should stay passed
        v1_result = next(d for d in result if d.version == "v01")
        assert v1_result.qa_status == "passed"
        # v2 (pending) should stay pending
        v2_result = next(d for d in result if d.version == "v02")
        assert v2_result.qa_status == "pending"

    def test_multiple_groups_scoped_per_workplan_dp_id(self):
        """Additional: Derivation scoped per (workplan_id, dp_id) group, not global."""
        # Group 1: wp001/mkscnr with v01 and v02
        wp1_mks_v1 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            qa_status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new",
            scan_root="/requests/qa",
        )
        wp1_mks_v2 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v02",
            qa_status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new",
            scan_root="/requests/qa",
        )
        # Group 2: wp002/nsdp with v01 (highest, stays pending)
        wp2_nsdp_v1 = ParsedDelivery(
            request_id="soc_qar_wp002",
            project="soc",
            request_type="qar",
            workplan_id="wp002",
            dp_id="nsdp",
            version="v01",
            qa_status="pending",
            source_path="/requests/qa/nsdp/packages/soc_qar_wp002/soc_qar_wp002_nsdp_v01/msoc_new",
            scan_root="/requests/qa",
        )

        result = derive_qa_statuses([wp1_mks_v1, wp1_mks_v2, wp2_nsdp_v1])

        assert len(result) == 3
        # wp001/mkscnr/v01 should be failed (superseded within its group)
        wp1_v1 = next(d for d in result if d.workplan_id == "wp001" and d.version == "v01")
        assert wp1_v1.qa_status == "failed"
        # wp001/mkscnr/v02 should be pending (highest in its group)
        wp1_v2 = next(d for d in result if d.workplan_id == "wp001" and d.version == "v02")
        assert wp1_v2.qa_status == "pending"
        # wp002/nsdp/v01 should stay pending (only version in its group)
        wp2_v1 = next(d for d in result if d.workplan_id == "wp002")
        assert wp2_v1.qa_status == "pending"

    def test_empty_list_returns_empty_list(self):
        """Additional: Empty input returns empty output."""
        result = derive_qa_statuses([])

        assert result == []
