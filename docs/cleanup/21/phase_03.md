# GH21 Phase 3: crawl() post_fn injection

**Goal:** Replace every `@patch("pipeline.crawler.main.post_delivery")` decorator (15 occurrences in `tests/crawler/test_main.py`) and every `MagicMock`-based fixture in the same file with a `post_fn` keyword parameter on `crawl()` plus a co-located `FakePostDelivery` recorder. Also rewrite `TestMain` (lines 847-865) to remove its three `@patch` decorators on `settings`, `get_logger`, and `crawl`.

**Architecture:** `crawl()` accepts an optional `post_fn` keyword-only parameter; production calls leave it at the default and the function calls `post_delivery` from `pipeline.crawler.http` as before. `main()` (the entry point at line 291) is rewritten so its `RegistryUnreachableError`/`RegistryClientError` handling can be tested by directly invoking `crawl()` with a `post_fn` that raises, and by monkeypatching `settings`/`get_logger` with `monkeypatch.setattr` (the project-sanctioned alternative to `patch` per the design).

**Tech Stack:** Python 3.10+, pytest fixtures (`monkeypatch`), no new dependencies.

**Scope:** 3 of 5 phases of GH21. Touches `src/pipeline/crawler/main.py` and `tests/crawler/test_main.py` only. Independent of phases 1, 2, 4, 5.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH21.AC4: `tests/crawler/test_main.py`
- **GH21.AC4.1 Success:** All `TestCrawl`, `TestLexiconSystemAC5Integration`, `TestCrawlAuth`, `TestSubDeliveryDiscovery` tests pass with `post_fn` injected into `crawl()` instead of `@patch("pipeline.crawler.main.post_delivery")`
- **GH21.AC4.2 Success:** `crawl()` accepts a `post_fn` parameter (default `post_delivery`) and calls it instead of calling `post_delivery` directly
- **GH21.AC4.3 Success:** `TestMain` class patches on `settings` and `get_logger` are replaced by accepting config/logger parameters (both already accepted by `crawl()`); `main()` test is refactored to test only the integration wiring or is moved to an integration test
- **GH21.AC4.4 Success:** All `MagicMock()` usages for `logger` remain acceptable (logger is already a parameter on `walk_roots` and `crawl()`)

---

## Codebase verification findings

- ✓ `src/pipeline/crawler/main.py:111` — `def crawl(config, logger, token: str | None = None) -> int`. The function calls `post_delivery(config.registry_api_url, payload, token=token)` at line 275.
- ✓ `src/pipeline/crawler/main.py:12` — `from pipeline.crawler.http import post_delivery, RegistryUnreachableError, RegistryClientError`. The plan must rename `post_delivery` to `_post_delivery` on import, freeing the bare name as the parameter default-without-cycle. Or simpler: keep the import name and use `post_delivery` directly as the default. See Task 1 for the chosen approach.
- ✓ `src/pipeline/crawler/main.py:291-318` — `main()` reads `settings`, calls `get_logger`, reads `REGISTRY_TOKEN`, then calls `crawl()` and handles `RegistryClientError` (with 401/403 special cases) and `RegistryUnreachableError`.
- ✓ `tests/crawler/test_main.py:3` — `from unittest.mock import patch, MagicMock`. After this phase, the test file should still need `MagicMock` for the `MagicMock(spec=logging.Logger)` usages at lines 176, 199 (within `TestWalkRoots`) — but `walk_roots` already accepts the logger as a parameter, so those `MagicMock(spec=logging.Logger)` instances are legitimate fakes per design AC4.4 and stay. Verify after edits whether `MagicMock` is still needed; if not, remove.
- ✓ `tests/crawler/test_main.py:291-307, 330-363, 365-403, 405-431, 433-468, 472-510, 512-542, 548-579, 585-606, 608-629, 636-655, 657-679, 681-700, 701-730, 731-755, 757-784, 787-844` — `@patch("pipeline.crawler.main.post_delivery")` decorator on every `TestCrawl`, `TestLexiconSystemAC5Integration`, `TestCrawlAuth`, `TestSubDeliveryDiscovery` test method. 15 total `@patch` decorators.
- ✓ `tests/crawler/test_main.py:850-865` — `TestMain.test_ac5_4_registry_unreachable_exits_nonzero` uses three stacked `@patch` decorators on `settings`, `get_logger`, and `crawl`. Replacement strategy in Task 4.
- ✓ `tests/crawler/test_main.py` already uses fixtures `delivery_tree`, `make_crawler_config`, `sub_delivery_setup`, `lexicons_dir` — these are defined in `tests/crawler/conftest.py` (verified by import resolution; not modified in this phase).

