# Registry API Authentication Design

## Summary

The registry API currently has no authentication — any client that can reach the endpoint can read or write delivery records. This document describes adding token-based bearer authentication to lock that down. The approach is intentionally minimal: no OAuth, no login endpoints, no session management. An admin runs a CLI tool (`registry-auth`) directly on the server to pre-issue tokens, which are then included in API requests via the standard `Authorization: Bearer` header. Three roles — `read`, `write`, and `admin` — control what each token can do, and the API enforces those roles at the route level using FastAPI's dependency injection system.

The design stays entirely within the Python standard library for auth and CLI concerns, adds a single `tokens` table to the existing SQLite database, and follows patterns already established in the codebase (dependency injection via `Depends()`, Pydantic models, console scripts). Tokens are generated with `secrets.token_urlsafe`, displayed once on creation, and stored only as SHA-256 hashes — the raw token is never persisted. Revocation is a soft delete (timestamp, not row deletion) to preserve audit trail. The implementation is broken into three sequential phases: token storage and auth logic, route protection, then the CLI tool.

## Definition of Done

- All API endpoints except /health require a valid bearer token
- Three access tiers enforced: admin (token management), write (POST/PATCH deliveries), read (GET deliveries)
- CLI tool (`registry-auth`) manages tokens via direct SQLite access on the server
- Tokens are high-entropy random strings, hashed with SHA-256 at rest
- One active token per username (UNIQUE constraint)
- Existing tests continue to pass; new tests cover auth enforcement and CLI operations
- No new external dependencies (stdlib only for auth and CLI)

## Acceptance Criteria

### registry-auth.AC1: API rejects unauthenticated requests
- **registry-auth.AC1.1 Success:** Request with valid bearer token returns expected response
- **registry-auth.AC1.2 Failure:** Request with no Authorization header returns 401
- **registry-auth.AC1.3 Failure:** Request with malformed Authorization header returns 401
- **registry-auth.AC1.4 Failure:** Request with revoked token returns 401
- **registry-auth.AC1.5 Failure:** Request with non-existent token returns 401
- **registry-auth.AC1.6 Success:** /health returns 200 with no Authorization header

### registry-auth.AC2: Role hierarchy enforced on endpoints
- **registry-auth.AC2.1 Success:** Admin token can access all endpoints
- **registry-auth.AC2.2 Success:** Write token can POST and PATCH deliveries
- **registry-auth.AC2.3 Success:** Write token can GET deliveries
- **registry-auth.AC2.4 Success:** Read token can GET deliveries
- **registry-auth.AC2.5 Failure:** Read token on POST /deliveries returns 403
- **registry-auth.AC2.6 Failure:** Read token on PATCH /deliveries/{id} returns 403

### registry-auth.AC3: CLI add-user creates token
- **registry-auth.AC3.1 Success:** add-user prints token to stdout and stores hash in DB
- **registry-auth.AC3.2 Success:** add-user with --role sets correct role
- **registry-auth.AC3.3 Success:** add-user defaults to read role
- **registry-auth.AC3.4 Failure:** add-user with existing active username errors

### registry-auth.AC4: CLI token lifecycle operations
- **registry-auth.AC4.1 Success:** list-users shows all users with role and status
- **registry-auth.AC4.2 Success:** revoke-user sets revoked_at on the token
- **registry-auth.AC4.3 Success:** revoke-user on already-revoked user is idempotent (no error)
- **registry-auth.AC4.4 Success:** rotate-token revokes old token and creates new one
- **registry-auth.AC4.5 Success:** rotate-token prints new token to stdout
- **registry-auth.AC4.6 Failure:** Old token rejected by API after rotation

### registry-auth.AC5: Token storage security
- **registry-auth.AC5.1:** Raw token is never stored in database (only SHA-256 hash)
- **registry-auth.AC5.2:** Token is generated with secrets.token_urlsafe(32)

## Glossary

