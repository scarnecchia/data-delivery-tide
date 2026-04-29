# GH21 Phase 1: auth_cli token_generator DI

**Goal:** Replace the single `unittest.mock.patch` call in `tests/test_auth_cli.py` by adding a `token_generator` DI parameter to `cmd_add_user` (and to `cmd_rotate_token` for consistency), so tests can inject a deterministic generator instead of patching the `secrets` module.

**Architecture:** Additive-only DI. Both functions gain a keyword-only parameter with the production default `secrets.token_urlsafe`. No call site outside tests changes — production code is untouched because the existing argparse dispatch path (`args.func(args)` in `auth_cli.main`) calls each `cmd_*` with a single positional `args` argument, leaving the new keyword at its default.

**Tech Stack:** Python 3.10+, stdlib `secrets`, pytest, no new dependencies.

**Scope:** 1 of 5 phases of GH21. Independent of phases 2-5. Touches `src/pipeline/auth_cli.py` and `tests/test_auth_cli.py` only.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH21.AC1: `tests/test_auth_cli.py`
- **GH21.AC1.1 Success:** `test_add_user_token_is_urlsafe` verifies token generation without `patch`
- **GH21.AC1.2 Success:** `cmd_add_user` accepts a `token_generator` parameter (default `secrets.token_urlsafe`) that tests can substitute with a deterministic callable

---

## Codebase verification findings

- ✓ `src/pipeline/auth_cli.py:32` — `cmd_add_user(args: argparse.Namespace) -> int` exists. `secrets.token_urlsafe(32)` called at line 52.
- ✓ `src/pipeline/auth_cli.py:123` — `cmd_rotate_token(args: argparse.Namespace) -> int` exists. `secrets.token_urlsafe(32)` called at line 140. Design directs us to add the same parameter for consistency even though no current test patches it.
- ✓ `tests/test_auth_cli.py:4` — `from unittest.mock import patch` (the only mock import in this file).
- ✓ `tests/test_auth_cli.py:103-108` — `test_add_user_token_is_urlsafe` is the sole `patch` user in this file. Replacing it removes the only `unittest.mock` usage in the test file, so the import on line 4 must also be removed.
- ✓ `auth_cli.main()` (line 156) dispatches via `args.func(args)` — single positional argument. Adding a keyword-only parameter with a default does not break this path.
- ✓ Project pattern: `engine.py` uses keyword-only DI parameters with production defaults — same pattern applies here.

## External dependency findings

N/A — `secrets.token_urlsafe` is a Python stdlib callable; no external dependency research required.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Add `token_generator` parameter to `cmd_add_user` and `cmd_rotate_token`

**Verifies:** GH21.AC1.2 (parameter exists and defaults to `secrets.token_urlsafe`)

**Files:**
- Modify: `src/pipeline/auth_cli.py:32` (signature of `cmd_add_user`) and `src/pipeline/auth_cli.py:52` (call site of `secrets.token_urlsafe(32)`).
- Modify: `src/pipeline/auth_cli.py:123` (signature of `cmd_rotate_token`) and `src/pipeline/auth_cli.py:140` (call site).

**Implementation:**

For `cmd_add_user`:

```python
def cmd_add_user(
    args: argparse.Namespace,
    *,
    token_generator: Callable[[int], str] = secrets.token_urlsafe,
) -> int:
    """Create a new token for a user."""
    ...
    raw_token = token_generator(32)
    ...
```

For `cmd_rotate_token`:

```python
def cmd_rotate_token(
    args: argparse.Namespace,
    *,
    token_generator: Callable[[int], str] = secrets.token_urlsafe,
) -> int:
    """Revoke old token and create a new one for a user."""
    ...
    raw_token = token_generator(32)
    ...
```