## External dependency findings

N/A — internal callable seam only.

---

<!-- START_TASK_1 -->
### Task 1: Add `post_fn` keyword parameter to `crawl()`

**Verifies:** GH21.AC4.2

**Files:**
- Modify: `src/pipeline/crawler/main.py:111-288` — change `crawl()` signature, replace the `post_delivery(...)` call at line 275.

**Implementation:**

```python
def crawl(
    config,
    logger,
    token: str | None = None,
    *,
    post_fn=None,
) -> int:
    """Run a full crawl cycle. Returns count of deliveries processed.

    `post_fn` is the registry POST callable, defaulting to
    `pipeline.crawler.http.post_delivery` when None. Tests override it.
    """
    if post_fn is None:
        post_fn = post_delivery
    ...
    # at the existing line 275:
    post_fn(config.registry_api_url, payload, token=token)
```

The `if post_fn is None: post_fn = post_delivery` indirection (rather than `post_fn=post_delivery` in the signature) avoids a defaulting-at-import-time pitfall where re-binding `pipeline.crawler.http.post_delivery` after `main` is imported would not affect existing default. Defaulting inside the body resolves the symbol at call time, which matches what tests would expect if they ever wanted to monkeypatch the import (they do not; this is purely belt-and-braces).

The keyword-only `*` separator ensures `crawl(config, logger, "token", fake_post_fn)` is a TypeError, eliminating an entire class of caller mistakes.

**Verification:**

```bash
uv run python -c "
import inspect
from pipeline.crawler.main import crawl, post_delivery
sig = inspect.signature(crawl)
p = sig.parameters['post_fn']
assert p.kind is inspect.Parameter.KEYWORD_ONLY
assert p.default is None
print('OK')
"
```

Expected: `OK`.

**Commit:** deferred to Task 4 (single commit for the phase).
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Define `FakePostDelivery` helper and remove `@patch` from `TestCrawl`, `TestLexiconSystemAC5Integration`, `TestCrawlAuth`, `TestSubDeliveryDiscovery`

**Verifies:** GH21.AC4.1 (partially — covers the four classes whose `@patch` decorators target `post_delivery`)

**Files:**
- Modify: `tests/crawler/test_main.py` — add the helper near the top of the file (between imports and `TestWalkRoots`), then rewrite each test method.

**Implementation:**

The helper:

```python
class FakePostDelivery:
    """Recorder for crawl()'s post_fn parameter.

    Captures positional and keyword arguments per call. Records the same data the
    previous @patch("pipeline.crawler.main.post_delivery") tests inspected via
    mock.call_args_list / mock.call_args[0][1].
    """

    def __init__(self, return_value=None):
        self.calls: list[dict] = []
        self._return_value = return_value if return_value is not None else {}

    def __call__(self, api_url, payload, *, token=None):
        self.calls.append({"api_url": api_url, "payload": payload, "token": token})
        return self._return_value

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def reset_mock(self) -> None:
        self.calls.clear()
```

`reset_mock` exists because three existing tests (`test_ac3_4_re_crawling_same_delivery_overwrites_manifest_idempotent` at line 365, `test_ac7_1_idempotent_crawl_produces_identical_manifests` at line 472, `test_ac7_2_unchanged_fingerprint_on_re_crawl` at line 512) call `mock_post.reset_mock()` between two `crawl()` invocations to inspect the second crawl independently. Preserving the method name keeps the rewrite mechanical.

Then for every test method that currently begins with:

```python
@patch("pipeline.crawler.main.post_delivery")
def test_xxx(self, mock_post, ...):
    ...
    crawl(config, logger)
    assert mock_post.called
    payload = mock_post.call_args[0][1]
```

