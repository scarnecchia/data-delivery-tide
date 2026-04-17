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