The `*` makes `token_generator` keyword-only — this is the project convention for injectable collaborators (mirrors `engine.convert_one`'s `http_module=…, convert_fn=…` pattern). Keyword-only means production code cannot accidentally collide with a positional argument.

`Callable` must be imported. Add at the top of the file:

```python
from collections.abc import Callable
```

**Note on import location:** the project's GH28 work canonicalises `Callable` from `collections.abc` (the runtime type), not `typing.Callable`. Use `collections.abc`.

**Note on `args` typing:** the existing signature is `args: argparse.Namespace`. Leave that unchanged — GH19 (annotation pass) handles annotation policy elsewhere; this task only adds the new parameter.

**Verification:**

```bash
uv run python -c "
import inspect, secrets
from pipeline.auth_cli import cmd_add_user, cmd_rotate_token
for fn in (cmd_add_user, cmd_rotate_token):
    sig = inspect.signature(fn)
    p = sig.parameters['token_generator']
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, f'{fn.__name__}: token_generator is not keyword-only'
    assert p.default is secrets.token_urlsafe, f'{fn.__name__}: default is not secrets.token_urlsafe'
print('OK')
"
```

Expected output: `OK`

**Commit:** deferred to Task 2 (single commit for the whole phase).
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Replace the `patch` call in `test_add_user_token_is_urlsafe`, remove the now-unused `unittest.mock` import, run tests, commit

**Verifies:** GH21.AC1.1 (test verifies token generation without `patch`)

**Files:**
- Modify: `tests/test_auth_cli.py:4` — remove `from unittest.mock import patch`.
- Modify: `tests/test_auth_cli.py:103-108` — replace the `with patch(...)` block with a fake generator passed via the new keyword.

**Implementation:**

Test rewrite (replaces lines 103-108):

```python
def test_add_user_token_is_urlsafe(self, cli_db, capsys):
    """registry-auth.AC5.2: Token is generated by a callable that receives length=32."""
    calls = []

    def fake_generator(n):
        calls.append(n)
        return "mocked-token-value"

    args = argparse.Namespace(username="urlsafe_user", role="read")
    cmd_add_user(args, token_generator=fake_generator)

    assert calls == [32]
```

Behaviour preserved:
- The original `mock_urlsafe.assert_called_once_with(32)` becomes `assert calls == [32]` — same shape, no information lost.
- The original `return_value="mocked-token-value"` becomes the explicit return from `fake_generator`. The test does not assert on the token contents, so the value choice is arbitrary and matches the original.

Then remove line 4:

```python
from unittest.mock import patch
```

This is the only `unittest.mock` usage in this file — verify with `grep -n unittest.mock tests/test_auth_cli.py` after the edit and expect zero matches.

**Testing:**

The test must still cover GH21.AC1.1 (token generation verified without `patch`). The task-implementor will run the existing test name unchanged and confirm it asserts on the new fake's recorded calls.

**Verification:**

```bash
grep -n "unittest.mock" tests/test_auth_cli.py && echo "FAIL: unittest.mock still imported" || echo "OK: no unittest.mock"

uv run pytest tests/test_auth_cli.py -v
```

Expected: `OK: no unittest.mock`, then pytest reports all `tests/test_auth_cli.py` tests pass with the same count as before (no tests removed, none added).

**Commit:**

```bash
git add src/pipeline/auth_cli.py tests/test_auth_cli.py
git commit -m "refactor(auth_cli): replace patch with token_generator DI (GH21 phase 1)"
```
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

---

## Phase 1 Done When

- `cmd_add_user` and `cmd_rotate_token` both accept `token_generator` as a keyword-only parameter with default `secrets.token_urlsafe`.
- `tests/test_auth_cli.py` does not import or use anything from `unittest.mock`.
- `test_add_user_token_is_urlsafe` exercises injection rather than patching.
- `uv run pytest tests/test_auth_cli.py` passes with the same number of tests as before.

## Notes for executor

- **Phase ordering:** independent of phases 2, 3, 4, 5.
- **Conflict surface:**
  - **GH22** (lowercase error messages) modifies `auth_cli.py` error strings — different lines from this phase's signature edits. Compose cleanly.
  - **GH19** (type annotations) is in flight and may add return/parameter annotations across `auth_cli.py`. If GH19 lands first, the `Callable[[int], str]` annotation in this phase's signatures may be redundant or conflict with whatever GH19 chose. The executor should run `git status src/pipeline/auth_cli.py` before applying Task 1 — if GH19 has already added annotations, harmonise the `token_generator` annotation with the surrounding style rather than duplicating.
  - **GH27** prepends `# pattern: test file` to `tests/test_auth_cli.py:1`. This phase's edit at line 4 (the `unittest.mock` import) is unaffected by line-1 prepends; the Edit tool will match line 4 regardless.
