# Lexicon System — Human Test Plan

**Implementation plan:** `docs/implementation-plans/2026-04-14-lexicon-system/`
**Generated:** 2026-04-14
**Automated tests:** 304 passing (`uv run pytest`)

## Prerequisites

- Development environment with `uv` installed
- `uv run pytest` passing (all automated tests green)
- Registry API runnable via `uv run registry-api`
- Access to a test directory tree or the ability to create one under `/tmp`
- A WebSocket client tool (e.g., `websocat`, `wscat`, or Python `websockets` library)

## Phase 1: Config and Lexicon Loading

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | Run `uv run registry-api` from the project root with no environment variable overrides | API starts on port 8000 without any lexicon load errors in the log output. Startup log should mention loading lexicons from `pipeline/lexicons/`. |
| 1.2 | Verify the real `pipeline/config.json` references valid lexicon IDs | Open `pipeline/config.json`, note each scan root's `lexicon` field. Confirm matching JSON files exist under `pipeline/lexicons/` (e.g., `pipeline/lexicons/soc/qar.json` for `"soc.qar"`). |
| 1.3 | Intentionally set a scan root's `lexicon` to `"soc.nonexistent"` in a copy of `config.json`, point `PIPELINE_CONFIG` at it, and run `uv run registry-api` | API should fail to start with a `LexiconLoadError` mentioning `"soc.nonexistent"`. |
| 1.4 | Remove `lexicons_dir` from the test config and run again | API should fail with a `ValueError` mentioning `lexicons_dir`. |

## Phase 2: API Status Validation and Transitions

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | Start the registry API. POST to `http://localhost:8000/deliveries` with body: `{"request_id": "soc_qar_wp001", "project": "soc", "request_type": "qar", "workplan_id": "wp001", "dp_id": "mkscnr", "version": "v01", "scan_root": "/requests/qa", "lexicon_id": "soc.qar", "status": "pending", "source_path": "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc_new"}` | 200 response with `delivery_id`, `lexicon_id: "soc.qar"`, `status: "pending"`, `metadata: {}` |
| 2.2 | POST to the same endpoint with `"status": "nonexistent"` and `"lexicon_id": "soc.qar"` | 422 response with detail mentioning "not valid for lexicon" |
| 2.3 | POST with `"lexicon_id": "nonexistent.lexicon"` | 422 response with detail mentioning "unknown lexicon_id" |
| 2.4 | Using the `delivery_id` from step 2.1, PATCH `http://localhost:8000/deliveries/{delivery_id}` with `{"status": "passed"}` | 200 response with `status: "passed"` and `metadata.passed_at` containing a valid ISO 8601 timestamp |
| 2.5 | PATCH the same delivery again with `{"status": "pending"}` | 422 response indicating the transition is not allowed (passed -> pending not in transitions) |
| 2.6 | Create a new pending delivery, then PATCH with `{"status": "pending"}` (same status) | 200 response. `metadata` should NOT contain `passed_at`. |

## Phase 3: Crawler End-to-End

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | Create a test directory tree: `/tmp/test_crawl/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc/` with a dummy `.sas7bdat` file inside | Directory structure created |
| 3.2 | Create a test `config.json` pointing at the tree with `scan_roots: [{"path": "/tmp/test_crawl/requests/qa", "label": "qa", "lexicon": "soc.qar"}]` and `lexicons_dir` pointing to `pipeline/lexicons` | Config file created |
| 3.3 | Start the registry API, then run the crawler with the test config | Crawler completes without errors. Check the registry via `GET http://localhost:8000/deliveries` |
| 3.4 | Inspect the response from `GET /deliveries` | Response includes a delivery with `lexicon_id: "soc.qar"`, `status: "passed"`, and NO `qa_status` field. `source_path` matches the test directory. |
| 3.5 | Add a second version directory: `/tmp/test_crawl/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v02/msoc_new/` with a dummy file, re-run crawler | `GET /deliveries` should show v01 with `status: "passed"` (unchanged) and v02 with `status: "pending"`. Both have `lexicon_id: "soc.qar"`. |

## Phase 4: WebSocket Event Verification

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | Start the registry API. Connect a WebSocket client to `ws://localhost:8000/ws` | Connection established (no error) |
| 4.2 | In a separate terminal, POST a new delivery (as in step 2.1) | WebSocket client receives a JSON message with `event_type: "delivery.created"`, containing `lexicon_id`, `status`, and `metadata` keys in the payload. NO `qa_status` or `qa_passed_at` keys present. |
| 4.3 | PATCH the delivery from step 4.2 to `status: "passed"` | WebSocket client receives `event_type: "delivery.status_changed"` with `status: "passed"` and `metadata.passed_at` containing a timestamp. NO `qa_status` or `qa_passed_at` keys. |
| 4.4 | Verify catch-up: `GET http://localhost:8000/events?after=0` | Returns all events as JSON array, each with `seq`, `event_type`, `delivery_id`, `payload`, `created_at`. Events ordered by seq ascending. |