- **Bearer token**: An opaque credential sent in the `Authorization: Bearer <token>` HTTP header. Possession of the string is sufficient proof of identity — no signature or challenge involved.
- **SHA-256**: A cryptographic hash function. Used here to store a one-way fingerprint of the token rather than the token itself, so a database breach doesn't expose usable credentials.
- **Soft delete**: Marking a record as inactive (setting `revoked_at`) rather than removing the row. Preserves history for auditing.
- **Role hierarchy**: A ranked ordering of access levels (`read < write < admin`) where higher roles inherit the permissions of lower ones.
- **Router-level dependency**: A FastAPI pattern where a dependency is applied to an entire router (group of routes) rather than individual endpoints. Used here to apply `require_auth` to all `/deliveries` routes at once.
- **`secrets.token_urlsafe`**: Python stdlib function that generates a cryptographically secure random string safe for use in URLs. `token_urlsafe(32)` produces 43 characters of entropy.
- **Console script**: A Python package entry point that installs a named command-line executable (e.g., `registry-auth`) when the package is installed.
- **Idempotent**: An operation that produces the same result whether run once or multiple times. `revoke-user` on an already-revoked user is a no-op rather than an error.

## Architecture

Token-based bearer authentication for the registry API. Tokens are pre-issued via a CLI tool by an admin user, not through login endpoints or OAuth flows.

**Auth flow:** Client sends `Authorization: Bearer <token>` header. API hashes the token with SHA-256, looks up the hash in the `tokens` table, checks it's not revoked, and extracts the role. Role is compared against the endpoint's minimum requirement.

**Two routers:** `main.py` mounts a public router (`/health`) and a protected router (all `/deliveries` endpoints). The protected router has a router-level `require_auth` dependency that runs on every request. POST and PATCH endpoints add an explicit `require_role("write")` dependency.

**CLI tool:** `registry-auth` console script uses argparse and talks directly to SQLite. No API round-trip, no bootstrap chicken-and-egg. If you can SSH to the box and run the command, you can manage tokens. The first `add-user --role admin` bootstraps the system.

**Token lifecycle:** `secrets.token_urlsafe(32)` generates a 43-character token. Displayed once on creation. Stored as SHA-256 hash. Revocation sets `revoked_at` timestamp (soft delete for audit trail). Rotation revokes old + creates new atomically.

### Data Model

**`tokens` table** (added to `init_db` alongside `deliveries`):

| Column | Type | Constraints |
|--------|------|-------------|
| `token_hash` | TEXT | PRIMARY KEY |
| `username` | TEXT | NOT NULL, UNIQUE |
| `role` | TEXT | NOT NULL, CHECK IN ('admin', 'write', 'read') |
| `created_at` | TEXT | NOT NULL (ISO 8601 UTC) |
| `revoked_at` | TEXT | NULL = active |

Username UNIQUE constraint means one active token per user. The `revoked_at` soft delete preserves audit trail while the UNIQUE constraint applies only to the non-revoked row pattern — handled by revoking (updating) the existing row before inserting a new one during rotation.

### Auth Dependency Chain

```python
# Contract — not implementation
class TokenInfo(BaseModel):
    username: str
    role: Literal["admin", "write", "read"]

def require_auth(credentials: HTTPAuthorizationCredentials) -> TokenInfo
    # Hash token, look up in DB, reject if missing/revoked
    # Returns TokenInfo on success, raises 401 on failure

def require_role(minimum: str) -> Depends
    # Wraps require_auth, enforces role hierarchy: admin > write > read
    # Raises 403 if role insufficient
```

### Route Protection

| Endpoint | Auth | Minimum Role |
|----------|------|-------------|
| `GET /health` | none | — |
| `GET /deliveries` | required | read |
| `GET /deliveries/actionable` | required | read |
| `GET /deliveries/{id}` | required | read |
| `POST /deliveries` | required | write |
| `PATCH /deliveries/{id}` | required | write |

### CLI Contract

**Entrypoint:** `registry-auth` console script -> `pipeline.auth_cli:main`

