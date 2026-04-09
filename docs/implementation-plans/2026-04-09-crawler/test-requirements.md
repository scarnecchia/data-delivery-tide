# Crawler Test Requirements

## Automated Tests

| Criterion | Test Type | Test File | Description | Phase/Task |
|-----------|-----------|-----------|-------------|------------|
| crawler.AC1.1 | unit | tests/crawler/test_parser.py | Standard path returns correct metadata (all 9 fields: request_id, project, request_type, workplan_id, dp_id, version, qa_status, source_path, scan_root) | P1/T2 |
| crawler.AC1.2 | unit | tests/crawler/test_parser.py | Path ending in `/msoc_new` returns qa_status=`pending` | P1/T2 |
| crawler.AC1.3 | unit | tests/crawler/test_parser.py | dp_id at boundary lengths (exactly 3 chars, exactly 8 chars) parses successfully | P1/T2 |
| crawler.AC1.4 | unit | tests/crawler/test_parser.py | Version variants `v01`, `v1`, `v10` all parse correctly | P1/T2 |
| crawler.AC1.5 | unit | tests/crawler/test_parser.py | Same relative path under different scan_roots returns correct scan_root in each result | P1/T2 |
| crawler.AC1.6 | unit | tests/crawler/test_parser.py | dp_id with 2 chars and 9 chars both return ParseError | P1/T2 |
| crawler.AC1.7 | unit | tests/crawler/test_parser.py | Directory name missing `_v\d+` suffix returns ParseError with reason containing "version" | P1/T2 |
| crawler.AC1.8 | unit | tests/crawler/test_parser.py | Path ending in neither `msoc` nor `msoc_new` returns ParseError with reason containing "msoc" | P1/T2 |
| crawler.AC1.9 | unit | tests/crawler/test_parser.py | dp_id in exclusions set returns `None` (not ParseError, not ParsedDelivery) | P1/T2 |
| crawler.AC1.10 | unit | tests/crawler/test_parser.py | Request ID `soc_qar_wp001_extra` parses with workplan_id=`wp001_extra` | P1/T2 |
| crawler.AC2.1 | integration | tests/crawler/test_main.py | `walk_roots()` discovers all `msoc` and `msoc_new` directories under temp scan_roots | P5/T4 |
| crawler.AC2.2 | integration | tests/crawler/test_main.py | `inventory_files()` returns correct filename, size_bytes, modified_at for `.sas7bdat` files in temp dir | P5/T4 |
| crawler.AC2.3 | integration | tests/crawler/test_main.py | `crawl()` with mocked `post_delivery` is called with valid DeliveryCreate payload fields | P5/T4 |
| crawler.AC2.4 | integration | tests/crawler/test_main.py | Temp trees under two different scan_roots both processed in single `crawl()` run | P5/T4 |
| crawler.AC2.5 | integration | tests/crawler/test_main.py | Non-existent scan_root is logged as warning and skipped; valid root still processed | P5/T4 |
| crawler.AC2.6 | integration | tests/crawler/test_main.py | Empty delivery dir (no `.sas7bdat` files) still processed with file_count=0 and POST made | P5/T4 |
| crawler.AC2.7 | unit | tests/crawler/test_parser.py | Two pending deliveries for same workplan+dp_id: v01 becomes `failed`, v02 stays `pending` | P5/T2 |
| crawler.AC2.8 | unit | tests/crawler/test_parser.py | Single pending delivery (no newer version) remains `pending` after derivation | P5/T2 |
| crawler.AC2.9 | unit | tests/crawler/test_parser.py | Passed delivery is never changed to `failed` regardless of newer versions | P5/T2 |
| crawler.AC3.1 | unit | tests/crawler/test_manifest.py | `build_manifest()` returns dict with all required fields (crawled_at, crawler_version, delivery_id, source_path, scan_root, parsed, qa_status, fingerprint, files, file_count, total_bytes) | P2/T2 |
| crawler.AC3.2 | unit | tests/crawler/test_manifest.py | delivery_id in manifest matches `hashlib.sha256(source_path.encode()).hexdigest()` | P2/T2 |
| crawler.AC3.3 | unit | tests/crawler/test_manifest.py | files array contains all entries with filename, size_bytes, modified_at | P2/T2 |
| crawler.AC3.4 | integration | tests/crawler/test_main.py | Run `crawl()` twice on same temp tree, read manifest files from disk, assert identical content | P5/T4 |
| crawler.AC3.5 | unit | tests/crawler/test_manifest.py | Manifest includes crawler_version and crawled_at with values matching inputs | P2/T2 |
| crawler.AC4.1 | unit | tests/crawler/test_manifest.py | `build_error_manifest()` returns dict with all required fields (error_at, crawler_version, raw_path, scan_root, error) | P2/T2 |
| crawler.AC4.2 | unit | tests/crawler/test_manifest.py | Error manifest contains raw_path, scan_root, error reason, and crawler_version | P2/T2 |
| crawler.AC4.3 | unit | tests/crawler/test_manifest.py | Error manifest filename is SHA-256 hex of raw_path; same raw_path produces same filename | P2/T2 |
| crawler.AC4.4 | integration | tests/crawler/test_main.py | Create tree with excluded dp_id, run `crawl()`, assert no error manifest written in errors/ directory | P5/T4 |
| crawler.AC5.1 | unit | tests/crawler/test_http.py | Mock urlopen to return 200 on first call; assert response dict returned, urlopen called exactly once | P3/T1 |
| crawler.AC5.2 | unit | tests/crawler/test_http.py | Mock urlopen to raise HTTPError(500) twice then return 200; assert success. Patch `time.sleep` to verify 2s, 4s backoff durations | P3/T1 |
| crawler.AC5.3 | unit | tests/crawler/test_http.py | Mock urlopen to always raise URLError; assert `RegistryUnreachableError` raised after 4 total attempts | P3/T1 |
| crawler.AC5.4 | integration | tests/crawler/test_main.py | Mock `post_delivery` to raise `RegistryUnreachableError`; assert `main()` triggers `SystemExit` with code 1 | P5/T4 |
| crawler.AC5.5 | unit | tests/crawler/test_http.py | Mock urlopen to raise HTTPError(422); assert `RegistryClientError` raised immediately, urlopen called exactly once | P3/T1 |
| crawler.AC6.1 | unit | tests/test_json_logging.py | Emit log message, capture output, parse each line as JSON without error | P4/T1 |
| crawler.AC6.2 | unit | tests/test_json_logging.py | Parse JSON output, assert `timestamp`, `level`, `message` keys present with correct values | P4/T1 |
| crawler.AC6.3 | unit | tests/test_json_logging.py | Log with `extra={"scan_root": ..., "delivery_id": ...}`, assert those keys present in JSON output; log without extras, assert absent | P4/T1 |
| crawler.AC6.4 | unit | tests/test_json_logging.py | Create logger with `tmp_path` log_dir, emit message, assert message appears in both captured stderr and file on disk | P4/T1 |
| crawler.AC7.1 | integration | tests/crawler/test_main.py | Run `crawl()` twice on same temp tree with mocked HTTP; assert manifests identical and same number of POST calls | P5/T4 |
| crawler.AC7.2 | integration | tests/crawler/test_main.py | Run `crawl()` twice on unchanged tree; verify fingerprint identical in both POST payloads via mock call args | P5/T4 |
| crawler.AC8.1 | unit | tests/crawler/test_parser.py | All AC1 parser tests run with zero filesystem or network I/O (pure function inputs only) | P1/T2 |
| crawler.AC8.2 | unit | tests/crawler/test_fingerprint.py | Fingerprint determinism (same input = same output), ordering invariance (shuffled file list = same hash), change detection (altered field = different hash) | P2/T1 |
| crawler.AC8.3 | integration | tests/crawler/test_main.py | All integration tests use `tmp_path` directory trees and `unittest.mock.patch` for HTTP calls | P5/T4 |
| crawler.AC8.4 | integration | tests/crawler/test_main.py | Tests use class-based grouping (`TestWalkRoots`, `TestInventoryFiles`, `TestCrawl`, `TestMain`) and factory helpers (`delivery_tree`, `make_crawler_config`) | P5/T4 |

## Human Verification

All 38 acceptance criteria (crawler.AC1 through crawler.AC8) are covered by automated tests. No human verification required.
