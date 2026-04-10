# Human Test Plan: Crawler Structured Traversal

## Prerequisites
- Python 3.10+ with project installed: `uv pip install -e ".[registry,dev]"`
- `uv run pytest` passing (all 175 tests green)
- Access to a filesystem where you can create test directory trees (e.g., `/tmp/crawler-test/`)

## Phase 1: Config Target Field Integration

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Open `pipeline/config.json`. Confirm `"target"` field exists on all scan root entries. | All 4 scan roots have `"target": "packages"` |
| 1.2 | Run `uv run python -c "from pipeline.config import load_config; c = load_config(); print([(r.path, r.target) for r in c.scan_roots])"` | Each scan root prints with `target='packages'` |
| 1.3 | Copy `pipeline/config.json` to `/tmp/test-config.json`. Add `"target": "compare"` to the first scan root entry. Run `PIPELINE_CONFIG=/tmp/test-config.json uv run python -c "from pipeline.config import load_config; c = load_config(); print(c.scan_roots[0].target)"` | Prints `compare` |

## Phase 2: Structured Traversal on Synthetic Tree

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Create test tree: `mkdir -p /tmp/crawler-test/qa/DPID1/packages/soc_qar_wp001/soc_qar_wp001_DPID1_v01/msoc` | Directory created |
| 2.2 | Create decoy at wrong depth: `mkdir -p /tmp/crawler-test/qa/DPID1/msoc` | Directory created |
| 2.3 | Create decoy in sibling: `mkdir -p /tmp/crawler-test/qa/DPID1/compare/soc_qar_wp001/soc_qar_wp001_DPID1_v01/msoc` | Directory created |
| 2.4 | Create decoy nested too deep: `mkdir -p /tmp/crawler-test/qa/DPID1/packages/soc_qar_wp001/soc_qar_wp001_DPID1_v01/subdir/msoc` | Directory created |
| 2.5 | Run `uv run python -c "from pipeline.config import ScanRoot; from pipeline.crawler.main import walk_roots; print(walk_roots([ScanRoot(path='/tmp/crawler-test/qa', label='test')]))"` | Single result: only the canonical path from step 2.1. No decoys. |

## Phase 3: Logging Diagnostics

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | Create dpid with no target dir: `mkdir -p /tmp/crawler-test/qa2/ORPHAN_DPID` (no `packages/` underneath) | Directory created |
| 3.2 | Run `uv run python -c "import logging; from pipeline.config import ScanRoot; from pipeline.crawler.main import walk_roots; logger = logging.getLogger('test'); logger.addHandler(logging.StreamHandler()); logger.setLevel(logging.WARNING); walk_roots([ScanRoot(path='/tmp/crawler-test/qa2', label='test')], logger)"` | Warning printed to stderr containing "ORPHAN_DPID" and "packages" |

## End-to-End: Full Crawl Against Synthetic Tree

| Step | Action | Expected |
|------|--------|----------|
| E2E.1 | Create config at `/tmp/e2e-config.json` with `scan_roots: [{"path": "/tmp/crawler-test/qa", "label": "qa"}]`, valid `registry_api_url`, `output_root`, `crawl_manifest_dir` pointing to `/tmp/e2e-manifests/` | Config file created |
| E2E.2 | Populate `/tmp/crawler-test/qa/DPID1/packages/soc_qar_wp001/soc_qar_wp001_DPID1_v01/msoc/` with a dummy `.sas7bdat` file (any content) | File created |
| E2E.3 | Run `PIPELINE_CONFIG=/tmp/e2e-config.json uv run crawl` (or the equivalent entry point) | Crawler runs, discovers the single delivery, writes manifest to `/tmp/e2e-manifests/`. If registry is not running, expect connection error. |
| E2E.4 | Inspect manifest JSON in `/tmp/e2e-manifests/` | `source_path` matches the canonical msoc path. `parsed.dp_id` is `DPID1`. `parsed.version` is `v01`. File inventory includes the `.sas7bdat` file. |
| E2E.5 | Re-run the crawl command from E2E.3 | Manifest is overwritten with identical content (same `delivery_id`, `fingerprint`, `file_count`) |

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| AC1.1: Explicit target loads | `test_load_config_target_explicit_packages` | 1.2 |
| AC1.2: Default target | `test_load_config_target_defaults_to_packages` | 1.2 |
| AC1.3: Non-default target | `test_load_config_target_non_default` | 1.3 |
| AC1.4: Real config loads | `test_load_config_default_json_all_targets_packages` | 1.1, 1.2 |
| AC2.1: msoc discovered | `test_ac2_1_discovers_msoc_and_msoc_new_directories` | 2.5 |
| AC2.2: msoc_new discovered | `test_ac2_1_discovers_msoc_and_msoc_new_directories` | 2.5 |
| AC2.3: Sibling not discovered | `test_ac2_3_msoc_in_sibling_not_discovered` | 2.5 |
| AC2.4: Wrong depth not discovered | `test_ac2_4_msoc_at_wrong_depth_not_discovered` | 2.5 |
| AC2.5: Too deep not discovered | `test_ac2_5_msoc_nested_too_deep_not_discovered` | 2.5 |
| AC2.6: Multiple dpids | `test_ac2_6_multiple_dpids_discovered` | 2.5 (add second dpid) |
| AC2.7: Multiple versions | `test_ac2_7_multiple_version_dirs_discovered` | E2E.3-E2E.5 |
| AC3.1: Warning on missing target | `test_ac3_1_warning_when_target_missing` | 3.1, 3.2 |
| AC3.2: No warning when target exists | `test_ac3_2_no_warning_when_target_exists` | 3.2 (implicit) |
| AC4.1: Backward compat config | `test_load_config_default_json_all_targets_packages` | 1.1 |
| AC4.2: Signature compatible | `test_ac2_1_*`, `test_ac2_4_processes_multiple_scan_roots` | 2.5 |
