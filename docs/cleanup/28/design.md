# Issue #28: Use collections.abc.Callable instead of typing.Callable

## Summary

Replace the deprecated `typing.Callable` import in `models.py` with `collections.abc.Callable` and add the full type signature to `derive_hook`. One file, two lines, no behaviour change.

## Definition of Done

`src/pipeline/lexicons/models.py` imports `Callable` from `collections.abc` and annotates `derive_hook` with the full parameterised signature. All existing tests pass. No other files are touched.

## Acceptance Criteria

- **28.AC1** `from typing import Callable` is removed from `models.py`
- **28.AC2** `from collections.abc import Callable` is present in `models.py`
- **28.AC3** `derive_hook` is typed as `Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]] | None = None`
- **28.AC4** `uv run pytest` passes without modification to any other file

## Scope

| In scope | Out of scope |
|---|---|
| `src/pipeline/lexicons/models.py` | All other files |
| Import + annotation change | Runtime behaviour |

## Existing State

```
# src/pipeline/lexicons/models.py line 3
from typing import Callable
...
derive_hook: Callable | None = None
```

`typing.Callable` appears in no other file under `src/`.

## Change

```python
# Before
from typing import Callable

# After
from collections.abc import Callable
```

```python
# Before
derive_hook: Callable | None = None

# After
derive_hook: Callable[[list[ParsedDelivery], Lexicon], list[ParsedDelivery]] | None = None
```

**Decision:** Use a `TYPE_CHECKING` guard to import `ParsedDelivery` without creating a runtime dependency from `lexicons` → `crawler`. `ParsedDelivery` lives in `pipeline.crawler.parser`; importing it at runtime would violate the package boundary. `from __future__ import annotations` is too broad for a single field. `Callable[..., Any]` defeats the purpose of parameterising the signature.

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.crawler.parser import ParsedDelivery
```

`Lexicon` is defined in the same module — no guard needed for it.

## Impact Assessment

- **Runtime:** None. `collections.abc.Callable` and `typing.Callable` are identical at runtime on 3.10+.
- **Type checking:** Strictly more informative — static analysers can now validate hook signatures.
- **Tests:** No changes expected; no tests target the import directly.
- **Dependencies:** None added.

## Effort Estimate

Trivial. < 5 minutes. Single-file edit, no test authoring required.
