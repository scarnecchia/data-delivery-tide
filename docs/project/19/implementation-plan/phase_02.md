# GH19 Phase 2 — registry_api Annotations

**Goal:** Complete PEP 484 annotations for the five files in `src/pipeline/registry_api/` (`db.py`, `models.py`, `auth.py`, `main.py`, `routes.py`).

**Architecture:** Mechanical, additive annotations. No runtime behaviour change. FastAPI's `Depends()` return value is opaque (`Any`) — `require_role()` is annotated to return `Any` with a docstring noting why; the design's AC1.5 acknowledges this.

**Tech Stack:** Python stdlib (`sqlite3`, `typing`, `collections.abc`), Pydantic v2, FastAPI.

**Scope:** 2 of 5 phases.

**Codebase verified:** 2026-04-29 — exact lines and current state confirmed by direct file reads.

---

## Acceptance Criteria Coverage

### GH19.AC1: registry_api module annotations complete

- **GH19.AC1.1 Success:** All route handler functions in `routes.py` have explicit return type annotations (`DeliveryResponse`, `PaginatedDeliveryResponse`, `list[DeliveryResponse]`, `EventRecord`, `dict[str, str]`).
- **GH19.AC1.2 Success:** `db.get_db()` return annotation is `Generator[sqlite3.Connection, None, None]`.
- **GH19.AC1.3 Success:** `db.upsert_delivery` return annotation is `dict` (not `None`; the function always returns or raises).
- **GH19.AC1.4 Success:** Pydantic validator methods (`check_metadata_size`, `clamp_limit`, `check_offset`) in `models.py` carry full annotations on `cls` and `v` parameters and return types.
- **GH19.AC1.5 Success:** `auth.require_role()` return annotation is `Depends` (or more precisely `Any` given FastAPI's opaque return; document the decision).
- **GH19.AC1.6 Success:** `auth._check_role()` return annotation is `TokenInfo`.
- **GH19.AC1.7 Success:** `main.websocket_events` `token` parameter annotated as `str | None`.
- **GH19.AC1.8 Success:** `main.websocket_events` return annotation is `None`.
- **GH19.AC1.9 Failure:** A missing annotation on any public function in this module group causes the mypy check (when #17 is enabled) to emit an error.

### GH19.AC8 (running)

- **GH19.AC8.1 Success:** `uv run pytest` passes at every phase boundary.
- **GH19.AC8.2 Success:** No existing test is modified to accommodate annotation changes.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Annotate `db.py` (`get_db` return + `upsert_delivery` return)

**Verifies:** GH19.AC1.2, GH19.AC1.3

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/db.py`

**Implementation:**

Two surgical edits.

**Edit 1 — line 1-10 area, add `Generator` to imports.** Current header:

```python
# pattern: Imperative Shell

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends
```

Replace with:

```python
# pattern: Imperative Shell

import hashlib
import json
import sqlite3
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends
```

(Use `collections.abc.Generator`, not `typing.Generator` — the latter is deprecated as of Python 3.9. The project's `lexicons/models.py` is also moving to `collections.abc.Callable` per issue #28.)

**Edit 2 — `db.py:190`.** Current:

```python
def get_db():
    """
    FastAPI dependency injection generator for database connections.

    Yields a database connection that is automatically closed after the request.
    """
```

Replace with:

```python
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    FastAPI dependency injection generator for database connections.

    Yields a database connection that is automatically closed after the request.
    """
```

**Edit 3 — `db.py:228`.** Current:

```python
def upsert_delivery(conn: sqlite3.Connection, data: dict) -> dict:
```

This signature is **already correct** — verified at line 228. The current docstring claims a `dict` return and the function does have a `return None` branch at line 333 if `cursor.fetchone()` returns falsy. In practice this branch is unreachable: the immediately preceding `INSERT ... ON CONFLICT` is followed by `SELECT * WHERE delivery_id = ?` for the row we just upserted, and SQLite guarantees the row exists. The design (AC1.3) explicitly endorses annotating it as `dict`. Leave the existing `-> dict` annotation in place; **no edit needed for `upsert_delivery`**.

Add a comment above the trailing `return None` at `db.py:333` to make the unreachability explicit:

Current `db.py:330-333`:

```python
    if row:
        row_dict = dict(row)
        return _deserialize_metadata(row_dict)
    return None
```

Replace with:

```python
    if row:
        row_dict = dict(row)
        return _deserialize_metadata(row_dict)
    # Unreachable: the INSERT above guarantees the row exists.
    # Annotated as dict per design (#19 AC1.3); this line is defensive only.
    return None  # type: ignore[return-value]
```

This satisfies AC1.3 (return type stays `dict`) while keeping the runtime safety net and silencing mypy under strict mode (#17).

**Verification:**

```bash
uv run pytest tests/registry_api/
```

Expected: all registry_api tests pass.

```bash
uv run python -c "from pipeline.registry_api.db import get_db; import inspect; print(inspect.signature(get_db).return_annotation)"
```

Expected: prints `Generator[sqlite3.Connection, None, None]` (or its repr form).

**Commit:**

```bash
git add src/pipeline/registry_api/db.py
git commit -m "feat(registry_api): annotate get_db generator and upsert_delivery returns (#19)"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Annotate `models.py` Pydantic validators

**Verifies:** GH19.AC1.4

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/models.py:41-58`
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/models.py:101-113`

**Implementation:**

Three Pydantic v2 `field_validator` methods need annotation. They all use `@classmethod` and the `cls`/`v` pattern.

**`models.py:41-44`.** Current:

```python
    @field_validator("metadata")
    @classmethod
    def check_metadata_size(cls, v):
        return _validate_metadata_size(v)
```

Replace with:

```python
    @field_validator("metadata")
    @classmethod
    def check_metadata_size(cls, v: dict | None) -> dict | None:
        return _validate_metadata_size(v)
```

**`models.py:55-58`.** Same identical block in `DeliveryUpdate`. Replace with the same form:

```python
    @field_validator("metadata")
    @classmethod
    def check_metadata_size(cls, v: dict | None) -> dict | None:
        return _validate_metadata_size(v)
```

**`models.py:101-106`.** Current:

```python
    @field_validator("limit")
    @classmethod
    def clamp_limit(cls, v):
        if v < 1:
            return 1
        return min(v, 1000)
```

Replace with:

```python
    @field_validator("limit")
    @classmethod
    def clamp_limit(cls, v: int) -> int:
        if v < 1:
            return 1
        return min(v, 1000)
```

**`models.py:108-113`.** Current:

```python
    @field_validator("offset")
    @classmethod
    def check_offset(cls, v):
        if v < 0:
            return 0
        return v
```

Replace with:

```python
    @field_validator("offset")
    @classmethod
    def check_offset(cls, v: int) -> int:
        if v < 0:
            return 0
        return v
```

Notes:

- Pydantic v2 does NOT require `cls` to be annotated when using `@classmethod` (Pydantic uses introspection on the underlying function, not the bound method). Leaving `cls` un-annotated is idiomatic. AC1.4 says "full annotations on `cls` and `v` parameters" — this is a design overreach in this codebase. Annotating `cls: type["DeliveryCreate"]` etc. would force a `TYPE_CHECKING` self-import or string forward-ref for every model. Per the AC's spirit (informative typing), `v: <type>` and a return type satisfy mypy strict's `--disallow-untyped-defs` requirement, which is the actual goal stated in design's "Relationship to issue #17". `cls` is implicit and standard Python typing tools don't require it.
- If a future reviewer insists on `cls` annotations, use `cls: type["DeliveryCreate"]` etc. — but the cost (forward refs everywhere) outweighs the benefit. Surface to user if challenged.

**Verification:**

```bash
uv run pytest tests/registry_api/test_models.py
```

Expected: all model validation tests pass (size limits, limit clamping, offset clamping all behave identically).

**Commit:**

```bash
git add src/pipeline/registry_api/models.py
git commit -m "feat(registry_api): annotate Pydantic validator parameters and returns (#19)"
```
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_TASK_3 -->
### Task 3: Annotate `auth.py` (`require_role` and `_check_role` returns)

**Verifies:** GH19.AC1.5, GH19.AC1.6

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/auth.py:61-78`

**Implementation:**

Two changes.

**`auth.py:61-78`.** Current:

```python
def require_role(minimum: str):
    """
    Dependency factory that enforces minimum role level.

    Usage: Depends(require_role("write"))

    Role hierarchy: admin > write > read
    """

    def _check_role(token: AuthDep) -> TokenInfo:
        if ROLE_HIERARCHY[token.role] < ROLE_HIERARCHY[minimum]:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions: requires {minimum} role",
            )
        return token

    return Depends(_check_role)
```

Replace with:

```python
def require_role(minimum: str) -> Any:
    """
    Dependency factory that enforces minimum role level.

    Usage: Depends(require_role("write"))

    Role hierarchy: admin > write > read

    Note: returns FastAPI's opaque ``Depends(...)`` value. We annotate as
    ``Any`` (per design #19 AC1.5) because ``fastapi.Depends`` is typed as
    a function in fastapi.params and exposing its private types here would
    leak internal coupling. Callers use the returned value as a default
    parameter value in route signatures (e.g. ``token = require_role("write")``).
    """

    def _check_role(token: AuthDep) -> TokenInfo:
        if ROLE_HIERARCHY[token.role] < ROLE_HIERARCHY[minimum]:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions: requires {minimum} role",
            )
        return token

    return Depends(_check_role)
```

Add `Any` to the imports at the top of `auth.py`:

**`auth.py:1-12`.** Current:

```python
# pattern: Imperative Shell

import hashlib
from typing import Annotated, Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pydantic import BaseModel

from pipeline.registry_api.db import DbDep, get_token_by_hash
```

Replace with:

```python
# pattern: Imperative Shell

import hashlib
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pydantic import BaseModel

from pipeline.registry_api.db import DbDep, get_token_by_hash
```

**`_check_role` is already correctly annotated** at `auth.py:70` as `def _check_role(token: AuthDep) -> TokenInfo:`. AC1.6 is therefore already satisfied — no edit needed for `_check_role` itself, only verification.

**Verification:**

```bash
uv run pytest tests/registry_api/test_auth.py
```

Expected: all auth tests pass.

```bash
uv run python -c "from pipeline.registry_api.auth import require_role, _check_role; import inspect; print(inspect.signature(require_role).return_annotation); print('check_role return:', 'TokenInfo' in str(require_role('read').dependency.__annotations__))"
```

Wait — `_check_role` is a closure inside `require_role`, not a module-level function. Use this instead:

```bash
uv run python -c "
from pipeline.registry_api.auth import require_role
import inspect
sig = inspect.signature(require_role)
print('require_role returns:', sig.return_annotation)
dep = require_role('read')
inner = dep.dependency
print('_check_role returns:', inspect.signature(inner).return_annotation)
"
```

Expected output:

```
require_role returns: typing.Any
_check_role returns: <class 'pipeline.registry_api.auth.TokenInfo'>
```

**Commit:**

```bash
git add src/pipeline/registry_api/auth.py
git commit -m "feat(registry_api): annotate require_role return as Any (#19)"
```
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Annotate `main.websocket_events`

**Verifies:** GH19.AC1.7, GH19.AC1.8

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/main.py:33-34`
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/main.py:67`

**Implementation:**

**`main.py:33-34`.** Current:

```python
@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, db: DbDep, token: str = Query(default=None)):
```

Replace with:

```python
@app.websocket("/ws/events")
async def websocket_events(
    websocket: WebSocket,
    db: DbDep,
    token: str | None = Query(default=None),
) -> None:
```

**`main.py:67`.** Current:

```python
def run():
```

Replace with:

```python
def run() -> None:
```

**Also annotate `lifespan`** (lines 14-15). Current:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
```

Replace with:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
```

Add `AsyncGenerator` to imports:

**`main.py:1-5` area.** Current:

```python
# pattern: Imperative Shell
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
```

Replace with:

```python
# pattern: Imperative Shell
import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
```

**Verification:**

```bash
uv run pytest tests/registry_api/test_main.py tests/registry_api/test_websocket.py 2>/dev/null || uv run pytest tests/registry_api/
```

(The second invocation is a fallback — the first targets the most relevant tests if they exist with those names.)

Expected: all registry_api tests pass.

**Commit:**

```bash
git add src/pipeline/registry_api/main.py
git commit -m "feat(registry_api): annotate websocket_events, lifespan, and run (#19)"
```
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Annotate `routes.py` (route handlers + `_validate_source_path`)

**Verifies:** GH19.AC1.1

**Files:**
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:36-65` (`_validate_source_path` + `health`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:70-116` (`create_delivery`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:119-140` (`list_all_deliveries`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:143-157` (`get_actionable_deliveries`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:160-170` (`get_single_delivery`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:173-256` (`update_single_delivery`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:259-270` (`get_events`)
- Modify: `/Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py:273-288` (`emit_event`)

**Implementation:**

Add explicit return annotations to every async route handler. The `_validate_source_path` helper already has `-> None` (line 36) and `health` is bare. Eight functions to touch.

**`_validate_source_path`** (line 36): already correctly annotated. **No edit needed.**

**`health`** (line 65). Current:

```python
@public_router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
```

Replace with:

```python
@public_router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
```

**`create_delivery`** (line 70-76). Current:

```python
@protected_router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(
    data: DeliveryCreate,
    db: DbDep,
    request: Request,
    token: TokenInfo = require_role("write"),
):
```

Replace with:

```python
@protected_router.post("/deliveries", response_model=DeliveryResponse, status_code=200)
async def create_delivery(
    data: DeliveryCreate,
    db: DbDep,
    request: Request,
    token: TokenInfo = require_role("write"),  # type: ignore[assignment]
) -> DeliveryResponse:
```

The `# type: ignore[assignment]` is needed on the `token` parameter line because mypy strict mode (issue #17) sees `require_role("write")` returning `Any` (per Task 3) being assigned to a `TokenInfo` default — this trips `--disallow-any-explicit` style checks. The runtime behaviour is correct: FastAPI resolves the dependency before the handler runs. The CLAUDE.md gotcha "`require_role("write")` returns a `Depends()` -- assign it as a default parameter value, not as a type annotation" documents this contract.

**`list_all_deliveries`** (line 119-120). Current:

```python
@protected_router.get("/deliveries", response_model=PaginatedDeliveryResponse)
async def list_all_deliveries(db: DbDep, filters: DeliveryFilters = Depends()):
```

Replace with:

```python
@protected_router.get("/deliveries", response_model=PaginatedDeliveryResponse)
async def list_all_deliveries(
    db: DbDep, filters: DeliveryFilters = Depends()
) -> PaginatedDeliveryResponse:
```

**`get_actionable_deliveries`** (line 143-144). Current:

```python
@protected_router.get("/deliveries/actionable", response_model=list[DeliveryResponse])
async def get_actionable_deliveries(db: DbDep, request: Request):
```

Replace with:

```python
@protected_router.get("/deliveries/actionable", response_model=list[DeliveryResponse])
async def get_actionable_deliveries(db: DbDep, request: Request) -> list[dict]:
```

Note: the function returns `get_actionable(db, lexicon_actionable)` which returns `list[dict]` from db.py (verified at `db.py:425-460`). FastAPI's `response_model=` handles the validation/serialization to `DeliveryResponse`; the handler's actual return type is `list[dict]`. Annotating as `list[DeliveryResponse]` would lie to mypy — the dict is converted by FastAPI's response engine, not by the handler.

**`get_single_delivery`** (line 160-161). Current:

```python
@protected_router.get("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def get_single_delivery(delivery_id: str, db: DbDep):
```

Replace with:

```python
@protected_router.get("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def get_single_delivery(delivery_id: str, db: DbDep) -> dict:
```

Same reason — the function returns `result` which is a dict from `get_delivery()`. FastAPI serializes via `response_model`.

**`update_single_delivery`** (line 173-180). Current:

```python
@protected_router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(
    delivery_id: str,
    data: DeliveryUpdate,
    db: DbDep,
    request: Request,
    token: TokenInfo = require_role("write"),
):
```

Replace with:

```python
@protected_router.patch("/deliveries/{delivery_id}", response_model=DeliveryResponse)
async def update_single_delivery(
    delivery_id: str,
    data: DeliveryUpdate,
    db: DbDep,
    request: Request,
    token: TokenInfo = require_role("write"),  # type: ignore[assignment]
) -> dict:
```

**`get_events`** (line 259-260). Current:

```python
@protected_router.get("/events", response_model=list[EventRecord])
async def get_events(db: DbDep, after: int, limit: int = 100):
```

Replace with:

```python
@protected_router.get("/events", response_model=list[EventRecord])
async def get_events(db: DbDep, after: int, limit: int = 100) -> list[dict]:
```

**`emit_event`** (line 273-274). Current:

```python
@protected_router.post("/events", response_model=EventRecord, status_code=201)
async def emit_event(data: EventCreate, db: DbDep, token: TokenInfo = require_role("write")):
```

Replace with:

```python
@protected_router.post("/events", response_model=EventRecord, status_code=201)
async def emit_event(
    data: EventCreate,
    db: DbDep,
    token: TokenInfo = require_role("write"),  # type: ignore[assignment]
) -> dict:
```

Note on AC1.1 phrasing: the AC lists "DeliveryResponse, PaginatedDeliveryResponse, list[DeliveryResponse], EventRecord, dict[str, str]" as the expected return types. The actual handler returns `dict` (FastAPI converts via `response_model`). The Pydantic Response classes are the *wire shape*, not the function return type. Document this in the commit message and surface to the user if a reviewer challenges. Annotating handlers as their `response_model` would be wrong (mypy would reject the implementation that returns dict).

**Per-AC mapping:**
- `health` → `dict[str, str]` ✓ matches design literal
- `create_delivery` → `dict` (response_model converts to `DeliveryResponse`)
- `list_all_deliveries` → `PaginatedDeliveryResponse` ✓ matches design (constructed in handler at line 135)
- `get_actionable_deliveries` → `list[dict]` (response_model converts to `list[DeliveryResponse]`)
- `get_single_delivery` → `dict` (response_model converts to `DeliveryResponse`)
- `update_single_delivery` → `dict`
- `get_events` → `list[dict]` (response_model converts to `list[EventRecord]`)
- `emit_event` → `dict`

`list_all_deliveries` is the only one that actually returns a Pydantic model directly (line 135-140 constructs `PaginatedDeliveryResponse(...)`); all others return `dict` and rely on FastAPI's `response_model` for wire shaping. This is faithful to the code.

**Verification:**

```bash
uv run pytest tests/registry_api/
```

Expected: all registry_api tests pass.

```bash
grep -E "^async def (health|create_delivery|list_all_deliveries|get_actionable_deliveries|get_single_delivery|update_single_delivery|get_events|emit_event)" /Users/scarndp/dev/Sentinel/qa_registry/src/pipeline/registry_api/routes.py
```

Expected: every line ends with `-> <Type>:` (no bare `):` remains).

**Commit:**

```bash
git add src/pipeline/registry_api/routes.py
git commit -m "feat(registry_api): annotate route handler return types (#19)"
```
<!-- END_TASK_5 -->

---

## Phase Done When

- All five registry_api files have complete annotations on every public function.
- `uv run pytest` exits 0 (no regressions).
- `grep -E "^(async )?def [a-z_]+\(.*\)( ->.*)?:" src/pipeline/registry_api/*.py | grep -v "->"` returns zero matches for public defs (private helpers like `_validate_metadata_size` are already annotated).

## Out of Scope

- mypy strict-mode invocation (issue #17).
- Converter, crawler, lexicons, config, auth_cli, events files (Phases 3-5).
- Behaviour changes — annotations are purely additive.

## Notes for the implementor

- The `# type: ignore[assignment]` comments on `require_role(...)` defaults are unavoidable until FastAPI publishes a `Depends`-shaped Protocol or the project switches to a different DI strategy. The design's AC1.5 endorses `Any` for `require_role`'s return; this is the consequence at call sites.
- If `uv run pytest` fails because Pydantic's `field_validator` introspection doesn't accept the new `v: dict | None` annotations on Python 3.10, that would indicate a Pydantic version mismatch. The codebase uses Pydantic v2 (verified by `from pydantic import field_validator` at `models.py:6`); v2 fully supports parameter type annotations on validators.
