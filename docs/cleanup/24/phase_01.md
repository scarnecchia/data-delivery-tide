# GH24 Structured Logging Extra — Implementation Plan

**Goal:** Replace eight f-string-interpolated log messages in `src/pipeline/crawler/main.py` with static messages plus `extra=` dict fields so dynamic values are queryable as first-class JSON fields.

**Architecture:** Pure mechanical substitution at call sites. The project's `JsonFormatter` (`src/pipeline/json_logging.py`) already serialises every key in `extra=` into the top-level JSON object — no formatter or infrastructure changes are required. The converter module (`converter/engine.py`, `converter/daemon.py`, `converter/cli.py`) already follows this pattern; this phase brings the crawler into alignment.

**Tech Stack:** Python stdlib `logging`, project's `JsonFormatter`. No new dependencies.

**Scope:** 1 phase from the original design (single phase, all 8 call sites).

**Codebase verified:** 2026-04-29

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH24.AC1: All f-string log calls in crawler/main.py are replaced
- **GH24.AC1.1 Success:** `grep -n 'logger\.\(info\|warning\|error\)(f"' src/pipeline/crawler/main.py` returns no results after the fix is applied.
- **GH24.AC1.2 Success:** Each of the 8 call sites (CS-1 through CS-8) produces a static string as the first argument to the log call.
- **GH24.AC1.3 Success:** Dynamic values previously interpolated into the message are present as named keys in `extra=` for each call site.

### GH24.AC2: Dynamic values appear as structured fields in JSON output
- **GH24.AC2.1 Success:** `JsonFormatter` serialises each `extra` key as a top-level field in the JSON log line (existing `JsonFormatter` behaviour; no code change required).
- **GH24.AC2.2 Success:** CS-3 emits `candidate_count` as a structured field.
- **GH24.AC2.3 Success:** CS-4 emits `reason` as a structured field (in addition to existing `scan_root` and `source_path`).
- **GH24.AC2.4 Success:** CS-5 emits `lexicon_id` as a structured field (in addition to existing `source_path` and `sub_dir`).
- **GH24.AC2.5 Success:** CS-6 emits `processed` as a structured field.
- **GH24.AC2.6 Success:** CS-7 and CS-8 emit `error_message` as a structured field, consistent with the field name used in `converter/cli.py` and `converter/daemon.py`.

### GH24.AC3: Existing tests continue to pass without modification
- **GH24.AC3.1 Success:** `uv run pytest tests/crawler/test_main.py` passes with no test changes.
- **GH24.AC3.2 Success:** The message-content assertion at `tests/crawler/test_main.py:183` (`"dpid missing target directory" in call_args[0][0]`) passes because the static message string preserves that text.
- **GH24.AC3.3 Success:** The `extra["dpid"]` and `extra["target"]` assertions at lines 184–185 of the same test pass unchanged.

### GH24.AC4: No violations introduced in other modules
- **GH24.AC4.1 Success:** `grep -rn 'logger\.\(info\|warning\|error\)(f"' src/pipeline/` returns no results after the fix.

---

## Codebase verification findings

