# GH27: Pattern Labels — Phase 1 Implementation Plan

**Goal:** Add `# pattern:` labels to 22 Python files that lack them or carry an inaccurate label, so every classified file declares its FCIS role on line 1.

**Architecture:** Mechanical line-1 edit. Two `# pattern: Functional Core` additions to `src/` package init files (which contain re-exports), and twenty `# pattern: test file` additions/replacements across `tests/`. Empty `__init__.py` files are explicitly excluded — they have no architectural classification.

**Tech Stack:** Python only. No new dependencies, no logic changes, no test changes required.

**Scope:** 1 phase from `docs/project/27/design.md`. The design itself classifies this as a single-commit mechanical change.

**Codebase verified:** 2026-04-29 — all 22 target files exist; their line 1 contents match the design assumptions; the 11 `__init__.py` files declared empty in the design are confirmed 0 bytes.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH27.AC1: Source files carry accurate pattern labels
- **GH27.AC1.1 Two non-empty `__init__.py` files in `src/` get `# pattern: Functional Core`:** `src/pipeline/lexicons/__init__.py`, `src/pipeline/crawler/__init__.py`.
- **GH27.AC1.2 Empty `__init__.py` files remain unlabelled:** the seven empty init files under `src/pipeline/` and its subpackages stay 0 bytes.

### GH27.AC2: Test files carry `# pattern: test file`
- **GH27.AC2.1 Eighteen test files lacking a label get `# pattern: test file` on line 1:** all files listed in the design "add" rows.
- **GH27.AC2.2 Two mislabelled test files have `# pattern: Functional Core` replaced with `# pattern: test file`:** `tests/lexicons/test_loader.py`, `tests/lexicons/test_qa_hook.py`.
- **GH27.AC2.3 `tests/test_end_to_end_converter.py` is untouched** (already correctly labelled per design rationale — removing the only correct label is a regression).
- **GH27.AC2.4 Empty `tests/.../__init__.py` files remain unlabelled.**

### GH27.AC3: No regressions
- **GH27.AC3.1 Existing tests still pass:** `uv run pytest` returns the same outcome as before the commit.
- **GH27.AC3.2 No source file in `src/` retains an inaccurate label:** the pre-existing labels documented as "no change" in the design stay as they were.

---

## Codebase verification findings

- ✓ All 22 target files exist at the paths the design specifies.
- ✓ `tests/lexicons/test_loader.py` and `tests/lexicons/test_qa_hook.py` line 1 is currently `# pattern: Functional Core` — confirmed needs replacement.
- ✓ All 11 `__init__.py` files the design marks empty are confirmed 0 bytes.
- ✓ Two `src/` init files needing the label are non-empty (re-export imports on line 1).
- ⚠ `tests/crawler/test_parser.py` currently has a **blank** first line. The label must replace the blank line rather than be inserted above it, otherwise the file gains a leading blank-then-comment which is uglier than necessary. Task 1 handles this with an explicit case.
- ✓ All other "add" target test files have actual code (`import …`, docstrings) on line 1 — the label gets prepended as a new line 1.

---

<!-- START_TASK_1 -->
### Task 1: Add `# pattern: Functional Core` to two non-empty src init files

**Verifies:** GH27.AC1.1

**Files:**
- Modify: `src/pipeline/lexicons/__init__.py:1` — prepend new line 1
- Modify: `src/pipeline/crawler/__init__.py:1` — prepend new line 1

**Implementation:**

For each of the two files, insert `# pattern: Functional Core` as a new line 1, pushing existing content down by one line. No blank line between the comment and the existing content — match the convention already used by labelled `src/` files (e.g. `src/pipeline/config.py`).

Before:
```python
from pipeline.lexicons.models import (
    ...
)
```

After:
```python
# pattern: Functional Core
from pipeline.lexicons.models import (
    ...
)
```

Use the Edit tool with `old_string` matching the current line 1 (e.g. `from pipeline.lexicons.models import (`) and `new_string` being the comment plus a newline plus that same line 1 — guarantees an exact, unique match without touching any other content.

**Verification:**

```bash
head -1 src/pipeline/lexicons/__init__.py
head -1 src/pipeline/crawler/__init__.py
```

Expected output for each: `# pattern: Functional Core`

**Commit:** wait — commit at the end of Task 4 covers the whole change set as a single commit per the design ("Can be done in a single commit").
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Replace mislabelled `# pattern: Functional Core` on two lexicon test files

**Verifies:** GH27.AC2.2

**Files:**
- Modify: `tests/lexicons/test_loader.py:1`
- Modify: `tests/lexicons/test_qa_hook.py:1`

**Implementation:**

Both files currently have `# pattern: Functional Core` on line 1. Replace with `# pattern: test file`. Single-line, in-place replacement — no surrounding context changes.

