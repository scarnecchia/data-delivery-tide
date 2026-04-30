# Loading Dock

Last verified: 2026-04-30
Last context update: 2026-04-30

## Purpose

Data delivery tracking and conversion pipeline for healthcare data arriving on a network share. Crawls directory structures that encode metadata (project, workplan, version, status), registers deliveries in SQLite, and converts SAS7BDAT files to Parquet. Status semantics (valid statuses, transitions, directory mappings, actionable states) are defined by configurable lexicons rather than hardcoded values.

## Tech Stack

- Python 3.11+ (target environment: RHEL, no Docker, no systemd)
- FastAPI + Uvicorn (registry API)
- SQLite via stdlib sqlite3 (registry backing store, WAL mode)
- pyreadstat + pyarrow + pandas (SAS-to-Parquet conversion)
- websockets (WebSocket event stream)
- pytest + pytest-asyncio + httpx (testing)
- hatchling (build system)

## Commands

- `pytest` -- run all tests
- `registry-api` -- start the registry API on port 8000
- `registry-auth` -- manage auth tokens (add-user, list-users, revoke-user, rotate-token)
- `pip install -e ".[registry,converter,consumer,dev]"` -- install all deps
- `registry-convert` -- drain unconverted deliveries backlog (backfill CLI)
- `registry-convert --limit 10` -- process at most 10 deliveries
- `registry-convert --shard 0/4` -- process shard 0 of 4 (horizontal split)
- `registry-convert --include-failed` -- re-attempt errored deliveries
- `registry-convert-daemon` -- start the event-driven converter daemon
- `pipeline/scripts/ensure_registry.sh` -- PID-based watchdog for the registry API
- `pipeline/scripts/ensure_converter.sh` -- PID-based watchdog for the converter daemon

## Project Structure

- `src/pipeline/` -- main package
  - `config.py` -- config loading with env var override (`PIPELINE_CONFIG`)
  - `json_logging.py` -- JSON structured logging (JsonFormatter + file/stderr handlers)
  - `auth_cli.py` -- CLI for token lifecycle (add-user, list-users, revoke-user, rotate-token)
  - `lexicons/` -- lexicon system: models, loader, domain hooks (see `src/pipeline/lexicons/CLAUDE.md`)
  - `registry_api/` -- FastAPI app, SQLite db, Pydantic models, routes, auth, WebSocket event stream (see `src/pipeline/registry_api/CLAUDE.md`)
  - `crawler/` -- filesystem crawler (see `src/pipeline/crawler/CLAUDE.md`)
  - `events/` -- reference EventConsumer for WebSocket + REST catch-up consumption
  - `converter/` -- SAS-to-Parquet converter (see `src/pipeline/converter/CLAUDE.md`)
- `pipeline/` -- runtime config and scripts
  - `config.json` -- default pipeline configuration
  - `lexicons/` -- lexicon JSON definitions (namespace directories, e.g. `soc/`)
  - `scripts/ensure_registry.sh` -- PID-based watchdog for registry API
  - `scripts/ensure_converter.sh` -- PID-based watchdog for converter daemon
- `tests/` -- mirrors src structure
- `docs/` -- documentation
  - `setup-guide.md` -- end-to-end setup and operations guide
  - `implementation-plans/` -- phased implementation plans
- `output/` -- pipeline output directory

## Conventions

- Functional Core / Imperative Shell pattern (files annotated with `# pattern:` comment)
- Delivery IDs are deterministic SHA-256 of source_path
- Config loaded lazily via module-level `__getattr__` on `pipeline.config.settings`
- Status semantics are defined by lexicons, not hardcoded. Each lexicon declares valid statuses, allowed transitions, directory-to-status mappings (`dir_map`), actionable statuses, metadata fields, and an optional `derive_hook`. Lexicon JSON files live in `pipeline/lexicons/` and support single-level inheritance via `extends`
- Lexicons can declare `sub_dirs` mapping subdirectory names to lexicon IDs; the crawler discovers these inside terminal directories and registers them as separate deliveries correlated to the parent by shared identity fields
- Crawler uses a two-pass approach: (1) walk/parse/fingerprint/write manifests, (2) derive statuses via lexicon hooks then POST to registry
- Config fields `dp_id_exclusions`, `crawl_manifest_dir`, `crawler_version`, and `lexicons_dir` control crawler behaviour
- API authentication uses SHA-256 hashed bearer tokens with role hierarchy: admin > write > read
- Routes split into public (health) and protected (all delivery endpoints require auth; mutating endpoints require write role)
- `ScanRoot` has `path`, `label`, `lexicon`, and `target` fields; `target` (default `"packages"`) controls which subdirectory the crawler enters under each dpid; `lexicon` references a lexicon ID (e.g. `"soc.qar"`)
- Event stream uses WebSocket for real-time broadcast + REST GET /events for catch-up; events are persisted in SQLite with monotonic sequence numbers
- Events are emitted only for genuine state changes: delivery.created on first POST (not re-crawl), delivery.status_changed on status transitions
- Database stores `lexicon_id`, `status`, and `metadata` (JSON dict) per delivery instead of the former `qa_status`/`qa_passed_at` columns
- Converter writes one Parquet file per SAS file at `{source_path}/parquet/{sas_stem}.parquet`. Output path stored in registry is the directory (`{source_path}/parquet/`). Partial success supported: if some SAS files fail, others still convert and the delivery is marked converted with `metadata.conversion_errors` recording per-file failures.
- Converter event emission flows through `POST /events` (not PATCH side-effects), keeping registry as the single event writer while allowing converter-computed payload fields.

