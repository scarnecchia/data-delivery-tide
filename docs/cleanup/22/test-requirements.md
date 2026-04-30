# GH22 Test Requirements

Maps each acceptance criterion in `docs/implementation-plans/GH22/phase_01.md` to either an automated test (existing or new) or documented human verification.

GH22 is a string-casing change only. The existing test suite already exercises every code path that emits the touched strings; the bulk of verification is regression-style ("does pytest still go green") rather than new test authoring. Two tests pin exact strings and must be updated as part of Task 1; they are listed below as automated tests rather than as separate test additions, because the design treats those edits as part of the same atomic change.

---

## Automated tests

### GH22.AC1.1 — `"missing authentication credentials"` (auth.py:44)

- **Test type:** integration (FastAPI test client)
- **Test file:** `tests/registry_api/test_auth.py`
- **Coverage approach:** the existing test suite already calls protected endpoints without a bearer token and asserts `status_code == 401`. The string itself is not pinned. Coverage of the casing change is delivered transitively by `uv run pytest` returning green; no new assertion is required because the design explicitly elects status-code-only checks for `auth.py`.
- **Why no exact-match assertion:** pinning the literal string in the test suite would just duplicate the production constant and create a second place that must change in lockstep on any future copy edit. The design accepts this trade-off.

### GH22.AC1.2 — `"invalid authentication credentials"` (auth.py:50)

- Same as GH22.AC1.1: existing 401 status-code assertions in `tests/registry_api/test_auth.py` provide regression coverage. No new test required.

### GH22.AC1.3 — `"token has been revoked"` (auth.py:53)

- Same as GH22.AC1.1: existing revocation tests in `tests/registry_api/test_auth.py` (and `tests/test_auth_cli.py` substring checks against `"already has an active token"` / `"already revoked"`) provide coverage. No new test required.

### GH22.AC1.4 — `"insufficient permissions: requires {minimum} role"` (auth.py:74)

- Same as GH22.AC1.1: existing 403 status-code assertions cover the path. No new test required.

### GH22.AC2.1 — `"delivery not found"` (routes.py:169, 195, 248, 284)

- **Test type:** integration (FastAPI test client)
- **Test file:** `tests/registry_api/test_routes.py:1325`
- **Coverage approach:** this is the single exact-match assertion on a `detail` string anywhere in the test suite. Task 1 Step 4 updates the literal to the new lowercase form. The test continues to exercise the 404 path; pytest passing on this assertion proves the casing is correct in production.
- **Verification command:** `uv run pytest tests/registry_api/test_routes.py::<owning_test> -v` (the test name surrounding line 1325 is whatever the existing not-found test is called — task-implementor will discover it during Task 1).

### GH22.AC3.1 — `Error:` stderr messages already conform (auth_cli.py:45, 103, 134)

- **Test type:** unit / CLI substring check
- **Test file:** `tests/test_auth_cli.py`
- **Coverage approach:** the existing tests use `in` substring checks against `"already has an active token"`, `"already revoked"`, and `"not found"`. None of these substrings change as part of GH22, so the tests provide regression coverage that lines 45/103/134 stay lowercase. No new assertion required.

### GH22.AC4.1 — `"no users found"` (auth_cli.py:76)

- **Test type:** unit / CLI substring check
- **Test file:** `tests/test_auth_cli.py`
- **Coverage approach:** the existing `list-users` empty-state test (if present) checks substring `"no users found"` or similar — task-implementor must verify during Task 1 that no test pins the old `"No users found."` casing. The phase plan's Step 6 grep over `tests/` is the safety net: if it surfaces a hit, that test must be updated alongside the source change.
- **Why no new test:** GH22 is a copy edit; adding a test purely to pin casing is the kind of duplication §4.3 isn't asking for.

### GH22.AC4.2 — `"user '{username}' is already revoked"` (auth_cli.py:108)

- Same as GH22.AC4.1: covered by existing substring assertion on `"already revoked"` (which still appears as a substring of the new copy). Step 6 grep guards against any tests that pinned the old period-terminated form.

### GH22.AC4.3 — `"user '{username}' revoked"` (auth_cli.py:117)

- Same as GH22.AC4.1: covered by existing CLI tests. Step 6 grep guards against any test that pinned `User '...' revoked.` (with title case and trailing period).

### GH22.AC5 — `uv run pytest` is green

- **Test type:** full suite
- **Test file:** N/A (whole tree)
- **Coverage approach:** Task 1 Verification step runs `uv run pytest` and requires zero failures, zero new skips. This is the cardinal acceptance gate.

---

## Human verification

None. Every AC is fully covered by the automated test suite or by the in-task `grep` safety net in Step 6 of Task 1. There is no UI surface, no operator-facing log output, and no rendered template that requires eyes-on review.

---

## Notes on test-suite philosophy for this change

The design deliberately avoids asking for new tests pinning the literal new strings. Adding such tests would duplicate the production constant and turn future copy edits into double-edits with no real safety gain. The existing suite already covers each code path; GH22's job is to prove that "lowercase the copy" is a non-breaking change by leaving the suite green. That is exactly what GH22.AC5 encodes, and it is the only meaningful gate for this issue.
