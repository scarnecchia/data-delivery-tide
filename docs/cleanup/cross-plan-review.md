# Cross-Plan Implementation Review
Date: 2026-04-29

## Summary

Twelve plans across four DAG tiers; the merge order in `docs/project/DAG.md` is sound and most plans correctly reason about their upstreams. However, there are several real cross-plan contradictions and one bona-fide bug worth fixing before execution: GH27 prepends a label to two test files that GH21 then rewrites the import block of, GH21's design vs ACs disagree on whether `unittest.mock` is fully purged (the plans pick AC over DoD but flag the tension), and GH17 plus GH28 both touch `lexicons/models.py` with different shapes than what GH19 ships. The DAG's listed conflict hotspots are sequenced correctly by tier order. Most "unchanged tests" claims in design docs are honestly contradicted in the implementation plans, and the contradictions are resolved in favour of correctness.

## Critical Issues

### C1. GH17 Phase 5 prescribes a `routes.py` shape that conflicts with GH19's deliberate handler-return policy

- GH19 `phase_02.md:670-682` documents the deliberate decision to annotate route handlers as returning `dict` / `list[dict]` and let FastAPI's `response_model` shape the wire output. GH19's test-requirements (`test-requirements.md:25-32`) repeats this contract: "handlers return Python dicts; annotating handlers as their `response_model` would mis-type their actual return value."
- GH17 `phase_05.md` Task 4 (`fix arg-type`) tells the implementor to rewrite `list_all_deliveries` to `items=[DeliveryResponse.model_validate(item) for item in items]` so the Pydantic constructor receives a `list[DeliveryResponse]`.
- This *itself* is consistent with the dict-return signature, but later GH20 `phase_05.md` Task 2 then changes that exact same code path *again* to `items=[dataclasses.asdict(item) for item in items]` because by Tier 3 `list_deliveries` returns `list[DeliveryRecord]`, and instructs that **`return dataclasses.asdict(result)`** is the route's return.
- Net effect: GH17 Phase 5 will edit a line that GH20 Phase 5 will rewrite differently four hours later. Both the GH17 and GH20 changes are correct *for their tier's state of the codebase*, but `docs/project/17/implementation-plan/phase_05.md:288-303` does not flag the impending GH20 rewrite. **Action:** add a note to GH17 Phase 5 Task 4 acknowledging GH20 will rebuild this expression on top of dataclass returns; nothing to fix in code, but executors should not be surprised.

### C2. GH17 Phase 4 Task 3 proposes "Option A" reorder of `require_auth` parameters that breaks `auth.py`'s ordering relative to dependent files

- GH17 `phase_04.md:181-195` recommends reordering `require_auth(db: DbDep, credentials: ...)` (db first, defaulted credentials second) to satisfy mypy.
- GH19 `phase_02.md:300-323` documents `require_role` (a different function) and explicitly does not touch `require_auth` parameter order.
- GH20 `phase_05.md` Task 1 (auth.py) reads `token_row.revoked_at`, `.username`, `.role` and assumes `require_auth`'s body shape is unchanged. Re-ordering the *parameters* doesn't break this body, but if the executor has already merged GH17 with the swap and a follow-on plan (or a stale test) calls `require_auth` positionally, the swap silently breaks invocation.
- GH17's own escape hatch (Option B with `# type: ignore[assignment]`) is the safer choice, and the plan acknowledges it. **Action:** strengthen the recommendation toward Option B in the executor notes; the rename has too many co-edits in flight to risk a positional-call regression.

### C3. GH28 and GH19 Phase 4 Task 2 both rewrite `src/pipeline/lexicons/models.py` with the same target content

- GH28 `phase_01.md:51-79` rewrites the entire file.
- GH19 `phase_04.md:194-249` rewrites the entire file with byte-identical post-state, and explicitly says "If GH28 has already landed, this is a verified no-op."
- The DAG (`DAG.md:14-19`) makes GH19 the absorber: GH28 → GH19 (soft dep), with a note that GH19 absorbs GH28 if landed first. This is correct and the GH19 plan handles both orderings idempotently.
- Risk: if both branches are open and rebased independently, the executor will see a "no diff" rebase that is easy to mis-resolve. **Action (low cost):** before rebasing GH19 on top of merged GH28, run the verification grep in GH19 phase 4 Task 2 to confirm idempotency before committing.

## Important Issues

### I1. GH17 Phase 1 declares `requires-python = ">=3.11"` indirectly but assumes GH18 has landed

