# SAS-to-Parquet Converter — Phase 6: Integration + documentation

**Goal:** One real end-to-end integration test — crawler registers, daemon picks up the event, engine converts, Parquet lands on disk, registry row reflects the state. Plus documentation updates so a future engineer can operate the converter without reading the design plan.

**Architecture:** No new production code. One new integration test; three documentation files created or updated.

**Tech Stack:** pytest + TestClient (for registry), real filesystem, real SAS fixtures, no docker.

**Scope:** Phase 6 of 6. Depends on all prior phases being complete and green.

**Codebase verified:** 2026-04-16.

---

## Acceptance Criteria Coverage

### sas-to-parquet-converter.AC10: End-to-end integration
- **sas-to-parquet-converter.AC10.1 Success:** Crawler registers a delivery → daemon receives event → engine converts → registry row shows `parquet_converted_at` + `output_path` → Parquet file exists at expected path
- **sas-to-parquet-converter.AC10.2 Success:** Sub-delivery (e.g., `scdm_snapshot`) is converted independently with its own Parquet file at `{source_path}/parquet/{stem}.parquet`
- **sas-to-parquet-converter.AC10.3 Success:** `uv run pytest` passes with all new tests

---

## Engineer Briefing

**Integration-test scope:** The integration test exercises the engine end-to-end but **does not spawn the daemon subprocess**. Rationale: running `registry-convert-daemon` in a test implies an asyncio event loop, WebSocket, signal handling — all of which are tested directly in their own unit suites. Spawning a subprocess is flaky in CI and slow in dev. The integration test's value is proving the *contract between components* is aligned: crawler's POST shape matches registry; registry's GET shape matches engine; engine's PATCH shape matches registry; engine's output file matches the AC2.4 layout. This can be done with synchronous calls through function boundaries.

**Test layout:** `tests/test_end_to_end_converter.py` at the `tests/` root (not under `tests/converter/` or `tests/crawler/`) because it crosses package boundaries. There is precedent for root-level cross-package tests in this repo (verify this by looking at `tests/test_config.py` etc., which are at the root).

**Documentation files:**
- `src/pipeline/converter/CLAUDE.md` — new. Matches the style and length of `src/pipeline/crawler/CLAUDE.md` (53 lines) and `src/pipeline/lexicons/CLAUDE.md` (46 lines). Sections: Purpose, Contracts, Dependencies, Key Files, Invariants, Gotchas.
- `CLAUDE.md` at the repo root — update existing. Add converter to "Project Structure" and "Commands" sections.
- `README.md` at the repo root — update existing. Add a converter section with install, run, config fields.

**What NOT to document:**
- Internal implementation details of `convert_sas_to_parquet` (pyarrow/pyreadstat API choices) — those are in the code.
- Phase-by-phase evolution — the design plan captures that.
- Future work (aggregation, cross-workplan supersession) — belongs in design-plans, not in CLAUDE.md.

---

<!-- START_SUBCOMPONENT_A (tasks 1) -->

<!-- START_TASK_1 -->
### Task 1: End-to-end integration test

**Verifies:** AC10.1, AC10.2, AC10.3

**Files:**
- Create: `tests/test_end_to_end_converter.py`

**Implementation:**

The test builds a realistic on-disk tree matching what the crawler expects, runs the crawler against it to POST deliveries into a real in-memory (file-backed tmp) registry DB, then calls `engine.convert_one` (not the daemon) for each registered delivery. Asserts Parquet files exist and registry rows updated.

Key fixture sharing: use the existing `tests/crawler/conftest.py` `delivery_tree` fixture if it's reusable from a root-level test — otherwise inline a simpler tree. Verify pytest's conftest scoping rules: a conftest at `tests/crawler/` is only seen by tests *under* that directory. A root-level test at `tests/test_end_to_end_converter.py` will NOT see it. Options:

1. Inline the tree setup in the new test (simplest, duplicates some logic).
2. Promote the `delivery_tree` factory to `tests/conftest.py` (cleaner long-term, may affect crawler tests if scoping changes).

Go with option 1 for this phase — keep the integration test self-contained. Don't rearrange shared fixtures just for one integration test.

Contents of `tests/test_end_to_end_converter.py`:

