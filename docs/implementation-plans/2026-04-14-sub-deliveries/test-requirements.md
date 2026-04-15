# Sub-Delivery System -- Test Requirements

Maps each acceptance criterion from the sub-deliveries design to specific automated tests and human verification steps.

**Source:** `docs/design-plans/2026-04-14-sub-deliveries.md`

**Generated:** 2026-04-14

---

## Automated Tests

| AC ID | Test Type | Test File | Description |
|---|---|---|---|
| sub-deliveries.AC1.1 | unit | `tests/lexicons/test_loader.py` | Load a lexicon with `sub_dirs` field. Assert `lexicon.sub_dirs` is a `dict[str, str]` with correct mapping. |
| sub-deliveries.AC1.2 | unit | `tests/lexicons/test_loader.py` | Load a lexicon without `sub_dirs` field. Assert `lexicon.sub_dirs == {}`. |
| sub-deliveries.AC1.3 | unit | `tests/lexicons/test_loader.py` | Create base with `sub_dirs`, child extends it. Assert child inherits `sub_dirs`. Also test child overriding with additional entries (deep merge). |
| sub-deliveries.AC2.1 | unit | `tests/lexicons/test_loader.py` | Create lexicon with `sub_dirs` referencing an existing lexicon ID. Assert loads successfully. |
| sub-deliveries.AC2.2 | unit | `tests/lexicons/test_loader.py` | Create lexicon with `sub_dirs` referencing a non-existent lexicon ID. Assert `LexiconLoadError` with message mentioning "unknown lexicon". |
| sub-deliveries.AC2.3 | unit | `tests/lexicons/test_loader.py` | Load a lexicon without `sub_dirs`. Assert loads successfully (backward compatible). Covered by existing tests. |
| sub-deliveries.AC2.4 | unit | `tests/lexicons/test_loader.py` | Create lexicon A with `sub_dirs` pointing to lexicon B. Lexicon B has its own `sub_dirs`. Assert `LexiconLoadError` with message mentioning "recursive nesting". |
| sub-deliveries.AC3.1 | -- | -- | JSON Schema validation is editor-side. Verified by manual review. |
| sub-deliveries.AC3.2 | -- | -- | Existing lexicon files without `sub_dirs` continue to validate. Verified by existing tests loading without error. |
| sub-deliveries.AC4.1 | integration | `tests/crawler/test_main.py` | Create directory tree with terminal dir containing a sub-directory. Run `crawl()`. Assert sub-delivery POSTed to registry. |
| sub-deliveries.AC4.2 | integration | `tests/crawler/test_main.py` | Assert sub-delivery's `source_path` in POST payload ends with the sub-directory name. |
| sub-deliveries.AC4.3 | integration | `tests/crawler/test_main.py` | Assert sub-delivery POST payload has same `request_id`, `project`, `workplan_id`, `dp_id`, `version` as parent. |
| sub-deliveries.AC4.4 | integration | `tests/crawler/test_main.py` | Terminal dir maps to "passed" via `dir_map`. Assert sub-delivery POSTed with `status="passed"`. |
| sub-deliveries.AC4.5 | integration | `tests/crawler/test_main.py` | Assert sub-delivery `delivery_id` differs from parent and equals `sha256(sub_source_path)`. |
| sub-deliveries.AC4.6 | integration | `tests/crawler/test_main.py` | Put different files in parent dir and sub-dir. Assert different `file_count`/`total_bytes` in their respective POSTs. |
| sub-deliveries.AC4.7 | integration | `tests/crawler/test_main.py` | Configure `sub_dirs` but don't create the sub-directory on disk. Assert only parent delivery POSTed. No error. |
| sub-deliveries.AC4.8 | integration | `tests/crawler/test_main.py` | Create multiple versions with sub-deliveries. Parent lexicon has derive hook, sub-lexicon does not. Assert sub-deliveries are not affected by parent's derivation logic. |
| sub-deliveries.AC5.1 | integration | `tests/registry_api/test_routes.py` | POST parent and sub-delivery with different `lexicon_id`. GET with sub-delivery's `lexicon_id` filter. Assert only sub-delivery returned. |
| sub-deliveries.AC5.2 | integration | `tests/registry_api/test_routes.py` | POST parent and sub-delivery with same identity fields. GET by `request_id`. Assert both returned with matching identity but different `delivery_id` and `lexicon_id`. |
| sub-deliveries.AC5.3 | integration | `tests/registry_api/test_routes.py` | POST sub-delivery with actionable status and null `parquet_converted_at`. GET `/deliveries/actionable`. Assert sub-delivery appears. |
| sub-deliveries.AC5.4 | integration | `tests/registry_api/test_routes.py` | POST new sub-delivery. GET `/events?after=0`. Assert `delivery.created` event with sub-delivery's `lexicon_id`. |
| sub-deliveries.AC6.1 | unit | `tests/lexicons/test_loader.py` | Load from real `pipeline/lexicons/` directory. Assert `soc.scdm` exists, extends `soc._base`, has no derive hook and empty `sub_dirs`. |
| sub-deliveries.AC6.2 | unit | `tests/lexicons/test_loader.py` | Assert `soc.qar` and `soc.qmr` have `sub_dirs == {"scdm_snapshot": "soc.scdm"}`. |

## Human Verification

| Criterion | Why Manual | Steps |
|-----------|-----------|-------|
| sub-deliveries.AC3.1 | JSON Schema validation is an editor feature, not runtime | Open `soc/qar.json` in VS Code, verify `sub_dirs` field gets autocompletion and validates against the schema |
| sub-deliveries.AC4.1 | Automated tests use mock registry; need to verify actual crawler → registry flow | Create a test directory tree with `msoc/scdm_snapshot/`, run crawler against real registry API, verify both deliveries appear in `GET /deliveries` |
| sub-deliveries.AC5.1-AC5.4 | Automated tests use HTTPX test client; need to verify actual API behaviour | Start registry API, POST parent + sub-delivery manually, verify queries return expected results |