- GH17 `phase_01.md:97` sets `target-version = "py311"` in `[tool.ruff]` and `python_version = "3.11"` in `[tool.mypy]`.
- GH17 `phase_01.md:217` notes: "If GH18 has not landed, target-version is fine to ship — ruff and mypy honour it independently of `requires-python`."
- This is correct in the narrow sense, but GH17 Phase 2's `ruff check --fix` for `UP` rules will surface `UP006`/`UP007`/`UP035` migrations that *only* make sense under 3.11+. If `requires-python` still says `>=3.10`, the project will install on 3.10 and then fail at runtime on the rewritten syntax.
- **Action:** make GH18 a hard dep of GH17 in the DAG, not soft. The DAG has it as soft; tighten to hard.

### I2. GH21 Phase 4 contradicts its own design's Definition of Done about `unittest.mock` removal

- GH21 design (per `phase_04.md:36-37` summary) says the `AsyncMock` in `test_routes.py` is "documented as acceptable and kept with a comment".
- GH21 `phase_04.md:36-37` and Task 3 then explicitly *replace* that AsyncMock per AC5.1, calling out the design tension.
- GH21 `phase_03.md:259-263` retains `MagicMock` in `test_main.py` for legitimate logger duck-typing, which contradicts the design DoD's "Zero imports of `unittest.mock`."
- The plans pick AC over DoD and document the choice. This is the right call but the *test-requirements.md verification gate* at the bottom of `docs/project/21/test-requirements.md:48-56` correctly carves out two `unittest.mock` survivors:
  - `tests/events/test_consumer.py` (`AsyncMock`, `patch.object`, `patch("...connect")`)
  - `tests/crawler/test_main.py` (`MagicMock`)
- **Action:** none required, but reviewer should be aware. The carve-outs are deliberate and consistent across plans.

### I3. Two plans both mutate `tests/converter/test_http.py` line 39 (`b'{"detail":"Delivery not found"}'`)

- GH22 `phase_01.md:101-110` rewrites `b'{"detail":"Delivery not found"}'` to `b'{"detail":"delivery not found"}'`.
- GH21 `phase_02.md` Task 5 entirely rewrites every test method body in `test_http.py`, including the `_make_urlopen_response` helper at line 19-24 and the `http_err.read = lambda: ...` at line 39.
- DAG order: GH22 Tier 0, GH21 Tier 2 — so GH22 lands first. GH21's test rewrite includes a `read = lambda: b'{"detail":"Delivery not found"}'` snippet (`phase_02.md:529`) using **title-case** "Delivery", which would *re-introduce* the casing GH22 just lowercased.
- **Action:** GH21 Phase 2 Task 5 must use the lowercased string (`delivery not found`) since GH22 will have merged first per tier order. Fix the snippet at `docs/project/21/phase_02.md:529`.

### I4. GH27 vs GH21 ordering on `tests/crawler/test_http.py` and `tests/converter/test_http.py` line 1

- GH27 `phase_01.md:130` adds `# pattern: test file` to `tests/crawler/test_http.py:1` (currently `import json`).
- GH21 `phase_02.md:296-329` rewrites the entire top-of-file import block of both `test_http.py` files. Its rewritten template includes `# pattern: test file` at line 1, but the plan says: "prepend `# pattern: test file` if (and only if) GH27 has not already added it before this branch lands. ... The Edit tool will fail noisily on duplicate prepend."
- DAG order: GH27 Tier 0, GH21 Tier 2 — GH27 lands first, so the conditional should resolve to "do not prepend, just rewrite imports below the existing label."
- **Action:** GH21 Phase 2 Task 3's `Replace with:` block at `phase_02.md:316-328` should drop the `# pattern: test file` line so the Edit doesn't duplicate it. Or: explicitly include the existing label as part of the `old_string` to make the match exact.

### I5. GH26 will rename `TestMain.test_ac5_4_registry_unreachable_exits_nonzero` after GH21 has rewritten its body

- GH26 `phase_01.md:175-178` renames it to `test_main_registry_unreachable_exits_nonzero` and acknowledges GH21 lands first: "If GH21 lands first, the body is different but the method name still matches."
- GH21 Phase 3 Task 4 rewrites the test body but does not rename the method.
- This composes cleanly. **Action:** none.

### I6. GH20 Phase 3 (engine.py) overlaps with GH23 Phase 2 (engine.py exc_info) and GH24 (no overlap with engine.py)

- GH20 `phase_03.md:300-303` correctly anticipates GH23's edits to `engine.py:174-194` and says: "Reapply the failures-dataclass migration on top of the GH23 edits; the structural shape is identical."
- GH23 Phase 2 only adds `exc_info=True` to two existing `logger.warning` calls, which is orthogonal to GH20's `failures` dict change.
- DAG hotspot listing for `engine.py` (`#17, #19, #20, #23, #24`) is correct, but the GH24 entry is wrong — verified by reading GH24's plan, which only touches `crawler/main.py`, NOT `engine.py`. **Action:** correct the DAG hotspot table to remove GH24 from the `engine.py` row.