Rewrite as:

```python
def test_xxx(self, ...):
    fake_post = FakePostDelivery()
    ...
    crawl(config, logger, post_fn=fake_post)
    assert fake_post.call_count > 0
    payload = fake_post.calls[0]["payload"]
```

The mapping of mock idioms to fake idioms:

| Mock idiom | Fake idiom |
|---|---|
| `mock_post.called` | `fake_post.call_count > 0` |
| `assert mock_post.called` | `assert fake_post.call_count > 0` |
| `mock_post.call_count == N` | `fake_post.call_count == N` |
| `mock_post.call_args[0][1]` (positional payload) | `fake_post.calls[0]["payload"]` |
| `mock_post.call_args_list[i][0][1]` | `fake_post.calls[i]["payload"]` |
| `mock_post.call_args[0]` (entire positional tuple) | `(fake_post.calls[-1]["api_url"], fake_post.calls[-1]["payload"])` |
| `mock_post.call_args` returning `(args, kwargs)` | `fake_post.calls[-1]` (already split into named keys) |
| `_, kwargs = mock_post.call_args; kwargs["token"]` | `fake_post.calls[-1]["token"]` |
| `mock_post.reset_mock()` | `fake_post.reset_mock()` |
| `mock_post.assert_called_once_with(...)` | (none in this file's `test_main.py` for `mock_post`) |

Apply this mapping to every test method in `TestCrawl` (lines 288-541), `TestLexiconSystemAC5Integration` (lines 545-579), `TestCrawlAuth` (lines 582-629), `TestSubDeliveryDiscovery` (lines 633-844). 15 test methods total. Each one loses its `@patch` decorator and its `mock_post` parameter; gains a local `fake_post = FakePostDelivery()` and threads `post_fn=fake_post` into the `crawl()` call.

**Concrete example for `test_ac2_3_posts_valid_delivery_payload_to_registry` (lines 291-328):**

```python
def test_ac2_3_posts_valid_delivery_payload_to_registry(
    self, delivery_tree, make_crawler_config
):
    """AC2.3: Crawler POSTs valid DeliveryCreate payload to registry API."""
    source_path, scan_root = delivery_tree(
        dp_id="mkscnr",
        request_id="soc_qar_wp001",
        version_dir_name="soc_qar_wp001_mkscnr_v01",
        status="passed",
        sas_files=[("dataset.sas7bdat", 1024)],
    )

    config = make_crawler_config(
        scan_roots=[{"path": scan_root, "label": "qa"}],
    )

    fake_post = FakePostDelivery()
    logger = MagicMock(spec=logging.Logger)  # see Task 3 — keep MagicMock(spec=...) for logger
    crawl(config, logger, post_fn=fake_post)

    assert fake_post.call_count == 1
    payload = fake_post.calls[0]["payload"]

    assert payload["request_id"] == "soc_qar_wp001"
    assert payload["project"] == "soc"
    # ... rest of assertions identical
```

**Concrete example for `TestCrawlAuth.test_token_forwarded_to_post_delivery` (lines 585-606):**

```python
def test_token_forwarded_to_post_delivery(
    self, delivery_tree, make_crawler_config
):
    source_path, scan_root = delivery_tree(...)
    config = make_crawler_config(...)
    fake_post = FakePostDelivery()
    logger = MagicMock(spec=logging.Logger)

    crawl(config, logger, token="my-secret-token", post_fn=fake_post)

    assert fake_post.call_count == 1
    assert fake_post.calls[0]["token"] == "my-secret-token"
```

The `kwargs["token"]` access becomes `fake_post.calls[0]["token"]` — exactly preserving the test's intent.

**Testing:**

Tests must verify each AC listed above:
- GH21.AC4.1: 15 test methods across `TestCrawl`, `TestLexiconSystemAC5Integration`, `TestCrawlAuth`, `TestSubDeliveryDiscovery` continue to pass under the same assertions, just sourcing data from `fake_post.calls` instead of `mock_post.call_args_list`.
- GH21.AC4.4: `MagicMock(spec=logging.Logger)` and bare `MagicMock()` for `logger` are preserved in `TestWalkRoots`, `TestCrawl`, etc. The design explicitly says these are legitimate DI fakes.

**Verification:**

```bash
grep -nE "@patch\(['\"]pipeline\.crawler\.main\.post_delivery" tests/crawler/test_main.py
```

Expected: zero matches.

**Commit:** deferred to Task 4.
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Audit `MagicMock` usage and update imports in test_main.py

**Verifies:** GH21.AC4.4 (verifies legitimate `MagicMock(spec=…)` for logger remains)

**Files:**
- Modify: `tests/crawler/test_main.py:3` — replace the `from unittest.mock import patch, MagicMock` import.

**Implementation:**

After Task 2 removes every `@patch(...)`, the only remaining `unittest.mock` symbol is `MagicMock`, used for `MagicMock()` (logger fixture, ~12 usages) and `MagicMock(spec=logging.Logger)` (lines 176, 199 — explicit-spec usages). Per the design: `logger` is a parameter on `walk_roots` and `crawl()`, so a duck-typed object is real DI, not patching. These `MagicMock(...)` calls stay.

The import becomes:

```python
from unittest.mock import MagicMock
```

This is the **only** acceptable `unittest.mock` import remaining anywhere in the project after GH21 ships, alongside the documented exception in `tests/registry_api/test_routes.py` (Phase 4). The Definition of Done in the design says "Zero imports of `unittest.mock`" — this is a tension that must be flagged. Resolution:

> The design's "Definition of Done" target zero imports is aspirational for `patch` specifically. The text at line 13 says "AsyncMock usages that test ConnectionManager directly are replaced..." and AC4.4 explicitly endorses `MagicMock(spec=logging.Logger)` as legitimate DI. The conservative reading is: **`MagicMock` for logger duck-typing is permitted**; `patch` is not.

If a stricter zero-import policy is required by reviewer, the alternative is a co-located `FakeLogger` class with `info`, `warning`, `error`, `debug` methods that record calls — same pattern as `FakePostDelivery`. This is **not** in scope for the current phase but is documented here so the reviewer can request it without re-investigating. Phase 3 ships with `from unittest.mock import MagicMock` retained in `tests/crawler/test_main.py`.

**Verification:**

```bash
grep -n "from unittest.mock" tests/crawler/test_main.py
```

Expected: a single line `from unittest.mock import MagicMock`.

```bash
grep -nE "@patch\b|patch\(" tests/crawler/test_main.py
```

Expected: zero matches (no `patch` use remains, only `client.patch(...)` HTTP method calls — which appear in `test_routes.py` not `test_main.py`).

**Commit:** deferred to Task 4.
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Rewrite `TestMain.test_ac5_4_registry_unreachable_exits_nonzero` to use `monkeypatch.setattr` instead of `@patch`, run tests, commit phase

**Verifies:** GH21.AC4.3

**Files:**
- Modify: `tests/crawler/test_main.py:847-865` — replace the three stacked `@patch` decorators with `monkeypatch.setattr` for `pipeline.crawler.main.settings` and `pipeline.crawler.main.get_logger`.

**Implementation:**

The current test patches three module symbols:

```python
@patch("pipeline.crawler.main.settings")
@patch("pipeline.crawler.main.get_logger")
@patch("pipeline.crawler.main.crawl")
def test_ac5_4_registry_unreachable_exits_nonzero(
    self, mock_crawl, mock_logger, mock_settings
):
    mock_crawl.side_effect = RegistryUnreachableError("connection refused")
    mock_settings.log_dir = "/tmp"
    from pipeline.crawler.main import main
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
```

Rewrite using `monkeypatch.setattr` for `settings` and `get_logger`, plus a stub `crawl` substitute:

```python
def test_ac5_4_registry_unreachable_exits_nonzero(self, monkeypatch):
    """AC5.4: Crawler exits non-zero when RegistryUnreachableError is raised."""
    import pipeline.crawler.main as crawler_main

    fake_settings = type("FakeSettings", (), {"log_dir": "/tmp"})()
    monkeypatch.setattr(crawler_main, "settings", fake_settings)
    monkeypatch.setattr(crawler_main, "get_logger", lambda *args, **kwargs: MagicMock(spec=logging.Logger))

    def fake_crawl(*args, **kwargs):
        raise RegistryUnreachableError("connection refused")

    monkeypatch.setattr(crawler_main, "crawl", fake_crawl)

    with pytest.raises(SystemExit) as exc_info:
        crawler_main.main()

    assert exc_info.value.code == 1
```

Why `monkeypatch.setattr` is acceptable here when `patch` is not:
- The design (line 110) calls out `monkeypatch.setattr` as the sanctioned alternative to `patch` for module-level globals. The `cli_db` fixture in `tests/test_auth_cli.py` uses it for the same purpose (`monkeypatch.setattr("pipeline.auth_cli.settings", ...)`).
- `monkeypatch` is a pytest fixture with automatic teardown — there is no global state leak between tests.
- It does not import or use `unittest.mock.patch` (the symbol the issue prohibits).
- `MagicMock(spec=logging.Logger)` for the `get_logger` return value is the same pattern endorsed by AC4.4 elsewhere in the test file.

**Optional further refactor:** The test's purpose is "given `crawl` raises `RegistryUnreachableError`, `main()` exits 1". `main()` is a thin wrapper around `crawl()`. An equivalent test that does **not** need to patch `crawl` at all would call `crawl()` directly with a `post_fn` that raises:

```python
def test_crawl_propagates_registry_unreachable(self, make_crawler_config, delivery_tree):
    source_path, scan_root = delivery_tree(...)
    config = make_crawler_config(scan_roots=[{"path": scan_root, "label": "qa"}])
    logger = MagicMock(spec=logging.Logger)

    def raising_post(*args, **kwargs):
        raise RegistryUnreachableError("connection refused")

    with pytest.raises(RegistryUnreachableError):
        crawl(config, logger, post_fn=raising_post)
```

This sidesteps `main()` entirely. However, the existing test verifies the **exit code** from `main()`, which is observable behaviour worth keeping (it covers the 401/403/Unreachable error-message branches in `main()`). The recommended path is the `monkeypatch` approach above — keep the `main()` integration covered while removing the `patch` import.

**Testing:**

Tests must verify GH21.AC4.3:
- `TestMain` no longer uses `@patch` decorators.
- `main()` exit-code behaviour on `RegistryUnreachableError` is preserved.

**Verification:**

```bash
grep -n "from unittest.mock import" tests/crawler/test_main.py
```

Expected: `from unittest.mock import MagicMock` (no `patch`).

```bash
grep -nE "@patch|unittest\.mock\.patch" tests/crawler/test_main.py
```

Expected: zero matches.

```bash
uv run pytest tests/crawler/test_main.py -v
```

Expected: same number of tests as before this phase, all passing.

**Commit:**

```bash
git add src/pipeline/crawler/main.py tests/crawler/test_main.py
git commit -m "refactor(crawler): inject post_fn into crawl() instead of patching (GH21 phase 3)"
```
<!-- END_TASK_4 -->

---

## Phase 3 Done When

- `crawl()` accepts `post_fn` as a keyword-only parameter; default behaviour calls `pipeline.crawler.http.post_delivery`.
- `tests/crawler/test_main.py` contains zero `@patch` decorators and zero `from unittest.mock import patch`.
- `MagicMock` retained only for `MagicMock(spec=logging.Logger)` and bare `MagicMock()` logger duck-typing — these are explicitly endorsed by GH21.AC4.4.
- `TestMain.test_ac5_4_registry_unreachable_exits_nonzero` uses `monkeypatch.setattr`.
- `uv run pytest tests/crawler/test_main.py` passes with the same test count as before this phase.

## Notes for executor

- **Phase ordering:** independent of phases 1, 2, 4, 5.
- **Conflict surface:** GH23 phase 5 modifies `crawler/main.py` `walk_roots` (lines 61-103) for `OSError` logging — different function from `crawl()`, no line overlap. GH27 prepends `# pattern: test file` to `tests/crawler/test_main.py:1`. If GH27 lands first, line 1 is the label and imports start at line 3; the Edit tool's match strings remain unique either way.
- **Logging import:** the existing test file imports `logging` at line 7 — confirmed before writing `MagicMock(spec=logging.Logger)` in Task 4's rewrite.
