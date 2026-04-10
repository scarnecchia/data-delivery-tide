# Test Requirements: Registry Auth

## Automated Test Coverage

### registry-auth.AC1: API rejects unauthenticated requests

| AC | Description | Test Type | Test File | Test Method |
|----|-------------|-----------|-----------|-------------|
| AC1.1 | Request with valid bearer token returns expected response | unit | tests/registry_api/test_auth.py | TestRequireAuth::test_valid_token_returns_200 |
| AC1.2 | Request with no Authorization header returns 401 | unit | tests/registry_api/test_auth.py | TestRequireAuth::test_missing_auth_header_returns_401 |
| AC1.3 | Request with malformed Authorization header returns 401 | unit | tests/registry_api/test_auth.py | TestRequireAuth::test_malformed_auth_header_returns_401 |
| AC1.4 | Request with revoked token returns 401 | unit | tests/registry_api/test_auth.py | TestRequireAuth::test_revoked_token_returns_401 |
| AC1.5 | Request with non-existent token returns 401 | unit | tests/registry_api/test_auth.py | TestRequireAuth::test_nonexistent_token_returns_401 |
| AC1.6 | /health returns 200 with no Authorization header | integration | tests/registry_api/test_routes.py | TestHealthNoAuth::test_health_no_auth_header_returns_200 |

### registry-auth.AC2: Role hierarchy enforced on endpoints

| AC | Description | Test Type | Test File | Test Method |
|----|-------------|-----------|-----------|-------------|
| AC2.1 | Admin token can access all endpoints | unit | tests/registry_api/test_auth.py | TestRequireRole::test_admin_token_on_write_endpoint_returns_200 |
| AC2.1 | Admin token can access admin-protected endpoints | unit | tests/registry_api/test_auth.py | TestRequireRole::test_admin_token_on_admin_endpoint_returns_200 |
| AC2.2 | Write token can POST and PATCH deliveries | unit | tests/registry_api/test_auth.py | TestRequireRole::test_write_token_on_write_endpoint_returns_200 |
| AC2.2 | Write token can POST and PATCH deliveries (route-level) | integration | tests/registry_api/test_routes.py | TestCreateDelivery (all methods with auth_headers) |
| AC2.3 | Write token can GET deliveries (route-level) | integration | tests/registry_api/test_routes.py | TestListDeliveries (all methods with auth_headers) |
| AC2.4 | Read token can GET deliveries | unit | tests/registry_api/test_auth.py | TestRequireRole::test_read_token_on_read_endpoint_returns_200 |
| AC2.4 | Read token can GET deliveries (route-level) | integration | tests/registry_api/test_routes.py | TestAuthEnforcement::test_read_token_can_get_deliveries |
| AC2.5 | Read token on POST /deliveries returns 403 | unit | tests/registry_api/test_auth.py | TestRequireRole::test_read_token_on_write_endpoint_returns_403 |
| AC2.5 | Read token on POST /deliveries returns 403 (route-level) | integration | tests/registry_api/test_routes.py | TestAuthEnforcement::test_read_token_cannot_post_deliveries |
| AC2.6 | Read token on PATCH /deliveries/{id} returns 403 (route-level) | integration | tests/registry_api/test_routes.py | TestAuthEnforcement::test_read_token_cannot_patch_deliveries |

### registry-auth.AC3: CLI add-user creates token

| AC | Description | Test Type | Test File | Test Method |
|----|-------------|-----------|-----------|-------------|
| AC3.1 | add-user prints token to stdout and stores hash in DB | unit | tests/test_auth_cli.py | TestAddUser::test_add_user_prints_token_and_stores_hash |
| AC3.2 | add-user with --role sets correct role | unit | tests/test_auth_cli.py | TestAddUser::test_add_user_with_role_sets_correct_role |
| AC3.3 | add-user defaults to read role | unit | tests/test_auth_cli.py | TestAddUser::test_add_user_defaults_to_read_role |
| AC3.4 | add-user with existing active username errors | unit | tests/test_auth_cli.py | TestAddUser::test_add_user_existing_active_username_errors |

### registry-auth.AC4: CLI token lifecycle operations

| AC | Description | Test Type | Test File | Test Method |
|----|-------------|-----------|-----------|-------------|
| AC4.1 | list-users shows all users with role and status | unit | tests/test_auth_cli.py | TestListUsers::test_list_users_shows_all_users |
| AC4.2 | revoke-user sets revoked_at on the token | unit | tests/test_auth_cli.py | TestRevokeUser::test_revoke_user_sets_revoked_at |
| AC4.3 | revoke-user on already-revoked user is idempotent | unit | tests/test_auth_cli.py | TestRevokeUser::test_revoke_user_idempotent |
| AC4.4 | rotate-token revokes old token and creates new one | unit | tests/test_auth_cli.py | TestRotateToken::test_rotate_token_creates_new_token |
| AC4.5 | rotate-token prints new token to stdout | unit | tests/test_auth_cli.py | TestRotateToken::test_rotate_token_prints_new_token |
| AC4.6 | Old token rejected by API after rotation | unit | tests/test_auth_cli.py | TestRotateToken::test_rotate_token_old_token_invalid |

