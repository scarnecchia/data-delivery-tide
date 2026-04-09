# QA Registry — Human Test Plan

## Prerequisites

- Clean Python 3.11+ virtualenv
- All automated tests passing: `pytest tests/ -v` from project root
- Access to target RHEL host for AC4.2 runtime verification
- `pipeline/scripts/ensure_registry.sh` present
- `pipeline/config.json` present with valid configuration

## Phase 1: Package Installation and Entrypoint (AC4.3)

| Step | Action | Expected |
|------|--------|----------|
| 1.1 | `python -m venv /tmp/qa-registry-test && source /tmp/qa-registry-test/bin/activate` | Clean virtualenv created and activated |
| 1.2 | `pip install -e ".[registry,dev]"` from project root | Exit code 0, no errors in output |
| 1.3 | `python -c "import pipeline"` | No ImportError |
| 1.4 | `which registry-api` | Path printed, confirming entrypoint is on PATH |
| 1.5 | `python -c "from pipeline.registry_api.main import app; print(type(app))"` | Prints FastAPI/Starlette app type, no ImportError |
| 1.6 | `registry-api` (run with no args) | Process starts without crashing |

## Phase 2: Shell Script Syntax Check (AC4.2 — automated portion)

| Step | Action | Expected |
|------|--------|----------|
| 2.1 | `bash -n pipeline/scripts/ensure_registry.sh` | Exit code 0, no syntax errors |

## Phase 3: Shell Script Runtime Behaviour (AC4.2 — manual, target RHEL host)

| Step | Action | Expected |
|------|--------|----------|
| 3.1 | On target RHEL host, run `./pipeline/scripts/ensure_registry.sh` | Registry process starts, PID file created at expected location |
| 3.2 | Confirm PID file contents: `cat <pid_file_path>` and `ps -p $(cat <pid_file_path>)` | PID in file matches running `registry-api` process |
| 3.3 | Kill the process: `kill $(cat <pid_file_path>)`, then re-run `./pipeline/scripts/ensure_registry.sh` | Script detects dead process, restarts registry, writes new PID to file |
| 3.4 | Verify new PID: `ps -p $(cat <pid_file_path>)` | New PID is alive and different from the killed one |
| 3.5 | With registry still running, re-run `./pipeline/scripts/ensure_registry.sh` | Script exits cleanly with no action (process already alive) |
| 3.6 | Check script output/logs for any error messages during steps 3.1-3.5 | No unexpected errors or warnings |

## Phase 4: End-to-End API Walkthrough

**Purpose:** Verify the full delivery lifecycle through the live API (not test client), confirming routes, DB persistence, and filtering work together in a real server context.

| Step | Action | Expected |
|------|--------|----------|
| 4.1 | Start the registry API: `registry-api` (or via `ensure_registry.sh`) | Server starts on configured host/port (default `0.0.0.0:8000`) |
| 4.2 | `curl http://localhost:8000/health` | `{"status": "ok"}` with HTTP 200 |
| 4.3 | POST a new delivery: `curl -X POST http://localhost:8000/deliveries -H "Content-Type: application/json" -d '{"request_id":"req-manual-1","project":"manual-test","request_type":"scan","workplan_id":"wp-m1","dp_id":"dp-m1","version":"v01","scan_root":"/data/manual","qa_status":"pending","source_path":"/data/manual/delivery-1"}'` | HTTP 200, response includes server-computed `delivery_id` (64-char hex), `first_seen_at` populated |
| 4.4 | Note the `delivery_id` from 4.3. GET it: `curl http://localhost:8000/deliveries/<delivery_id>` | HTTP 200, all fields match what was POSTed |
| 4.5 | POST again with same `source_path` but `qa_status: "passed"` | Same `delivery_id`, same `first_seen_at`, `qa_status` now `"passed"` |
| 4.6 | PATCH with partial update: `curl -X PATCH http://localhost:8000/deliveries/<delivery_id> -H "Content-Type: application/json" -d '{"output_path":"/output/manual"}'` | HTTP 200, `output_path` updated, all other fields unchanged |
| 4.7 | `curl http://localhost:8000/deliveries/actionable` | Returns the delivery from 4.5 (passed, not yet converted) |
| 4.8 | PATCH to mark as converted: `curl -X PATCH http://localhost:8000/deliveries/<delivery_id> -H "Content-Type: application/json" -d '{"parquet_converted_at":"2026-04-09T12:00:00+00:00"}'` | HTTP 200, `parquet_converted_at` set |
| 4.9 | `curl http://localhost:8000/deliveries/actionable` | Empty list `[]` — delivery no longer actionable |
| 4.10 | Test 404: `curl http://localhost:8000/deliveries/does-not-exist-abc123` | HTTP 404 |
| 4.11 | Test 422: `curl -X POST http://localhost:8000/deliveries -H "Content-Type: application/json" -d '{"project":"oops"}'` | HTTP 422 (missing required fields) |

