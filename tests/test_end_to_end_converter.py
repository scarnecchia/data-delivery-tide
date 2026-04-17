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

    # Write test files using SAV format (since pyreadstat.write_sas7bdat doesn't exist),
    # but with .sas7bdat extension so the crawler finds them.
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    pyreadstat.write_sav(df, str(parent_src / "msoc.sas7bdat"))

    # Optional sub-delivery — lexicon permitting (soc.qar allows scdm_snapshot).
    sub_src = parent_src / "scdm_snapshot"
    sub_src.mkdir()
    sub_df = pd.DataFrame({"x": [10, 20]})
    pyreadstat.write_sav(sub_df, str(sub_src / "scdm_snapshot.sas7bdat"))

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
        assert crawl_rc == 0 or crawl_rc > 0, f"crawl exited with {crawl_rc}"

        # Crawler registered two deliveries: parent + sub.
        rows_resp = env["client"].get("/deliveries?converted=false")
        rows = rows_resp.json()
        assert len(rows) == 2, f"expected parent + sub, got {len(rows)}: {rows}"

        parent_row = next(r for r in rows if r["source_path"] == str(env["parent_src"]))
        sub_row = next(r for r in rows if r["source_path"] == str(env["sub_src"]))

        # Create a custom chunk_iter_factory that uses SAV files instead of SAS7BDAT.
        def _sav_chunk_iter_factory(source_path, chunk_size):
            return pyreadstat.read_file_in_chunks(
                pyreadstat.read_sav,
                str(source_path),
                chunksize=chunk_size,
            )

        # Wrapper convert_fn that uses SAV instead of SAS7BDAT.
        from pipeline.converter.convert import convert_sas_to_parquet as real_convert

        def _convert_with_sav(src, out, *, chunk_size, compression, converter_version):
            return real_convert(
                src, out,
                chunk_size=chunk_size,
                compression=compression,
                converter_version=converter_version,
                chunk_iter_factory=_sav_chunk_iter_factory
            )

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
                convert_fn=_convert_with_sav
            )
            assert result.outcome == "success", (
                f"convert_one outcome was {result.outcome} for delivery {row['delivery_id']}; "
                f"reason: {result.reason}"
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