## Phase 5: No Hardcoded QA References (Code Review)

| Step | Action | Expected |
|------|--------|----------|
| 5.1 | Run `grep -rn "qa_status\|qa_passed_at" src/pipeline/` from the project root | Zero matches. If any match, this is a failure. |
| 5.2 | Manually review `src/pipeline/` for semantically equivalent hardcoding -- any logic that assumes specific status string values (e.g., `status == "passed"`) outside of lexicon JSON definitions and the QA derivation hook (`src/pipeline/lexicons/soc/qa.py`) | No business logic should branch on specific status strings outside of: (a) lexicon JSON files, (b) the QA derive hook, (c) test fixtures. Any other occurrences indicate incomplete decoupling. |

## End-to-End: Full Pipeline Lifecycle

| Step | Action | Expected |
|------|--------|----------|
| E2E.1 | Start registry API with default config | Starts successfully, loads lexicons |
| E2E.2 | Connect WebSocket client to `/ws` | Connected |
| E2E.3 | Run crawler against a prepared directory tree with both `msoc` and `msoc_new` deliveries | Crawler completes, WebSocket receives `delivery.created` events |
| E2E.4 | `GET /deliveries` | All crawled deliveries present with correct `lexicon_id` and `status` values |
| E2E.5 | `GET /deliveries/actionable` | Only deliveries with statuses matching the lexicon's `actionable_statuses` (and not yet converted) appear |
| E2E.6 | PATCH one delivery to `"passed"` | `delivery.status_changed` event received on WebSocket with `metadata.passed_at` auto-populated |
| E2E.7 | `GET /events?after=0` | All events present, correctly ordered, with lexicon-aware payload shape |

## Human Verification Required

| Criterion | Why Manual | Steps |
|-----------|-----------|-------|
| AC7.1 | Automated grep catches literal `qa_status`/`qa_passed_at` but not semantically equivalent hardcoding | Phase 5, steps 5.1-5.2 |
| AC7.2 | Full suite passing is automated, but a human should verify test count and coverage completeness | Run `uv run pytest --co -q` and verify count |
| AC2.1 | Automated tests use `tmp_path` with synthetic config; need to verify real config loads | Phase 1, steps 1.1-1.2 |
| AC5.6 | Integration test mocks HTTP; need to verify actual crawler -> registry flow | Phase 3, steps 3.1-3.4 |
| AC6.1 | WebSocket broadcast tested indirectly via DB; need to verify actual WS stream | Phase 4, steps 4.1-4.3 |

## Traceability

| AC | Automated Test | Manual Step |
|----|----------------|-------------|
| AC1.1-AC1.9 | `tests/lexicons/test_loader.py` (34 tests) | -- |
| AC2.1 | `tests/test_config.py::test_load_config_valid_lexicon_reference` | Phase 1, 1.1-1.2 |
| AC2.2 | `tests/test_config.py::test_load_config_invalid_lexicon_reference` | Phase 1, 1.3 |
| AC2.3 | `tests/test_config.py::test_load_config_missing_lexicons_dir` | Phase 1, 1.4 |
| AC3.1-AC3.5 | `tests/registry_api/test_db.py::TestLexiconSchema` (6 tests) | -- |
| AC4.1-AC4.6 | `tests/registry_api/test_routes.py::TestLexiconValidation` (7 tests) | Phase 2, 2.1-2.6 |
| AC5.1-AC5.2 | `tests/crawler/test_parser.py::TestLexiconSystemAC5` (2 tests) | -- |
| AC5.3 | `tests/lexicons/test_qa_hook.py` + `tests/crawler/test_parser.py` | -- |
| AC5.4 | `tests/crawler/test_parser.py::test_ac5_4` | -- |
| AC5.5 | `tests/lexicons/test_qa_hook.py` (6 tests) | -- |
| AC5.6 | `tests/crawler/test_main.py::test_ac5_6` | Phase 3, 3.1-3.4 |
| AC6.1-AC6.3 | `tests/registry_api/test_routes.py::TestEventPayloadShape` (4 tests) | Phase 4, 4.1-4.3 |
| AC7.1 | `tests/test_no_hardcoded_qa.py` (2 tests) | Phase 5, 5.1-5.2 |
| AC7.2 | (full suite) | `uv run pytest --co -q` |