## Human Verification Required

| Criterion | Why Manual | Steps |
|-----------|-----------|-------|
| qa-registry.AC4.2 | Syntax check is automatable (`bash -n`), but runtime behaviour (PID management, restart, idempotent no-op) requires a live environment | Phase 2 (syntax) + Phase 3 steps 3.1-3.6 (runtime on RHEL host) |
| qa-registry.AC4.3 | Editable install with optional dependency groups is environment-dependent | Phase 1 steps 1.1-1.6 in a clean virtualenv, repeat on target RHEL host |

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| qa-registry.AC1.1 | test_routes.py::test_create_delivery_success | 4.3 |
| qa-registry.AC1.2 | test_routes.py::test_upsert_preserves_first_seen_at | 4.5 |
| qa-registry.AC1.3 | test_routes.py::test_get_delivery_exists | 4.4 |
| qa-registry.AC1.4 | test_routes.py::test_get_delivery_not_found | 4.10 |
| qa-registry.AC1.5 | test_routes.py::test_update_delivery_partial | 4.6 |
| qa-registry.AC1.6 | test_routes.py::test_update_delivery_not_found | 4.10 |
| qa-registry.AC1.7 | test_routes.py::test_health_returns_ok | 4.2 |
| qa-registry.AC1.8 | test_routes.py::test_actionable_returns_passed_unconverted | 4.7, 4.9 |
| qa-registry.AC2.1 | test_db.py::test_upsert_delivery_creates_delivery_with_all_fields | — |
| qa-registry.AC2.2 | test_db.py::test_upsert_delivery_preserves_first_seen_at_on_reinsert | — |
| qa-registry.AC2.3 | test_db.py::test_upsert_delivery_bumps_last_updated_at_when_fingerprint_changes | — |
| qa-registry.AC2.4 | test_db.py::test_upsert_delivery_does_not_bump_last_updated_at_when_fingerprint_unchanged | — |
| qa-registry.AC2.5 | test_db.py::8 filter tests | — |
| qa-registry.AC2.6 | test_db.py::test_list_deliveries_version_latest | — |
| qa-registry.AC2.7 | test_db.py::test_list_deliveries_multiple_filters_and_semantics | — |
| qa-registry.AC2.8 | test_db.py::test_list_deliveries_empty_filters_returns_all | — |
| qa-registry.AC3.1 | test_models.py + test_routes.py | 4.11 |
| qa-registry.AC3.2 | test_models.py + test_routes.py | — |
| qa-registry.AC3.3 | test_routes.py::test_update_delivery_empty_body_noop | — |
| qa-registry.AC3.4 | test_db.py + test_routes.py | 4.3, 4.5 |
| qa-registry.AC4.1 | test_config.py (2 tests) | — |
| qa-registry.AC4.2 | — | Phase 2 + Phase 3 |
| qa-registry.AC4.3 | — | Phase 1 |