## Coding Standards

Full standards: `~/dev/Sentinel/programming-standards/python-programming-standards.md`. What follows is the condensed version.

### Architecture: Functional Core / Imperative Shell

- Pure functions take data in, return data out. No I/O, no side effects.
- Shell functions orchestrate I/O around core calls. The shell is thin — it sequences, it doesn't compute.
- Core never imports shell. Dependencies flow inward.
- If you need "and" to describe what a function does, split it.
- Label every source file: `# pattern: Functional Core`, `# pattern: Imperative Shell`, or `# pattern: Mixed (unavoidable) — [justification]` on line 1.
- Data flows into core. I/O handles (db connections, HTTP clients) stay in shell.
- Dependency injection via default parameters, not mocking frameworks. Shell accepts its dependencies; tests provide fakes.

### Type Hints & Data Structures

- All function signatures get type annotations — parameters and return type. No exceptions.
- Modern syntax: `str | None` not `Optional[str]`, `list[str]` not `List[str]`.
- Use `Literal[...]` for constrained value sets.
- Use frozen dataclasses for structured return types, not bare tuples or dicts. Use `tuple` for collection fields in frozen dataclasses (lists are still mutable via `.append()`).
- Always specify explicit dtypes for columns holding identifiers, counts, or monetary values.

### Testing

- pytest only. No `unittest.TestCase`, no `unittest.mock.patch`.
- Unit tests exercise the functional core (fast, no I/O). Integration tests exercise the shell (real files, real deps).
- Name tests `test_<function>_<scenario>`.
- If your test needs more setup than assertion, the function under test is doing too much.
- Fake only unmanaged dependencies (HTTP APIs, external services). Use real managed dependencies (in-memory DataFrames, `tmp_path`, SQLite).
- Use `pytest.raises` for exceptions, `pytest.approx` for floats.
- Fixtures share data, not state. Mutable fixtures get `function` scope; immutable ones can use `session`.

### Error Handling

- Validation errors (expected, domain-level): return as data. Caller decides severity.
- System errors (unexpected): catch at shell boundary, classify, log context, fail gracefully.
- Never bare `except` without re-raising or classifying.
- Custom exceptions for domain concepts.
- Error messages are lowercase sentence fragments. No title case, no periods.

### Logging

- Use `logging` module, never `print`. JSON lines via `JsonFormatter`.
- Configure once at the entry point. Library code uses `logging.getLogger(__name__)`.
- Include semantic context via `extra` fields: delivery_id, source_path, outcome, etc.
- Never log row-level patient data. Counts and metadata only.
- Use relative paths in `source_path` log fields, not absolute paths.

### Style & Formatting

- `ruff` for linting and formatting. Line length 100. Target Python 3.11.
- Functions are verbs. Classes are dataclasses. No God-objects.
- No `utils.py`, `helpers.py`, or `common.py` — name modules for their contents.
- If a class has one public method, it should be a function.
- Docstrings only when the signature alone is insufficient. Google-style, no `:param:` blocks.
- No comments for self-documenting code.

### Project Structure

- `src/` layout always. `pyproject.toml` only — no `setup.py`.
- One repository, one package.
- Bundled non-code files (lookups, schemas) in `resources/`. Access via `importlib.resources`.
- Entry points in `[project.scripts]`.

## Boundaries

- Safe to edit: `src/`, `tests/`, `pipeline/config.json`
- Never touch: `spec.md` (upstream requirements), `uv.lock` (managed by uv)
