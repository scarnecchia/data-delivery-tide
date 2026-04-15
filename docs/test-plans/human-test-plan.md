# Data Registry Pipeline — Consolidated Human Test Plan

**Date:** 2026-04-15
**Automated tests:** 324 passing (`pytest`)
**Covers:** Registry API, crawler, event stream, lexicon system, sub-deliveries

## Prerequisites

- Python 3.10+ installed
- Project installed: `pip install -e ".[registry,consumer,dev]"`
- All automated tests passing: `pytest tests/ -v` (324 tests, 0 failures)
- Access to a filesystem where you can create test directory trees (e.g., `/tmp/`)
- A WebSocket client tool (e.g., `websocat`, `wscat`, or the reference consumer at `src/pipeline/events/consumer.py`)
- VS Code with JSON Schema support (for schema validation steps)

## 1. Installation and Startup

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | `pip install -e ".[registry,consumer,dev]"` from project root | Exit code 0, no errors |
| 1.2 | `python -c "import pipeline"` | No ImportError |
| 1.3 | `which registry-api` | Path printed, entrypoint on PATH |
| 1.4 | `registry-api` | API starts on port 8000, logs mention loading lexicons from `pipeline/lexicons/` |
| 1.5 | `curl http://localhost:8000/health` | 200 response |

## 2. Config and Lexicon Loading

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Open `pipeline/config.json`, verify each scan root has `path`, `label`, `lexicon`, and `target` fields | All 4 scan roots have required fields. `/requests/qa` and `/requests/qad` use `soc.qar`; `/requests/qm` and `/requests/qmd` use `soc.qmr` |
| 2.2 | Verify matching lexicon JSON files exist under `pipeline/lexicons/` | `pipeline/lexicons/soc/_base.json`, `soc/qar.json`, `soc/qmr.json`, `soc/scdm.json` all exist |
| 2.3 | Verify `soc/qar.json` and `soc/qmr.json` both have `"sub_dirs": {"scdm_snapshot": "soc.scdm"}` | Both files contain sub_dirs config |
| 2.4 | Copy `pipeline/config.json` to `/tmp/test-config.json`. Change a scan root's `lexicon` to `"soc.nonexistent"`. Run `PIPELINE_CONFIG=/tmp/test-config.json registry-api` | API fails to start with `LexiconLoadError` mentioning `"soc.nonexistent"` |
| 2.5 | Edit `/tmp/test-config.json` to remove `lexicons_dir`. Run `PIPELINE_CONFIG=/tmp/test-config.json registry-api` | API fails with `ValueError` mentioning `lexicons_dir` |

## 3. JSON Schema Validation (Editor)

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | Open `pipeline/lexicons/soc/qar.json` in VS Code | No schema errors. `$schema` reference resolved |
| 3.2 | Hover over `sub_dirs` field | Autocompletion and description shown |
| 3.3 | Temporarily change `"sub_dirs": {"scdm_snapshot": "soc.scdm"}` to `"sub_dirs": 123` | Red underline — type mismatch error |
| 3.4 | Revert the change | Error clears |
| 3.5 | Open `pipeline/lexicons/soc/_base.json` (no `sub_dirs`, no `extends`) | Validates without error |

## 4. API Status Validation and Transitions

Start the registry API with default config: `registry-api`

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | POST a new delivery: `curl -X POST http://localhost:8000/deliveries -H "Content-Type: application/json" -d '{"request_id":"soc_qar_wp001","project":"soc","request_type":"qar","workplan_id":"wp001","dp_id":"mkscnr","version":"v01","scan_root":"/requests/qa","lexicon_id":"soc.qar","status":"pending","source_path":"/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new"}'` | 200 response with `delivery_id`, `lexicon_id: "soc.qar"`, `status: "pending"`, `metadata: {}` |
| 4.2 | POST with invalid status: same body but `"status": "nonexistent"` and different `source_path` | 422 response mentioning "not valid for lexicon" |
| 4.3 | POST with unknown lexicon: `"lexicon_id": "nonexistent.lexicon"` and different `source_path` | 422 response mentioning "unknown lexicon_id" |
| 4.4 | PATCH the delivery from 4.1 to passed: `curl -X PATCH http://localhost:8000/deliveries/{delivery_id} -H "Content-Type: application/json" -d '{"status":"passed"}'` | 200 response with `status: "passed"` and `metadata.passed_at` containing ISO 8601 timestamp |
| 4.5 | PATCH back to pending: `curl -X PATCH http://localhost:8000/deliveries/{delivery_id} -H "Content-Type: application/json" -d '{"status":"pending"}'` | 422 response — `passed -> pending` not allowed |
| 4.6 | Create a new pending delivery, PATCH with same status `"pending"` | 200 response. `metadata` does NOT contain `passed_at` |

