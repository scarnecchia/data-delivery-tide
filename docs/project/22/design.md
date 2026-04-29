# Lowercase Error Messages

## Summary

Normalise all `HTTPException` detail strings and CLI stderr messages to lowercase sentence
fragments with no title case and no trailing period, per Python Programming Standards §4.3.
Pure find-and-replace across three files; one test assertion requires updating.

## Definition of Done

All user-visible error strings in `registry_api/auth.py`, `registry_api/routes.py`, and
`auth_cli.py` are lowercase sentence fragments with no title case and no trailing period.
The existing test suite passes without modification beyond the one assertion that checks
an exact `detail` string.

## Acceptance Criteria

- **AC1** — `auth.py` HTTP 401/403 detail strings are lowercase sentence fragments.
- **AC2** — `routes.py` HTTP 404 detail strings (four occurrences) are lowercase sentence fragments.
- **AC3** — `auth_cli.py` `Error:` stderr messages are lowercase sentence fragments.
- **AC4** — All other `auth_cli.py` user-facing `print` statements that contain title-cased
  or period-terminated copy are normalised.
- **AC5** — `uv run pytest` passes with no failures.

## Changes

### `src/pipeline/registry_api/auth.py`

| Before | After |
|--------|-------|
| `"Missing authentication credentials"` | `"missing authentication credentials"` |
| `"Invalid authentication credentials"` | `"invalid authentication credentials"` |
| `"Token has been revoked"` | `"token has been revoked"` |
| `f"Insufficient permissions: requires {minimum} role"` | `f"insufficient permissions: requires {minimum} role"` |

### `src/pipeline/registry_api/routes.py`

Four identical occurrences (lines 169, 195, 248, 284):

| Before | After |
|--------|-------|
| `"Delivery not found"` | `"delivery not found"` |

### `src/pipeline/auth_cli.py`

The `Error:` prefix is a CLI convention (not an HTTP detail string); the issue identifies
it as out-of-spec only where the message body is title-cased or period-terminated.

| Line | Before | After |
|------|--------|-------|
| 45 | `"Error: user '{args.username}' already has an active token"` | unchanged — already lowercase |
| 76 | `"No users found."` | `"no users found"` |
| 103 | `"Error: user '{args.username}' not found"` | unchanged — already lowercase |
| 108 | `"User '{args.username}' is already revoked."` | `"user '{args.username}' is already revoked"` |
| 117 | `"User '{args.username}' revoked."` | `"user '{args.username}' revoked"` |
| 134 | `"Error: user '{args.username}' not found"` | unchanged — already lowercase |

> Note: Lines 45, 103, and 134 are already lowercase sentence fragments; no change needed.
> The `Error:` prefix itself is a CLI idiom, not a sentence fragment subject to §4.3 — it
> is left intact.

## Test Impact

### `tests/registry_api/test_routes.py` — one exact-match assertion

```
# line 1325
assert response.json()["detail"] == "Delivery not found"
```

Must change to:

```python
assert response.json()["detail"] == "delivery not found"
```

### `tests/registry_api/test_auth.py`

No `detail` string assertions. Status-code-only checks; no update needed.

### `tests/converter/test_http.py`

```
# line 39
http_err.read = lambda: b'{"detail":"Delivery not found"}'
```

This is a mock fixture constructing a synthetic HTTP response body, not an assertion on
production output. Must be updated to match the new casing:

```python
http_err.read = lambda: b'{"detail":"delivery not found"}'
```

### `tests/test_auth_cli.py`

Assertions use `in` substring checks against normalised strings (`"already has an active
token"`, `"already revoked"`, `"not found"`). None of these substrings change; no updates
needed.

## Strategy

Simple find-and-replace in order:

1. `auth.py` — four strings (three `HTTPException` details + one f-string).
2. `routes.py` — four identical occurrences of `"Delivery not found"` (use replace_all).
3. `auth_cli.py` — three `print` statements (lines 76, 108, 117).
4. `test_routes.py` line 1325 — update exact-match assertion.
5. `test_http.py` line 39 — update mock fixture body.
6. Run `uv run pytest` to confirm green.

## Effort Estimate

~15 minutes. No logic changes, no new tests, no dependencies.