### I7. GH17 Phase 3 Task 3 (SIM105 in convert.py) overlaps with GH23 Phase 1 (cleanup logging in convert.py)

- GH23 `phase_01.md:81-94` replaces `try/except: pass` with `try/except: logger.debug(...)` in the convert.py cleanup block.
- GH17 `phase_03.md:236-266` says SIM105 wants `try/except: pass` rewritten as `with contextlib.suppress(...)`. After GH23 lands, the block is `try/except: logger.debug(...)` — which is *not* a SIM105 candidate (the except has a body now).
- GH17 is Tier 2, GH23 is Tier 0, so GH23 lands first, eliminating the SIM105 violation entirely. The GH17 plan does not anticipate this and may produce a "ruff already happy" no-op for SIM105 in `convert.py`.
- **Action:** GH17 Phase 3 Task 3 should run `uv run ruff check --select SIM105 src/` first to confirm hits before assuming the lines are still violations.

### I8. GH20 Phase 5 changes `dict[Any, Any]` annotations that GH17 Phase 5 Task 1 just fixed

- GH17 Phase 5 Task 1 parameterises bare `dict` → `dict[str, Any]` (~42 sites including in `db.py`).
- GH20 Phase 4 then changes db.py return types from `dict | None` → `DeliveryRecord | None`, removing or replacing many of those annotations.
- This is harmless work-on-work, but the GH17 commit's diff will include lines that GH20 then deletes. **Action:** none — the redundancy is unavoidable given the tier ordering and is small enough not to bundle.

## Minor Issues

### M1. Plan output paths inconsistent

- `docs/project/##/...` for GH17, GH18, GH19, GH20, GH21, GH23, GH25, GH26, GH27, GH28
- `docs/implementation-plans/GH22/...` for GH22
- `docs/implementation-plans/2026-04-29-GH24/...` for GH24

Three different shapes. **Action:** consolidate to `docs/project/##/...` for consistency. This is cosmetic and low-priority; flagged per the team-lead's checklist.

### M2. GH27 has no separate `test-requirements.md`

- `docs/project/27/` contains only `design.md` and `phase_01.md`.
- The phase_01.md does include AC coverage with verification commands, so the content is present but lacks the separation other plans use.
- **Action:** either accept this as adequate for a 1-commit mechanical change or extract the AC verification block into `test-requirements.md` for consistency.

### M3. GH18 phase_01.md Task 3 verifies install failure on Python 3.10 manually

- Listed as "human verification" and reasonable, but if CI does not have a Py3.10 interpreter, the AC is documented as "not-locally-verified" — the only AC across all 12 plans that ships unverified.
- **Action:** none required; the rationale is documented and PEP 440 behaviour is well-defined.

### M4. GH19 Phase 2 Task 5 pre-emptively adds `# type: ignore[assignment]` for `require_role(...)` defaults that mypy hasn't been wired yet

- These ignores will be unused warnings until GH17 Phase 1 lands `mypy --strict`.
- mypy strict's `--warn-unused-ignores` will then either pass them (if the ignore is needed) or flag them.
- **Action:** none — the comments are correct in target state and will not break anything in transit.

### M5. GH19 plan's `ConvertOneFnProtocol` vs `ConvertSasToParquetFnProtocol` naming clash

- GH19 Phase 1 introduces `ConvertOneFnProtocol`. Phase 3 discovers the design conflated two distinct seams and *adds* a second protocol `ConvertSasToParquetFnProtocol` to `protocols.py`.
- The plan handles this transparently — Phase 3 Task 1 documents the discrepancy and edits both `protocols.py` and `engine.py` together.
- **Action:** none — the plan correctly diagnoses and corrects the design's naming.

## Per-Plan Notes

