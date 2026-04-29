# GH19 Phase 3 — converter Annotations

**Goal:** Annotate `engine.py`, `cli.py`, `daemon.py`, and `convert.py` using the Phase 1 Protocols where applicable, and add `Generator`/`Iterator`/`Callable` annotations on remaining bare parameters.

**Architecture:** Wire `HttpModuleProtocol`, `ConvertOneFnProtocol`, and `ConsumerFactoryProtocol` (Phase 1) into the engine/CLI/daemon test seams. Annotate `chunk_iter_factory` in `convert.py` with the explicit `Callable` signature. Existing test fakes pass via structural subtyping — no test changes.

**Tech Stack:** Python stdlib (`argparse`, `typing`, `collections.abc`), Phase 1 Protocols.

**Scope:** 3 of 5 phases.

**Codebase verified:** 2026-04-29 — exact lines and current state confirmed.

---

## Acceptance Criteria Coverage

### GH19.AC2: converter module annotations complete

- **GH19.AC2.1 Success:** `engine.convert_one` all parameters annotated; return type is `ConversionResult`.
- **GH19.AC2.2 Success:** `engine.convert_one` `http_module` and `convert_fn` DI parameters annotated using Protocol types defined in Phase 2.
- **GH19.AC2.3 Success:** `cli._iter_unconverted` annotated as `Generator[dict, None, None]`; `http_module` parameter uses Protocol type.
- **GH19.AC2.4 Success:** `cli._run` `args` parameter annotated as `argparse.Namespace`; `http_module` and `convert_one_fn` parameters use Protocol types; return is `int`.
- **GH19.AC2.5 Success:** `convert.convert_sas_to_parquet` `chunk_iter_factory` parameter annotated using `Callable[[Path, int], Iterator[tuple[pd.DataFrame, object]]]` or equivalent Protocol.
- **GH19.AC2.6 Success:** `daemon.DaemonRunner.__init__` all parameters annotated; `consumer_factory` and `convert_one_fn` use Protocol types.

(Note: Design AC2.2 says "Phase 2" but the design phase that creates the Protocols is design-Phase-1, which we mapped to implementation Phase 1. Same Protocols, correct semantics.)

### GH19.AC8 (running)

- GH19.AC8.1, GH19.AC8.2 unchanged.

---

<!-- START_TASK_1 -->
### Task 1: Annotate `engine.convert_one` DI parameters

**Verifies:** GH19.AC2.1, GH19.AC2.2

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/engine.py:1-12` (imports)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/engine.py:32-43` (`convert_one` signature)

**Implementation:**

**Edit 1 — `engine.py:1-12`.** Current:

```python
# pattern: Imperative Shell (orchestration + side effects), with helper pure functions

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pipeline.converter import http as converter_http
from pipeline.converter.classify import classify_exception
from pipeline.converter.convert import convert_sas_to_parquet
from pipeline.json_logging import get_logger
```

Replace with:

```python
# pattern: Imperative Shell (orchestration + side effects), with helper pure functions

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pipeline.converter import http as converter_http
from pipeline.converter.classify import classify_exception
from pipeline.converter.convert import convert_sas_to_parquet
from pipeline.converter.protocols import ConvertOneFnProtocol, HttpModuleProtocol
from pipeline.json_logging import get_logger
```

**Edit 2 — `engine.py:32-43`.** Current:

```python
def convert_one(
    delivery_id: str,
    api_url: str,
    *,
    converter_version: str,
    chunk_size: int,
    compression: str,
    dp_id_exclusions: set[str] | None = None,
    log_dir: str | None = None,
    http_module=converter_http,
    convert_fn=convert_sas_to_parquet,
) -> ConversionResult:
```

Replace with:

```python
def convert_one(
    delivery_id: str,
    api_url: str,
    *,
    converter_version: str,
    chunk_size: int,
    compression: str,
    dp_id_exclusions: set[str] | None = None,
    log_dir: str | None = None,
    http_module: HttpModuleProtocol = converter_http,  # type: ignore[assignment]
    convert_fn: ConvertOneFnProtocol = convert_sas_to_parquet,  # type: ignore[assignment]
) -> ConversionResult:
```

