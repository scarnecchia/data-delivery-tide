# Human Test Plan: Registry Auth

Generated from implementation plan: `docs/implementation-plans/2026-04-10-registry-auth/`

## Prerequisites

- Registry API deployed and accessible (e.g., `http://localhost:8000`)
- `registry-auth` CLI entrypoint installed and on PATH
- Both CLI and API pointing at the same SQLite database (verify via `PIPELINE_CONFIG` or default `pipeline/config.json`)
- Package installed in the environment: `pip install -e ".[registry,dev]"`
- All automated tests passing: `pytest` (206 passed)

## Phase 1: CLI Default Role Verification

Purpose: Verify that argparse `default="read"` on `--role` is exercised end-to-end via the actual CLI entrypoint, not just the underlying function.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Run `registry-auth add-user testdefault` (no `--role` flag) | Prints a raw token to stdout, exits 0 |
| 2 | Run `registry-auth list-users` | Output shows `testdefault` with role `read` and status `active` |
| 3 | Cleanup: `registry-auth revoke-user testdefault` | Exits 0, confirms revocation |

## Phase 2: Full Token Rotation Integration

Purpose: Verify that a rotated token is rejected by the live API and the new token works. The unit test only checks the DB; this confirms the API auth middleware honours the change.

| Step | Action | Expected |
|------|--------|----------|
| 1 | Run `registry-auth add-user e2e-rotate --role write` | Prints token (save as `$OLD_TOKEN`) |
| 2 | `curl -H "Authorization: Bearer $OLD_TOKEN" http://localhost:8000/deliveries` | Returns 200 with JSON array |
| 3 | Run `registry-auth rotate-token e2e-rotate` | Prints new token (save as `$NEW_TOKEN`), exits 0 |
| 4 | `curl -H "Authorization: Bearer $OLD_TOKEN" http://localhost:8000/deliveries` | Returns 401 |
| 5 | `curl -H "Authorization: Bearer $NEW_TOKEN" http://localhost:8000/deliveries` | Returns 200 |
| 6 | Cleanup: `registry-auth revoke-user e2e-rotate` | Exits 0 |

## Phase 3: Role Hierarchy End-to-End

Purpose: Confirm role enforcement works through the actual FastAPI app with real HTTP, not just TestClient.

| Step | Action | Expected |
|------|--------|----------|
| 1 | `registry-auth add-user e2e-reader --role read` | Save token as `$READ_TOKEN` |
| 2 | `registry-auth add-user e2e-writer --role write` | Save token as `$WRITE_TOKEN` |
| 3 | `curl -H "Authorization: Bearer $WRITE_TOKEN" -X POST -H "Content-Type: application/json" -d '{"source_path":"/e2e/test","request_id":"req-e2e","project":"proj-e2e","request_type":"scan","workplan_id":"wp-e2e","dp_id":"dp-e2e","version":"1.0","scan_root":"/scan","qa_status":"pending"}' http://localhost:8000/deliveries` | Returns 200 with delivery JSON |
| 4 | `curl -H "Authorization: Bearer $READ_TOKEN" http://localhost:8000/deliveries` | Returns 200 with the delivery created in step 3 |
| 5 | `curl -H "Authorization: Bearer $READ_TOKEN" -X POST -H "Content-Type: application/json" -d '{"source_path":"/e2e/blocked","request_id":"req-x","project":"p","request_type":"scan","workplan_id":"wp","dp_id":"dp","version":"1","scan_root":"/s","qa_status":"pending"}' http://localhost:8000/deliveries` | Returns 403 |
| 6 | Note the `delivery_id` from step 3. `curl -H "Authorization: Bearer $READ_TOKEN" -X PATCH -H "Content-Type: application/json" -d '{"qa_status":"passed"}' http://localhost:8000/deliveries/$DELIVERY_ID` | Returns 403 |
| 7 | Cleanup: revoke both users | Exits 0 |

## Phase 4: Health Endpoint Accessibility

Purpose: Confirm /health is not behind auth on a live deployment (load balancer health checks depend on this).

| Step | Action | Expected |
|------|--------|----------|
| 1 | `curl http://localhost:8000/health` (no Authorization header) | Returns 200, body `{"status":"ok"}` |
| 2 | `curl -H "Authorization: Bearer garbage" http://localhost:8000/health` | Still returns 200 (health is exempt from auth) |

## End-to-End: Full Lifecycle

