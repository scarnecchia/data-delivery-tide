# Lexicon System Implementation Plan — Phase 6: QA Derivation Hook

**Goal:** Implement the QA-specific "superseded pending → failed" derivation as a hook function, extracted from the current `derive_qa_statuses` in `parser.py`. The hook must produce identical results to the current implementation for all existing test cases.

**Architecture:** The hook function at `pipeline.lexicons.soc.qa:derive` receives a list of `ParsedDelivery` objects and a `Lexicon`, groups by `(workplan_id, dp_id)`, sorts by version descending, and marks non-highest pending deliveries as failed. This is a direct extraction of `derive_qa_statuses` logic with the added `Lexicon` parameter for the hook contract. The lexicon's `soc/qar.json` references this hook via `"derive_hook": "pipeline.lexicons.soc.qa:derive"`.

**Tech Stack:** Python 3.10+ stdlib

**Scope:** Phase 6 of 8 from original design

**Codebase verified:** 2026-04-14

---

## Acceptance Criteria Coverage

This phase completes testing for:

### lexicon-system.AC5: Crawler generalisation (hook-specific)
- **lexicon-system.AC5.3 Success:** Derivation hook called when `derive_hook` is set
- **lexicon-system.AC5.5 Success:** QA hook marks superseded pending as failed (identical to current behaviour)

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Create QA derivation hook module

**Verifies:** None (implementation — tested in Task 2)

**Files:**
- Create: `src/pipeline/lexicons/soc/__init__.py`
- Create: `src/pipeline/lexicons/soc/qa.py`
- Modify: `pipeline/lexicons/soc/qar.json` (add `derive_hook` field)

**Implementation:**

Extract the grouping, sorting, and supersession logic from `src/pipeline/crawler/parser.py:116-156` (the current `derive_qa_statuses` and its helpers `_group_key`, `_version_sort_key`) into the new hook module.

`src/pipeline/lexicons/soc/__init__.py`: empty file

`src/pipeline/lexicons/soc/qa.py`:

```python
# pattern: Functional Core
from dataclasses import replace
from itertools import groupby

from pipeline.crawler.parser import ParsedDelivery
from pipeline.lexicons.models import Lexicon


def _group_key(delivery: ParsedDelivery) -> tuple[str, str]:
    return (delivery.workplan_id, delivery.dp_id)


def _version_sort_key(delivery: ParsedDelivery) -> str:
    return delivery.version


def derive(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
    """Derive 'failed' status for pending deliveries superseded by newer versions.

    Within each (workplan_id, dp_id) group, any pending delivery that is NOT
    the highest version is marked as failed. Passed deliveries are never changed.

    Returns a new list — does not mutate the input.
    """
    if not deliveries:
        return []

    result = []
    sorted_deliveries = sorted(deliveries, key=_group_key)

    for _key, group in groupby(sorted_deliveries, key=_group_key):
        group_list = list(group)
        if len(group_list) == 1:
            result.append(group_list[0])
            continue

        by_version = sorted(group_list, key=_version_sort_key, reverse=True)
        highest_version = by_version[0].version

        for delivery in group_list:
            if delivery.status == "pending" and delivery.version != highest_version:
                result.append(replace(delivery, status="failed"))
            else:
                result.append(delivery)

    return result
```

Note the only differences from the original `derive_qa_statuses`:
1. Added `lexicon: Lexicon` parameter (hook contract)
2. References `delivery.status` instead of `delivery.qa_status` (renamed in Phase 5)
3. Uses `replace(delivery, status="failed")` instead of `replace(delivery, qa_status="failed")`

After creating this module, also clean up `src/pipeline/crawler/parser.py`:
- Remove `_group_key` and `_version_sort_key` helper functions
- Remove the inline QA supersession fallback from `derive_statuses` — it now simply delegates to the hook or returns deliveries unchanged:

```python
def derive_statuses(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
    if lexicon.derive_hook is not None:
        return lexicon.derive_hook(deliveries, lexicon)
    return list(deliveries)
```

After creating the hook module, update `pipeline/lexicons/soc/qar.json` to add the derive_hook reference:

```json
{
  "extends": "soc._base",
  "derive_hook": "pipeline.lexicons.soc.qa:derive",
  "metadata_fields": {
    "passed_at": {
      "type": "datetime",
      "set_on": "passed"
    }
  }
}
```

This was intentionally omitted in Phase 1 to avoid import failures before the hook module existed. Now that it exists, the reference resolves correctly.

**Verification:**

```bash
python -c "from pipeline.lexicons.soc.qa import derive; print('OK')"
```

Expected: `OK`

**Commit:** `feat: extract QA derivation hook to pipeline.lexicons.soc.qa`

<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Write derivation hook tests

**Verifies:** lexicon-system.AC5.3, lexicon-system.AC5.5

**Files:**
- Create: `tests/lexicons/test_qa_hook.py`

**Implementation:**

Port the existing derivation tests from `tests/crawler/test_parser.py` that test `derive_qa_statuses` (check what exists — the existing test class likely has tests for supersession logic). Write equivalent tests calling the new `derive()` hook function.

The test needs a `Lexicon` fixture for the QAR lexicon:

```python
from pipeline.lexicons.models import Lexicon, MetadataField

QAR_LEXICON = Lexicon(
    id="soc.qar",
    statuses=("pending", "passed", "failed"),
    transitions={"pending": ("passed", "failed"), "passed": (), "failed": ()},
    dir_map={"msoc": "passed", "msoc_new": "pending"},
    actionable_statuses=("passed",),
    metadata_fields={"passed_at": MetadataField(type="datetime", set_on="passed")},
    derive_hook=None,  # Not used inside the hook itself
)
```

**Testing:**

Tests must verify:

- **lexicon-system.AC5.3:** Call `derive()` with a list of deliveries and the QAR lexicon. Assert it returns a modified list (proves hook was called and executed).
- **lexicon-system.AC5.5:** Specific supersession cases (must produce identical results to old `derive_qa_statuses`):
  - Two pending deliveries in same (workplan_id, dp_id) with different versions → lower version becomes "failed", higher stays "pending"
  - Single delivery → returned unchanged
  - Passed delivery with lower version → stays "passed" (never changed)
  - Mixed statuses: passed v01, pending v02, pending v03 → v01 stays passed, v02 becomes failed, v03 stays pending
  - Empty list → returns empty list
  - Deliveries in different (workplan_id, dp_id) groups → each group handled independently

Follow project patterns: class-based tests, docstrings referencing ACs.

**Verification:**

```bash
uv run pytest tests/lexicons/test_qa_hook.py -v
```

Expected: All tests pass.

**Commit:** `test: add QA derivation hook tests covering AC5.3, AC5.5`

<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_3 -->
### Task 3: Run full test suite, verify no regressions

**Verifies:** None (regression check)

**Files:** None (read-only)

**Verification:**

```bash
uv run pytest -v
```

Expected: All tests pass. The `soc/qar.json` derive_hook reference now resolves, so any tests that load the real config should pass.

**Commit:** No commit if clean.

<!-- END_TASK_3 -->