Use the Edit tool:
- `old_string`: `# pattern: Functional Core`
- `new_string`: `# pattern: test file`

This `old_string` is unique to line 1 in both files (verified — these files do not contain that comment elsewhere).

**Verification:**

```bash
head -1 tests/lexicons/test_loader.py
head -1 tests/lexicons/test_qa_hook.py
```

Expected output for each: `# pattern: test file`

**Commit:** deferred to Task 4.
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Add `# pattern: test file` to seventeen unlabelled test files (line 1 has content)

**Verifies:** GH27.AC2.1 (partial — covers 17 of 18 add-target files; the 18th is handled in Task 3b)

**Files (prepend `# pattern: test file` as a new line 1):**

| File | Current line 1 |
|------|----------------|
| `tests/conftest.py` | `import hashlib` |
| `tests/crawler/conftest.py` | `import pytest` |
| `tests/crawler/test_fingerprint.py` | `from pipeline.crawler.fingerprint import FileEntry, compute_fingerprint` |
| `tests/crawler/test_http.py` | `import json` |
| `tests/crawler/test_main.py` | `import json` |
| `tests/crawler/test_manifest.py` | `import hashlib` |
| `tests/events/test_consumer.py` | `"""Tests for EventConsumer.` |
| `tests/lexicons/conftest.py` | `import json` |
| `tests/registry_api/test_auth.py` | `import hashlib` |
| `tests/registry_api/test_db.py` | `import hashlib` |
| `tests/registry_api/test_events.py` | `import asyncio` |
| `tests/registry_api/test_models.py` | `import pytest` |
| `tests/registry_api/test_routes.py` | `import asyncio` |
| `tests/test_auth_cli.py` | `import argparse` |
| `tests/test_config.py` | `import json` |
| `tests/test_json_logging.py` | `import json` |
| `tests/test_no_hardcoded_qa.py` | `"""Test that hardcoded QA status references don't exist in the codebase.` |

**Implementation:**

For each file, prepend `# pattern: test file` followed by a newline before the current line 1. No blank line between the comment and the existing line — matches the convention used by `tests/test_end_to_end_converter.py`.

Per-file Edit pattern:
- `old_string`: the current line 1 (from the table above) — verified unique because it is at line 1 and the surrounding "first import" pattern is sufficiently specific
- `new_string`: `# pattern: test file\n` followed by that same `old_string`

Where the current line 1 is too short to be unique on its own (e.g. `import json`), include line 2 in both `old_string` and `new_string` to disambiguate. The Edit tool surfaces non-unique-match errors immediately, so failures are loud, not silent.

**Verification:**

```bash
for f in tests/conftest.py tests/crawler/conftest.py tests/crawler/test_fingerprint.py \
         tests/crawler/test_http.py tests/crawler/test_main.py tests/crawler/test_manifest.py \
         tests/events/test_consumer.py tests/lexicons/conftest.py \
         tests/registry_api/test_auth.py tests/registry_api/test_db.py \
         tests/registry_api/test_events.py tests/registry_api/test_models.py \
         tests/registry_api/test_routes.py tests/test_auth_cli.py tests/test_config.py \
         tests/test_json_logging.py tests/test_no_hardcoded_qa.py; do
    head -1 "$f"
done
```

Expected output: `# pattern: test file` repeated 17 times.

**Commit:** deferred to Task 4.
<!-- END_TASK_3 -->

<!-- START_TASK_3B -->
### Task 3b: Add `# pattern: test file` to `tests/crawler/test_parser.py` (blank line 1)

**Verifies:** GH27.AC2.1 (the eighteenth file)

**Files:**
- Modify: `tests/crawler/test_parser.py:1` — file currently has an empty first line; replace it with the label rather than insert a new one above the blank.

**Implementation:**

This file is the only one in the add-set whose line 1 is currently empty. Inserting a new line above the blank would produce `# pattern: test file\n\n<line 2 content>` — gratuitous double blank. Instead, replace the blank line directly so line 1 becomes the label and the existing line 2 becomes line 2.

Read the file first to determine the actual line-2 content (`Read` tool, line offset 1, limit 3). Then use Edit with:
- `old_string`: `\n<line 2 content>\n<line 3 content>` (the blank line 1 plus the next two lines, sufficient for uniqueness)
- `new_string`: `# pattern: test file\n<line 2 content>\n<line 3 content>`

If the `\n`-as-first-character approach is awkward, an equivalent alternative is to read the whole file, check that line 1 is genuinely empty, then `Write` the file back with `# pattern: test file\n` prepended to the post-line-1 content. Either is acceptable — the constraint is the resulting file's line 1 must be the label and line 2 onwards must be unchanged from the current line 2 onwards.

**Verification:**

```bash
head -3 tests/crawler/test_parser.py
```