Purpose: Validate the complete user lifecycle -- creation through revocation -- works as a coherent flow against the live system.

| Step | Action | Expected |
|------|--------|----------|
| 1 | `registry-auth add-user lifecycle-test --role write` | Prints token, exits 0 |
| 2 | Use token to POST a delivery via API | 200 |
| 3 | Use token to GET /deliveries | 200, includes the delivery |
| 4 | Use token to PATCH the delivery (set qa_status to passed) | 200 |
| 5 | `registry-auth list-users` | Shows `lifecycle-test`, role `write`, status `active` |
| 6 | `registry-auth revoke-user lifecycle-test` | Exits 0 |
| 7 | Use same token to GET /deliveries | 401 |
| 8 | `registry-auth list-users` | Shows `lifecycle-test`, status `revoked` |
| 9 | `registry-auth add-user lifecycle-test --role read` | Succeeds (reuses revoked username), prints new token |
| 10 | Use new token to GET /deliveries | 200 |
| 11 | Use new token to POST a delivery | 403 (read role cannot write) |

## Human Verification Required

| Criterion | Why Manual | Steps |
|-----------|------------|-------|
| AC3.3: Default role argument | The unit test passes `role="read"` explicitly to the function. The argparse `default="read"` on `--role` is only exercised by invoking the real CLI without the flag. | Phase 1 above |
| AC4.6: Old token rejected by API after rotation | The unit test verifies the old hash is gone from the DB. Full integration requires the API and CLI operating against the same database simultaneously. | Phase 2 above |

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| AC1.1 Valid token returns 200 | `test_auth.py::TestRequireAuth::test_valid_token_returns_200` | Phase 3 steps 3-4 |
| AC1.2 Missing auth returns 401 | `test_auth.py::TestRequireAuth::test_missing_auth_header_returns_401` | Phase 4 step 1 (inverse) |
| AC1.3 Malformed auth returns 401 | `test_auth.py::TestRequireAuth::test_malformed_auth_header_returns_401` | -- |
| AC1.4 Revoked token returns 401 | `test_auth.py::TestRequireAuth::test_revoked_token_returns_401` | E2E step 7 |
| AC1.5 Non-existent token returns 401 | `test_auth.py::TestRequireAuth::test_nonexistent_token_returns_401` | -- |
| AC1.6 /health no auth | `test_routes.py::TestHealthNoAuth::test_health_no_auth_header_returns_200` | Phase 4 steps 1-2 |
| AC2.1 Admin access | `test_auth.py::TestRequireRole::test_admin_*` (2 tests) | -- |
| AC2.2 Write token POST/PATCH | `test_auth.py` + `test_routes.py` (multiple) | Phase 3 step 3 |
| AC2.3 Write token GET | `test_routes.py::TestListDeliveries` | -- |
| AC2.4 Read token GET | `test_auth.py` + `test_routes.py` | Phase 3 step 4 |
| AC2.5 Read token POST 403 | `test_auth.py` + `test_routes.py` | Phase 3 step 5 |
| AC2.6 Read token PATCH 403 | `test_routes.py::TestAuthEnforcement` | Phase 3 step 6 |
| AC3.1 add-user prints token, stores hash | `test_auth_cli.py::TestAddUser` | E2E step 1 |
| AC3.2 add-user --role | `test_auth_cli.py::TestAddUser` | -- |
| AC3.3 add-user defaults to read | `test_auth_cli.py::TestAddUser` | **Phase 1** |
| AC3.4 Duplicate username errors | `test_auth_cli.py::TestAddUser` | -- |
| AC4.1 list-users shows all | `test_auth_cli.py::TestListUsers` | E2E steps 5, 8 |
| AC4.2 revoke-user sets revoked_at | `test_auth_cli.py::TestRevokeUser` | E2E step 6 |
| AC4.3 revoke-user idempotent | `test_auth_cli.py::TestRevokeUser` | -- |
| AC4.4 rotate-token creates new | `test_auth_cli.py::TestRotateToken` | Phase 2 step 3 |
| AC4.5 rotate-token prints token | `test_auth_cli.py::TestRotateToken` | Phase 2 step 3 |
| AC4.6 Old token rejected after rotation | `test_auth_cli.py::TestRotateToken` | **Phase 2** |
| AC5.1 Hash-only storage | `test_auth.py` + `test_db.py` | -- |
| AC5.2 secrets.token_urlsafe(32) | `test_auth_cli.py::TestAddUser` | -- |
