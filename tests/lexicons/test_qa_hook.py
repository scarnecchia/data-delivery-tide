# pattern: test file
from pipeline.crawler.parser import ParsedDelivery
from pipeline.lexicons.models import Lexicon, MetadataField
from pipeline.lexicons.soc.qa import derive


class TestQADeriveHook:
    """Tests for QA derivation hook — lexicon-system.AC5.3, AC5.5."""

    @staticmethod
    def _make_qar_lexicon():
        """Create a QAR lexicon for testing."""
        return Lexicon(
            id="soc.qar",
            statuses=("pending", "passed", "failed"),
            transitions={"pending": ("passed", "failed"), "passed": (), "failed": ()},
            dir_map={"msoc": "passed", "msoc_new": "pending"},
            actionable_statuses=("passed",),
            metadata_fields={"passed_at": MetadataField(type="datetime", set_on="passed")},
            derive_hook=None,
        )

    def test_ac5_3_hook_called_and_executes(self):
        """AC5.3: Hook is called and executes successfully."""
        v1 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new",
            scan_root="/requests/qa",
        )
        lexicon = self._make_qar_lexicon()

        result = derive([v1], lexicon)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == v1

    def test_ac5_5_pending_superseded_by_newer_version_becomes_failed(self):
        """AC5.5: Pending delivery superseded by newer version is marked failed."""
        v1 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            status="pending",
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
            status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new",
            scan_root="/requests/qa",
        )
        lexicon = self._make_qar_lexicon()

        result = derive([v1, v2], lexicon)

        assert len(result) == 2
        v1_result = next(d for d in result if d.version == "v01")
        assert v1_result.status == "failed"
        v2_result = next(d for d in result if d.version == "v02")
        assert v2_result.status == "pending"

    def test_single_pending_delivery_remains_pending(self):
        """Additional: Single pending delivery (no newer version) remains pending."""
        v1 = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new",
            scan_root="/requests/qa",
        )
        lexicon = self._make_qar_lexicon()

        result = derive([v1], lexicon)

        assert len(result) == 1
        assert result[0].status == "pending"

    def test_passed_delivery_never_changed(self):
        """Additional: Passed delivery is never marked failed, even with newer pending."""
        v1_passed = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            status="passed",
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
            status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new",
            scan_root="/requests/qa",
        )
        lexicon = self._make_qar_lexicon()

        result = derive([v1_passed, v2_pending], lexicon)

        assert len(result) == 2
        v1_result = next(d for d in result if d.version == "v01")
        assert v1_result.status == "passed"
        v2_result = next(d for d in result if d.version == "v02")
        assert v2_result.status == "pending"

    def test_empty_list_returns_empty_list(self):
        """Additional: Empty input returns empty output."""
        lexicon = self._make_qar_lexicon()

        result = derive([], lexicon)

        assert result == []

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
            status="pending",
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
            status="pending",
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
            status="pending",
            source_path="/requests/qa/nsdp/packages/soc_qar_wp002/soc_qar_wp002_nsdp_v01/msoc_new",
            scan_root="/requests/qa",
        )
        lexicon = self._make_qar_lexicon()

        result = derive([wp1_mks_v1, wp1_mks_v2, wp2_nsdp_v1], lexicon)

        assert len(result) == 3
        wp1_v1 = next(d for d in result if d.workplan_id == "wp001" and d.version == "v01")
        assert wp1_v1.status == "failed"
        wp1_v2 = next(d for d in result if d.workplan_id == "wp001" and d.version == "v02")
        assert wp1_v2.status == "pending"
        wp2_v1 = next(d for d in result if d.workplan_id == "wp002")
        assert wp2_v1.status == "pending"

    def test_mixed_statuses_passed_v01_pending_v02_v03(self):
        """Additional: Mixed statuses — passed v01, pending v02 and v03."""
        v1_passed = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v01",
            status="passed",
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
            status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new",
            scan_root="/requests/qa",
        )
        v3_pending = ParsedDelivery(
            request_id="soc_qar_wp001",
            project="soc",
            request_type="qar",
            workplan_id="wp001",
            dp_id="mkscnr",
            version="v03",
            status="pending",
            source_path="/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v03/msoc_new",
            scan_root="/requests/qa",
        )
        lexicon = self._make_qar_lexicon()

        result = derive([v1_passed, v2_pending, v3_pending], lexicon)

        assert len(result) == 3
        v1_result = next(d for d in result if d.version == "v01")
        assert v1_result.status == "passed"
        v2_result = next(d for d in result if d.version == "v02")
        assert v2_result.status == "failed"
        v3_result = next(d for d in result if d.version == "v03")
        assert v3_result.status == "pending"