```python
# pattern: test file
"""
End-to-end integration test for the SAS-to-Parquet converter.

Exercises the full chain: build an on-disk scan root with a real SAS file,
run the crawler to register deliveries, call engine.convert_one for each,
verify registry row updates and Parquet files on disk.

Does NOT spawn the registry HTTP server or the daemon subprocess — uses
FastAPI's TestClient with a tmp-path DB, and calls engine.convert_one
through an http_module stub that wraps TestClient's request methods.
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pyreadstat
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def end_to_end_env(tmp_path, monkeypatch):
    """
    Build an isolated environment: registry DB, lexicons dir, scan root,
    FastAPI app, and HTTP client that routes engine calls through TestClient.

    NOTE: `pipeline.registry_api.main` exposes the FastAPI instance as the
    module-level `app`, not a `build_app()` factory. We import it directly
    and overwrite `app.state.lexicons` for test isolation. Because `app` is
    a module-level singleton, tests using this fixture MUST NOT run in
    parallel with each other (pytest-xdist with this test would need
    isolation via separate processes). Single-process serial pytest is the
    current convention.
    """
    from pipeline.config import PipelineConfig, ScanRoot
    from pipeline.lexicons.loader import load_all_lexicons
    from pipeline.registry_api import main as registry_main
    from pipeline.registry_api.db import init_db

    # 1. Lexicons: copy the soc lexicons into a tmp lexicons dir.
    src_lexicons = Path(__file__).resolve().parent.parent / "pipeline" / "lexicons"
    lex_dir = tmp_path / "lexicons"
    lex_dir.mkdir()
    soc_dir = lex_dir / "soc"
    soc_dir.mkdir()
    for lex_file in (src_lexicons / "soc").glob("*.json"):
        (soc_dir / lex_file.name).write_text(lex_file.read_text())

    # 2. Database.
    db_path = tmp_path / "registry.db"
    init_db(str(db_path))

    # 3. Scan root tree: one parent delivery with a real SAS file.
    scan_root = tmp_path / "scan"
    parent_src = scan_root / "dpid_abc" / "packages" / "req001" / "soc_qar_wp001_mkscnr_v01" / "msoc"
    parent_src.mkdir(parents=True)

    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    pyreadstat.write_sas7bdat(df, str(parent_src / "msoc.sas7bdat"))

    # Optional sub-delivery — lexicon permitting (soc.qar allows scdm_snapshot).
    sub_src = parent_src / "scdm_snapshot"
    sub_src.mkdir()
    sub_df = pd.DataFrame({"x": [10, 20]})
    pyreadstat.write_sas7bdat(sub_df, str(sub_src / "scdm_snapshot.sas7bdat"))

    # 4. Config.
    config = PipelineConfig(
        scan_roots=[ScanRoot(path=str(scan_root), label="test", lexicon="soc.qar", target="packages")],
        registry_api_url="http://testserver",  # TestClient base URL
        output_root=str(tmp_path / "output"),
        schema_path=str(tmp_path / "schema.json"),
        overrides_path=str(tmp_path / "overrides.json"),
        log_dir=str(tmp_path / "logs"),
        db_path=str(db_path),
        dp_id_exclusions=[],
        crawl_manifest_dir=str(tmp_path / "manifests"),
        crawler_version="1.0.0",
        lexicons_dir=str(lex_dir),
        converter_version="0.1.0",
        converter_chunk_size=100,
        converter_compression="zstd",
        converter_state_path=str(tmp_path / "state.json"),
        converter_cli_batch_size=200,
        converter_cli_sleep_empty_secs=0,
    )

    # Monkey-patch pipeline.config.settings so crawler/engine see our config.
    import pipeline.config as config_mod
    monkeypatch.setattr(config_mod, "_settings", config)

    # 5. Use the module-level FastAPI app.
    # CRITICAL: `TestClient(app)` alone does NOT trigger FastAPI's lifespan;
    # the lifespan only runs inside a context manager (`with TestClient(app)
    # as client:`). The registry's lifespan initializes `app.state.lexicons`,
    # so without entering the context manager, that attribute is missing and
    # any monkeypatch.setattr(app.state, "lexicons", ...) would raise
    # AttributeError (the default `raising=True` requires the attr to exist).
    #
    # Two-step approach:
    #   (a) Enter the TestClient context manager so lifespan runs and sets
    #       app.state.lexicons to whatever the config points at.
    #   (b) Override app.state.lexicons with our tmp_path lexicons via
    #       monkeypatch so teardown restores the lifespan-set value.
    #
    # This is a `yield` fixture, not a plain `return`. Caller tests receive
    # the dict; teardown runs at test exit to exit the context manager.
    with TestClient(registry_main.app) as client:
        monkeypatch.setattr(
            registry_main.app.state, "lexicons",
            load_all_lexicons(str(lex_dir)),
        )
        yield {
            "tmp_path": tmp_path,
            "db_path": db_path,
            "parent_src": parent_src,
            "sub_src": sub_src,
            "config": config,
            "client": client,
        }


