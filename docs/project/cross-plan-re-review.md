# Cross-Plan Re-Review
Date: 2026-04-29

## Fix Verification

- **C1 (GH17 Phase 5 — flag GH20 rewrite of `list_all_deliveries`): PASS.** `docs/project/17/implementation-plan/phase_05.md:306` carries the upstream note: "GH20 Phase 5 will rewrite this expression again when deliveries become frozen dataclasses. This edit is correct for the post-GH19 codebase state; the GH20 executor will rebuild it on top of dataclass returns." Placement is correct (immediately after the fix snippet, before the Step 1 instructions). Accurate, terse, non-actionable as intended.

- **C2 (GH17 Phase 4 — strengthen Option B recommendation for `require_auth`): PASS.** `docs/project/17/implementation-plan/phase_04.md:208` now states: "**Recommended:** Use Option B. Multiple downstream plans (GH20, GH21) assume require_auth's current parameter order. Reordering risks positional-call regressions across concurrent branches." The note is well-placed (between the Option B definition and the Step 1 grep) and correctly inverts the prior tilt toward Option A. Mild internal tension: Step 1 still says "If `require_auth` is only invoked via `Depends()` ... choose Option A" — that's not contradictory (the recommendation is a preference, the grep still gates the choice), but a vigilant executor might see the two cues as competing. Acceptable, not a blocker.

- **I1 (GH17 Phase 1 — note GH18 as hard dep): PASS.** `docs/project/17/implementation-plan/phase_01.md:219` adds: "**DAG correction:** GH18 should be a hard dependency of GH17, not soft. GH17 Phase 2's UP rule migrations produce 3.11+ syntax that will fail at runtime if requires-python still allows 3.10. Ensure GH18 has merged before executing GH17." Note the pre-existing line 217 still reads as if GH18 may not have landed and that's "fine to ship" — the new line correctly overrides this for the runtime-syntax concern. Minor textual tension but no factual contradiction (line 217 is about ruff/mypy config tolerance, line 219 is about the UP rule output runtime). The fixer left both lines, which is honest. Acceptable.

- **I3 (GH21 Phase 2 — lowercase "delivery not found"): PASS.** `docs/project/21/phase_02.md:532` now reads: `err.read = lambda: b'{"detail":"delivery not found"}'` — lowercase as required post-GH22. Verified via the surrounding `test_404_raises_registry_client_error` block (lines 528-539); the rest of the snippet is unchanged.

- **I4 (GH21 Phase 2 — GH27 pattern label coordination): PASS.** `docs/project/21/phase_02.md:331` adds: "**GH27 coordination:** GH27 (Tier 0) adds `# pattern: test file` to line 1 before this task runs. The Edit's old_string must include the existing `# pattern: test file` line as the first line to match correctly. Do NOT prepend a duplicate label." This is clearer than the original conditional ("prepend if and only if GH27 has not added it") because per DAG order GH27 will always have landed. Note: the prior line 329 still describes the conditional as if GH27 might not have run yet — slightly redundant but not wrong (defence-in-depth in case DAG order is violated). Acceptable.

- **I7 (GH17 Phase 3 — pre-check note for SIM105 after GH23): PASS.** `docs/project/17/implementation-plan/phase_03.md:212` adds: "**GH23 coordination:** GH23 Phase 1 replaces the `try/except: pass` block with `try/except: logger.debug(...)`, eliminating this SIM105 violation before GH17 executes. Run `uv run ruff check --select SIM105 src/pipeline/converter/convert.py` first — if clean, skip this fix." Correctly placed at the top of Task 3, before the file modification list. The pre-check command is exactly what the original review recommended.

- **M2 (GH27 — inline test-requirements note): PASS.** `docs/project/27/phase_01.md:319-320` adds a "Test Requirements" section: "AC verification is embedded in Task 4 above. No separate test-requirements.md file — this is a single-commit mechanical change with inline verification." Accurate and minimally invasive.

## New Issues Introduced

NONE.

A couple of minor textual tensions (noted under C2 and I1) where new authoritative guidance sits next to older, more permissive guidance. In both cases the new note dominates correctly and an executor following the plan top-to-bottom will land in the right place. Not worth a follow-up edit.

## Remaining Open Items

The original review flagged several issues with action "none" (informational only — I2, I5, I6 partial, I8, M3, M4, M5). These were not in the fixer's scope and remain as-is, which is correct per the original recommendations.

Two items from the original review that recommended **DAG-level** edits (not plan-text edits) were intentionally out of scope for the fixer and remain open:

- **I6 / Hotspot table:** drop GH24 from `engine.py` and `tests/crawler/test_main.py` rows in `docs/project/DAG.md`.
- **Hotspot table:** drop GH20 from `tests/registry_api/test_routes.py` row.
- **M1:** consolidate plan output paths (GH22 under `docs/implementation-plans/GH22/`, GH24 under `docs/implementation-plans/2026-04-29-GH24/`) to `docs/project/##/`. Cosmetic.

These are all DAG/structural housekeeping; none block execution. Flagging for the team-lead to decide whether to schedule a follow-up cleanup pass.

## Verdict

**APPROVED.** All seven fixes are present, correctly placed, and accurate. No new errors were introduced and no surrounding plan text was broken. The plan set is ready for execution.
