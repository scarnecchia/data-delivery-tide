# Human Test Plan: SAS-to-Parquet Converter

## Prerequisites

- RHEL target machine (or equivalent Linux env) with Python 3.10+ and `pip install -e ".[registry,converter,dev]"`
- Registry API running: `registry-api` (port 8000)
- A scan root containing at least one real SAS7BDAT file registered in the registry
- `uv run pytest` passing: 474 tests green

## Phase 1: Backfill CLI Smoke

| Step | Action | Expected |
|------|--------|----------|
| 1 | Start registry: `registry-api` | API responds at `http://localhost:8000/health` with `{"status": "ok"}` |
| 2 | Run crawler to register deliveries with real SAS files | `GET /deliveries?converted=false` returns at least one row |
| 3 | Run `registry-convert --limit 1` | Exit code 0. Exactly one delivery processed. Parquet file at `{source_path}/parquet/{stem}.parquet`. `GET /deliveries/{id}` shows non-null `parquet_converted_at` and `output_path` |
| 4 | Run `registry-convert --limit 1` again on same backlog | The previously converted delivery is skipped (already_converted). If more remain, next one is processed |
| 5 | Run `registry-convert` with no flags | All remaining unconverted deliveries processed. Exit 0 |
| 6 | Run `registry-convert` on empty backlog | Exit 0 immediately. No conversion attempts |
| 7 | Run `registry-convert --shard 0/2` on fresh unconverted set | Only ~half the deliveries processed (those whose delivery_id hash mod 2 == 0). Running `--shard 1/2` processes the remainder |

## Phase 2: Failure Path Smoke

| Step | Action | Expected |
|------|--------|----------|
| 1 | Register a delivery whose `source_path` points to a non-existent directory | Run `registry-convert`. Delivery gets `metadata.conversion_error.class = "source_missing"`. `GET /events?after=0` includes a `conversion.failed` event for that delivery_id |
| 2 | Run `registry-convert` again (without --include-failed) | The errored delivery is skipped. No new PATCH or event |
| 3 | Run `registry-convert --include-failed` | CLI issues PATCH clearing `conversion_error`, then re-attempts conversion. If source still missing, error is re-recorded |

## Phase 3: Daemon Lifecycle

| Step | Action | Expected |
|------|--------|----------|
| 1 | Start daemon: `registry-convert-daemon` | Process starts, logs "daemon started". State file created at `converter_state_path` |
| 2 | POST a new delivery via crawler or direct `POST /deliveries` | Daemon logs receipt of `delivery.created` event and begins conversion. Parquet file appears. `conversion.completed` event emitted |
| 3 | Check state file (e.g., `cat pipeline/.converter_state.json`) | `last_seq` reflects the seq of the most recently processed event |
| 4 | Kill the registry API process | Daemon logs WebSocket disconnect. Daemon attempts reconnection with backoff |
| 5 | Restart registry API | Daemon reconnects. Catch-up via `GET /events?after={last_seq}` processes any events missed during downtime |

## Phase 4: Signal Handling (AC9.6 Human Verification)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Start daemon: `registry-convert-daemon` | Running normally |
| 2 | POST a delivery with a large SAS file (takes >1s to convert) | Daemon begins conversion |
| 3 | While conversion is in-flight, send `SIGTERM`: `kill -TERM <pid>` | In-flight conversion completes (Parquet file fully written). State file reflects the event's seq. Process exits with code 0. No partial/corrupt Parquet files on disk |
| 4 | Restart daemon | Daemon resumes from persisted `last_seq`. No duplicate processing of the delivery that was in-flight when SIGTERM arrived |

## Phase 5: Parquet Output Verification

| Step | Action | Expected |
|------|--------|----------|
| 1 | Open a converted Parquet file in Python: `pq.read_table(path)` | Table loads without error. Row count matches source SAS file |
| 2 | Inspect file metadata: `pq.read_metadata(path).metadata` | Contains keys `b"sas_labels"`, `b"sas_value_labels"`, `b"sas_encoding"`, `b"converter_version"`. Labels JSON parses correctly |
| 3 | For a file with column labels in SAS, verify `sas_labels` | Dict maps column names to their SAS labels. No columns missing |
| 4 | For a sub-delivery (e.g., scdm_snapshot), verify path | Parquet at `{sub_source_path}/parquet/{sub_stem}.parquet`, not under the parent's parquet dir |

## End-to-End: Full Pipeline Round-Trip

1. Ensure registry API is running with a fresh database
2. Place a new SAS delivery on the scan root (new dpid/version directory with .sas7bdat files)
3. Run the crawler
4. Verify `GET /deliveries` returns the new delivery with `parquet_converted_at: null`
5. Verify `GET /events?after=0` includes `delivery.created` for the new delivery
6. Start the daemon: `registry-convert-daemon`
7. Observe daemon picks up the delivery.created event from catch-up, converts the file
8. Verify Parquet file exists at `{source_path}/parquet/{stem}.parquet`
9. Verify `GET /deliveries/{id}` shows `parquet_converted_at` and `output_path` populated
10. Verify `GET /events?after=0` includes `conversion.completed` with correct `row_count` and `bytes_written`
11. Place a second delivery on the scan root, run crawler again
12. Observe daemon receives real-time `delivery.created` via WebSocket (no restart needed), converts immediately
13. Send SIGTERM to daemon. Verify clean shutdown (state persisted, no partial files)
14. Restart daemon. Verify it resumes from the correct seq (no duplicate work)

## Traceability

| Acceptance Criterion | Automated Test | Manual Step |
|----------------------|----------------|-------------|
| AC1.1-AC1.6 | `test_convert.py` (6 tests) | Phase 5 |
| AC2.1-AC2.5 | `test_convert.py` (5 tests) | Phase 5 Step 4 |
| AC3.1-AC3.3 | `test_convert.py` (3 tests) | -- |
| AC4.1-AC4.9 | `test_classify.py` (12 cases) | -- |
| AC5.1-AC5.6 | `test_engine.py` (10+ tests) | Phase 2 |
| AC6.1-AC6.4 | `test_db.py` + `test_routes.py` + `test_models.py` | E2E Step 10 |
| AC7.1-AC7.3 | `test_db.py` + `test_routes.py` | -- |
| AC8.1-AC8.6 | `test_cli.py` (8+ tests) | Phase 1 |
| AC9.1-AC9.5, AC9.7 | `test_daemon.py` + `test_consumer.py` | Phase 3 |
| AC9.6 | `test_daemon.py` (unit) | Phase 4 |
| AC10.1-AC10.2 | `test_end_to_end_converter.py` | E2E round-trip |
| AC10.3 | -- (meta-criterion) | `uv run pytest` green |