### registry-auth.AC5: Token storage security

| AC | Description | Test Type | Test File | Test Method |
|----|-------------|-----------|-----------|-------------|
| AC5.1 | Raw token is never stored in database (only SHA-256 hash) | unit | tests/registry_api/test_auth.py | TestRequireAuth::test_token_stored_as_hash_not_raw |
| AC5.1 | Lookup is by hash, not raw token (db layer) | unit | tests/registry_api/test_db.py | TestGetTokenByHash::test_get_token_by_hash_returns_existing_token |
| AC5.2 | Token is generated with secrets.token_urlsafe(32) | unit | tests/test_auth_cli.py | TestAddUser::test_add_user_token_is_urlsafe |

## Supplementary Tests (not mapped to ACs)

These tests verify infrastructure or edge cases that support the acceptance criteria without mapping directly to one.

| Description | Test Type | Test File | Test Method |
|-------------|-----------|-----------|-------------|
| init_db creates tokens table | unit | tests/registry_api/test_db.py | TestTokensTable::test_init_db_creates_tokens_table |
| Tokens table has expected columns | unit | tests/registry_api/test_db.py | TestTokensTable::test_tokens_table_has_expected_columns |
| Tokens table rejects invalid role values | unit | tests/registry_api/test_db.py | TestTokensTable::test_tokens_table_role_check_constraint |
| Tokens table enforces unique username | unit | tests/registry_api/test_db.py | TestTokensTable::test_tokens_table_username_unique_constraint |
| get_token_by_hash returns None for nonexistent hash | unit | tests/registry_api/test_db.py | TestGetTokenByHash::test_get_token_by_hash_returns_none_for_nonexistent |
| get_token_by_hash returns revoked tokens (caller filters) | unit | tests/registry_api/test_db.py | TestGetTokenByHash::test_get_token_by_hash_returns_revoked_tokens |
| Write token cannot access admin-protected endpoints | unit | tests/registry_api/test_auth.py | TestRequireRole::test_write_token_on_admin_endpoint_returns_403 |
| GET /deliveries without auth returns 401 | integration | tests/registry_api/test_routes.py | TestAuthEnforcement::test_get_deliveries_no_auth_returns_401 |
| POST /deliveries without auth returns 401 | integration | tests/registry_api/test_routes.py | TestAuthEnforcement::test_post_deliveries_no_auth_returns_401 |
| PATCH /deliveries/{id} without auth returns 401 | integration | tests/registry_api/test_routes.py | TestAuthEnforcement::test_patch_delivery_no_auth_returns_401 |
| GET /deliveries/actionable without auth returns 401 | integration | tests/registry_api/test_routes.py | TestAuthEnforcement::test_get_actionable_no_auth_returns_401 |
| add-user succeeds for previously revoked username | unit | tests/test_auth_cli.py | TestAddUser::test_add_user_reuses_revoked_username |
| list-users shows revoked status | unit | tests/test_auth_cli.py | TestListUsers::test_list_users_shows_revoked_status |
| list-users with no users prints message | unit | tests/test_auth_cli.py | TestListUsers::test_list_users_empty |
| revoke-user for nonexistent user returns error | unit | tests/test_auth_cli.py | TestRevokeUser::test_revoke_user_nonexistent_errors |
| rotate-token for nonexistent user returns error | unit | tests/test_auth_cli.py | TestRotateToken::test_rotate_token_nonexistent_errors |

## Human Verification

### AC3.3: Default role argument

The automated test (`TestAddUser::test_add_user_defaults_to_read_role`) verifies the command function works when `role="read"` is passed. However, the argparse `default="read"` on the `--role` argument is only exercised by invoking the CLI entrypoint without `--role`. This is covered implicitly by the argparse definition in `auth_cli.py` but is not tested via subprocess invocation.

**Verification approach:** After deployment, manually run `registry-auth add-user testdefault` and confirm the output token has role `read` via `registry-auth list-users`.

### AC4.6: Old token rejected by API after rotation (full integration)

The unit test (`TestRotateToken::test_rotate_token_old_token_invalid`) verifies the old hash no longer exists in the database after rotation. Phase 3, Task 4 calls for a full end-to-end verification that a rotated token is actually rejected by the running API. This requires the API and CLI operating against the same database, which is not covered by the isolated unit tests.

**Verification approach:** After deployment, run `registry-auth add-user e2e-test --role write`, use the token against the API, then `registry-auth rotate-token e2e-test`, and confirm the old token returns 401 while the new token returns 200.