| Subcommand | Arguments | Behaviour |
|------------|-----------|-----------|
| `add-user` | `username`, `--role` (default: read) | Create token, print once. Error if username already active. |
| `list-users` | — | Print table: username, role, created_at, revoked status |
| `revoke-user` | `username` | Set `revoked_at`. Idempotent. |
| `rotate-token` | `username` | Revoke old, create new, print new token. |

## Existing Patterns

Investigation found no existing authentication in the codebase. This design introduces auth as a new concern but follows established patterns:

- **Dependency injection via `Depends()`**: matches existing `DbDep` pattern in `db.py:116`
- **SQLite table in `init_db`**: tokens table added alongside deliveries using the same `CREATE TABLE IF NOT EXISTS` pattern
- **Per-request connections**: auth lookup uses the same `get_db()` dependency, no new connection management
- **Pydantic models**: `TokenInfo` follows existing model conventions in `models.py`
- **Console scripts in pyproject.toml**: `registry-auth` added alongside existing `registry-api`
- **Config access via `pipeline.config.settings`**: CLI reads `db_path` the same way the API does

New pattern introduced: **router-level dependency injection** (protected router with `require_auth`). The existing code uses a single router. This design splits into public + protected routers, which is a standard FastAPI pattern but new to this codebase.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Token Storage and Auth Dependencies

**Goal:** Add tokens table to the database and implement the auth dependency chain (require_auth, require_role).

**Components:**
- `src/pipeline/registry_api/db.py` — add tokens table to `init_db`, add `get_token_by_hash()` query function
- `src/pipeline/registry_api/auth.py` — new file: `TokenInfo` model, `require_auth` dependency, `require_role` dependency factory
- `src/pipeline/registry_api/models.py` — add `TokenInfo` if shared beyond auth module

**Dependencies:** None (first phase)

**Done when:** Auth dependencies can validate a token against the database, enforce role hierarchy, and return 401/403 appropriately. Tests cover valid token, revoked token, missing token, and insufficient role scenarios.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: API Route Protection

**Goal:** Wire auth into the API by splitting routers and protecting delivery endpoints.

**Components:**
- `src/pipeline/registry_api/main.py` — split into public router (/health) and protected router (all /deliveries), protected router gets `require_auth` as router-level dependency
- `src/pipeline/registry_api/routes.py` — add `Depends(require_role("write"))` to POST and PATCH endpoints
- `tests/` — update existing delivery route tests to include bearer tokens, add tests for unauthenticated access (401) and insufficient role (403)

**Dependencies:** Phase 1 (auth dependencies must exist)

**Done when:** /health is accessible without auth. All /deliveries endpoints require valid bearer token. POST and PATCH require write or admin role. GET requires read or higher. Existing tests updated and passing with tokens.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: CLI Token Management

**Goal:** Implement the `registry-auth` CLI tool for token lifecycle management.

**Components:**
- `src/pipeline/auth_cli.py` — new file: argparse CLI with add-user, list-users, revoke-user, rotate-token subcommands, direct SQLite access
- `pyproject.toml` — add `registry-auth = "pipeline.auth_cli:main"` to `[project.scripts]`
- `tests/` — CLI tests covering add-user (success + duplicate), list-users output, revoke-user (success + idempotent), rotate-token (old revoked, new created)

**Dependencies:** Phase 1 (tokens table and hash functions)

**Done when:** All four subcommands work correctly against SQLite. Token printed to stdout on creation. Duplicate username errors cleanly. Revocation is idempotent. Rotation atomically revokes + creates.
<!-- END_PHASE_3 -->

## Additional Considerations

**Token in test fixtures:** Existing delivery tests will need a valid token to pass after Phase 2. A test fixture that seeds a write-role token into the test database avoids boilerplate across all test files.

**Username uniqueness with revoked tokens:** The UNIQUE constraint on username means rotation must update (revoke) the existing row before inserting a new one within the same transaction. A simple approach: delete the old row and insert a new one, or update the existing row's hash/created_at and clear revoked_at. The implementation plan will determine the exact approach, but the constraint is that one username = one row in the table.