class _TestClientHttpAdapter:
    """
    Adapter so engine.convert_one can call TestClient as if it were the
    converter HTTP client. Implements the same method surface as
    pipeline.converter.http.
    """

    def __init__(self, client: TestClient):
        self.client = client
        # Engine catches this exception class; alias to a real one.
        from pipeline.converter.http import RegistryUnreachableError
        self.RegistryUnreachableError = RegistryUnreachableError

    def get_delivery(self, api_url, delivery_id):
        r = self.client.get(f"/deliveries/{delivery_id}")
        r.raise_for_status()
        return r.json()

    def patch_delivery(self, api_url, delivery_id, updates):
        r = self.client.patch(f"/deliveries/{delivery_id}", json=updates)
        r.raise_for_status()
        return r.json()

    def emit_event(self, api_url, event_type, delivery_id, payload):
        r = self.client.post("/events", json={
            "event_type": event_type,
            "delivery_id": delivery_id,
            "payload": payload,
        })
        r.raise_for_status()
        return r.json()

    def list_unconverted(self, api_url, after="", limit=200):
        r = self.client.get(
            f"/deliveries?converted=false&after={after}&limit={limit}"
        )
        r.raise_for_status()
        return r.json()


class TestEndToEndConverter:
    def test_crawler_to_converter_full_chain(self, end_to_end_env, monkeypatch):
        # AC10.1
        from pipeline.crawler.main import crawl
        from pipeline.converter.engine import convert_one
        from pipeline.json_logging import get_logger

        env = end_to_end_env

        # Patch at the import site (crawler.main), not the definition site.
        # crawler/main.py:12 does `from pipeline.crawler.http import post_delivery`,
        # which creates a local name in the main module. Patching
        # `pipeline.crawler.http.post_delivery` would NOT affect the call at
        # crawler/main.py:269 — the name is already bound in `main`'s namespace.
        def _patched_post(api_url, payload):
            r = env["client"].post("/deliveries", json=payload)
            r.raise_for_status()
            return r.json()

        monkeypatch.setattr("pipeline.crawler.main.post_delivery", _patched_post)

        # crawl() signature is `crawl(config, logger) -> int` (see
        # src/pipeline/crawler/main.py). Build a logger and pass both.
        test_logger = get_logger("test-crawler", log_dir=None)
        crawl_rc = crawl(env["config"], test_logger)
        assert crawl_rc == 0, f"crawl exited with {crawl_rc}"

        # Crawler registered two deliveries: parent + sub.
        rows_resp = env["client"].get("/deliveries?converted=false")
        rows = rows_resp.json()
        assert len(rows) == 2, f"expected parent + sub, got {len(rows)}: {rows}"

        parent_row = next(r for r in rows if r["source_path"] == str(env["parent_src"]))
        sub_row = next(r for r in rows if r["source_path"] == str(env["sub_src"]))

        # Run engine for each.
        adapter = _TestClientHttpAdapter(env["client"])
        for row in (parent_row, sub_row):
            result = convert_one(
                row["delivery_id"],
                "http://testserver",
                converter_version="0.1.0",
                chunk_size=100,
                compression="zstd",
                log_dir=None,
                http_module=adapter,
            )
            assert result.outcome == "success", (
                f"convert_one outcome was {result.outcome} for delivery {row['delivery_id']}"
            )

        # Parquet files exist at expected paths (AC2.4, AC10.2).
        parent_out = env["parent_src"] / "parquet" / "msoc.parquet"
        sub_out = env["sub_src"] / "parquet" / "scdm_snapshot.parquet"
        assert parent_out.exists(), f"parent Parquet missing at {parent_out}"
        assert sub_out.exists(), f"sub Parquet missing at {sub_out}"

        # Round-trip the Parquet files to confirm they're valid.
        parent_table = pq.read_table(parent_out)
        sub_table = pq.read_table(sub_out)
        assert parent_table.num_rows == 3
        assert sub_table.num_rows == 2

        # Registry rows reflect conversion.
        updated_parent = env["client"].get(f"/deliveries/{parent_row['delivery_id']}").json()
        assert updated_parent["parquet_converted_at"] is not None
        assert updated_parent["output_path"] == str(parent_out)

        updated_sub = env["client"].get(f"/deliveries/{sub_row['delivery_id']}").json()
        assert updated_sub["parquet_converted_at"] is not None
        assert updated_sub["output_path"] == str(sub_out)

        # Events table contains conversion.completed for both.
        conn = sqlite3.connect(str(env["db_path"]))
        conn.row_factory = sqlite3.Row
        rows_events = conn.execute(
            "SELECT event_type, delivery_id FROM events "
            "WHERE event_type = 'conversion.completed'"
        ).fetchall()
        conn.close()
        completed_ids = {r["delivery_id"] for r in rows_events}
        assert parent_row["delivery_id"] in completed_ids
        assert sub_row["delivery_id"] in completed_ids