The `# type: ignore[assignment]` comments are needed because:
1. `converter_http` is a module, not an instance. Protocol structural matching against modules works at runtime but mypy's strict mode flags the assignment as `Module is not assignable to HttpModuleProtocol` even though attribute access works. The standard idiom for typing module-shaped seams is the explicit ignore.
2. `convert_sas_to_parquet` (from `convert.py`) has a slightly different signature than `ConvertOneFnProtocol` — the protocol describes how `convert_one`-shaped callables are called, not `convert_sas_to_parquet`. **Wait — verify this.** Actually `convert_fn` in `engine.py` is called as `convert_fn(sas_file, output, chunk_size=..., compression=..., converter_version=...)` (line 115-121). That's the signature of `convert_sas_to_parquet`, NOT of `convert_one`. The Protocol is misnamed in the design.

**Design discrepancy surfaced.** The design plan calls the protocol `ConvertOneFnProtocol` and says it covers "the `convert_one` signature". But in `engine.py`, the parameter named `convert_fn` actually injects `convert_sas_to_parquet` (the SAS-to-Parquet streamer in `convert.py`), not the `convert_one` orchestrator. Two distinct seams.

To stay faithful to the codebase, define the protocol shape that matches the actual call site. Replace Phase 1's `ConvertOneFnProtocol` definition to describe what `engine.py` actually injects. **Update Phase 1's `protocols.py`** in this task to add a SECOND protocol called `ConvertSasToParquetFnProtocol` (and keep `ConvertOneFnProtocol` for the daemon/cli case, which DOES inject `convert_one`).

**Concretely, two protocols are needed:**
- `ConvertOneFnProtocol` — used by `cli._run.convert_one_fn` and `daemon.DaemonRunner.__init__.convert_one_fn`. Calls match `convert_one(delivery_id, api_url, *, converter_version, chunk_size, compression, dp_id_exclusions, log_dir)`.
- `ConvertSasToParquetFnProtocol` — used by `engine.convert_one.convert_fn`. Calls match `convert_sas_to_parquet(source_path, output_path, *, chunk_size, compression, converter_version)`.

**Action:** Phase 1's plan as written defines `ConvertOneFnProtocol` correctly for the cli/daemon case. This Phase 3 plan must also extend `protocols.py` to add `ConvertSasToParquetFnProtocol`.

**Edit 3 — Add to `src/pipeline/converter/protocols.py`** (after `ConvertOneFnProtocol`, before `ConsumerFactoryProtocol`):

```python
class ConvertSasToParquetFnProtocol(Protocol):
    """Shape of `convert.convert_sas_to_parquet` for engine dependency injection."""

    def __call__(
        self,
        source_path: Path,
        output_path: Path,
        *,
        chunk_size: int = ...,
        compression: str = ...,
        converter_version: str = ...,
    ) -> ConversionMetadata: ...
```

Add the corresponding `TYPE_CHECKING` imports at the top of `protocols.py`:

```python
if TYPE_CHECKING:
    from pathlib import Path

    from pipeline.converter.convert import ConversionMetadata
    from pipeline.converter.engine import ConversionResult
    from pipeline.events.consumer import EventConsumer
```

(The `Path` import is required because the type appears in the protocol signature; under `from __future__ import annotations` the import is type-check-only.)

**Edit 4 — Use the new Protocol in `engine.py:32-43`.** Final form:

```python
def convert_one(
    delivery_id: str,
    api_url: str,
    *,
    converter_version: str,
    chunk_size: int,
    compression: str,
    dp_id_exclusions: set[str] | None = None,
    log_dir: str | None = None,
    http_module: HttpModuleProtocol = converter_http,  # type: ignore[assignment]
    convert_fn: ConvertSasToParquetFnProtocol = convert_sas_to_parquet,  # type: ignore[assignment]
) -> ConversionResult:
```

Update the import line accordingly:

```python
from pipeline.converter.protocols import ConvertSasToParquetFnProtocol, HttpModuleProtocol
```

