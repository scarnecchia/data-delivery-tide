# GH24 Test Requirements

Maps each acceptance criterion from `docs/project/24/design.md` to either an automated test or documented human/tooling verification.

---

## Automated tests / verifications

### GH24.AC1.1 — No f-string log calls in crawler/main.py

- **Type:** static check (shell command)
- **Command:** `grep -n 'logger\.\(info\|warning\|error\)(f"' src/pipeline/crawler/main.py`
- **Pass condition:** exit code 1 (no matches)
- **Verified by:** Phase 1 Task 1 verification step 1

### GH24.AC1.2 — Each of CS-1 through CS-8 has a static string first argument

- **Type:** code-review-style assertion, gated by GH24.AC1.1 (no f-string at any of the 8 call sites means the first argument is a static string)
- **Pass condition:** GH24.AC1.1 passes AND visual confirmation that each call site (lines around 75-78, 141-144, 147, 170-173, 203-206, 287, 310, 313) has a string-literal first argument
- **Verified by:** Phase 1 Task 1 — direct edits applied as specified

### GH24.AC1.3 — Dynamic values appear as named keys in `extra=`

- **Type:** code-review assertion, mechanically derivable from the diff
- **Pass condition:** Each former f-string substitution variable appears as a key in the call site's `extra=` dict
- **Verified by:** Phase 1 Task 1 — substitution table in the plan enumerates each key explicitly

### GH24.AC2.1 — JsonFormatter serialises `extra` keys as top-level fields

- **Type:** existing behaviour, verified by code reading
- **Pass condition:** `src/pipeline/json_logging.py:11-24` walks `record.__dict__` and merges non-standard, non-None attributes into the JSON output
- **Verified by:** No change required; verified during codebase investigation. No new test needed.

### GH24.AC2.2 — CS-3 emits `candidate_count`

- **Type:** unit (optional new assertion, NOT required by design)
- **Pass condition:** GH24.AC1.3 covers this mechanically. If a regression test is desired: mock the logger, run `crawl()` against a tmp scan root, assert `logger.info` was called with `extra={"candidate_count": <int>}` for the "found delivery candidates" message.
- **Test file (if added):** `tests/crawler/test_main.py`
- **Verified by:** Mechanical via Phase 1 Task 1; no new automated test mandated.

### GH24.AC2.3 — CS-4 emits `reason`

- **Type:** unit (optional new assertion)
- **Pass condition:** `extra` for the "parse error" call contains keys `scan_root`, `source_path`, AND `reason`
- **Verified by:** Mechanical via Phase 1 Task 1.

### GH24.AC2.4 — CS-5 emits `lexicon_id`

- **Type:** unit (optional new assertion)
- **Pass condition:** `extra` for the "sub_dirs references unknown lexicon, skipping" call contains keys `source_path`, `sub_dir`, AND `lexicon_id`
- **Verified by:** Mechanical via Phase 1 Task 1.

### GH24.AC2.5 — CS-6 emits `processed`

- **Type:** unit (optional new assertion)
- **Pass condition:** `extra` for the "crawl complete" call contains key `processed` with the integer count
- **Verified by:** Mechanical via Phase 1 Task 1.

### GH24.AC2.6 — CS-7 and CS-8 emit `error_message`

- **Type:** unit (optional new assertion)
- **Pass condition:** Both error-path log calls in `main()` set `extra={"error_message": str(exc)}`. Field name matches the convention in `converter/cli.py` and `converter/daemon.py`.
- **Verified by:** Mechanical via Phase 1 Task 1.

### GH24.AC3.1 — Existing crawler tests pass without modification

- **Type:** unit + integration (existing suite)
- **Command:** `uv run pytest tests/crawler/test_main.py`
- **Pass condition:** All tests pass; no test file edits in this phase.
- **Verified by:** Phase 1 Task 1 verification step 2.

### GH24.AC3.2 — Existing message-content assertion still passes

- **Type:** existing unit test
- **Test:** `tests/crawler/test_main.py:183` (`assert "dpid missing target directory" in call_args[0][0]`)
- **Pass condition:** New static message string `"dpid missing target directory"` contains the substring; assertion holds.
- **Verified by:** Phase 1 Task 1 verification step 2.

### GH24.AC3.3 — Existing `extra["dpid"]` and `extra["target"]` assertions still pass

- **Type:** existing unit test
- **Test:** `tests/crawler/test_main.py:184-185`
- **Pass condition:** Both keys remain in `extra=` after the substitution.
- **Verified by:** Phase 1 Task 1 verification step 2.

### GH24.AC4.1 — No f-string log violations anywhere under src/pipeline/

- **Type:** static check (shell command)
- **Command:** `grep -rn 'logger\.\(info\|warning\|error\)(f"' src/pipeline/`
- **Pass condition:** exit code 1 (no matches)
- **Verified by:** Phase 1 Task 2 verification step 1. Task 2 also handles the one in-scope-by-AC-but-not-by-CS hit at `crawler/main.py:277-284`.

---

## Human verification

None required. All ACs are either covered by mechanical edits + grep checks, or by the existing pytest suite. The design is a closed-form mechanical refactor with no behavioural surface area outside log line emission, which the JSON formatter's deterministic merge logic makes inspectable via grep + code review.

---

## Notes for execution

- The design's "Additional Considerations" section explicitly states that no test updates are required for the existing assertions, and that new test coverage for CS-3/CS-6/CS-7/CS-8 is optional. This plan mirrors that stance: optional assertions are documented above but not mandated by tasks.
- If the executor or reviewer wants to harden regression coverage, the optional assertions in AC2.2 / AC2.3 / AC2.4 / AC2.5 / AC2.6 can be added to `tests/crawler/test_main.py` as a follow-up commit. They are not blocking for this phase.