## 5. Crawler End-to-End

### 5a. Basic Crawl

| Step | Action | Expected |
|------|--------|----------|
| 5.1 | Create test directory tree: `mkdir -p /tmp/test_crawl/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc` | Created |
| 5.2 | Add a dummy file: `dd if=/dev/zero of=/tmp/test_crawl/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/test.sas7bdat bs=100 count=1` | File created |
| 5.3 | Create test config pointing at the tree: `scan_roots: [{"path": "/tmp/test_crawl", "label": "test", "lexicon": "soc.qar", "target": "packages"}]` with `lexicons_dir` pointing to `pipeline/lexicons` | Config created |
| 5.4 | Delete any existing `pipeline/registry.db`. Start registry API, then run crawler with test config | Crawler completes without errors |
| 5.5 | `curl http://localhost:8000/deliveries` | Delivery present with `lexicon_id: "soc.qar"`, `status: "passed"` (msoc maps to passed). No `qa_status` field |

### 5b. Sub-Delivery Discovery

| Step | Action | Expected |
|------|--------|----------|
| 5.6 | Add sub-directory: `mkdir -p /tmp/test_crawl/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/scdm_snapshot` | Created |
| 5.7 | Add sub file: `dd if=/dev/zero of=/tmp/test_crawl/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/scdm_snapshot/snapshot.sas7bdat bs=50 count=1` | File created |
| 5.8 | Re-run the crawler | Completes without errors |
| 5.9 | `curl http://localhost:8000/deliveries` | Two deliveries: parent (`lexicon_id: "soc.qar"`, source_path ends in `msoc`) and sub-delivery (`lexicon_id: "soc.scdm"`, source_path ends in `scdm_snapshot`) |
| 5.10 | Verify parent and sub share `request_id`, `project`, `workplan_id`, `dp_id`, `version` | Identity fields match |
| 5.11 | Verify parent and sub have different `delivery_id`, `file_count`, `total_bytes` | Values differ |

### 5c. Version Supersession with Sub-Deliveries

| Step | Action | Expected |
|------|--------|----------|
| 5.12 | Add a second version: `mkdir -p /tmp/test_crawl/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new/scdm_snapshot` with files in both `msoc_new/` and `scdm_snapshot/` | Created |
| 5.13 | Delete `pipeline/registry.db`, restart API, re-run crawler | Completes without errors |
| 5.14 | `curl http://localhost:8000/deliveries` | Four deliveries: v01 parent `"passed"`, v01 sub `"passed"`, v02 parent `"pending"`, v02 sub `"pending"`. v01 is NOT marked failed because v01 is `"passed"` (derive hook only supersedes pending) |

### 5d. Missing Sub-Directory (Graceful)

| Step | Action | Expected |
|------|--------|----------|
| 5.15 | Remove `scdm_snapshot` from v02: `rm -rf /tmp/test_crawl/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new/scdm_snapshot` | Removed |
| 5.16 | Delete `pipeline/registry.db`, restart API, re-run crawler | Completes without errors |
| 5.17 | `curl http://localhost:8000/deliveries` | Three deliveries: v01 parent, v01 sub, v02 parent. No sub-delivery for v02 — silently skipped |

### 5e. Structured Traversal

