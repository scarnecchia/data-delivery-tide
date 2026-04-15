# Sub-Delivery System — Phase 2: Crawler Sub-Directory Discovery

**Goal:** Extend the crawler to discover configured sub-directories inside matched terminal directories and register them as separate deliveries with their own lexicon, inventory, fingerprint, and manifest.

**Architecture:** After the crawler creates a parent `ParsedDelivery`, it checks the parent lexicon's `sub_dirs` field. For each configured sub-directory that exists on disk, it creates an additional `ParsedDelivery` with the sub-directory's lexicon ID and the parent's derived status. Sub-deliveries go through the same inventory → fingerprint → manifest → POST pipeline as parent deliveries.

**Tech Stack:** Python 3.10+ stdlib only

**Scope:** Phase 2 of 3 from sub-deliveries design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### sub-deliveries.AC4: Crawler sub-directory discovery
- **sub-deliveries.AC4.1 Success:** Crawler finds sub-directory inside terminal directory and creates separate `ParsedDelivery`
- **sub-deliveries.AC4.2 Success:** Sub-delivery `source_path` includes the sub-directory
- **sub-deliveries.AC4.3 Success:** Sub-delivery inherits `request_id`, `project`, `workplan_id`, `dp_id`, `version` from parent
- **sub-deliveries.AC4.4 Success:** Sub-delivery inherits status from parent's `dir_map` resolution
- **sub-deliveries.AC4.5 Success:** Sub-delivery gets its own `delivery_id` (SHA-256 of its own source_path)
- **sub-deliveries.AC4.6 Success:** Sub-delivery gets its own file inventory and fingerprint
- **sub-deliveries.AC4.7 Edge:** Missing sub-directory on disk is silently skipped
- **sub-deliveries.AC4.8 Success:** Sub-deliveries are included in derive hook pass grouped by their own lexicon

---

<!-- START_TASK_1 -->
### Task 1: Extend `crawl()` to discover sub-deliveries

**Verifies:** sub-deliveries.AC4.1, sub-deliveries.AC4.2, sub-deliveries.AC4.3, sub-deliveries.AC4.4, sub-deliveries.AC4.5, sub-deliveries.AC4.6, sub-deliveries.AC4.7

**Files:**
- Modify: `src/pipeline/crawler/main.py`

**Implementation:**

In the `crawl()` function, after a parent `ParsedDelivery` is successfully created and inventoried (after `delivery_data[result.source_path] = ...`), add sub-delivery discovery:

```python
        # --- Sub-delivery discovery ---
        for sub_dir_name, sub_lexicon_id in lexicon.sub_dirs.items():
            sub_path = os.path.join(source_path, sub_dir_name)
            if not os.path.isdir(sub_path):
                continue

            sub_lexicon = lexicons.get(sub_lexicon_id)
            if sub_lexicon is None:
                # Should not happen — loader validates sub_dirs references.
                # Log and skip defensively.
                logger.warning(
                    f"sub_dirs references unknown lexicon '{sub_lexicon_id}', skipping",
                    extra={"source_path": source_path, "sub_dir": sub_dir_name},
                )
                continue

            sub_delivery = ParsedDelivery(
                request_id=result.request_id,
                project=result.project,
                request_type=result.request_type,
                workplan_id=result.workplan_id,
                dp_id=result.dp_id,
                version=result.version,
                status=result.status,
                source_path=sub_path,
                scan_root=result.scan_root,
            )

            sub_files = inventory_files(sub_path)
            sub_fingerprint = compute_fingerprint(sub_files)
            sub_manifest = build_manifest(
                sub_delivery, sub_files, sub_fingerprint,
                config.crawler_version, now, sub_lexicon_id,
            )

            sub_delivery_id = sub_manifest["delivery_id"]
            sub_manifest_path = os.path.join(manifest_dir, f"{sub_delivery_id}.json")
            with open(sub_manifest_path, "w") as f:
                json.dump(sub_manifest, f, indent=2)

            parsed_deliveries.append(sub_delivery)
            delivery_data[sub_delivery.source_path] = (sub_files, sub_fingerprint, sub_manifest)
            delivery_lexicons[sub_delivery.source_path] = (sub_lexicon_id, sub_lexicon)
```

