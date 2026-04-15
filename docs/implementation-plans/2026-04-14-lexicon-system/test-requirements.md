# Lexicon System -- Test Requirements

Maps each acceptance criterion from the lexicon system design to specific automated tests and human verification steps.

**Source:** `docs/design-plans/2026-04-14-lexicon-system.md`

**Generated:** 2026-04-14

---

## Automated Tests

| AC ID | Test Type | Test File | Description |
|---|---|---|---|
| lexicon-system.AC1.1 | unit | `tests/lexicons/test_loader.py` | Load a valid lexicon JSON (no extends). Assert result is a frozen `Lexicon` dataclass with all fields correctly populated (tuples, dicts, etc.). Verify immutability via `setattr` raising `FrozenInstanceError`. |
| lexicon-system.AC1.2 | unit | `tests/lexicons/test_loader.py` | Create base + child lexicons where child declares `extends`. Assert child inherits all base fields (statuses, transitions, dir_map, actionable_statuses). |
| lexicon-system.AC1.3 | unit | `tests/lexicons/test_loader.py` | Create base + child where child overrides `actionable_statuses` and adds `metadata_fields`. Assert child has overridden field while retaining all other base fields. |
| lexicon-system.AC1.4 | unit | `tests/lexicons/test_loader.py` | Create two lexicons with circular extends (A extends B, B extends A). Assert `LexiconLoadError` raised with message mentioning circular/cycle. |
| lexicon-system.AC1.5 | unit | `tests/lexicons/test_loader.py` | Create lexicon with transition referencing a status not in `statuses`. Assert `LexiconLoadError` with message identifying the bad status reference. |
| lexicon-system.AC1.6 | unit | `tests/lexicons/test_loader.py` | Create lexicon with `dir_map` value not present in `statuses`. Assert `LexiconLoadError` with message identifying the bad dir_map reference. |
| lexicon-system.AC1.7 | unit | `tests/lexicons/test_loader.py` | Create lexicon with `metadata_fields[].set_on` value not present in `statuses`. Assert `LexiconLoadError` with message identifying the bad set_on reference. |
| lexicon-system.AC1.8 | unit | `tests/lexicons/test_loader.py` | Create lexicon with `derive_hook` pointing to a non-importable module path. Assert `LexiconLoadError` with message identifying the bad hook path. |
| lexicon-system.AC1.9 | unit | `tests/lexicons/test_loader.py` | Create a single lexicon with multiple simultaneous errors (bad transition ref + bad dir_map ref + bad actionable ref + bad set_on ref). Assert `LexiconLoadError` with `len(exc.errors) >= 4` -- all errors collected in one batch. |
| lexicon-system.AC1.9 | unit | `tests/lexicons/test_loader.py` | (additional) Call `load_lexicon()` for an ID not present in the lexicons directory. Assert `LexiconLoadError` with message mentioning "not found". |
| lexicon-system.AC2.1 | unit | `tests/test_config.py` | Create config with valid `lexicons_dir` and scan root `lexicon` reference matching a loaded lexicon ID. Assert `load_config()` succeeds and `ScanRoot.lexicon` field is populated correctly. |
| lexicon-system.AC2.2 | unit | `tests/test_config.py` | Create config where scan root references a non-existent lexicon ID (`"soc.nonexistent"`). Assert `LexiconLoadError` raised with message mentioning the bad reference. |
| lexicon-system.AC2.3 | unit | `tests/test_config.py` | Create config JSON missing the `lexicons_dir` field entirely. Assert `ValueError` raised with message about missing `lexicons_dir`. |
| lexicon-system.AC3.1 | integration | `tests/registry_api/test_db.py` | Upsert a delivery with `lexicon_id`, `status`, and `metadata` fields. Assert the returned row contains all three fields with correct values. |
| lexicon-system.AC3.2 | integration | `tests/registry_api/test_db.py` | Upsert a delivery with `metadata` containing `{"passed_at": "2026-04-14T12:00:00Z"}`. Query it back. Assert `metadata` round-trips as valid JSON with identical content. |
| lexicon-system.AC3.3 | integration | `tests/registry_api/test_db.py` | Insert deliveries for a single lexicon with mixed statuses. Call `get_actionable()` with that lexicon's `actionable_statuses`. Assert only deliveries matching actionable statuses (and not yet converted) are returned. |
| lexicon-system.AC3.4 | integration | `tests/registry_api/test_db.py` | Insert deliveries across two lexicons with different `actionable_statuses`. Call `get_actionable()` with both lexicons' mappings. Assert correct per-lexicon filtering. |
| lexicon-system.AC3.5 | integration | `tests/registry_api/test_db.py` | Insert deliveries with varying `lexicon_id` and `status` values. Call `list_deliveries()` with `lexicon_id` filter, assert only matching rows. Repeat with `status` filter. |
| lexicon-system.AC4.1 | integration | `tests/registry_api/test_routes.py` | POST a delivery with `lexicon_id="soc.qar"` and `status="pending"`. Assert 200 response with correct fields. |
| lexicon-system.AC4.2 | integration | `tests/registry_api/test_routes.py` | POST with `status="nonexistent"` for `lexicon_id="soc.qar"`. Assert 422 response with detail mentioning invalid status. |
| lexicon-system.AC4.2 | integration | `tests/registry_api/test_routes.py` | (additional) POST with `lexicon_id="nonexistent"`. Assert 422 response with detail mentioning unknown lexicon_id. |
| lexicon-system.AC4.3 | integration | `tests/registry_api/test_routes.py` | Create delivery with `status="pending"`, then PATCH with `status="passed"` (legal transition). Assert 200 response. |
| lexicon-system.AC4.4 | integration | `tests/registry_api/test_routes.py` | Create delivery with `status="passed"`, then PATCH with `status="pending"` (illegal transition). Assert 422 response. |
| lexicon-system.AC4.5 | integration | `tests/registry_api/test_routes.py` | Create delivery with `status="pending"`, then PATCH with `status="passed"`. Assert response `metadata` contains `passed_at` with a valid ISO 8601 timestamp (auto-populated by `set_on` rule). |
| lexicon-system.AC4.6 | integration | `tests/registry_api/test_routes.py` | Create delivery with `status="pending"`, then PATCH with same `status="pending"`. Assert no `delivery.status_changed` event emitted (query events table; only creation event present). Assert `metadata` does not contain `passed_at`. |
| lexicon-system.AC5.1 | unit | `tests/crawler/test_parser.py` | Call `parse_path()` with paths ending in terminal directories that are keys in `dir_map`. Assert `ParsedDelivery.status` matches the mapped value. Test with multiple dir_map entries. |
| lexicon-system.AC5.2 | unit | `tests/crawler/test_parser.py` | Call `parse_path()` with a path ending in a terminal directory not in `dir_map`. Assert `ParseError` returned with reason mentioning "not in dir_map". |
| lexicon-system.AC5.3 | unit | `tests/lexicons/test_qa_hook.py` | Create a `Lexicon` with `derive_hook` set to a callable. Call `derive_statuses()`. Assert the hook was invoked and its return value used. |
| lexicon-system.AC5.4 | unit | `tests/crawler/test_parser.py` | Create a `Lexicon` with `derive_hook=None`. Call `derive_statuses()`. Assert input deliveries returned unchanged. |
| lexicon-system.AC5.5 | unit | `tests/lexicons/test_qa_hook.py` | Call QA `derive()` hook with multiple pending deliveries in the same (workplan_id, dp_id) group at different versions. Assert lower versions become `"failed"`, highest stays `"pending"`. Also test: single delivery unchanged, passed deliveries untouched, mixed status groups, empty list, independent groups handled independently. |
| lexicon-system.AC5.6 | integration | `tests/crawler/test_main.py` | Build a directory tree, run the crawler with a lexicon config. Mock `post_delivery` to capture the payload. Assert payload contains `lexicon_id` and `status` fields (no `qa_status`). |
| lexicon-system.AC6.1 | integration | `tests/registry_api/test_routes.py` | POST a new delivery (triggers `delivery.created`). Query events from DB. Assert event payload contains keys `lexicon_id`, `status`, `metadata` with correct values. |
| lexicon-system.AC6.2 | integration | `tests/registry_api/test_routes.py` | POST delivery with `status="pending"`, PATCH to `status="passed"`. Query events. Find `delivery.status_changed` event. Assert payload contains `status="passed"` and `metadata` with `passed_at` timestamp. |
| lexicon-system.AC6.3 | integration | `tests/registry_api/test_routes.py` | For events from AC6.1 and AC6.2, assert `"qa_status" not in payload` and `"qa_passed_at" not in payload`. |
| lexicon-system.AC7.1 | unit | `tests/test_no_hardcoded_qa.py` | Run `grep -rn "qa_status\|qa_passed_at" src/pipeline/` programmatically. Assert zero matches. This is a static analysis gate. |
| lexicon-system.AC7.2 | integration | (full suite) | `uv run pytest` -- all tests pass. Verified by the full test run, not a single test file. |