| Step | Action | Expected |
|------|--------|----------|
| 5.18 | Add a sibling directory at the wrong level: `mkdir /tmp/test_crawl/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/compare` | Created |
| 5.19 | Re-run crawler | `compare` directory is NOT registered — only `dir_map` matches (`msoc`, `msoc_new`) are discovered |

## 6. API Query Filtering

Using deliveries created in section 5:

| Step | Action | Expected |
|------|--------|----------|
| 6.1 | `curl "http://localhost:8000/deliveries?lexicon_id=soc.scdm"` | Only sub-deliveries returned |
| 6.2 | `curl "http://localhost:8000/deliveries?lexicon_id=soc.qar"` | Only parent deliveries returned |
| 6.3 | `curl "http://localhost:8000/deliveries?request_id=soc_qar_wp001"` | All deliveries for that request returned (both parents and subs) |
| 6.4 | `curl "http://localhost:8000/deliveries?status=passed"` | Only deliveries with `status: "passed"` returned |
| 6.5 | `curl "http://localhost:8000/deliveries/actionable"` | Deliveries matching their lexicon's `actionable_statuses` (passed) and not yet converted |

## 7. WebSocket Event Stream

| Step | Action | Expected |
|------|--------|----------|
| 7.1 | Connect a WebSocket client to `ws://localhost:8000/ws/events` | Connection established |
| 7.2 | POST a new delivery (new `source_path`) | WebSocket receives `{"event_type": "delivery.created", ...}` with `lexicon_id`, `status`, `metadata` in payload. NO `qa_status` or `qa_passed_at` keys |
| 7.3 | POST the same delivery again (identical payload) | No new WebSocket message (re-crawl suppression) |
| 7.4 | PATCH the delivery to `"passed"` | WebSocket receives `{"event_type": "delivery.status_changed", ...}` with `status: "passed"` and `metadata.passed_at` timestamp |
| 7.5 | PATCH with non-status field only: `{"output_path": "/out/test"}` | No WebSocket message |
| 7.6 | `curl "http://localhost:8000/events?after=0"` | All events returned as JSON array, ordered by `seq` ascending |
| 7.7 | `curl "http://localhost:8000/events?after=999"` | Empty array `[]` |

## 8. Multi-Client and Reconnection

| Step | Action | Expected |
|------|--------|----------|
| 8.1 | Connect two WebSocket clients | Both connected |
| 8.2 | POST a new delivery | Both clients receive the same event |
| 8.3 | Disconnect one client | No API error |
| 8.4 | POST another delivery | Remaining client receives the event |
| 8.5 | Stop and restart the API | API restarts, existing DB data preserved |
| 8.6 | Connect a new WebSocket client, POST a new delivery | Client receives the event. `GET /events?after=0` returns events from both before and after restart |

## 9. No Hardcoded QA References

| Step | Action | Expected |
|------|--------|----------|
| 9.1 | `grep -rn "qa_status\|qa_passed_at" src/pipeline/` | Zero matches |
| 9.2 | Review `src/pipeline/` for any logic branching on specific status strings outside of lexicon JSON files, the QA derive hook (`src/pipeline/lexicons/soc/qa.py`), and test fixtures | No business logic should assume specific status values |

## Checklist Summary

| Area | Key Verification | Section |
|------|-----------------|---------|
| Installation | `pip install`, entrypoint works | 1 |
| Config | Lexicon references valid, missing refs fail fast | 2 |
| JSON Schema | Editor validation works | 3 |
| API validation | Status/transition enforcement, metadata auto-population | 4 |
| Crawler (basic) | Dir-map status, lexicon_id in delivery | 5a |
| Sub-deliveries | Discovery, identity inheritance, own inventory | 5b |
| Supersession | Derive hook, sub-delivery isolation | 5c |
| Missing sub-dirs | Graceful skip | 5d |
| Structured traversal | Only dir_map matches discovered | 5e |
| Query filtering | By lexicon_id, status, request_id, actionable | 6 |
| Event stream | WS broadcast, re-crawl suppression, catch-up | 7 |
| Multi-client | Fan-out, disconnect resilience, restart | 8 |
| No hardcoding | Zero qa_status/qa_passed_at in src/ | 9 |