- **GH17:** The single largest plan, 6 phases. Acknowledges GH19 hard-dep and GH18 soft-dep. Phase 4's "this may be a near no-op" stance is good. Phase 6's third-party-stub override decision is well-justified.
- **GH18:** Clean, surgical, only edits `pyproject.toml`. Task 2 invents a temp test file for marker verification; the cleanup step deletes it before commit. Tidy.
- **GH19:** Comprehensive 5-phase annotation pass. Honestly resolves design overreach (cls annotations on Pydantic validators, the wrong protocol name in design). Most surface-area plan after GH17.
- **GH20:** 5 phases, the most invasive type-shape refactor. Honestly contradicts the design's "no test modification" claim and rewrites tests for attribute access. Wire-shape preservation gates (the `_failure_to_wire` helper, `dataclasses.asdict()` boundaries) are well-specified.
- **GH21:** 5 phases of DI refactor; per-phase independent. Correctly carves `unittest.mock` survivors. Cross-references GH22, GH27, GH23 conflicts inline in each phase's "Notes for executor".
- **GH22:** Smallest production change in the set. Correctly identifies the 5 files and the single test assertion that pins exact strings. The grep in Step 6 is a useful safety net.
- **GH23:** 5-phase split mapping cleanly to category buckets (cleanup, exc_info, narrow except, broadcast, scandir). Each phase has its own commit; no coordination needed beyond DAG order.
- **GH24:** Mechanical 8-site substitution. Identifies a 9th site that matches the regex but isn't on the design's CS-list, and handles it in Task 2 with a documented decision. Good.
- **GH25:** Five class decorators, transparently soft-deps GH18. Verification commands are clean.
- **GH26:** Pure rename, last in DAG. Correctly notes that `tests/registry_api/test_routes.py` has 11 AC-prefix names that are *out of scope* by the design's five-file enumeration. Surface this to reviewer for a possible scope expansion.
- **GH27:** Mechanical line-1 prepend across 22 files. No `test-requirements.md` (see M2). The Task 3b handling of the blank-line-1 case in `test_parser.py` is thoughtful.
- **GH28:** Trivial single-file change, fully absorbed by GH19 if GH28 lands second.

## Conflict Hotspot Analysis

From `docs/project/DAG.md:108-114`:

| File | DAG-listed issues | Per-plan coordination | Verdict |
|------|-------------------|------------------------|---------|
| `src/pipeline/converter/engine.py` | #17, #19, #20, #23, #24 | GH24 does NOT touch this file (verified — GH24 only touches `crawler/main.py`). #17 (formatting), #19 (signatures), #20 (FileConversionSuccess/Failure dataclasses), #23 (exc_info) all properly tier-sequenced. | DAG entry should drop #24. Sequencing otherwise correct. |
| `src/pipeline/registry_api/routes.py` | #17, #19, #20, #22 | GH22 (lowercase strings, 4 lines) → GH19 (signatures, all handlers) → GH17 (formatting + arg-type fixes) → GH20 (asdict and attribute access). Each plan acknowledges the next via "Conflict surface" notes. | Sequencing correct; expect a sizeable diff in GH20 Phase 5 since it rewrites lines GH17 Phase 5 Task 4 just rewrote (see C1, I8). |
| `src/pipeline/crawler/main.py` | #19, #20, #23, #24 | GH23 Phase 5 (scandir OSError sites, 4 spots in walk_roots) → GH24 (8 log f-string sites in walk_roots and crawl) → GH19 (annotations on walk_roots/crawl/main) → GH20 (WalkResult, DeliveryAccumulator, manifest.delivery_id reads). Each plan touches different lines or different concerns. | Coordinated; GH24 might add `extra={"path": ...}` to a log call that GH23 then changes — verify before committing. Risk is low because the changes are textually distinct sites within walk_roots. |
| `tests/crawler/test_main.py` | #20, #21, #24, #26, #27 | GH27 (line 1 label) → GH24 (no — GH24 only modifies the crawler source's log calls, not its tests) → GH23 (no — adds tests, doesn't rename existing) → GH21 (15 @patch removals + TestMain rewrite) → GH20 (WalkResult attribute updates) → GH26 (32 method renames). | The DAG entry includes #24 incorrectly — GH24 makes assertions about log message *content* in tests but doesn't rewrite them in the plan. Sequencing of #21 → #20 → #26 is correct: DI scaffolding, then dataclass attribute reads, then renames. |
| `tests/registry_api/test_routes.py` | #20, #21, #22, #27 | GH27 (line 1 label) → GH22 (line 1325 string) → GH21 (FakeWebSocket replacement) → GH20 (no test changes per the GH20 plan — `test_routes.py` operates on `response.json()`). | Coordinated correctly. The DAG mentions GH20 here, but GH20's own plan says `test_routes.py` is "unaffected because it operates on response.json()". Mild mismatch — the DAG hotspots row could drop #20 from this file. |

DAG corrections suggested: drop #24 from `engine.py` and `tests/crawler/test_main.py`; drop #20 from `tests/registry_api/test_routes.py`. None are blocking — the tier ordering still produces correct merges.

## Net assessment

The plan set is in good shape for execution. The most consequential issue to fix before kicking off is **I3** (GH21 Phase 2 Task 5 must use the lowercased "delivery not found" string post-GH22). **I1** (promote GH18 to hard dep of GH17) and **I4** (GH21 Phase 2 Task 3's conditional prepend handling) are simple to address in plan-text edits. The remaining items are documentation polish or executor-awareness notes.
