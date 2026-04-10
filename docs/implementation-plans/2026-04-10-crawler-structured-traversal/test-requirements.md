# Test Requirements: Crawler Structured Traversal

**Design:** `docs/design-plans/2026-04-10-crawler-structured-traversal.md`
**Generated:** 2026-04-10

---

## Automated Tests

### AC1: Config supports target field

| Criterion | ID | Test Type | Test File | Description |
|---|---|---|---|---|
| `ScanRoot` with explicit `"target": "packages"` loads correctly | AC1.1 | Unit | `tests/test_config.py` | Create config JSON with `"target": "packages"` on a scan root entry, call `load_config`, assert `scan_root.target == "packages"` |
| `ScanRoot` without `target` field defaults to `"packages"` | AC1.2 | Unit | `tests/test_config.py` | Create config JSON with no `target` field on a scan root entry, call `load_config`, assert `scan_root.target == "packages"` |
| `ScanRoot` with non-default target loads correctly | AC1.3 | Unit | `tests/test_config.py` | Create config JSON with `"target": "compare"`, call `load_config`, assert `scan_root.target == "compare"` |
| Existing config JSON without any `target` fields loads without error | AC1.4 | Unit | `tests/test_config.py` | Load `pipeline/config.json` (real config, no `target` fields pre-Phase 1 Task 4), assert no exception raised and all scan roots have `target == "packages"` |

### AC2: Traversal constrained to canonical structure

| Criterion | ID | Test Type | Test File | Description |
|---|---|---|---|---|
| `msoc` at canonical depth is discovered | AC2.1 | Unit | `tests/crawler/test_main.py` | Create `<scan_root>/<dpid>/packages/<request_id>/<version_dir>/msoc`, call `walk_roots`, assert path is in results |
| `msoc_new` at canonical depth is discovered | AC2.2 | Unit | `tests/crawler/test_main.py` | Create `<scan_root>/<dpid>/packages/<request_id>/<version_dir>/msoc_new`, call `walk_roots`, assert path is in results |
| `msoc` inside sibling of `target` is not discovered | AC2.3 | Unit | `tests/crawler/test_main.py` | Create `<scan_root>/<dpid>/compare/<request_id>/<version_dir>/msoc` with `target="packages"`, call `walk_roots`, assert result is empty |
| `msoc` at wrong depth (directly under dpid) is not discovered | AC2.4 | Unit | `tests/crawler/test_main.py` | Create `<scan_root>/<dpid>/msoc`, call `walk_roots`, assert result is empty |
| `msoc` nested too deep is not discovered | AC2.5 | Unit | `tests/crawler/test_main.py` | Create `<scan_root>/<dpid>/packages/<request_id>/<version_dir>/subdir/msoc`, call `walk_roots`, assert result is empty |
| Multiple dpids under same scan root are all traversed | AC2.6 | Unit | `tests/crawler/test_main.py` | Create two dpid directories each with valid canonical `msoc`, call `walk_roots`, assert both paths are in results |
| Multiple version directories under same request_id are discovered | AC2.7 | Unit | `tests/crawler/test_main.py` | Create `v01/msoc` and `v02/msoc_new` under same request_id, call `walk_roots`, assert both are in results |

### AC3: Logging and diagnostics

| Criterion | ID | Test Type | Test File | Description |
|---|---|---|---|---|
| Warning logged when dpid is missing target subdirectory | AC3.1 | Unit | `tests/crawler/test_main.py` | Create dpid directory without `packages` subdirectory, call `walk_roots` with `MagicMock` logger, assert `logger.warning` called with message containing dpid name and target name |
| No warning logged when target subdirectory exists | AC3.2 | Unit | `tests/crawler/test_main.py` | Create dpid with valid `packages` subdirectory and canonical delivery, call `walk_roots` with `MagicMock` logger, assert `logger.warning` was not called |

### AC4: Backward compatibility

| Criterion | ID | Test Type | Test File | Description |
|---|---|---|---|---|
| Existing config without `target` produces identical results for canonical paths | AC4.1 | Integration | `tests/test_config.py` | Load real `pipeline/config.json` after adding `target` fields, assert all scan roots have `target == "packages"` and config structure is otherwise unchanged |
| `walk_roots` return type and signature remain compatible | AC4.2 | Unit | `tests/crawler/test_main.py` | Call `walk_roots(scan_roots)` without `logger` parameter (positional-only, no keyword), assert it returns `list[tuple[str, str]]` and does not raise `TypeError` |

---

## Human Verification

| Criterion | ID | Justification | Verification Approach |
|---|---|---|---|
| *None* | | All acceptance criteria are fully automatable via unit and integration tests against filesystem fixtures and config loading. | |

---

## Coverage Summary

| Category | Count | Automated | Human |
|---|---|---|---|
| AC1: Config supports target field | 4 | 4 | 0 |
| AC2: Traversal constrained to canonical structure | 7 | 7 | 0 |
| AC3: Logging and diagnostics | 2 | 2 | 0 |
| AC4: Backward compatibility | 2 | 2 | 0 |
| **Total** | **15** | **15** | **0** |

All 15 acceptance criteria map to automated tests. No human verification required.