Expected: line 1 is `# pattern: test file`; lines 2 and 3 match what was previously lines 2 and 3.

```bash
diff <(tail -n +2 tests/crawler/test_parser.py) <(git show HEAD:tests/crawler/test_parser.py | tail -n +2)
```

Expected: no diff — the body from the original line 2 onwards is identical to the post-edit line 2 onwards.

**Commit:** deferred to Task 4.
<!-- END_TASK_3B -->

<!-- START_TASK_4 -->
### Task 4: Verify nothing else changed, run tests, commit

**Verifies:** GH27.AC1.2, GH27.AC2.3, GH27.AC2.4, GH27.AC3.1, GH27.AC3.2

**Files:** none modified in this task — verification and commit only.

**Implementation:**

1. Confirm the empty `__init__.py` files were not touched:

```bash
for f in src/pipeline/__init__.py src/pipeline/converter/__init__.py \
         src/pipeline/events/__init__.py src/pipeline/registry_api/__init__.py \
         src/pipeline/lexicons/soc/__init__.py tests/__init__.py \
         tests/converter/__init__.py tests/crawler/__init__.py \
         tests/events/__init__.py tests/lexicons/__init__.py \
         tests/registry_api/__init__.py; do
    size=$(wc -c < "$f")
    [ "$size" -eq 0 ] || echo "REGRESSION: $f is $size bytes (expected 0)"
done
```

Expected: no `REGRESSION:` lines printed.

2. Confirm `tests/test_end_to_end_converter.py` was not touched and still carries its label:

```bash
head -1 tests/test_end_to_end_converter.py
git diff -- tests/test_end_to_end_converter.py
```

Expected: line 1 prints `# pattern: test file`; `git diff` prints nothing.

3. Confirm the previously labelled `src/` files are unchanged:

```bash
git diff --stat -- src/ | grep -v -E '(crawler|lexicons)/__init__\.py' || true
```

Expected: empty output (the only `src/` files in the diff are the two init files modified in Task 1).

4. Confirm every label is now spelled correctly. The two valid spellings are `# pattern: Functional Core` and `# pattern: test file` (and the existing `# pattern: Imperative Shell` labels in untouched files):

```bash
grep -rEn '^# pattern:' src tests | grep -vE '# pattern: (Functional Core|Imperative Shell|test file)$' || echo "OK: all labels spelled correctly"
```

Expected: `OK: all labels spelled correctly`.

5. Run the test suite to confirm no regression:

```bash
uv run pytest
```

Expected: same pass/fail state as before the commit. Pattern labels are inert comments — any change in test outcome indicates an unrelated issue and the commit must not proceed until investigated.

6. Stage and commit. Per the design, the entire change ships as one commit:

```bash
git add src/pipeline/lexicons/__init__.py \
        src/pipeline/crawler/__init__.py \
        tests/conftest.py \
        tests/crawler/conftest.py \
        tests/crawler/test_fingerprint.py \
        tests/crawler/test_http.py \
        tests/crawler/test_main.py \
        tests/crawler/test_manifest.py \
        tests/crawler/test_parser.py \
        tests/events/test_consumer.py \
        tests/lexicons/conftest.py \
        tests/lexicons/test_loader.py \
        tests/lexicons/test_qa_hook.py \
        tests/registry_api/test_auth.py \
        tests/registry_api/test_db.py \
        tests/registry_api/test_events.py \
        tests/registry_api/test_models.py \
        tests/registry_api/test_routes.py \
        tests/test_auth_cli.py \
        tests/test_config.py \
        tests/test_json_logging.py \
        tests/test_no_hardcoded_qa.py

git commit -m "chore: add # pattern: labels to files missing or mislabelled (GH27)"
```

Expected: commit succeeds; `git status` shows clean tree afterwards (assuming no unrelated edits were in progress).

7. Final sanity check:

```bash
git show --stat HEAD | head -30
```

Expected: 22 files changed, ~22 insertions, ~2 deletions (the two replaced `# pattern: Functional Core` lines).
<!-- END_TASK_4 -->

---

## Definition of Done (per design)

- [x] Every non-empty Python file under `src/` carries a `# pattern:` label on line 1 — Task 1 handles the two outstanding cases.
- [x] Every non-empty Python file under `tests/` carries `# pattern: test file` on line 1 — Tasks 2, 3, 3b cover all 20 cases.
- [x] Empty `__init__.py` files remain exempt — Task 4 verifies their byte count.
- [x] No file retains an inaccurate label — Task 4 greps for non-canonical label spellings.
- [x] Tests still pass — Task 4 runs `uv run pytest`.
- [x] Single commit — Task 4 stages and commits all 22 files together.

## Test Requirements
AC verification is embedded in Task 4 above. No separate test-requirements.md file — this is a single-commit mechanical change with inline verification.