```

**Note on fixtures:** This test creates its own environment; it does not depend on `tests/crawler/conftest.py`. If the lexicons under `pipeline/lexicons/soc/` change structure, the test may need updating — document this dependency in the test docstring (already done).

**Why not also test `--shard` and daemon resume in integration?** Those are covered by their own unit suites (Phase 4 and 5 tests). Integration tests are expensive — cover what the unit tests can't (contract alignment between modules), not what they already cover.

**Verification:**

Run: `uv run pytest tests/test_end_to_end_converter.py -v`
Expected: `test_crawler_to_converter_full_chain` passes.

Run: `uv run pytest`
Expected: Full suite green. This is AC10.3.

**Commit:** `test: end-to-end integration for converter`
<!-- END_TASK_1 -->

<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (tasks 2-4) -->

<!-- START_TASK_2 -->
### Task 2: Converter CLAUDE.md

**Files:**
- Create: `src/pipeline/converter/CLAUDE.md`

**Implementation:**

Match the style of `src/pipeline/crawler/CLAUDE.md` (see `src/pipeline/crawler/CLAUDE.md` for template). Sections: Purpose, Contracts, Dependencies, Key Files, Invariants, Gotchas. Keep under ~70 lines.

```markdown
# Converter

Last verified: 2026-04-16

## Purpose

Streams SAS7BDAT files to Parquet files, one delivery at a time, writing output in place on the network share. Exposes a one-shot backfill CLI (`registry-convert`) and a long-running event-driven daemon (`registry-convert-daemon`) sharing one orchestration engine. Status-blind: any delivery with null `parquet_converted_at` and no `metadata.conversion_error` is eligible for conversion.

## Contracts

- **Expects**: `pipeline.config.settings` with `registry_api_url`, `converter_version`, `converter_chunk_size`, `converter_compression`, `converter_state_path`, `converter_cli_batch_size`, `converter_cli_sleep_empty_secs`, `log_dir`. Registry API reachable at `registry_api_url`.
- **Reads**: `GET /deliveries?converted=false&after=&limit=` (backfill CLI), `GET /events?after=` + `WS /ws/events` (daemon).
- **Writes**: Parquet file at `{delivery.source_path}/parquet/{stem}.parquet`. PATCH `/deliveries/{id}` with `{output_path, parquet_converted_at}` on success or `{metadata: {conversion_error}}` on failure. POST `/events` with `conversion.completed` or `conversion.failed`.
- **Guarantees**: Atomic writes (tmp-then-rename). No automatic retry on classified failure. Skip guards on already-converted and errored deliveries. Serial (one delivery per process). Sub-deliveries are treated identically to parent deliveries — each gets its own `parquet/` subdirectory.

## Dependencies

- **Uses**: `pipeline.config.settings`, `pipeline.json_logging.get_logger`, `pipeline.events.consumer.EventConsumer` (daemon only), `pipeline.registry_api.models` (for wire shapes).
- **Uses**: `pyreadstat`, `pyarrow`, `websockets` (daemon), `httpx` (daemon — via EventConsumer).
- **Boundary**: no imports from `pipeline.registry_api.db`, `pipeline.registry_api.routes`, or crawler internals. Models are shared; nothing else.

## Key Files