- ✓ Target file exists: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/crawler/main.py`.
- ✓ All 8 call sites confirmed at the line numbers stated in the design (CS-1 line 76, CS-2 line 142, CS-3 line 147, CS-4 line 171, CS-5 line 204, CS-6 line 287, CS-7 line 310, CS-8 line 313).
- ✓ `JsonFormatter` in `src/pipeline/json_logging.py:11-24` walks `record.__dict__` and merges every non-standard, non-None attribute into the JSON output. Adding new keys to `extra=` requires no formatter change.
- ✓ Existing test `tests/crawler/test_main.py:183` asserts substring `"dpid missing target directory"` in the message argument — the new static string `"dpid missing target directory"` satisfies the substring check.
- ✓ Test `tests/crawler/test_main.py:184-185` asserts `extra["dpid"]` and `extra["target"]` — both remain in `extra=` after the fix.
- + Additional observation: `main.py:277-284` contains a partially-interpolated `logger.info(f"processed delivery {delivery_id[:12]}...", extra={...})` call. **This call is OUT OF SCOPE** for this issue (not listed in CS-1 through CS-8 and the dynamic field is already mirrored in `extra=delivery_id`). It does, however, match the regex in AC4.1. See Task 2 verification step for handling.
- ✓ No other source files under `src/pipeline/` contain `logger.(info|warning|error)(f"...` patterns aside from `crawler/main.py` (verified by design's investigation).

---

<!-- START_PHASE_1 -->
<!-- START_TASK_1 -->
### Task 1: Replace 8 f-string log calls in crawler/main.py

**Verifies:** GH24.AC1.1, GH24.AC1.2, GH24.AC1.3, GH24.AC2.2, GH24.AC2.3, GH24.AC2.4, GH24.AC2.5, GH24.AC2.6

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/crawler/main.py` (8 call sites)

**Implementation:**

Apply each substitution exactly as specified. Each substitution is a localised text replacement at one call site. Make all 8 edits before running tests.

**CS-1 — `walk_roots` (around line 75-78):** dpid missing target directory

Replace:
```python
logger.warning(
    f"dpid missing target directory: {dpid_entry.name}/{target}",
    extra={"scan_root": root_path, "dpid": dpid_entry.name, "target": target},
)
```

With:
```python
logger.warning(
    "dpid missing target directory",
    extra={"scan_root": root_path, "dpid": dpid_entry.name, "target": target},
)
```

The static prefix `"dpid missing target directory"` is preserved verbatim so the substring assertion at `tests/crawler/test_main.py:183` continues to pass.

---

**CS-2 — `crawl` (around line 141-144):** scan root does not exist

Replace:
```python
logger.warning(
    f"scan root does not exist, skipping: {root.path}",
    extra={"scan_root": root.path},
)
```

With:
```python
logger.warning(
    "scan root does not exist, skipping",
    extra={"scan_root": root.path},
)
```

---

**CS-3 — `crawl` (line 147):** candidate count

Replace:
```python
logger.info(f"found {len(candidates)} delivery candidates")
```

With:
```python
logger.info(
    "found delivery candidates",
    extra={"candidate_count": len(candidates)},
)
```

---

**CS-4 — `crawl` (around line 170-173):** parse error

Replace:
```python
logger.warning(
    f"parse error: {result.reason}",
    extra={"scan_root": scan_root, "source_path": source_path},
)
```

With:
```python
logger.warning(
    "parse error",
    extra={"scan_root": scan_root, "source_path": source_path, "reason": result.reason},
)
```

---

**CS-5 — `crawl` (around line 203-206):** unknown sub_dirs lexicon

Replace:
```python
logger.warning(
    f"sub_dirs references unknown lexicon '{sub_lexicon_id}', skipping",
    extra={"source_path": source_path, "sub_dir": sub_dir_name},
)
```

With:
```python
logger.warning(
    "sub_dirs references unknown lexicon, skipping",
    extra={"source_path": source_path, "sub_dir": sub_dir_name, "lexicon_id": sub_lexicon_id},
)
```

---

**CS-6 — `crawl` (line 287):** crawl complete

Replace:
```python
logger.info(f"crawl complete: {processed} deliveries processed")
```

With:
```python
logger.info(
    "crawl complete",
    extra={"processed": processed},
)
```

---

**CS-7 — `main` (line 310):** registry client error

Replace:
```python
logger.error(f"registry client error: {exc}")
```

With:
```python
logger.error(
    "registry client error",
    extra={"error_message": str(exc)},
)
```

The field name `error_message` matches the convention used in `src/pipeline/converter/cli.py` and `src/pipeline/converter/daemon.py`.

---

**CS-8 — `main` (line 313):** registry unreachable

Replace:
```python
logger.error(f"registry unreachable, aborting: {exc}")
```

With:
```python
logger.error(
    "registry unreachable, aborting",
    extra={"error_message": str(exc)},
)
```

---

**Testing:**

No new test code is required for this task. The existing assertion at `tests/crawler/test_main.py:183` continues to verify GH24.AC3.2 (substring `"dpid missing target directory"` appears in the message argument). The assertions at lines 184–185 verify GH24.AC3.3 (`extra["dpid"]` and `extra["target"]`).

Optional new assertions for `extra["candidate_count"]` (CS-3), `extra["processed"]` (CS-6), and `extra["error_message"]` (CS-7/CS-8) are not required by the design and are not produced by this task. The integrator may add them in a follow-up if regression coverage is desired.

**Verification:**

Run from repo root `/Users/scarndp/dev/Sentinel/qa_registry/`:

1. **Static-string check (verifies GH24.AC1.1):**
   ```bash
   grep -n 'logger\.\(info\|warning\|error\)(f"' src/pipeline/crawler/main.py
   ```
   Expected: no output, exit code 1.

2. **Test suite (verifies GH24.AC3.1, GH24.AC3.2, GH24.AC3.3):**
   ```bash
   uv run pytest tests/crawler/test_main.py
   ```
   Expected: all tests pass.

3. **Full pytest sanity (defensive — catches any indirect breakage):**
   ```bash
   uv run pytest
   ```
   Expected: pre-existing pass/fail profile unchanged.

**Commit:**
```bash
git add src/pipeline/crawler/main.py
git commit -m "refactor(crawler): move log message dynamic values into extra= (#24)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Verify no f-string log violations remain anywhere under src/pipeline/

**Verifies:** GH24.AC4.1

**Files:**
- No code changes. This is a verification-only task that gates on the AC4 grep result.

**Implementation:**

Run the project-wide grep specified by the design's AC4.1:

```bash
grep -rn 'logger\.\(info\|warning\|error\)(f"' /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/
```

**Expected:** No output, exit code 1.

**Handling the partially-interpolated call at `crawler/main.py:277-284`:**

A call exists at lines 277-284 that interpolates `delivery_id[:12]` into the message string while also placing `delivery_id` in `extra=`. This call is NOT one of the 8 design-listed call sites (CS-1 through CS-8). However, it does match the AC4.1 regex.

If the grep produces this single hit only, treat it as in-scope for AC4.1 (the AC is "no violations") and apply the same pattern:

Replace:
```python
logger.info(
    f"processed delivery {delivery_id[:12]}... (status={delivery.status})",
    extra={
        "scan_root": delivery.scan_root,
        "source_path": delivery.source_path,
        "delivery_id": delivery_id,
    },
)
```

With:
```python
logger.info(
    "processed delivery",
    extra={
        "scan_root": delivery.scan_root,
        "source_path": delivery.source_path,
        "delivery_id": delivery_id,
        "status": delivery.status,
    },
)
```

`delivery_id` is already in `extra=`; the `[:12]` prefix is a presentational truncation that downstream tooling can derive from the full id when needed. `status` is added so it remains queryable.

If the grep produces other hits not anticipated here, STOP and surface them — they fall outside the documented scope and need a decision before being touched.

**Verification:**

1. **Final AC4.1 grep:**
   ```bash
   grep -rn 'logger\.\(info\|warning\|error\)(f"' /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/
   ```
   Expected: no output, exit code 1.

2. **Test suite (re-run after Task 2 edit, if any):**
   ```bash
   uv run pytest tests/crawler/test_main.py
   ```
   Expected: all tests pass.

**Commit:**

If Task 2 made any edits, append to Task 1's commit via amend OR create a follow-up commit:
```bash
git add src/pipeline/crawler/main.py
git commit -m "refactor(crawler): make 'processed delivery' log static (#24)"
```

If no edits were needed (Task 1 already eliminated the only matches), skip the commit.
<!-- END_TASK_2 -->
<!-- END_PHASE_1 -->
