# Structured Logging Extra Fields Design

## Summary

Eight log call sites in `src/pipeline/crawler/main.py` interpolate dynamic values directly into message strings via f-strings, making those values inaccessible as structured fields in the JSON log output. The fix replaces each f-string message with a static string and moves the dynamic data into the `extra=` dict, which `JsonFormatter` already serialises as top-level JSON fields.

The change is purely mechanical — no new infrastructure, no changes to `json_logging.py`. The converter module already follows the correct pattern throughout; this fix brings the crawler into alignment with the rest of the codebase.

## Definition of Done

All f-string log message interpolations in `crawler/main.py` (and any similar violations found in other modules) are replaced with static message strings and `extra=` dict fields. The `JsonFormatter` already serialises `extra` fields into the JSON output; no changes to `json_logging.py` are required. After this change, dynamic values are queryable as first-class structured fields rather than being buried inside the `message` string.

## Acceptance Criteria

### issue-24.AC1: All f-string log calls in crawler/main.py are replaced

- **issue-24.AC1.1 Success:** `grep -n 'logger\.\(info\|warning\|error\)(f"' src/pipeline/crawler/main.py` returns no results after the fix is applied.
- **issue-24.AC1.2 Success:** Each of the 8 call sites (CS-1 through CS-8) produces a static string as the first argument to the log call.
- **issue-24.AC1.3 Success:** Dynamic values previously interpolated into the message are present as named keys in `extra=` for each call site.

### issue-24.AC2: Dynamic values appear as structured fields in JSON output

- **issue-24.AC2.1 Success:** `JsonFormatter` serialises each `extra` key as a top-level field in the JSON log line (existing `JsonFormatter` behaviour; no code change required).
- **issue-24.AC2.2 Success:** CS-3 emits `candidate_count` as a structured field.
- **issue-24.AC2.3 Success:** CS-4 emits `reason` as a structured field (in addition to existing `scan_root` and `source_path`).
- **issue-24.AC2.4 Success:** CS-5 emits `lexicon_id` as a structured field (in addition to existing `source_path` and `sub_dir`).
- **issue-24.AC2.5 Success:** CS-6 emits `processed` as a structured field.
- **issue-24.AC2.6 Success:** CS-7 and CS-8 emit `error_message` as a structured field, consistent with the field name used in `converter/cli.py` and `converter/daemon.py`.

### issue-24.AC3: Existing tests continue to pass without modification

- **issue-24.AC3.1 Success:** `uv run pytest tests/crawler/test_main.py` passes with no test changes.
- **issue-24.AC3.2 Success:** The message-content assertion at `tests/crawler/test_main.py:183` (`"dpid missing target directory" in call_args[0][0]`) passes because the static message string preserves that text.
- **issue-24.AC3.3 Success:** The `extra["dpid"]` and `extra["target"]` assertions at lines 184–185 of the same test pass unchanged.

### issue-24.AC4: No violations introduced in other modules

- **issue-24.AC4.1 Success:** `grep -rn 'logger\.\(info\|warning\|error\)(f"' src/pipeline/` returns no results after the fix.

## Glossary

- **structured logging:** Logging where each piece of context is a named field in the output record rather than embedded in a free-form message string. Enables filtering, aggregation, and indexing by field value in log management systems.
- **extra=:** The keyword argument accepted by Python's `logging.Logger` methods for attaching arbitrary key-value pairs to a log record. `JsonFormatter` merges these into the top-level JSON object.
- **JsonFormatter:** The project's custom `logging.Formatter` in `src/pipeline/json_logging.py` that serialises log records as JSON lines, including all `extra` fields at the top level.
- **f-string interpolation (in log messages):** The anti-pattern of using f-strings to embed dynamic values in the message argument, which results in those values being visible only as substrings of the `message` field rather than as queryable structured fields.
- **static message string:** A log message with no dynamic content — the same string for every occurrence of that log event. Used as a stable key for grouping and counting events in log aggregators.
- **call site:** A specific location in source code where a logger method (`logger.info`, `logger.warning`, etc.) is called. This document identifies 8 call sites requiring changes (CS-1 through CS-8).
- **CS-N:** Short-hand used in this document to identify a specific call site by number (CS-1 through CS-8).

---

## Architecture

The fix is a pure mechanical substitution: move dynamic values from the f-string portion of the message into the `extra=` dict. The message becomes a static string, which is the key that log aggregators use to group and count events. Dynamic context moves to named fields that can be indexed and queried.

No infrastructure changes. `JsonFormatter` in `src/pipeline/json_logging.py` already merges every key in `extra` into the top-level JSON object; the only change required is at the call sites.

### Scope

