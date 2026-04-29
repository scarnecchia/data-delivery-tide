# GH28 — Test Requirements

Maps each acceptance criterion in `docs/project/28/design.md` to either an automated test or documented human verification.

## Summary

This issue is a pure import/annotation change with **zero runtime behaviour change**. `collections.abc.Callable` and `typing.Callable` are runtime-identical on Python 3.10+. The change is verified by:

1. The existing test suite continuing to pass unchanged (regression check).
2. Static `grep`-based assertions on the file's contents (mechanical verification of AC1 and AC2).
3. Optional static type-checking inspection (human verification, future-facing).

No new test code is required. Per the project's testing philosophy and the design plan ("No test authoring required"), inventing tests for the dataclass annotation itself would test the language, not the code.

---

## Coverage Map

### GH28.AC1.1 — `from typing import Callable` is removed from `models.py`

- **Verification type:** Automated (mechanical check)
- **Test:** Inline grep assertion run as part of the verification step in phase_01.md, Task 1.
- **Command:**
  ```bash
  grep -rn "from typing import.*Callable\|typing\.Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/
  ```
- **Pass condition:** zero matches.
- **Why this is sufficient:** The AC is a textual property of the source file. A grep is the test.

### GH28.AC1.2 — `from collections.abc import Callable` is present in `models.py`

- **Verification type:** Automated (mechanical check)
- **Test:** Inline grep assertion in phase_01.md, Task 1.
- **Command:**
  ```bash
  grep -n "from collections.abc import Callable" /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py
  ```
- **Pass condition:** exactly one match on line 3.
- **Why this is sufficient:** Same reasoning as AC1.1 — textual property, grep is the test.

### GH28.AC2.1 — `derive_hook` annotation is `Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]] | None = None`

- **Verification type:** Hybrid — mechanical + human review
- **Mechanical check:** A targeted grep confirms the annotation literal:
  ```bash
  grep -n 'derive_hook: Callable\[\[list\["ParsedDelivery"\], "Lexicon"\], list\["ParsedDelivery"\]\] | None = None' /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/lexicons/models.py
  ```
  Pass condition: exactly one match.
- **Human verification:** Reviewer should also visually confirm the `TYPE_CHECKING` block imports `ParsedDelivery` from `pipeline.crawler.parser` and that `Lexicon` is forward-quoted. Justification: a grep cannot fully validate that the type expression is *semantically correct* (e.g., that `ParsedDelivery` resolves to the right class). Static type-check tooling (`mypy`) does not yet run on this repo (blocked by issue #17). Once #17 lands, mypy will mechanically verify this AC.
- **Verification approach:** Code review at PR time. Reviewer reads `models.py` end-to-end and confirms the import guard, forward references, and field annotation match the plan.

### GH28.AC3.1 / Design AC4 — `uv run pytest` passes without modification to any other file

- **Verification type:** Automated (regression test suite)
- **Test:** Existing `uv run pytest` invocation. The change does not introduce a new test file.
- **Command:**
  ```bash
  uv run pytest
  ```
- **Pass condition:** exit code 0, no failures, no errors.
- **Why this is sufficient:** The hook signature change is a static-typing concern only. If tests pass, runtime semantics are unchanged. The full crawler + registry test paths exercise lexicon loading, derive-hook invocation (`soc/qa.py`), and the registry API — any runtime regression from the dataclass change would surface there.
- **Additional check:** A pre-commit `git diff --stat` should show exactly one file modified: `src/pipeline/lexicons/models.py`. Any other modified file fails AC4.

---

## Human Verification Items (consolidated)

| Item | Justification | Approach |
|---|---|---|
| `TYPE_CHECKING` guard correctness for `ParsedDelivery` | Static type-checker (mypy) is not configured in this repo until issue #17 lands. Until then, only human review can confirm the import path and absence of runtime side-effects. | PR review of `src/pipeline/lexicons/models.py` |
| Single-file scope (only `models.py` is touched) | The AC is a property of the diff, not of any single file's contents. | `git diff --stat` inspection at PR time |

---

## Out of Scope for Test Requirements

- Mypy type-check execution (depends on issue #17).
- Tests of `derive_hook` runtime behaviour (already covered by existing crawler tests around `soc/qa.py`; not the subject of this issue).
- New unit tests for the `Lexicon` dataclass (the language and `dataclasses` module already verify dataclass mechanics).
