# Crawler Structured Traversal Design

## Summary

The crawler currently uses `os.walk` to find `msoc` and `msoc_new` directories anywhere in the filesystem subtree under each configured scan root. This works when the directory structure is clean, but it silently picks up deliveries that land in the wrong location — for example, in a `compare` subdirectory that sits alongside the intended `packages` subdirectory, or at an unexpected depth. The fix is to replace the unconstrained walk with a level-by-level `os.scandir` descent that knows exactly where each level of the hierarchy should be.

The approach enforces a canonical five-level structure: `<scan_root> / <dpid> / <target> / <request_id> / <version_dir> / {msoc|msoc_new}`. Each level is descended into explicitly and independently, so a directory in the wrong position is simply never entered rather than discovered and then filtered. The `target` subdirectory name (the second level, currently always `packages`) becomes a per-scan-root config field with a default, keeping backward compatibility while enabling future crawl roots aimed at other subdirectories like `compare`. The function signature of `walk_roots` is unchanged so no callers need to be updated.

## Definition of Done

- Crawler only descends into the configured target subdirectory (default: `packages`) under each dpid, ignoring sibling directories like `compare`
- Traversal follows the canonical 5-level structure: `<scan_root>/<dpid>/<target>/<request_id>/<version_dir>/{msoc|msoc_new}`
- Target subdirectory is configurable per scan root via config JSON
- Existing configs without `target` field continue to work (defaults to `packages`)
- Crawler logs a warning when a dpid directory is missing its target subdirectory
- No rogue `msoc`/`msoc_new` directories outside the canonical structure are picked up
- All existing tests pass; new tests cover the structural constraints

## Acceptance Criteria

### crawler-structured-traversal.AC1: Config supports target field
- **crawler-structured-traversal.AC1.1 Success:** `ScanRoot` with explicit `"target": "packages"` loads correctly
- **crawler-structured-traversal.AC1.2 Success:** `ScanRoot` without `target` field defaults to `"packages"`
- **crawler-structured-traversal.AC1.3 Success:** `ScanRoot` with non-default target (e.g. `"compare"`) loads correctly
- **crawler-structured-traversal.AC1.4 Edge:** Existing config JSON without any `target` fields loads without error

### crawler-structured-traversal.AC2: Traversal constrained to canonical structure
- **crawler-structured-traversal.AC2.1 Success:** `msoc` directory at canonical depth (`<dpid>/<target>/<request_id>/<version_dir>/msoc`) is discovered
- **crawler-structured-traversal.AC2.2 Success:** `msoc_new` directory at canonical depth is discovered
- **crawler-structured-traversal.AC2.3 Failure:** `msoc` directory inside a sibling of `target` (e.g. `compare/`) is not discovered
- **crawler-structured-traversal.AC2.4 Failure:** `msoc` directory at wrong depth (e.g. directly under dpid) is not discovered
- **crawler-structured-traversal.AC2.5 Failure:** `msoc` directory nested too deep (extra level between version_dir and msoc) is not discovered
- **crawler-structured-traversal.AC2.6 Success:** Multiple dpids under the same scan root are all traversed
- **crawler-structured-traversal.AC2.7 Success:** Multiple version directories under the same request_id are all discovered

### crawler-structured-traversal.AC3: Logging and diagnostics
- **crawler-structured-traversal.AC3.1 Success:** Warning logged when a dpid directory is missing its target subdirectory
- **crawler-structured-traversal.AC3.2 Success:** No warning logged when target subdirectory exists

### crawler-structured-traversal.AC4: Backward compatibility
- **crawler-structured-traversal.AC4.1 Success:** Existing config JSON without `target` field produces identical crawl results to current behaviour for canonical paths
- **crawler-structured-traversal.AC4.2 Success:** `walk_roots` return type and signature remain compatible with callers

## Glossary

