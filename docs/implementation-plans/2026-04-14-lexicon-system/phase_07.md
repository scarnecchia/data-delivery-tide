# Lexicon System Implementation Plan — Phase 7: Event System Alignment

**Goal:** Verify and test that event payloads carry `lexicon_id`, `status`, and `metadata` instead of `qa_status`/`qa_passed_at`. The event consumer handles updated payload shape.

**Architecture:** Event payloads are already derived from `DeliveryResponse.model_dump()` (updated in Phase 3) and emitted in routes (updated in Phase 4). This phase verifies the pipeline end-to-end: events emitted by POST/PATCH contain the new fields, the consumer processes them, and no old field names leak through.

**Tech Stack:** Python 3.10+, FastAPI, websockets, httpx

**Scope:** Phase 7 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase implements and tests:

### lexicon-system.AC6: Event system
- **lexicon-system.AC6.1 Success:** `delivery.created` event payload contains `lexicon_id`, `status`, `metadata`
- **lexicon-system.AC6.2 Success:** `delivery.status_changed` event payload contains updated `status` and `metadata`
- **lexicon-system.AC6.3 Success:** Event payloads do not contain `qa_status` or `qa_passed_at`

---

<!-- START_TASK_1 -->
### Task 1: Write event payload shape tests

**Verifies:** lexicon-system.AC6.1, lexicon-system.AC6.2, lexicon-system.AC6.3

**Files:**
- Modify: `tests/registry_api/test_routes.py` (update existing event tests or add new class)

**Implementation:**

The existing test file `tests/registry_api/test_routes.py` already has event tests (e.g., `test_new_delivery_creates_event`). These were updated in Phase 3 to use `status`/`lexicon_id` in payloads. This phase adds explicit assertions about event payload shape.

**Testing:**

Tests must verify each AC listed above:

- **lexicon-system.AC6.1:** POST a new delivery (triggers `delivery.created`). Query events from DB. Assert event payload dict contains keys `lexicon_id`, `status`, `metadata`. Assert `lexicon_id` matches the posted value. Assert `status` matches. Assert `metadata` is a dict.
- **lexicon-system.AC6.2:** POST a delivery with `status="pending"`, then PATCH with `status="passed"`. Query events. Find the `delivery.status_changed` event. Assert payload contains `status="passed"` and `metadata` with `passed_at` timestamp (from `set_on` rule).
- **lexicon-system.AC6.3:** For both events from AC6.1 and AC6.2, assert `"qa_status" not in payload` and `"qa_passed_at" not in payload`.

Use the existing `get_events(db)` helper pattern from the test file to query and deserialize events directly from SQLite.

**Verification:**

```bash
uv run pytest tests/registry_api/test_routes.py -v -k "event"
```

Expected: All event tests pass.

**Commit:** `test: add AC6.1-AC6.3 coverage for event payload shape`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Verify consumer handles updated payloads

**Verifies:** lexicon-system.AC6.1 (consumer side)

**Files:**
- Check: `src/pipeline/events/consumer.py` (verify no `qa_status`/`qa_passed_at` references)
- Modify or check: `tests/events/test_consumer.py` (update any assertions referencing old field names)

**Implementation:**

The `EventConsumer` at `src/pipeline/events/consumer.py` is payload-agnostic — it passes through `dict` payloads to the `on_event` callback without inspecting field names. Verify this by grepping:

```bash
grep -n "qa_status\|qa_passed_at" src/pipeline/events/consumer.py
```

Expected: zero matches.

If consumer tests exist and assert specific payload field names (`qa_status`, `qa_passed_at`), update those assertions to use `status`, `lexicon_id`, `metadata`.

If no consumer tests reference payload field names (likely — the consumer just checks `seq` for dedup), no changes needed. Mark as verified by inspection.

**Verification:**

```bash
uv run pytest tests/events/ -v
```

Expected: All tests pass (or N/A if no event-specific tests exist that check field names).

**Commit:** No commit if no changes needed. If updates required: `test: update consumer tests for lexicon event payload`

<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Run full test suite, verify no regressions

**Verifies:** None (regression check)

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: All tests pass.

**Commit:** No commit if clean.

<!-- END_TASK_3 -->
