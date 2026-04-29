# GH22 Lowercase Error Messages — Implementation Plan

**Goal:** Normalise all user-visible HTTPException detail strings and CLI stderr/stdout messages to lowercase sentence fragments per Python Programming Standards §4.3.

**Architecture:** Pure find-and-replace across three production source files plus two test files. No logic changes, no signature changes, no new dependencies. The existing test suite covers all touched code paths; only one exact-match assertion and one mock fixture body need updating to track the new casing.

**Tech Stack:** Python 3.10+, FastAPI HTTPException, pytest. No new tools.

**Scope:** 1 phase from the GH22 design at `docs/project/22/design.md`.

**Codebase verified:** 2026-04-29 — all five files exist and the line numbers in the design match the current `security-hardening` branch exactly:
- `src/pipeline/registry_api/auth.py` lines 44, 50, 53, 74
- `src/pipeline/registry_api/routes.py` lines 169, 195, 248, 284 (four identical occurrences)
- `src/pipeline/auth_cli.py` lines 76, 108, 117 (require change); lines 45, 103, 134 already lowercase
- `tests/registry_api/test_routes.py` line 1325 (sole exact-match `detail` assertion in the test suite)
- `tests/converter/test_http.py` line 39 (mock `http_err.read` body)

`tests/registry_api/test_auth.py` was checked — it contains zero `detail` string assertions, so no test updates are needed for `auth.py` changes.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH22.AC1: `auth.py` HTTP 401/403 detail strings are lowercase sentence fragments
- **GH22.AC1.1** `"Missing authentication credentials"` → `"missing authentication credentials"`
- **GH22.AC1.2** `"Invalid authentication credentials"` → `"invalid authentication credentials"`
- **GH22.AC1.3** `"Token has been revoked"` → `"token has been revoked"`
- **GH22.AC1.4** `f"Insufficient permissions: requires {minimum} role"` → `f"insufficient permissions: requires {minimum} role"`

### GH22.AC2: `routes.py` HTTP 404 detail strings (four occurrences) are lowercase sentence fragments
- **GH22.AC2.1** All four occurrences of `"Delivery not found"` → `"delivery not found"`

### GH22.AC3: `auth_cli.py` `Error:` stderr messages are lowercase sentence fragments
- **GH22.AC3.1** Lines 45, 103, 134 already conform per the design's no-op finding. No source change required; this AC is satisfied by absence of regression in those lines after Task 1.

### GH22.AC4: All other `auth_cli.py` user-facing `print` statements with title-cased or period-terminated copy are normalised
- **GH22.AC4.1** Line 76: `"No users found."` → `"no users found"`
- **GH22.AC4.2** Line 108: `"User '{args.username}' is already revoked."` → `"user '{args.username}' is already revoked"`
- **GH22.AC4.3** Line 117: `"User '{args.username}' revoked."` → `"user '{args.username}' revoked"`

### GH22.AC5: `uv run pytest` passes with no failures.

---

<!-- START_TASK_1 -->
### Task 1: Normalise error message casing across auth, routes, CLI, and the two test files that pin the old strings

**Verifies:** GH22.AC1.1, GH22.AC1.2, GH22.AC1.3, GH22.AC1.4, GH22.AC2.1, GH22.AC3.1, GH22.AC4.1, GH22.AC4.2, GH22.AC4.3, GH22.AC5

**Files:**
- Modify: `src/pipeline/registry_api/auth.py:44,50,53,74`
- Modify: `src/pipeline/registry_api/routes.py:169,195,248,284`
- Modify: `src/pipeline/auth_cli.py:76,108,117`
- Modify: `tests/registry_api/test_routes.py:1325`
- Modify: `tests/converter/test_http.py:39`

**Implementation:**

This is a string-only change. No control flow, no signatures, no imports. Apply each edit literally. Do NOT touch the `Error:` prefix on `auth_cli.py` lines 45, 103, 134 — those are already lowercase sentence fragments per the design (the `Error:` prefix itself is a CLI idiom, not a sentence fragment subject to §4.3).