- **`os.walk`**: Python stdlib function that recursively yields all files and directories under a root, without structural constraints — visits everything it can reach.
- **`os.scandir`**: Python stdlib function that lists the direct children of a single directory, returning entry objects. Used here one level at a time to enforce traversal structure.
- **scan root**: A top-level directory the crawler is configured to search. Each scan root has a `path`, a `label`, and (after this change) a `target` field.
- **dpid**: Data product ID. A directory directly under the scan root, representing a distinct healthcare data product.
- **target**: The subdirectory under each dpid that contains deliveries (e.g. `packages`). Configurable per scan root; defaults to `"packages"`.
- **request_id**: A directory under `target` that groups version directories for a single delivery request.
- **version_dir**: A directory under `request_id` representing a specific versioned delivery. Named according to a validated regex convention.
- **`msoc` / `msoc_new`**: Terminal directories encoding QA status. `msoc` = passed, `msoc_new` = pending. Only these two names are recognised at the final level.
- **`ScanRoot`**: Python dataclass in `config.py` representing one configured crawl root, including path, label, and target.
- **`walk_roots`**: The imperative shell function in `crawler/main.py` that performs filesystem traversal and returns `(path, scan_root)` tuples for discovered delivery directories.
- **`parse_path`**: The functional core function in `crawler/parser.py` that validates naming conventions on a discovered path. Complementary to `walk_roots`: structure vs. naming.
- **Functional Core / Imperative Shell**: An architectural pattern that separates pure logic (no I/O, easily testable) from side-effectful orchestration code. The crawler already follows this split; this design stays within it.

## Architecture

Replace the unconstrained `os.walk` in `walk_roots` with a level-by-level `os.scandir` descent that enforces the canonical directory hierarchy at each level.

The `ScanRoot` config dataclass gains an optional `target` field (default: `"packages"`), allowing each scan root to specify which subdirectory contains deliveries. This is a config-level concern, not hardcoded.

Traversal proceeds through exactly 5 levels:

1. **Level 1 (dpid):** `os.scandir` on scan_root, yield all subdirectories
2. **Level 2 (target):** Only enter the directory matching `target` (e.g. `packages`). Log warning if missing. Skip all siblings.
3. **Level 3 (request_id):** List all subdirectories under target
4. **Level 4 (version_dir):** List all subdirectories under each request_id directory
5. **Level 5 (terminal):** Check for `msoc` or `msoc_new` only. Collect matches, ignore everything else.

No directory outside this structure is ever entered. The function signature remains `walk_roots(scan_roots) -> list[tuple[str, str]]` to avoid breaking callers.

`parse_path` is unchanged. It continues to validate naming conventions (version directory regex, request_id segments). The two functions have complementary responsibilities:

- `walk_roots` enforces structural correctness (right place in the tree)
- `parse_path` enforces naming correctness (right naming conventions)

## Existing Patterns

Investigation found that the crawler already uses a functional core / imperative shell split:

- `parser.py` (Functional Core) handles all path parsing and metadata extraction
- `main.py` (Imperative Shell) handles filesystem I/O and orchestration
- `walk_roots` lives in `main.py` as an imperative shell function

This design follows the same split. `walk_roots` remains in `main.py` as imperative shell code. No new modules needed.

The `ScanRoot` dataclass in `config.py` already uses Python dataclass defaults (`path: str`, `label: str`). Adding `target: str = "packages"` follows the existing pattern.

`load_config` in `config.py` already uses `data.get()` with defaults for optional fields (`dp_id_exclusions`, `crawl_manifest_dir`, `crawler_version`). The `target` field follows this same pattern.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Config Extension

**Goal:** Add `target` field to `ScanRoot` and config loading

**Components:**
- `ScanRoot` dataclass in `src/pipeline/config.py` — add `target: str = "packages"` field
- `load_config` in `src/pipeline/config.py` — parse `target` from each scan root entry, default to `"packages"`
- Config JSON `pipeline/config.json` — add `target` field to existing scan root entries

**Dependencies:** None

**Done when:** Config loads with `target` field present on each `ScanRoot` instance. Existing config without `target` defaults to `"packages"`. Tests verify both cases.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Structured Traversal

**Goal:** Replace unconstrained `os.walk` with level-by-level `os.scandir` descent

**Components:**
- `walk_roots` in `src/pipeline/crawler/main.py` — rewrite to use 5-level scandir descent, constrained by `target` from each scan root
- Logger integration — warn when dpid is missing its target subdirectory

**Dependencies:** Phase 1 (ScanRoot has `target` field)

**Done when:**
- Crawler only finds `msoc`/`msoc_new` at the canonical depth within the target subdirectory
- Sibling directories of `target` (e.g. `compare/`) are never entered, even if they contain `msoc` directories
- `msoc` directories at wrong depths are not picked up
- Warning logged for dpid directories missing their target subdirectory
- All existing tests updated and passing; new tests cover structural constraints
<!-- END_PHASE_2 -->

## Additional Considerations

**Backward compatibility:** Omitting `target` from config JSON defaults to `"packages"`. No existing deployment needs config changes unless they want a non-default target.

**Future extensibility:** When `compare` directory crawling is needed, add a second scan root entry with `"target": "compare"` and (if needed) a separate parser for compare's metadata conventions. One crawler binary, multiple configurations.
