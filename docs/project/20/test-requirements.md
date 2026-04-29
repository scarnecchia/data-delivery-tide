# GH20 Test Requirements

This document maps each GH20 acceptance criterion to a specific test (or set of tests) and identifies the file the test lives in. Generated from `docs/project/20/design.md` and `phase_0{1..5}.md`.

Every criterion maps to an automated test. None of GH20's criteria require human verification — every change is internal-API-shape and observable via Python introspection plus pytest assertions on either dataclass fields or HTTP-response JSON.

## Coverage matrix

| AC | Spec (verbatim from design, scoped to GH20) | Test file | Test name (existing or kept) | Test type | Phase |
|----|----------------------------------------------|-----------|-------------------------------|-----------|-------|
| GH20.AC1.1 | `FileEntry` is a frozen dataclass; `compute_fingerprint` accepts and returns correctly typed values | `tests/crawler/test_fingerprint.py` | All existing tests in the file (assertions converted from subscript to attribute access) + introspection assertion in Phase 1 Task 1 verification block | unit | 1 |
| GH20.AC1.2 | `ParsedMetadata`, `CrawlManifest`, `ErrorManifest` are frozen dataclasses | `tests/crawler/test_manifest.py` | All `TestBuildManifest` tests + introspection assertion in Phase 1 Task 2 verification block | unit | 1 |
| GH20.AC1.3 | `build_error_manifest` returns a named `ErrorManifestResult` dataclass | `tests/crawler/test_manifest.py` | `TestBuildErrorManifest::test_*` (rewritten from `filename, manifest = build_error_manifest(...)` to `result = build_error_manifest(...)`) | unit | 1 |
| GH20.AC1.4 | Passing a dict where a `FileEntry` is expected raises `TypeError` | `tests/crawler/test_fingerprint.py` (new test) | `test_compute_fingerprint_rejects_dict_entries` (added in Phase 1 Task 3 if not already present, verifying `compute_fingerprint([{"filename": ..., ...}])` raises `AttributeError` on the lambda's `f.filename` access — this is the dataclass-strict behaviour AC1.4 calls for) | unit | 1 |
| GH20.AC1.5 | `build_manifest` constructs `CrawlManifest` using keyword arguments; all fields accounted for | `tests/crawler/test_manifest.py` | `TestBuildManifest::test_includes_all_fields` (existing — verifies every field is populated) + introspection assertion in Phase 1 Task 2 | unit | 1 |
| GH20.AC2.1 | `walk_roots` returns `list[WalkResult]` with `.source_path` and `.scan_root` attributes | `tests/crawler/test_main.py` | `TestWalkRoots::*` (all methods, with `r[0]`/`r[1]` rewritten to `r.source_path`/`r.scan_root`) + introspection assertion in Phase 2 Task 1 | unit | 2 |
| GH20.AC2.2 | `delivery_data` accumulator value is a frozen dataclass with `.files`, `.fingerprint`, `.manifest` | introspection assertion in Phase 2 Task 1 verification block; behavioural coverage indirect via `TestCrawl` | unit | 2 |
| GH20.AC2.3 | All destructuring in `crawl()` uses attribute access, not tuple unpacking | grep gate in Phase 2 verification: `grep -nE 'manifest\["\|files, fingerprint, manifest = ' src/pipeline/crawler/main.py` returns zero matches | static check | 2 |
| GH20.AC2.4 | Existing `test_main.py` tests pass | `tests/crawler/test_main.py` | All `TestWalkRoots`, `TestInventoryFiles`, `TestCrawl`, `TestSubDeliveryDiscovery`, `TestMain` methods | unit | 2 |
| GH20.AC3.1 | `successes` list holds `FileConversionSuccess` instances | `tests/converter/test_engine.py` | All `TestConvertOne::test_partial_success_*` and `test_full_success_*` methods (assertions on PATCH body shape pass unchanged because `_failure_to_wire` preserves wire shape; introspection assertion in Phase 3 Task 1 covers the dataclass shape) | unit | 3 |
| GH20.AC3.2 | `failures` dict values are `FileConversionFailure` instances | `tests/converter/test_engine.py` | `TestConvertOne::test_partial_success_*` and `test_total_failure_*` methods (assertions on `patch["metadata"]["conversion_errors"][filename]["class"]` pass unchanged) + introspection assertion in Phase 3 Task 1 | unit | 3 |
| GH20.AC3.3 | `total_rows`, `total_bytes`, `converted_files` aggregations use attribute access | grep gate in Phase 3 verification: `grep -nE 'sum\(.* for _, .* in successes\)' src/pipeline/converter/engine.py` returns zero matches | static check | 3 |
| GH20.AC3.4 | `patch_body` and `event_payload` dicts built from `failures` serialise identically | `tests/converter/test_engine.py` | All `test_engine.py` tests that assert on `patch["metadata"]["conversion_errors"]` shape (lines 433, 476, 677 in pre-migration) | unit | 3 |
| GH20.AC3.5 | Existing `test_engine.py` assertions on patch body shapes pass without modification | `tests/converter/test_engine.py` | All test methods in the file | unit | 3 |
| GH20.AC4.1 | `DeliveryRecord`, `TokenRecord`, `EventRow` frozen dataclasses defined in `records.py` | introspection assertion in Phase 4 Task 1 verification block | unit | 4 |
| GH20.AC4.2 | `get_delivery` returns `DeliveryRecord \| None`; `list_deliveries` returns `tuple[list[DeliveryRecord], int]` | `tests/registry_api/test_db.py` | `TestGetDelivery::*`, `TestListDeliveries::*` (assertions converted from subscript to attribute) + introspection assertion in Phase 4 Task 2 | unit | 4 |
| GH20.AC4.3 | `get_token_by_hash` returns `TokenRecord \| None` | `tests/registry_api/test_db.py` | `TestGetTokenByHash::*` (assertions converted from `result["X"]` to `result.X`) | unit | 4 |
| GH20.AC4.4 | `insert_event` and `get_events_after` return `EventRow` / `list[EventRow]` | `tests/registry_api/test_db.py` | `TestInsertEvent::*`, `TestGetEventsAfter::*` (assertions converted from `result["payload"]` etc. to `result.payload`) | unit | 4 |
| GH20.AC4.5 | Routes call `DeliveryResponse.model_validate(dataclasses.asdict(record))` | `tests/registry_api/test_routes.py` | All `TestGetSingleDelivery`, `TestListAllDeliveries`, `TestPatchDelivery`, `TestPostDelivery` tests (response shapes verified by `response.json()` — same dict shape before/after) | unit | 5 |
| GH20.AC4.6 | `auth.py` uses `TokenRecord` attribute access | `tests/registry_api/test_auth.py` | All authentication tests in `test_auth.py` (cover the require_auth code path that reads `token_row.revoked_at`, `.username`, `.role`) | unit | 5 |
| GH20.AC4.7 | `tests/registry_api/test_db.py` and `test_routes.py` tests pass | `tests/registry_api/test_db.py` (modified for attribute access), `tests/registry_api/test_routes.py` (unmodified — operates on JSON) | All test methods in both files | unit | 4-5 |
| GH20.AC4.8 | `upsert_delivery` still accepts a plain `dict` input; return type becomes `DeliveryRecord \| None` | `tests/registry_api/test_db.py` | `TestUpsertDelivery::*` (assertions on returned record converted from subscript to attribute; input dict unchanged) | unit | 4 |
| GH20.AC5.1 | JSON responses from all GET endpoints byte-for-byte equivalent | `tests/registry_api/test_routes.py` | All GET tests (`TestGetSingleDelivery`, `TestListAllDeliveries`, `TestGetActionable`, `TestCatchUpEndpoint`) — assertions on `response.json()` are unchanged | unit | 5 |
| GH20.AC5.2 | WebSocket broadcast payloads unchanged | `tests/registry_api/test_routes.py`, `tests/registry_api/test_events.py` | `TestWebSocketBroadcast::*`, `TestConnectionManager::*` — fake WebSocket clients receive the same JSON shape | unit | 5 |
| GH20.AC5.3 | Crawl manifest JSON files written to disk are unchanged | `tests/crawler/test_main.py`, `tests/crawler/test_manifest.py` | Tests that load manifests from disk and assert on their JSON shape (e.g., `TestCrawl::test_*` that read back the written manifest) | unit | 1-2 |
| GH20.AC5.4 | Dataclass field access on a missing key fails loudly at construction time | inherent to `_record_from_row` (KeyError on missing column) — verified at Phase 4 Task 2 by the unit tests passing on every column path; no separate test required | introspection | 4 |

## Phase rollups

| Phase | Test files touched | Tests rewritten (assertion-only) | Test count delta |
|-------|---------------------|---------------------------------|-------------------|
| 1 | `tests/crawler/test_fingerprint.py`, `tests/crawler/test_manifest.py` | All assertions on `manifest[...]` and `result[...]` (both files) | +0 (one optional new test for AC1.4: `test_compute_fingerprint_rejects_dict_entries` — see note below) |
| 2 | `tests/crawler/test_main.py` | `TestWalkRoots::*` (assertions on `r[0]`/`r[1]` and tuple equality) | 0 |
| 3 | `tests/converter/test_engine.py` | None (all assertions on PATCH body dicts pass unchanged because `_failure_to_wire` preserves wire shape) | 0 |
| 4 | `tests/registry_api/test_db.py` | All assertions on `result["X"]` patterns where `result` is a db return; `sqlite3.Row` subscripts preserved | 0 |
| 5 | None (test_routes.py, test_auth.py, test_events.py operate on JSON or sqlite3.Row directly) | 0 | 0 |

**Net test count change across the entire issue: +0 or +1.** The optional `test_compute_fingerprint_rejects_dict_entries` is the only candidate addition; if Phase 1 Task 3 finds that the existing fingerprint tests already cover the dataclass-strict access path (which they likely do, by virtue of `lambda f: f.filename` blowing up on a dict), the new test is omitted. Every other change preserves test names and assertion semantics; only access syntax changes.

## Verification gate (final)

Before considering GH20 done, the following commands must all return zero exit codes:

```bash
# No subscript reads on dataclass returns in test files (sqlite3.Row subscripts are OK; they live in test_auth.py:126-130 and test_db.py:1118):
grep -rnE 'result\[\"[a-z_]+\"\]|delivery\[\"[a-z_]+\"\]' tests/registry_api/test_db.py | grep -v '# sqlite3.Row' | head

# No bare-tuple constructions or destructurings of walk_roots in crawler/main.py:
grep -nE 'tuple\[str, str\]|for source_path, scan_root in candidates' src/pipeline/crawler/main.py
# Expected: zero matches.

# No bare-tuple/dict accumulators in converter/engine.py:
grep -nE 'list\[tuple\[str, int, int\]\]|dict\[str, dict\]' src/pipeline/converter/engine.py
# Expected: zero matches.

# No `**dict` constructions of DeliveryResponse / EventRecord in routes.py (model_validate is the canonical path):
grep -nE 'DeliveryResponse\(\*\*|EventRecord\(\*\*' src/pipeline/registry_api/routes.py
# Expected: zero matches.

# No subscript reads on TokenRecord in auth.py:
grep -nE 'token_row\[' src/pipeline/registry_api/auth.py
# Expected: zero matches.

# Every TypedDict import has been removed from crawler:
grep -nE 'from typing import TypedDict' src/pipeline/crawler/
# Expected: zero matches.

# Full test suite passes:
uv run pytest
```

Each command's expected output is empty (or, for the test suite, "all tests pass with same count as before GH20 began" plus at most one new fingerprint test for AC1.4).

## Human verification: none required

Every criterion is verifiable via Python introspection + pytest. No UI, no side effects on external systems, no behavioural change visible to consumers of the registry API or the crawler. The pipeline's HTTP wire shape, WebSocket protocol, on-disk manifest JSON, and database state are all unchanged — this issue is a pure type-quality refactor.

## Cross-issue dependencies for tests

- **Phase 4-5 / GH21 overlap:** GH21 (DI refactor) lands at Tier 2 before GH20 starts. By the time Phase 4-5 begin, `tests/registry_api/test_routes.py` already uses fake fixtures instead of `unittest.mock.patch`. The GH20 edits to `test_db.py` (assertion syntax) do not touch the DI scaffolding GH21 introduced.
- **Phase 1-2 / GH19 overlap:** GH19 (annotations) lands at Tier 1 before GH20 starts. The signatures touched by Phases 1-2 (`compute_fingerprint`, `build_manifest`, `walk_roots`, `crawl`) are already annotated; Phase 1-2's edits flip return types from `TypedDict` to dataclass without otherwise altering annotations.
- **Phase 3 / GH23 overlap:** GH23 (exception logging) modifies the `except BaseException` block in `engine.py`. Phase 3 reapplies the failures-dataclass migration on top of the GH23 edits; the `failures[name] = FileConversionFailure(...)` construction replaces the prior dict literal but leaves the surrounding `logger.warning(..., exc_info=True)` calls intact.
- **All phases / GH17 overlap:** GH17 (ruff format + mypy strict) lands at Tier 2. mypy strict will flag the GH20 edits in real time during execution — any leftover `dict | None` return annotation that mismatches the new dataclass return raises an error at type-check time. This is a feature: GH17 is the safety net for GH20 (per the DAG: "Frozen dataclasses (benefits from mypy validation)").
