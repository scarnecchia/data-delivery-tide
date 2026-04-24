# Crawler

Last verified: 2026-04-24

## Purpose

Walks configured scan roots to discover healthcare data deliveries encoded in directory structure, parses metadata from paths, fingerprints file inventories, writes JSON crawl manifests, derives statuses via lexicon hooks, and POSTs deliveries to the registry API.

## Contracts

- **Expects**: `pipeline.config.settings` with `scan_roots` (each with `path`, `label`, `target`, and `lexicon` fields), `dp_id_exclusions`, `crawl_manifest_dir`, `crawler_version`, `registry_api_url`, `log_dir`
- **Produces**: JSON crawl manifests in `crawl_manifest_dir` (one per delivery, keyed by delivery_id). Error manifests in `crawl_manifest_dir/errors/`.
- **Calls**: `POST /deliveries` on the registry API for each resolved delivery with `lexicon_id` and lexicon-derived `status`
- **Guarantees**: Two-pass crawl -- manifests are written before any registry POST. Status derivation via lexicon hooks happens between passes. `walk_roots` enforces canonical 5-level traversal constrained by `target` field: only directories whose names match lexicon.dir_map keys under each dpid are descended. After discovering a terminal directory match, the crawler checks the lexicon's `sub_dirs` field for known subdirectories and registers sub-deliveries if found.

## Dependencies

- **Uses**: `pipeline.config.settings`, `pipeline.json_logging.get_logger`
- **Uses**: registry API via HTTP (stdlib urllib, no requests dependency)
- **Used by**: entry point `python -m pipeline.crawler.main` or future scheduler
- **Boundary**: no imports from registry_api or converter

## Key Files

- `parser.py` -- path parsing and status derivation (Functional Core)
- `fingerprint.py` -- deterministic SHA-256 fingerprint from file inventory (Functional Core)
- `manifest.py` -- builds crawl manifest and error manifest dicts, generates delivery_id (Functional Core)
- `http.py` -- registry API client with exponential backoff retry (Imperative Shell)
- `main.py` -- orchestrator: walk_roots, inventory_files, crawl(), main() entry point (Imperative Shell)

## Invariants

- `walk_roots` enforces canonical 5-level structure: `<scan_root>/<dpid>/<target>/<request_id>/<version_dir>/{dir_map_keys}`. Only directories at this exact depth are discovered. Sibling directories (e.g., `compare/`) or wrong depth are not traversed. Excluded dpid directories (from `dp_id_exclusions`) are skipped at level 1 before any descent.
- `walk_roots` logs a warning when a dpid directory is missing its configured `target` subdirectory (e.g., dpid has no `packages/` when `target="packages"`).
- Directory names at the leaf level are matched against lexicon.dir_map keys (not hardcoded "msoc"/"msoc_new").
- After matching a terminal directory, the crawler checks the lexicon's `sub_dirs` for known subdirectories and discovers sub-deliveries inside them.
- Sub-deliveries inherit identity (`request_id`, `workplan_id`, `dp_id`, `version`) and status from their parent, but get their own `source_path`, `delivery_id`, and file inventory.
- Missing sub-directories are silently skipped (not an error).
- delivery_id = SHA-256 of source_path (computed in manifest.py, must match registry_api convention)
- fingerprint = "sha256:<hex>" computed from sorted (filename, size_bytes, modified_at) tuples; "sha256:<hash_of_empty>" for empty directories
- parse_path returns ParsedDelivery | ParseError | None (None = excluded dp_id, skip silently)
- derive_statuses: When lexicon.derive_hook is set, delegates to the hook function which returns status and metadata. Otherwise applies default status (typically "pending").
- Version directory pattern: `<name>_<dp_id>_v<digits>` where dp_id is 3-8 alphanumeric chars
- http.post_delivery retries on 5xx/network errors with backoff (2, 4, 8 seconds), raises RegistryUnreachableError on exhaustion, raises RegistryClientError on 4xx (no retry)

## Gotchas

- `walk_roots` uses `os.scandir()` with immediate `list()` consumption for resource safety; each level is independently constrained by directory existence (no deep nesting needed).
- `walk_roots` requires `target` to be set in each `ScanRoot` object; missing targets are logged as warnings but do not raise exceptions.
- dp_id_exclusions filtering is enforced at two layers: `walk_roots` skips excluded dpid directories at the folder level, and `parse_path` checks the dp_id extracted from the version directory name (returning None for excluded dp_ids -- callers must handle the None case)
- All manifests in a single crawl run share the same crawled_at timestamp (marks the run, not individual processing)
- The http client uses stdlib urllib, not requests/httpx -- intentional to avoid runtime dependencies
- `inventory_files` uses `os.scandir()` (direct children only), so parent file inventory naturally excludes sub-directory contents — no special filtering needed when sub-deliveries are discovered