## Human Verification

| AC ID | Justification | Verification Approach |
|---|---|---|
| lexicon-system.AC7.1 | While the grep test automates the check, a human reviewer should confirm that semantically equivalent hardcoding (e.g., `status == "passed"` outside of test fixtures or lexicon JSON) hasn't replaced the old field names while preserving the same coupling. | Code review of `src/pipeline/` after Phase 8 completion. Scan for any logic that assumes specific status string values outside of lexicon JSON definitions and the QA derivation hook. |
| lexicon-system.AC7.2 | The full test suite passing is automated, but a human should verify that test coverage is adequate -- that removed tests were replaced with lexicon-aware equivalents and no coverage gaps were introduced. | Run `uv run pytest --co -q` to list all tests. Compare test count and AC coverage against this document. Spot-check that each AC has at least one passing test. |
| lexicon-system.AC2.1 | Automated tests use `tmp_path` with synthetic config. A human should verify the real `pipeline/config.json` loads correctly with the actual lexicon files in `pipeline/lexicons/`. | Run `uv run registry-api` and confirm startup succeeds without lexicon load errors. |
| lexicon-system.AC5.6 | Integration test mocks the HTTP call. A human should verify the actual end-to-end flow: crawler POSTing to a running registry with lexicon-driven payloads. | Start the registry API, run the crawler against a test directory tree, and inspect the created deliveries via `GET /deliveries`. Confirm `lexicon_id` and `status` fields are present and correct. |
| lexicon-system.AC6.1 | WebSocket broadcast is tested indirectly via DB event records. A human should verify the actual WebSocket stream delivers the correct payload shape to a connected client. | Start the registry API, connect a WebSocket client to `/ws`, POST a delivery, and inspect the received event payload for `lexicon_id`, `status`, `metadata` keys. |
