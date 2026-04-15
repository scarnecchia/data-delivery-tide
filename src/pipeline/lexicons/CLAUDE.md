# Lexicons

Last verified: 2026-04-14
Last updated: 2026-04-14 (added sub_dirs field)

## Purpose

Configurable status vocabulary system. Defines valid statuses, transitions, directory-to-status mappings, actionable states, metadata fields, derivation hooks, and sub-directory mappings per domain. Replaces hardcoded QA status logic with JSON-defined lexicons that support single-level inheritance.

## Contracts

- **Exposes**: `load_all_lexicons(lexicons_dir)` returns `dict[str, Lexicon]` keyed by lexicon ID (e.g. `"soc.qar"`). `load_lexicon(lexicon_id, lexicons_dir)` for single-lexicon convenience.
- **Raises**: `LexiconLoadError` with batch error list on any validation failure (missing dir, parse errors, circular extends, unknown references, depth exceeded, bad hooks, unknown sub_dirs references, recursive sub_dirs nesting)
- **Guarantees**: All lexicons are fully resolved (inheritance applied), validated (statuses, transitions, dir_map, metadata_fields, sub_dirs all cross-referenced), and frozen before return. Max inheritance depth is 3. sub_dirs references must point to existing lexicons with no sub_dirs themselves (no recursive nesting).

## Dependencies

- **Uses**: stdlib only (`json`, `dataclasses`, `graphlib`, `importlib`, `pathlib`)
- **Used by**: `pipeline.config` (validates scan root lexicon references), `pipeline.registry_api.main` (loads at startup into `app.state`), `pipeline.crawler.main` (loads for dir_map and derive_hook)
- **Boundary**: no imports from registry_api, crawler, or events

## Key Files

- `models.py` -- `Lexicon` and `MetadataField` frozen dataclasses (Functional Core)
- `loader.py` -- discovery, inheritance resolution, validation, hook import, batch loading (Functional Core)
- `soc/qa.py` -- QA derivation hook: marks pending deliveries as "failed" when superseded by newer version in same workplan+dp_id (Functional Core)

## Invariants

- Lexicon ID is derived from file path relative to lexicons_dir: `soc/qar.json` becomes `soc.qar`
- Inheritance via `extends` field references another lexicon ID; child keys win on merge, nested dicts merge recursively
- Circular extends chains are detected via `graphlib.TopologicalSorter` and rejected
- `derive_hook` is a `"module.path:function"` string in JSON, imported at load time; signature is `(deliveries: list[ParsedDelivery], lexicon: Lexicon) -> list[ParsedDelivery]`
- `metadata_fields[].set_on` references a status; when a delivery transitions to that status, the field is auto-populated (datetime fields get UTC ISO timestamp)
- `sub_dirs` maps directory names to lexicon IDs (e.g., `{"scdm_snapshot": "soc.scdm"}`); all referenced lexicon IDs must exist and have no sub_dirs themselves (no recursive nesting)
- All validation errors are collected and reported in a single `LexiconLoadError`, not fail-fast

## Gotchas

- `load_all_lexicons` always loads ALL lexicons in the directory even when you only need one -- this is intentional for cross-validation of extends references and sub_dirs references
- Lexicon JSON files live in `pipeline/lexicons/` (runtime config), not `src/pipeline/lexicons/` (which has the Python code)
- The `soc._base` lexicon has no `derive_hook` and no `metadata_fields`; `soc.qar` extends it to add the QA hook and `passed_at` metadata
- `*.schema.json` files in the lexicons directory are skipped during discovery — they define the format, not a lexicon
- `$schema` keys in lexicon JSON files are stripped at parse time so they don't interfere with validation or building
- `sub_dirs` validation happens AFTER all lexicons are built (not during parsing), so all referenced lexicons must exist globally
- Recursive sub_dirs nesting is not allowed: if lexicon A has sub_dirs pointing to B, then B cannot have its own sub_dirs