- `convert.py` -- SAS-to-Parquet streaming core: pyreadstat chunks → pyarrow row groups (Functional Core)
- `classify.py` -- exception → error class mapping (Functional Core)
- `http.py` -- urllib registry client: GET/PATCH deliveries, POST events, list_unconverted (Imperative Shell)
- `engine.py` -- one-delivery orchestration: fetch, skip-guard, convert, PATCH, emit (Imperative Shell)
- `cli.py` -- `registry-convert` backfill entry point (Imperative Shell)
- `daemon.py` -- `registry-convert-daemon` event-driven entry point (Imperative Shell)

## Invariants

- Output path = `{source_path}/parquet/{source_path.name}.parquet` for both parent and sub-deliveries.
- Parquet file-level metadata always contains `sas_labels`, `sas_value_labels`, `sas_encoding`, `converter_version` as bytes keys.
- First chunk locks the Arrow schema; later mismatches raise `SchemaDriftError`.
- On exception, the tmp file (`{final}.tmp-{uuid}`) is unlinked before the exception propagates.
- Classified failures are recorded via PATCH `{metadata: {conversion_error: {...}}}` and emission of `conversion.failed` — never retried automatically.
- Daemon's `last_seq` advances on EVERY processed event regardless of type; only `delivery.created` triggers engine work.
- State file at `converter_state_path` is written via tmp + fsync + os.replace after every event the daemon processes.

## Gotchas

- The engine accepts `chunk_iter_factory` and `convert_fn` parameters as test seams — production callers never pass them.
- The daemon sets `consumer._last_seq` directly; this is an intentional contract with the reference EventConsumer. (Follow-up: if/when a third consumer needs the same resume-from-seq behaviour, promote `_last_seq` to a public setter or `resume_from(seq)` method on `EventConsumer`.)
- `--shard I/N` on the CLI uses `int(delivery_id[:8], 16) % N` — works for up to a few hundred shards; degrades beyond that.
- `registry-convert --include-failed` pre-clears `metadata.conversion_error` via PATCH before the engine sees the delivery; without the flag, the engine's skip guard filters errored deliveries.
- Signal handling is delegated to `loop.add_signal_handler`; it's a no-op on Windows (not a target platform).
- Multi-GB conversions are CPU+I/O bound; the daemon offloads them to `asyncio.to_thread` so the WebSocket keeps pumping pings.
```

**Verification:**

Review the file for matching style with `src/pipeline/crawler/CLAUDE.md`. Ensure every key claim reflects actual Phase 2–5 code.

**Commit:** `docs(converter): add package-level CLAUDE.md`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Update root CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (root) — update "Project Structure" and "Commands" sections; bump `Last verified` date.

**Implementation:**

In the "Project Structure" section, change the converter line from:

```
- `converter/` -- SAS-to-Parquet converter (placeholder)
```

to:

```
- `converter/` -- SAS-to-Parquet converter (see `src/pipeline/converter/CLAUDE.md`)
```

In the "Commands" section, add:

```
- `uv run registry-convert` -- drain unconverted deliveries backlog (backfill CLI)
- `uv run registry-convert --limit 10` -- process at most 10 deliveries
- `uv run registry-convert --shard 0/4` -- process shard 0 of 4 (horizontal split)
- `uv run registry-convert --include-failed` -- re-attempt errored deliveries
- `uv run registry-convert-daemon` -- start the event-driven converter daemon
- `pipeline/scripts/ensure_converter.sh` -- PID-based watchdog for the daemon
```

Add a new bullet to the `[project.optional-dependencies]`-related lines (after the existing `consumer` group install instruction):

```
- `uv pip install -e ".[converter]"` -- install SAS-to-Parquet converter deps (pyreadstat, pyarrow)
```

In the "Conventions" section, add:

```
- Converter writes per-delivery Parquet at `{source_path}/parquet/{stem}.parquet` — Shape A from `docs/design-plans/2026-04-16-aggregation-design-notes.md`. No hive layout, no cross-delivery aggregation.
- Converter event emission flows through `POST /events` (not PATCH side-effects), keeping registry as the single event writer while allowing converter-computed payload fields.
```

Bump the `Last verified:` and `Last context update:` dates at the top of the file to `2026-04-16`.

**Verification:**

Read the updated CLAUDE.md; verify the commands section is accurate and the structure section references the new CLAUDE.md.

**Commit:** `docs: add converter commands and conventions to root CLAUDE.md`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Update README.md

**Files:**
- Modify: `README.md` (root)

**Implementation:**

Identify where to insert the converter documentation. The existing README has sections for the registry and crawler; the converter section slots in analogously. Recommended placement: after the crawler section, before the event-consumer / testing sections.

Add this section to `README.md`:

```markdown
## Converter (`registry-convert`, `registry-convert-daemon`)

