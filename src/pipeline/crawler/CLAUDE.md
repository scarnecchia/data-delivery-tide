# Crawler

Last verified: 2026-04-10

## Purpose

Walks configured scan roots to discover healthcare data deliveries encoded in directory structure, parses metadata from paths, fingerprints file inventories, writes JSON crawl manifests, derives QA failure statuses, and POSTs deliveries to the registry API.

## Contracts

- **Expects**: `pipeline.config.settings` with `scan_roots` (each with `path`, `label`, and `target` fields), `dp_id_exclusions`, `crawl_manifest_dir`, `crawler_version`, `registry_api_url`, `log_dir`. Reads `REGISTRY_TOKEN` env var for bearer auth (required when registry auth is enabled).
- **Produces**: JSON crawl manifests in `crawl_manifest_dir` (one per delivery, keyed by delivery_id). Error manifests in `crawl_manifest_dir/errors/`.
- **Calls**: `POST /deliveries` on the registry API for each resolved delivery
- **Guarantees**: Two-pass crawl -- manifests are written before any registry POST. Failed status derivation happens between passes (pending delivery superseded by newer version in same workplan+dp_id = failed). `walk_roots` enforces canonical 5-level traversal constrained by `target` field: only directories matching the configured `target` under each dpid are descended.

## Dependencies

- **Uses**: `pipeline.config.settings`, `pipeline.json_logging.get_logger`
- **Uses**: registry API via HTTP (stdlib urllib, no requests dependency)
- **Used by**: entry point `python -m pipeline.crawler.main` or future scheduler
- **Boundary**: no imports from registry_api or converter

## Key Files

- `parser.py` -- path parsing and QA status derivation (Functional Core)
- `fingerprint.py` -- deterministic SHA-256 fingerprint from file inventory (Functional Core)
- `manifest.py` -- builds crawl manifest and error manifest dicts, generates delivery_id (Functional Core)
- `http.py` -- registry API client with exponential backoff retry and optional bearer auth (Imperative Shell)
- `main.py` -- orchestrator: walk_roots, inventory_files, crawl(), main() entry point (Imperative Shell)

## Invariants

- `walk_roots` enforces canonical 5-level structure: `<scan_root>/<dpid>/<target>/<request_id>/<version_dir>/{msoc|msoc_new}`. Only directories at this exact depth are discovered. Sibling directories (e.g., `compare/`) or wrong depth (e.g., `msoc` directly under dpid) are not traversed.
- `walk_roots` logs a warning when a dpid directory is missing its configured `target` subdirectory (e.g., dpid has no `packages/` when `target="packages"`).
- delivery_id = SHA-256 of source_path (computed in manifest.py, must match registry_api convention)
- fingerprint = "sha256:<hex>" computed from sorted (filename, size_bytes, modified_at) tuples; "sha256:<hash_of_empty>" for empty directories
- parse_path returns ParsedDelivery | ParseError | None (None = excluded dp_id, skip silently)
- derive_qa_statuses: groups by (workplan_id, dp_id), marks all pending deliveries except the highest version as "failed"
- Version directory pattern: `<name>_<dp_id>_v<digits>` where dp_id is 3-8 alphanumeric chars
- http.post_delivery retries on 5xx/network errors with backoff (2, 4, 8 seconds), raises RegistryUnreachableError on exhaustion, raises RegistryClientError on 4xx (no retry)

## Gotchas

- `walk_roots` uses `os.scandir()` with immediate `list()` consumption for resource safety; each level is independently constrained by directory existence (no deep nesting needed).
- `walk_roots` requires `target` to be set in each `ScanRoot` object; missing targets are logged as warnings but do not raise exceptions.
- dp_id_exclusions filtering happens in parse_path, returning None -- callers must handle the None case
- All manifests in a single crawl run share the same crawled_at timestamp (marks the run, not individual processing)
- The http client uses stdlib urllib, not requests/httpx -- intentional to avoid runtime dependencies
- `main()` catches `RegistryClientError` for 401/403 and logs actionable messages (set REGISTRY_TOKEN, check role). Other 4xx errors log the full error. All exit with code 1.
- `REGISTRY_TOKEN` is read in `main()` and threaded through `crawl()` to `post_delivery()` -- the token is optional at each layer for backwards compatibility
