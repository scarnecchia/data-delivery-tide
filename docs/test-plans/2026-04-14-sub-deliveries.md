# Sub-Delivery System — Human Test Plan

**Implementation plan:** `docs/implementation-plans/2026-04-14-sub-deliveries/`
**Generated:** 2026-04-14
**Automated tests:** 324 passing (`uv run pytest`)

## Prerequisites

- Development environment with `uv` installed
- `uv run pytest` passing (all automated tests green)
- Registry API runnable via `uv run registry-api`
- Access to a test directory tree or the ability to create one under `/tmp`
- VS Code with JSON Schema support installed

## Phase 1: Schema Validation (AC3.1)

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Open `pipeline/lexicons/soc/qar.json` in VS Code | File opens without schema errors |
| 1.2 | Hover over existing `sub_dirs` field or type a new key inside the object | VS Code shows autocompletion for `sub_dirs` key; validates as `object` with string values |
| 1.3 | Change `sub_dirs` value to `"sub_dirs": 123` (invalid type) | VS Code shows a schema validation error (red underline) indicating type mismatch |
| 1.4 | Revert the invalid change | File returns to valid state, no errors shown |
| 1.5 | Open `pipeline/lexicons/soc/_base.json` (no `sub_dirs` field) | File validates without error — backward compatibility confirmed |

## Phase 2: Crawler-to-Registry End-to-End (AC4.1-AC4.6)

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Create test directory tree: `mkdir -p /tmp/qa_test/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/scdm_snapshot` | Directories created |
| 2.2 | Add parent file: `dd if=/dev/zero of=/tmp/qa_test/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/parent.sas7bdat bs=100 count=1` | 100-byte file created in parent dir |
| 2.3 | Add sub file: `dd if=/dev/zero of=/tmp/qa_test/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/scdm_snapshot/sub.sas7bdat bs=50 count=1` | 50-byte file created in sub dir |
| 2.4 | Configure `pipeline/config.json` with `scan_roots` pointing to `/tmp/qa_test` with `lexicon: "soc.qar"` | Config updated |
| 2.5 | Start the registry API: `uv run registry-api` | API running on port 8000 |
| 2.6 | Run the crawler (in another terminal) | Crawler completes without errors |
| 2.7 | `curl http://localhost:8000/deliveries` | Response contains two deliveries: one parent (source_path ending in `msoc`) and one sub-delivery (source_path ending in `scdm_snapshot`) |
| 2.8 | Verify parent delivery has `lexicon_id: "soc.qar"` and sub-delivery has `lexicon_id: "soc.scdm"` | Lexicon IDs are correct |
| 2.9 | Verify parent and sub-delivery share `request_id`, `project`, `workplan_id`, `dp_id`, `version` but have different `delivery_id` values | Identity fields match, delivery IDs differ |
| 2.10 | Verify `file_count` and `total_bytes` differ between parent and sub | Parent: 1 file/100 bytes. Sub: 1 file/50 bytes |

## Phase 3: API Query Verification (AC5.1-AC5.4)

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | `curl http://localhost:8000/deliveries?lexicon_id=soc.scdm` | Only the sub-delivery returned |
| 3.2 | `curl http://localhost:8000/deliveries?lexicon_id=soc.qar` | Only the parent delivery returned |
| 3.3 | `curl http://localhost:8000/deliveries?request_id=soc_qar_wp001` | Both parent and sub-delivery returned |
| 3.4 | `curl http://localhost:8000/deliveries/actionable` | Sub-delivery appears if its status is in `soc.scdm`'s `actionable_statuses` and `parquet_converted_at` is null |
| 3.5 | `curl http://localhost:8000/events?after=0` | Events list includes `delivery.created` events for both parent and sub-delivery, each with correct `lexicon_id` in payload |

## End-to-End: Missing Sub-Directory Graceful Handling

| Step | Action | Expected |
|------|--------|----------|
| E2E.1 | Remove the `scdm_snapshot` directory from the test tree (leave only parent files) | Directory removed |
| E2E.2 | Re-run the crawler | Crawler completes without errors |
| E2E.3 | `curl http://localhost:8000/deliveries` | Only the parent delivery is present. No error events logged |

## End-to-End: Multi-Version Derivation Isolation