**Step 1: Edit `src/pipeline/registry_api/auth.py`**

Apply four replacements:

| Line | Before | After |
|------|--------|-------|
| 44 | `detail="Missing authentication credentials"` | `detail="missing authentication credentials"` |
| 50 | `detail="Invalid authentication credentials"` | `detail="invalid authentication credentials"` |
| 53 | `detail="Token has been revoked"` | `detail="token has been revoked"` |
| 74 | `detail=f"Insufficient permissions: requires {minimum} role"` | `detail=f"insufficient permissions: requires {minimum} role"` |

**Step 2: Edit `src/pipeline/registry_api/routes.py`**

Replace all four identical occurrences of `detail="Delivery not found"` with `detail="delivery not found"` (lines 169, 195, 248, 284). Use `replace_all` since the four occurrences are byte-identical.

**Step 3: Edit `src/pipeline/auth_cli.py`**

Apply three replacements (do not touch lines 45, 103, 134):

| Line | Before | After |
|------|--------|-------|
| 76  | `print("No users found.")` | `print("no users found")` |
| 108 | `print(f"User '{args.username}' is already revoked.")` | `print(f"user '{args.username}' is already revoked")` |
| 117 | `print(f"User '{args.username}' revoked.")` | `print(f"user '{args.username}' revoked")` |

**Step 4: Edit `tests/registry_api/test_routes.py:1325`**

Replace:
```python
assert response.json()["detail"] == "Delivery not found"
```
with:
```python
assert response.json()["detail"] == "delivery not found"
```

This is the only exact-match assertion on a `detail` string anywhere in the test suite — confirmed via `grep -rn '"detail"' tests/`.

**Step 5: Edit `tests/converter/test_http.py:39`**

Replace:
```python
http_err.read = lambda: b'{"detail":"Delivery not found"}'
```
with:
```python
http_err.read = lambda: b'{"detail":"delivery not found"}'
```

This is a synthetic HTTP response body used as a mock fixture, not an assertion on production output. It must track the production casing so the converter under test sees a realistic registry response.

**Step 6: Sanity check that no other test pins the old strings**

```bash
grep -rnE 'Delivery not found|Missing authentication credentials|Invalid authentication credentials|Token has been revoked|Insufficient permissions|No users found\.|is already revoked\.|" revoked\.' tests/ src/
```

Expected output: empty. If anything matches, investigate before proceeding to verification — there is a string the design did not catalogue.

**Verification:**

Run the full test suite:

```bash
uv run pytest
```

Expected: all tests pass with no failures and no skips beyond the existing baseline.

Spot-check that an actual 401 response carries the new casing:

```bash
uv run pytest tests/registry_api/test_auth.py -v
```

Expected: all auth tests pass. (They use status-code-only checks per the design, so this is a regression guard rather than a string check.)

**Commit:**

```bash
git add src/pipeline/registry_api/auth.py \
        src/pipeline/registry_api/routes.py \
        src/pipeline/auth_cli.py \
        tests/registry_api/test_routes.py \
        tests/converter/test_http.py
git commit -m "style: lowercase user-visible error messages

Normalise HTTPException detail strings and CLI stderr/stdout messages
to lowercase sentence fragments with no title case and no trailing
period, per Python Programming Standards §4.3.

Closes issue #22."
```
<!-- END_TASK_1 -->

---

## Done When

- `auth.py` lines 44, 50, 53, 74 carry the lowercased detail strings.
- `routes.py` lines 169, 195, 248, 284 all read `detail="delivery not found"`.
- `auth_cli.py` lines 76, 108, 117 carry the lowercased, period-stripped print copy.
- `test_routes.py:1325` and `test_http.py:39` track the new casing.
- `uv run pytest` is green.
- A single commit captures the change with a `style:` prefix referencing GH22.
