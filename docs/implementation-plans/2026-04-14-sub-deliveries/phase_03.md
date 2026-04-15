# Sub-Delivery System — Phase 3: Integration Validation and Documentation

**Goal:** Verify end-to-end integration of sub-deliveries through the registry API, update all documentation to reflect the `sub_dirs` feature.

**Architecture:** No new production code — this phase adds integration tests that exercise the full path (crawler → registry API → query) and updates documentation.

**Tech Stack:** Python 3.10+, pytest, httpx

**Scope:** Phase 3 of 3 from sub-deliveries design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### sub-deliveries.AC5: Integration
- **sub-deliveries.AC5.1 Success:** Sub-deliveries appear in `GET /deliveries?lexicon_id=soc.scdm`
- **sub-deliveries.AC5.2 Success:** Parent and sub-delivery are correlated by `(request_id, workplan_id, dp_id, version)`
- **sub-deliveries.AC5.3 Success:** Sub-deliveries appear in actionable query when their lexicon's `actionable_statuses` match
- **sub-deliveries.AC5.4 Success:** Events emitted for sub-deliveries with correct `lexicon_id`

---

<!-- START_TASK_1 -->
### Task 1: Integration tests for sub-deliveries through the API

**Verifies:** sub-deliveries.AC5.1, sub-deliveries.AC5.2, sub-deliveries.AC5.3, sub-deliveries.AC5.4

**Files:**
- Modify: `tests/registry_api/test_routes.py`

**Implementation:**

Add a new test class `TestSubDeliveryIntegration` in `tests/registry_api/test_routes.py`.

These tests exercise the API directly (not the crawler). They POST parent and sub-deliveries with different `lexicon_id` values and verify query behaviour.

The test setup needs `app.state.lexicons` to include both a parent lexicon (e.g., with `sub_dirs`) and a sub-lexicon. Use the existing `TEST_LEXICON` pattern from `tests/conftest.py` but add a second lexicon for the sub-delivery type.

**Tests:**

1. **`test_sub_delivery_queryable_by_lexicon_id`** (AC5.1): POST a parent delivery with `lexicon_id="test.parent"` and a sub-delivery with `lexicon_id="test.sub"`. GET `/deliveries?lexicon_id=test.sub`. Assert only the sub-delivery is returned.

2. **`test_parent_and_sub_correlated_by_identity`** (AC5.2): POST parent and sub-delivery with the same `request_id`, `workplan_id`, `dp_id`, `version` but different `source_path` and `lexicon_id`. GET `/deliveries?request_id=<id>`. Assert both are returned with matching identity fields but different `delivery_id` and `lexicon_id`.

3. **`test_sub_delivery_appears_in_actionable`** (AC5.3): POST a sub-delivery with a status matching the sub-lexicon's `actionable_statuses` and `parquet_converted_at=null`. GET `/deliveries/actionable`. Assert the sub-delivery appears.

4. **`test_sub_delivery_creation_emits_event`** (AC5.4): POST a new sub-delivery. GET `/events?after=0`. Assert a `delivery.created` event exists with `lexicon_id` matching the sub-delivery's lexicon.

**Fixture considerations:**

The existing `conftest.py` sets up `app.state.lexicons` with a single `TEST_LEXICON`. For these tests, add a second test lexicon to `app.state.lexicons`:

```python
TEST_SUB_LEXICON = Lexicon(
    id="test.sub",
    statuses=("pending", "passed", "failed"),
    transitions={"pending": ("passed", "failed"), "passed": (), "failed": ()},
    dir_map={"msoc": "passed", "msoc_new": "pending"},
    actionable_statuses=("passed",),
    metadata_fields={},
)
```

Add it in the test class's setup or as a fixture, adding it to `app.state.lexicons["test.sub"]`.

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update documentation

**Verifies:** (documentation — no AC)

**Files:**
- Modify: `src/pipeline/lexicons/CLAUDE.md`
- Modify: `src/pipeline/crawler/CLAUDE.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Implementation:**

**`src/pipeline/lexicons/CLAUDE.md`:**

In the **Contracts** section, update the `Lexicon` dataclass description to mention `sub_dirs`.

In the **Invariants** section, add:
- `sub_dirs` maps directory names to lexicon IDs for sub-delivery discovery
- Referenced sub-lexicons must exist and must not themselves have `sub_dirs` (no recursive nesting)

In the **Gotchas** section, add:
- `sub_dirs` validation runs after all lexicons are built (post-build pass), not during per-lexicon validation

**`src/pipeline/crawler/CLAUDE.md`:**

In the **Contracts** section, update to mention sub-delivery discovery from lexicon `sub_dirs`.

In the **Invariants** section, add:
- After matching a terminal directory, the crawler checks the lexicon's `sub_dirs` for known subdirectories
- Sub-deliveries inherit identity and status from the parent, get their own source_path, delivery_id, and file inventory
- Missing sub-directories are silently skipped (not an error)

In the **Gotchas** section, add:
- `inventory_files` uses `os.scandir` (direct children only), so parent file inventory naturally excludes sub-directory contents — no special filtering needed

**`CLAUDE.md`:**

In the **Conventions** section, add a bullet:
- Lexicons can declare `sub_dirs` mapping subdirectory names to lexicon IDs; the crawler discovers these inside terminal directories and registers them as separate deliveries correlated to the parent by shared identity fields

**`README.md`:**

In the **Lexicons** section, add to the field table:

| `sub_dirs` | Maps subdirectory names inside terminal directories to lexicon IDs for sub-delivery registration |

Add a brief note after the lexicon descriptions:

> Lexicons can declare `sub_dirs` to register subsidiary data (e.g., SCDM snapshots inside QAR/QMR deliveries) as separate, independently queryable deliveries. Sub-deliveries inherit status from their parent but have their own file inventory and conversion tracking.

<!-- END_TASK_2 -->
