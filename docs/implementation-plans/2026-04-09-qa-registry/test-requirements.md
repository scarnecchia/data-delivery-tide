# QA Registry Test Requirements

## Automated Tests

| AC ID | Description | Test Type | Expected Test File | Phase |
|-------|-------------|-----------|-------------------|-------|
| qa-registry.AC1.1 | POST /deliveries creates a new delivery and returns it with server-computed delivery_id | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC1.2 | POST /deliveries with same source_path upserts (updates fields, preserves first_seen_at) | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC1.3 | GET /deliveries/{delivery_id} returns the delivery | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC1.4 | GET /deliveries/{delivery_id} returns 404 for nonexistent ID | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC1.5 | PATCH /deliveries/{delivery_id} updates only provided fields | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC1.6 | PATCH /deliveries/{delivery_id} returns 404 for nonexistent ID | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC1.7 | GET /health returns {"status": "ok"} | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC1.8 | GET /deliveries/actionable returns only deliveries with qa_status=passed and parquet_converted_at IS NULL | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC2.1 | Upsert creates delivery with all metadata fields populated | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC2.2 | Upsert preserves first_seen_at when re-inserting existing delivery | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC2.3 | Upsert bumps last_updated_at when fingerprint changes | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC2.4 | Upsert does NOT bump last_updated_at when fingerprint is unchanged | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC2.5 | list_deliveries filters by each supported query param (dp_id, project, request_type, workplan_id, request_id, qa_status, converted, scan_root) | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC2.6 | version=latest returns highest version per (dp_id, workplan_id) | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC2.7 | Multiple filters combine with AND semantics | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC2.8 | Empty filter set returns all deliveries | unit | tests/registry_api/test_db.py | 3 |
| qa-registry.AC3.1 | POST /deliveries with missing required fields returns 422 | unit + integration | tests/registry_api/test_models.py, tests/registry_api/test_routes.py | 4, 5 |
| qa-registry.AC3.2 | POST /deliveries with invalid qa_status value returns 422 | unit + integration | tests/registry_api/test_models.py, tests/registry_api/test_routes.py | 4, 5 |
| qa-registry.AC3.3 | PATCH /deliveries/{delivery_id} with empty body is a no-op (not an error) | integration | tests/registry_api/test_routes.py | 5 |
| qa-registry.AC3.4 | delivery_id is deterministic -- same source_path always produces same ID | unit + integration | tests/registry_api/test_db.py, tests/registry_api/test_routes.py | 3, 5 |
| qa-registry.AC4.1 | Config loads from PIPELINE_CONFIG env var, falls back to pipeline/config.json | unit | tests/test_config.py | 2 |

## Human Verification

| AC ID | Description | Why Not Automated | Verification Approach |
|-------|-------------|-------------------|----------------------|
| qa-registry.AC4.2 | ensure_registry.sh is syntactically valid bash | Partially automatable -- syntax check is automated via `bash -n`, but runtime behaviour (PID management, process restart, log rotation) requires a live environment with the registry-api entrypoint installed and a running process to kill/restart. | Run `bash -n pipeline/scripts/ensure_registry.sh` in CI to verify syntax. Manually verify on target RHEL host: (1) start registry via the script, confirm PID file created, (2) kill the process, re-run script, confirm it restarts and writes new PID, (3) run script while process is alive, confirm it exits cleanly with no action. |
| qa-registry.AC4.3 | pip install -e ".[registry,dev]" installs all dependencies and registry-api entrypoint is available | Environment-dependent -- depends on Python version, pip version, and system state. Editable installs with optional dependency groups can behave differently across platforms and virtualenv configurations. | Run in a clean virtualenv: (1) `python -m venv .venv && source .venv/bin/activate`, (2) `pip install -e ".[registry,dev]"` -- confirm exit code 0, (3) `python -c "import pipeline"` -- confirm no ImportError, (4) `which registry-api` -- confirm entrypoint exists on PATH, (5) `python -c "from pipeline.registry_api.main import app"` -- confirm app object loads. Repeat on target RHEL host if CI environment differs. |