(`ConvertOneFnProtocol` is NOT imported in `engine.py` — it's used by `cli.py` and `daemon.py` only.)

**Verification:**

```bash
uv run pytest tests/converter/test_engine.py
```

Expected: all engine tests pass. The test fakes inject `http_module` (a module-like fake) and `convert_fn` (a callable fake) — both continue to satisfy the new Protocols structurally.

```bash
uv run python -c "from pipeline.converter.engine import convert_one; import inspect; sig = inspect.signature(convert_one); print(sig.parameters['http_module'].annotation); print(sig.parameters['convert_fn'].annotation)"
```

Expected: prints the Protocol class names.

**Commit:**

```bash
git add src/pipeline/converter/protocols.py src/pipeline/converter/engine.py
git commit -m "feat(converter): wire HttpModuleProtocol and ConvertSasToParquetFnProtocol into engine (#19)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Annotate `cli._iter_unconverted` and `cli._run`

**Verifies:** GH19.AC2.3, GH19.AC2.4

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/cli.py:1-10` (imports)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/cli.py:68-72` (`_iter_unconverted`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/cli.py:108-115` (`_run`)

**Implementation:**

**Edit 1 — `cli.py:1-10`.** Current:

```python
# pattern: Imperative Shell

import argparse
import sys

from pipeline.config import settings
from pipeline.converter import http as converter_http
from pipeline.converter.engine import convert_one
from pipeline.json_logging import get_logger
```

Replace with:

```python
# pattern: Imperative Shell

import argparse
import sys
from collections.abc import Generator

from pipeline.config import settings
from pipeline.converter import http as converter_http
from pipeline.converter.engine import convert_one
from pipeline.converter.protocols import ConvertOneFnProtocol, HttpModuleProtocol
from pipeline.json_logging import get_logger
```

**Edit 2 — `cli.py:68-72`.** Current:

```python
def _iter_unconverted(
    api_url: str,
    page_size: int,
    http_module=converter_http,
):
```

Replace with:

```python
def _iter_unconverted(
    api_url: str,
    page_size: int,
    http_module: HttpModuleProtocol = converter_http,  # type: ignore[assignment]
) -> Generator[dict, None, None]:
```

**Edit 3 — `cli.py:108-115`.** Current:

```python
def _run(
    args,
    shard: tuple[int, int] | None,
    *,
    http_module,
    convert_one_fn,
    dp_id_exclusions: set[str] | None = None,
) -> int:
```

Replace with:

```python
def _run(
    args: argparse.Namespace,
    shard: tuple[int, int] | None,
    *,
    http_module: HttpModuleProtocol,
    convert_one_fn: ConvertOneFnProtocol,
    dp_id_exclusions: set[str] | None = None,
) -> int:
```

(`http_module` and `convert_one_fn` are required keyword args here — no default — so no `# type: ignore` needed.)

**Verification:**

```bash
uv run pytest tests/converter/test_cli.py
```

Expected: all CLI tests pass (the test seams continue to work via structural typing).

```bash
uv run python -c "from pipeline.converter.cli import _iter_unconverted, _run; import inspect; print(inspect.signature(_iter_unconverted).return_annotation); print(inspect.signature(_run).parameters['args'].annotation)"
```

Expected: prints `Generator[dict, None, None]` (or its repr) and `<class 'argparse.Namespace'>`.

**Commit:**

```bash
git add src/pipeline/converter/cli.py
git commit -m "feat(converter): annotate cli._iter_unconverted and _run signatures (#19)"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Annotate `daemon.DaemonRunner.__init__`

**Verifies:** GH19.AC2.6

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/daemon.py:58-99` (imports + `__init__`)

**Implementation:**

**Edit 1 — `daemon.py:58-62`.** Current:

```python
from pipeline.config import settings
from pipeline.converter.engine import convert_one
from pipeline.events.consumer import EventConsumer
from pipeline.json_logging import get_logger
```

Replace with:

```python
from pipeline.config import settings
from pipeline.converter.engine import convert_one
from pipeline.converter.protocols import ConsumerFactoryProtocol, ConvertOneFnProtocol
from pipeline.events.consumer import EventConsumer
from pipeline.json_logging import get_logger
```

**Edit 2 — `daemon.py:76-99`.** Current:

```python
    def __init__(
        self,
        *,
        api_url: str,
        state_path: Path,
        converter_version: str,
        chunk_size: int,
        compression: str,
        dp_id_exclusions: set[str] | None = None,
        log_dir: str | None,
        consumer_factory=EventConsumer,
        convert_one_fn=convert_one,
    ) -> None:
```

Replace with:

```python
    def __init__(
        self,
        *,
        api_url: str,
        state_path: Path,
        converter_version: str,
        chunk_size: int,
        compression: str,
        dp_id_exclusions: set[str] | None = None,
        log_dir: str | None,
        consumer_factory: ConsumerFactoryProtocol = EventConsumer,  # type: ignore[assignment]
        convert_one_fn: ConvertOneFnProtocol = convert_one,  # type: ignore[assignment]
    ) -> None:
```

The `# type: ignore[assignment]` is needed because:
- `EventConsumer` is a class (its `__call__` is `__init__`), and structural matching of a class against `ConsumerFactoryProtocol.__call__` is not detected by mypy without explicit acknowledgement.
- `convert_one` is a function whose signature matches `ConvertOneFnProtocol.__call__` structurally; same mypy strict-mode warning.

These are runtime-correct assignments — both production paths and test fakes continue to work.

**Verification:**

```bash
uv run pytest tests/converter/test_daemon.py
```

Expected: all daemon tests pass.

```bash
uv run python -c "from pipeline.converter.daemon import DaemonRunner; import inspect; sig = inspect.signature(DaemonRunner.__init__); print(sig.parameters['consumer_factory'].annotation); print(sig.parameters['convert_one_fn'].annotation)"
```

Expected: prints the two Protocol class names.

**Commit:**

```bash
git add src/pipeline/converter/daemon.py
git commit -m "feat(converter): annotate DaemonRunner.__init__ DI parameters (#19)"
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Annotate `convert.convert_sas_to_parquet` `chunk_iter_factory`

**Verifies:** GH19.AC2.5

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/convert.py:1-15` (imports)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/converter/convert.py:83-91` (`convert_sas_to_parquet` signature)

**Implementation:**

**Edit 1 — `convert.py:1-15`.** Current:

```python
# pattern: Functional Core (file I/O only; no network, registry, or config)

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyreadstat

from pipeline.converter.classify import SchemaDriftError
```

Replace with:

```python
# pattern: Functional Core (file I/O only; no network, registry, or config)

import json
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyreadstat

from pipeline.converter.classify import SchemaDriftError
```

(Move `Iterator` from `typing` to `collections.abc` — `typing.Iterator` is deprecated. Add `Callable`.)

**Edit 2 — `convert.py:83-91`.** Current:

```python
def convert_sas_to_parquet(
    source_path: Path,
    output_path: Path,
    *,
    chunk_size: int = 100_000,
    compression: str = "zstd",
    converter_version: str = "0.1.0",
    chunk_iter_factory=_iter_sas_chunks,
) -> ConversionMetadata:
```

Replace with:

```python
def convert_sas_to_parquet(
    source_path: Path,
    output_path: Path,
    *,
    chunk_size: int = 100_000,
    compression: str = "zstd",
    converter_version: str = "0.1.0",
    chunk_iter_factory: Callable[[Path, int], Iterator[tuple[pd.DataFrame, object]]] = _iter_sas_chunks,
) -> ConversionMetadata:
```

The annotation matches the signature of `_iter_sas_chunks` exactly (verified at `convert.py:66-80`: `def _iter_sas_chunks(source_path: Path, chunk_size: int) -> Iterator[tuple[pd.DataFrame, object]]`).

`object` is correct for the second tuple element — pyreadstat yields a metadata object whose type isn't formally exposed by pyreadstat's stubs. Using `Any` would defeat strict mode; `object` is the conservative supertype that all metadata variants satisfy.

**Verification:**

```bash
uv run pytest tests/converter/test_convert.py
```

Expected: all conversion tests pass.

**Commit:**

```bash
git add src/pipeline/converter/convert.py
git commit -m "feat(converter): annotate convert_sas_to_parquet chunk_iter_factory (#19)"
```
<!-- END_TASK_4 -->

---

## Phase Done When

- All four converter source files (`engine.py`, `cli.py`, `daemon.py`, `convert.py`) and `protocols.py` (extended) have complete annotations on every public function and DI parameter.
- `uv run pytest` exits 0.
- `grep -rn "convert_fn=\|http_module=\|consumer_factory=" src/pipeline/converter/` shows the same default-value defaults as before (Protocols add types, not new defaults).

## Out of Scope

- mypy strict-mode invocation (issue #17).
- registry_api, crawler, lexicons (Phases 2, 4).

## Notes for the implementor

- The naming clash between `ConvertOneFnProtocol` (cli/daemon — actual `convert_one`) and `ConvertSasToParquetFnProtocol` (engine — actual `convert_sas_to_parquet`) is forced by the codebase having two distinct seams. The design plan conflated them; this plan splits them faithfully.
- The `# type: ignore[assignment]` pattern on Protocol-typed defaults is the standard mypy idiom for module/class-as-protocol assignments. It will become unnecessary when mypy improves its module-as-Protocol support; until then, the runtime check is what matters.