This code goes right after the parent's manifest write and delivery data registration, inside the same `for source_path, scan_root in candidates:` loop.

**Key details:**
- `sub_delivery.source_path` is the full path including the sub-directory (e.g., `.../msoc/scdm_snapshot`), giving it a unique `delivery_id`
- All identity fields (`request_id`, `project`, `workplan_id`, `dp_id`, `version`) are copied from the parent
- `status` is copied from the parent — not derived from the sub-lexicon's `dir_map`
- `inventory_files(sub_path)` scans only the sub-directory's direct `.sas7bdat` files
- Sub-deliveries are added to `parsed_deliveries` and `delivery_lexicons` so they participate in Pass 2 (derivation + POST)

**Tests:** See Task 2.

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Tests for crawler sub-delivery discovery

**Verifies:** sub-deliveries.AC4.1 through sub-deliveries.AC4.8

**Files:**
- Modify: `tests/crawler/test_main.py`

**Implementation:**

Add a new test class `TestSubDeliveryDiscovery` in `tests/crawler/test_main.py`. These tests need a test config with a lexicon that has `sub_dirs`, a sub-lexicon, and a directory tree with the sub-directory present.

Use the existing test patterns from `tests/crawler/test_main.py` — the file already has fixtures for creating delivery directory trees and mocking the registry API.

**Tests:**

1. **`test_sub_delivery_created_when_sub_dir_exists`** (AC4.1, AC4.2): Create a directory tree with `msoc/scdm_snapshot/` containing a `.sas7bdat` file. Configure a lexicon with `sub_dirs: {"scdm_snapshot": "soc.scdm"}`. Run `crawl()`. Assert the registry API received a POST for both the parent delivery and the sub-delivery. Assert the sub-delivery's `source_path` ends with `/scdm_snapshot`.

2. **`test_sub_delivery_inherits_parent_identity`** (AC4.3): Same setup. Assert the sub-delivery POST payload has the same `request_id`, `project`, `workplan_id`, `dp_id`, `version` as the parent.

3. **`test_sub_delivery_inherits_parent_status`** (AC4.4): Create tree with `msoc/scdm_snapshot/`. The parent terminal dir `msoc` maps to `"passed"`. Assert the sub-delivery is POSTed with `status="passed"`.

4. **`test_sub_delivery_has_own_delivery_id`** (AC4.5): Assert the sub-delivery's `delivery_id` (in the POST payload) differs from the parent's. Verify it equals `sha256(sub_source_path)`.

5. **`test_sub_delivery_has_own_file_inventory`** (AC4.6): Put different `.sas7bdat` files in `msoc/` and `msoc/scdm_snapshot/`. Assert the parent and sub-delivery POSTs have different `file_count` and `total_bytes` values.

6. **`test_missing_sub_dir_silently_skipped`** (AC4.7): Configure `sub_dirs: {"scdm_snapshot": "soc.scdm"}` but don't create the `scdm_snapshot/` directory. Run `crawl()`. Assert only the parent delivery is POSTed — no error, no sub-delivery.

7. **`test_sub_deliveries_grouped_by_own_lexicon_for_derivation`** (AC4.8): Create multiple version directories, each with `msoc_new/scdm_snapshot/`. The parent lexicon has a derive hook. The sub-lexicon does not. Assert sub-deliveries are NOT affected by the parent's derive hook (their status stays as inherited from parent, not modified by supersession logic).

**Fixture setup pattern:**

The tests will need:
- A `tmp_path`-based directory tree
- Lexicon JSON files written to a temp lexicons dir (reuse `make_lexicon_file` from conftest or create inline)
- A mock registry API (use `unittest.mock.patch` on `pipeline.crawler.http.post_delivery` as existing tests do)
- A test config object with `scan_roots`, `lexicons_dir`, `crawl_manifest_dir`, etc.

Follow the patterns already established in `tests/crawler/test_main.py` for fixture setup and config construction.

<!-- END_TASK_2 -->