Investigation found 8 f-string violations in `src/pipeline/crawler/main.py`. No violations exist in `src/pipeline/converter/engine.py`, `src/pipeline/converter/daemon.py`, `src/pipeline/converter/cli.py`, or `src/pipeline/registry_api/`.

## Existing Patterns

The converter module (`converter/engine.py`, `converter/daemon.py`, `converter/cli.py`) already uses the correct pattern throughout: static message strings with all dynamic context in `extra=`. The registry API has no logger calls. The fix aligns the crawler with the pattern already established across the rest of the codebase.

## Affected Call Sites

### CS-1: `walk_roots` — dpid missing target directory (line 76)

```python
# Before
logger.warning(
    f"dpid missing target directory: {dpid_entry.name}/{target}",
    extra={"scan_root": root_path, "dpid": dpid_entry.name, "target": target},
)

# After
logger.warning(
    "dpid missing target directory",
    extra={"scan_root": root_path, "dpid": dpid_entry.name, "target": target},
)
```

`dpid` and `target` are already in `extra`; the f-string was duplicating them in the message.

---

### CS-2: `crawl` — scan root does not exist (line 142)

```python
# Before
logger.warning(
    f"scan root does not exist, skipping: {root.path}",
    extra={"scan_root": root.path},
)

# After
logger.warning(
    "scan root does not exist, skipping",
    extra={"scan_root": root.path},
)
```

`root.path` is already in `extra` as `scan_root`.

---

### CS-3: `crawl` — delivery candidates count (line 147)

```python
# Before
logger.info(f"found {len(candidates)} delivery candidates")

# After
logger.info(
    "found delivery candidates",
    extra={"candidate_count": len(candidates)},
)
```

---

### CS-4: `crawl` — parse error (line 171)

```python
# Before
logger.warning(
    f"parse error: {result.reason}",
    extra={"scan_root": scan_root, "source_path": source_path},
)

# After
logger.warning(
    "parse error",
    extra={"scan_root": scan_root, "source_path": source_path, "reason": result.reason},
)
```

---

### CS-5: `crawl` — unknown sub_dirs lexicon (line 204)

```python
# Before
logger.warning(
    f"sub_dirs references unknown lexicon '{sub_lexicon_id}', skipping",
    extra={"source_path": source_path, "sub_dir": sub_dir_name},
)

# After
logger.warning(
    "sub_dirs references unknown lexicon, skipping",
    extra={"source_path": source_path, "sub_dir": sub_dir_name, "lexicon_id": sub_lexicon_id},
)
```

---

### CS-6: `crawl` — crawl complete (line 287)

```python
# Before
logger.info(f"crawl complete: {processed} deliveries processed")

# After
logger.info(
    "crawl complete",
    extra={"processed": processed},
)
```

---

### CS-7: `main` — registry client error (line 310)

```python
# Before
logger.error(f"registry client error: {exc}")

# After
logger.error(
    "registry client error",
    extra={"error_message": str(exc)},
)
```

Consistent with the pattern used in `converter/cli.py` and `converter/daemon.py` which both use `"error_message"` as the extra field name.

---

### CS-8: `main` — registry unreachable (line 313)

```python
# Before
logger.error(f"registry unreachable, aborting: {exc}")

# After
logger.error(
    "registry unreachable, aborting",
    extra={"error_message": str(exc)},
)
```

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Replace f-string log calls in crawler/main.py

**Goal:** Eliminate all 8 f-string log violations in `src/pipeline/crawler/main.py`.

**Components:**
- `src/pipeline/crawler/main.py` — apply CS-1 through CS-8 as specified above

**Dependencies:** None

**Done when:** `grep -n 'logger\.\(info\|warning\|error\)(f"' src/pipeline/crawler/main.py` returns no results; `uv run pytest tests/crawler/test_main.py` passes; the one existing message-content assertion at line 183 (`"dpid missing target directory"`) continues to pass because the static prefix is preserved.
<!-- END_PHASE_1 -->

## Additional Considerations

**Test impact:** One existing test in `tests/crawler/test_main.py` (line 183) asserts `"dpid missing target directory" in call_args[0][0]`. This assertion remains valid after CS-1 because the static message string retains that exact text. The test also asserts `call_args[1]["extra"]["dpid"]` and `call_args[1]["extra"]["target"]`, which are unchanged. No test updates are required for the existing assertions.

**New test coverage:** CS-3, CS-6, CS-7, and CS-8 introduce new `extra` fields that have no existing test assertions. Implementation may optionally add assertions for these fields to prevent future regression, but is not required to make the existing suite pass.

**No changes needed outside crawler:** The converter and registry_api modules already comply. `json_logging.py` requires no changes.