| Step | Action | Expected |
|------|--------|----------|
| E2E.4 | Create two versions: `v01` under `msoc_new` (pending) and `v02` under `msoc` (passed), both with `scdm_snapshot` sub-dirs containing files | Four directories with files |
| E2E.5 | Run the crawler | Four deliveries created: v01 parent, v01 sub, v02 parent, v02 sub |
| E2E.6 | `curl http://localhost:8000/deliveries` | v01 parent status is `"failed"` (superseded by v02 via derive hook). v01 sub status is `"pending"` (inherited from parent's initial status, unaffected by derivation). v02 parent is `"passed"`. v02 sub is `"passed"` |

## Human Verification Required

| Criterion | Why Manual | Steps |
|-----------|-----------|-------|
| sub-deliveries.AC3.1 | JSON Schema validation is editor-side, not runtime | Phase 1, steps 1.1-1.5 |
| sub-deliveries.AC4.1 (live) | Automated tests mock `post_delivery`; need real crawler-to-registry flow | Phase 2, steps 2.1-2.10 |
| sub-deliveries.AC5.1-AC5.4 (live) | Automated tests use HTTPX test client; need actual HTTP server | Phase 3, steps 3.1-3.5 |

## Traceability

| AC | Automated Test | Manual Step |
|----|----------------|-------------|
| sub-deliveries.AC1.1 | `tests/lexicons/test_loader.py::TestSubDirs::test_lexicon_with_valid_sub_dirs_loads` | -- |
| sub-deliveries.AC1.2 | `tests/lexicons/test_loader.py::TestSubDirs::test_lexicon_without_sub_dirs_has_empty_dict` | -- |
| sub-deliveries.AC1.3 | `tests/lexicons/test_loader.py::TestSubDirs::test_sub_dirs_inherited_via_extends`, `test_sub_dirs_overridden_via_extends` | -- |
| sub-deliveries.AC2.1 | `tests/lexicons/test_loader.py::TestSubDirs::test_lexicon_with_valid_sub_dirs_loads` | -- |
| sub-deliveries.AC2.2 | `tests/lexicons/test_loader.py::TestSubDirs::test_sub_dirs_reference_to_unknown_lexicon_fails` | -- |
| sub-deliveries.AC2.3 | `tests/lexicons/test_loader.py::TestSubDirs::test_lexicon_without_sub_dirs_has_empty_dict` | -- |
| sub-deliveries.AC2.4 | `tests/lexicons/test_loader.py::TestSubDirs::test_sub_dirs_recursive_nesting_rejected` | -- |
| sub-deliveries.AC3.1 | -- | Phase 1, 1.1-1.5 |
| sub-deliveries.AC3.2 | Existing loader tests | Phase 1, 1.5 |
| sub-deliveries.AC4.1 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_sub_delivery_created_when_sub_dir_exists` | Phase 2, 2.6-2.7 |
| sub-deliveries.AC4.2 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_sub_delivery_created_when_sub_dir_exists` | Phase 2, 2.7 |
| sub-deliveries.AC4.3 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_sub_delivery_inherits_parent_identity` | Phase 2, 2.9 |
| sub-deliveries.AC4.4 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_sub_delivery_inherits_parent_status` | Phase 2, 2.8 |
| sub-deliveries.AC4.5 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_sub_delivery_has_own_delivery_id` | Phase 2, 2.9 |
| sub-deliveries.AC4.6 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_sub_delivery_has_own_file_inventory` | Phase 2, 2.10 |
| sub-deliveries.AC4.7 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_missing_sub_dir_silently_skipped` | E2E, E2E.1-E2E.3 |
| sub-deliveries.AC4.8 | `tests/crawler/test_main.py::TestSubDeliveryDiscovery::test_sub_deliveries_grouped_by_own_lexicon_for_derivation` | E2E, E2E.4-E2E.6 |
| sub-deliveries.AC5.1 | `tests/registry_api/test_routes.py::TestSubDeliveryIntegration::test_sub_delivery_queryable_by_lexicon_id` | Phase 3, 3.1-3.2 |
| sub-deliveries.AC5.2 | `tests/registry_api/test_routes.py::TestSubDeliveryIntegration::test_parent_and_sub_correlated_by_identity` | Phase 3, 3.3 |
| sub-deliveries.AC5.3 | `tests/registry_api/test_routes.py::TestSubDeliveryIntegration::test_sub_delivery_appears_in_actionable` | Phase 3, 3.4 |
| sub-deliveries.AC5.4 | `tests/registry_api/test_routes.py::TestSubDeliveryIntegration::test_sub_delivery_creation_emits_event` | Phase 3, 3.5 |
| sub-deliveries.AC6.1 | `tests/lexicons/test_loader.py::TestSubDirs::test_real_lexicons_load_with_sub_dirs` | -- |
| sub-deliveries.AC6.2 | `tests/lexicons/test_loader.py::TestSubDirs::test_real_lexicons_load_with_sub_dirs` | -- |