Streams registered SAS7BDAT deliveries to Parquet files, writing output
in place under each delivery's `source_path/parquet/` directory. The
converter is status-blind: any delivery with null `parquet_converted_at`
and no `metadata.conversion_error` is eligible.

### Install

```bash
uv pip install -e ".[converter]"
```

Also required when running the daemon:

```bash
uv pip install -e ".[consumer]"
```

### Backfill CLI

Drain the unconverted backlog and exit:

```bash
uv run registry-convert
```

Flags:

- `--limit N` — process at most N deliveries.
- `--shard I/N` — process only deliveries whose `delivery_id` hashes to shard `I` of `N`. Use for horizontal scale across multiple CLI invocations.
- `--include-failed` — re-attempt deliveries with `metadata.conversion_error` set (clears the field first).

Exits 0 on drain, 1 on registry unreachable, 130 on SIGINT.

### Daemon

Long-running event-driven service. Catches up on missed events via
`GET /events` on startup, then opens a WebSocket for steady-state
consumption. Persists `last_seq` after each processed event to
`converter_state_path`.

```bash
uv run registry-convert-daemon
```

Use the watchdog script from cron or a systemd timer:

```bash
* * * * * /path/to/qa_registry/pipeline/scripts/ensure_converter.sh
```

Stop with `SIGTERM` or `SIGINT`: the daemon finishes the in-flight
conversion, persists state, and exits cleanly.

### Output layout

Every delivery — parent or sub — gets:

```
{source_path}/parquet/{source_path.name}.parquet
```

Each Parquet file carries the SAS column labels, value labels, and
declared encoding as file-level key-value metadata:

```python
import pyarrow.parquet as pq
meta = pq.read_metadata("/path/to/parquet/x.parquet").metadata
column_labels = json.loads(meta[b"sas_labels"])
encoding      = meta[b"sas_encoding"].decode()
```

### Failure semantics

Classified failures are written to `metadata.conversion_error` on the
delivery row and broadcast as `conversion.failed` events. The converter
does not retry automatically. Operators clear the error by PATCHing
`{"metadata": {"conversion_error": null}}` on the delivery, or by
re-crawling (a new fingerprint clears the field via crawler upsert).

Error classes: `source_missing`, `source_permission`, `source_io`,
`parse_error`, `encoding_mismatch`, `schema_drift`, `oom`,
`arrow_error`, `unknown`.

### Configuration

New config fields (with defaults; all settable via `pipeline/config.json`):

| Field | Default | Purpose |
|-------|---------|---------|
| `converter_version` | `"0.1.0"` | Embedded in Parquet file metadata |
| `converter_chunk_size` | `100000` | Rows per pyreadstat chunk / Parquet row group |
| `converter_compression` | `"zstd"` | Parquet codec |
| `converter_state_path` | `"pipeline/.converter_state.json"` | Daemon `last_seq` persistence |
| `converter_cli_batch_size` | `200` | Page size for `GET /deliveries?converted=false` |
| `converter_cli_sleep_empty_secs` | `0` | (reserved for future poll-loop mode) |
```

**Verification:**

Open README.md; verify the new section reads coherently in context and the command examples are copy-pasteable.

**Commit:** `docs: add converter section to README`
<!-- END_TASK_4 -->

<!-- END_SUBCOMPONENT_B -->

---

## Phase completion checklist

- [ ] Four tasks committed separately.
- [ ] `uv run pytest` full suite green, including the new end-to-end test (AC10.3).
- [ ] `src/pipeline/converter/CLAUDE.md` exists and describes the package accurately.
- [ ] Root `CLAUDE.md` references the new converter commands.
- [ ] `README.md` has a converter section covering install, commands, config, output layout, and failure semantics.
- [ ] Manual full-chain smoke:
  - Start `uv run registry-api`.
  - Start `uv run registry-convert-daemon`.
  - Run `uv run python -m pipeline.crawler.main` against a real scan root with a tiny SAS fixture.
  - Within seconds, the daemon converts the delivery; verify `parquet/{stem}.parquet` appears, the registry row is PATCHed, and a `conversion.completed` event is visible via `GET /events?after=0`.
- [ ] No stray commits, no skipped tests, no `# TODO` comments anywhere in the converter package.
