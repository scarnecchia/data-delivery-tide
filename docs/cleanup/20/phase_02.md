# GH20 Phase 2: Crawler Imperative Shell — `walk_roots` and `delivery_data`

**Goal:** Replace the bare-tuple shapes in `crawler/main.py` with frozen dataclasses: `walk_roots` returns `list[WalkResult]` instead of `list[tuple[str, str]]`, and the `delivery_data` accumulator stops being `dict[str, tuple[list[FileEntry], str, dict]]` and becomes `dict[str, DeliveryAccumulator]`. Update all destructuring inside `crawl()` to attribute access.

**Architecture:** Phase 1 already converted `FileEntry` and `CrawlManifest` to frozen dataclasses; Phase 2 finishes the crawler-side migration in the Imperative Shell. No new external API; the registry POST payload, the on-disk manifest, and the log-extra dict are unchanged because all conversions happen at construction time and `manifest.delivery_id` reads through the dataclass attribute layer.

**Tech Stack:** Python 3.10+ stdlib `dataclasses`; no new dependencies.

**Scope:** 2 of 5 phases of GH20. Touches `src/pipeline/crawler/main.py` and `tests/crawler/test_main.py`. Hard-depends on Phase 1 (the `CrawlManifest` and `FileEntry` types must already be dataclasses before this phase's `manifest.delivery_id` reads land). Independent of Phases 3-5.

**Codebase verified:** 2026-04-29.

---

## Acceptance Criteria Coverage

This phase implements and tests:

### GH20.AC2: Crawler Imperative Shell types are dataclasses
- **GH20.AC2.1 Success:** `walk_roots` returns `list[WalkResult]` with `.source_path` and `.scan_root` attributes.
- **GH20.AC2.2 Success:** `delivery_data` accumulator value is a frozen dataclass with `.files`, `.fingerprint`, and `.manifest` fields.
- **GH20.AC2.3 Success:** All destructuring in `crawl()` uses attribute access, not tuple unpacking.
- **GH20.AC2.4 Failure:** Existing `test_main.py` tests pass (with the access-syntax updates documented below).

### GH20.AC5: Cross-cutting — no serialization regression
- **GH20.AC5.3 Success:** Crawl manifest JSON files written to disk are unchanged. The serialisation site at `crawl()` becomes `json.dump(dataclasses.asdict(manifest), f, indent=2)`, which produces the same JSON shape as the previous `json.dump(manifest_dict, f, indent=2)` because `CrawlManifest`'s field order matches the previous dict literal.

---

## Codebase verification findings

- `src/pipeline/crawler/main.py:9` — currently: `from pipeline.crawler.manifest import build_manifest, build_error_manifest`. After Phase 1, `build_error_manifest` returns `ErrorManifestResult`. The destructuring at line 164 (`filename, error_manifest = build_error_manifest(...)`) breaks; rewrite to attribute access (see Task 2).
- `src/pipeline/crawler/main.py:34-39` — `walk_roots` currently typed `-> list[tuple[str, str]]`. Returns `(terminal_entry.path, root_path)` at line 106. Migration: typed `-> list[WalkResult]`; line 106 becomes `WalkResult(source_path=terminal_entry.path, scan_root=root_path)`.
- `src/pipeline/crawler/main.py:152-153` — `delivery_data: dict[str, tuple[list[FileEntry], str, dict]]` and `delivery_lexicons: dict[str, tuple[str, object]]`. The latter is also a bare-tuple value, but the design only specifies `delivery_data`'s migration (AC2.2). I leave `delivery_lexicons` as a tuple — it carries (lexicon_id, lexicon-instance), which is exactly two heterogeneous values consumed once at line 156-157. A two-tuple destructuring is idiomatic and the design does not require its replacement; promoting it would be scope creep. (Documented here for the executor so the omission is intentional.)
- `src/pipeline/crawler/main.py:155` — `for source_path, scan_root in candidates:` destructures the walk_roots tuple. After migration, this becomes `for candidate in candidates:` with `candidate.source_path` and `candidate.scan_root` reads inside the loop. Alternatively, dataclasses do support iter unpacking *only via* `__iter__` — but frozen dataclasses don't auto-generate `__iter__`. Idiomatic resolution: explicit attribute access.
- `src/pipeline/crawler/main.py:184` — `delivery_id = manifest["delivery_id"]`. After Phase 1, `manifest` is a `CrawlManifest` dataclass; subscript raises `TypeError`. Migration: `delivery_id = manifest.delivery_id`.
- `src/pipeline/crawler/main.py:187` — `json.dump(manifest, f, indent=2)`. After Phase 1, `manifest` is a dataclass. Migration: `json.dump(dataclasses.asdict(manifest), f, indent=2)`. Add `import dataclasses` at the top if not already present.
- `src/pipeline/crawler/main.py:190` — `delivery_data[result.source_path] = (files, fingerprint, manifest)`. Migration: `DeliveryAccumulator(files=files, fingerprint=fingerprint, manifest=manifest)`.
- `src/pipeline/crawler/main.py:228-231` — sub-delivery loop has the equivalent shape with `sub_manifest`. Same edits.
- `src/pipeline/crawler/main.py:256` — `files, fingerprint, manifest = delivery_data[delivery.source_path]` destructures the tuple. Migration: `acc = delivery_data[delivery.source_path]; files = acc.files; fingerprint = acc.fingerprint; manifest = acc.manifest`. Or use attribute access inline.
- `src/pipeline/crawler/main.py:257` — `delivery_id = manifest["delivery_id"]`. Migration: `delivery_id = manifest.delivery_id`.
- `src/pipeline/crawler/main.py:163-169` — error-manifest unpacking and JSON write. Migration: receive `ErrorManifestResult`; serialise the `.manifest` dataclass with `dataclasses.asdict(error_result.manifest)`.

- `tests/crawler/test_main.py:34` — `paths = [r[0] for r in results]`. Migration: `[r.source_path for r in results]`.
- `tests/crawler/test_main.py:58-59` — `assert (str(v1_path), str(scan_root1)) in results`. Migration: `assert WalkResult(source_path=str(v1_path), scan_root=str(scan_root1)) in results`. Frozen dataclass equality is structural, so `in results` works the same way.
- All other `walk_roots` call sites in `test_main.py` use either `len(results)` or destructure via index `r[0]` / `r[1]`; same fix.
- `tests/crawler/test_main.py:9` — imports `from pipeline.crawler.main import walk_roots, inventory_files, crawl`. Add `WalkResult` to that import where needed by the rewritten assertions.

## External dependency findings

N/A — `dataclasses` is stdlib. No external research required.

---

<!-- START_SUBCOMPONENT_A (tasks 1-2) -->
<!-- START_TASK_1 -->
### Task 1: Define `WalkResult` and `DeliveryAccumulator`; update `walk_roots` signature and return construction

**Verifies:** GH20.AC2.1, GH20.AC2.2 (definitions exist).

**Files:**
- Modify: `src/pipeline/crawler/main.py`.

**Implementation:**

Add the following dataclasses near the top of `crawler/main.py`, after the imports and before `inventory_files`:

```python
import dataclasses
from dataclasses import dataclass

# ... existing imports above ...


@dataclass(frozen=True)
class WalkResult:
    source_path: str
    scan_root: str


@dataclass(frozen=True)
class DeliveryAccumulator:
    files: list[FileEntry]
    fingerprint: str
    manifest: CrawlManifest
```

`CrawlManifest` is already imported via Phase 1's `from pipeline.crawler.manifest import build_manifest, build_error_manifest`. Add the type to that import:

```python
from pipeline.crawler.manifest import (
    build_manifest,
    build_error_manifest,
    CrawlManifest,
)
```

Update `walk_roots`'s signature from `-> list[tuple[str, str]]` to `-> list[WalkResult]`. Replace line 106's tuple construction with `results.append(WalkResult(source_path=terminal_entry.path, scan_root=root_path))`.

Update `walk_roots`'s docstring to say "Returns list of WalkResult records" instead of "Returns list of (source_path, scan_root_path) tuples."

**Verification:**

```bash
uv run python -c "
from dataclasses import is_dataclass
from pipeline.crawler.main import WalkResult, DeliveryAccumulator, walk_roots
import inspect

for cls in (WalkResult, DeliveryAccumulator):
    assert is_dataclass(cls), f'{cls.__name__} must be a dataclass'
    assert cls.__dataclass_params__.frozen, f'{cls.__name__} must be frozen'

assert {f.name for f in WalkResult.__dataclass_fields__.values()} == {'source_path', 'scan_root'}
assert {f.name for f in DeliveryAccumulator.__dataclass_fields__.values()} == {'files', 'fingerprint', 'manifest'}

ann = inspect.signature(walk_roots).return_annotation
# After the edit, the annotation is list[WalkResult] (string at runtime under PEP 563 isn't enabled here, so it should be the actual generic alias).
print('walk_roots return annotation:', ann)
print('OK')
"
```

Expected: `walk_roots return annotation: list[WalkResult]` (or the unsubscripted `list[WalkResult]` alias) and `OK`.

**Commit:** deferred to Phase 1's Task 5 (single combined commit).
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Update `crawl()` to use `WalkResult`, `DeliveryAccumulator`, `manifest.delivery_id`, `dataclasses.asdict(manifest)`, and the new `ErrorManifestResult` shape from Phase 1

**Verifies:** GH20.AC2.3, GH20.AC2.2 (use of `DeliveryAccumulator`), GH20.AC5.3.

**Files:**
- Modify: `src/pipeline/crawler/main.py` (the body of `crawl`, lines 111-288).

**Implementation:**

Inside `crawl()`, apply these edits in order:

1. **Type the `delivery_data` accumulator with the new dataclass:**

   ```python
   delivery_data: dict[str, DeliveryAccumulator] = {}
   ```

   Drop the old `dict[str, tuple[list[FileEntry], str, dict]]` annotation.

2. **Rewrite the iteration over `walk_roots` candidates.** Replace:

   ```python
   for source_path, scan_root in candidates:
   ```

   with:

   ```python
   for candidate in candidates:
       source_path = candidate.source_path
       scan_root = candidate.scan_root
   ```

   (The named locals are kept so the rest of the loop body — which references `source_path` and `scan_root` repeatedly — does not need other edits.)

3. **Rewrite the error-manifest branch.** Replace:

   ```python
   filename, error_manifest = build_error_manifest(
       result, config.crawler_version, now,
   )
   error_path = os.path.join(error_dir, f"{filename}.json")
   with open(error_path, "w") as f:
       json.dump(error_manifest, f, indent=2)
   ```

   with:

   ```python
   error_result = build_error_manifest(
       result, config.crawler_version, now,
   )
   error_path = os.path.join(error_dir, f"{error_result.filename}.json")
   with open(error_path, "w") as f:
       json.dump(dataclasses.asdict(error_result.manifest), f, indent=2)
   ```

4. **Rewrite the success-branch manifest write.** Replace:

   ```python
   delivery_id = manifest["delivery_id"]
   manifest_path = os.path.join(manifest_dir, f"{delivery_id}.json")
   with open(manifest_path, "w") as f:
       json.dump(manifest, f, indent=2)
   ```

   with:

   ```python
   delivery_id = manifest.delivery_id
   manifest_path = os.path.join(manifest_dir, f"{delivery_id}.json")
   with open(manifest_path, "w") as f:
       json.dump(dataclasses.asdict(manifest), f, indent=2)
   ```

5. **Rewrite `delivery_data` storage:**

   ```python
   delivery_data[result.source_path] = DeliveryAccumulator(
       files=files,
       fingerprint=fingerprint,
       manifest=manifest,
   )
   ```

6. **Sub-delivery branch (lines 222-235 in the pre-migration file).** Apply the same edits: write `dataclasses.asdict(sub_manifest)`, read `sub_delivery_id = sub_manifest.delivery_id`, and store `delivery_data[sub_delivery.source_path] = DeliveryAccumulator(files=sub_files, fingerprint=sub_fingerprint, manifest=sub_manifest)`.

7. **Rewrite the Pass-2 destructuring at line 256.** Replace:

   ```python
   files, fingerprint, manifest = delivery_data[delivery.source_path]
   delivery_id = manifest["delivery_id"]
   ```

   with:

   ```python
   acc = delivery_data[delivery.source_path]
   files = acc.files
   fingerprint = acc.fingerprint
   manifest = acc.manifest
   delivery_id = manifest.delivery_id
   ```

   (Or, equivalently, inline `acc.files`, `acc.fingerprint`, etc. throughout the loop body. The named locals are kept here for minimal diff.)

8. **Verify `total_bytes` aggregation in the POST payload.** Line 272 currently reads `sum(f["size_bytes"] for f in files)`. After Phase 1, `files` is `list[FileEntry]` (dataclass), so this becomes `sum(f.size_bytes for f in files)`. Confirm and edit.

The full `crawl` function after edits is the same shape as before; only the access syntax changes.

**Verification:**

After the edit, the JSON output of `dataclasses.asdict(manifest)` must match the pre-migration dict-literal output of `build_manifest`. Spot-check by running `tests/crawler/test_manifest.py` and `tests/crawler/test_main.py`:

```bash
uv run pytest tests/crawler/ -v
```

Expected: all crawler tests pass.

A targeted integrity check that the on-disk JSON shape is preserved (run only if golden manifests exist on disk):

```bash
uv run python -c "
import dataclasses, json
from pipeline.crawler.fingerprint import FileEntry
from pipeline.crawler.parser import ParsedDelivery
from pipeline.crawler.manifest import build_manifest

parsed = ParsedDelivery(
    request_id='r', project='p', request_type='t', workplan_id='w',
    dp_id='dp', version='v01', status='pending',
    source_path='/sp', scan_root='/sr',
)
files = [FileEntry(filename='a.sas7bdat', size_bytes=10, modified_at='2026-01-01T00:00:00Z')]
m = build_manifest(parsed, files, 'sha256:fp', '0.1.0', '2026-01-01T00:00:00Z', 'soc.qar')
encoded = json.dumps(dataclasses.asdict(m), indent=2, sort_keys=False)
expected_keys = ['crawled_at', 'crawler_version', 'delivery_id', 'source_path', 'scan_root',
                  'parsed', 'lexicon_id', 'status', 'fingerprint', 'files', 'file_count', 'total_bytes']
parsed_back = json.loads(encoded)
assert list(parsed_back.keys()) == expected_keys, parsed_back.keys()
assert parsed_back['files'] == [{'filename': 'a.sas7bdat', 'size_bytes': 10, 'modified_at': '2026-01-01T00:00:00Z'}]
print('OK: JSON shape preserved')
"
```

Expected: `OK: JSON shape preserved`.

**Commit:** with Phase 1 (single commit `refactor(crawler): replace TypedDict with frozen dataclasses (GH20 phases 1-2)`).
<!-- END_TASK_2 -->
<!-- END_SUBCOMPONENT_A -->

<!-- START_SUBCOMPONENT_B (task 3) -->
<!-- START_TASK_3 -->
### Task 3: Update `tests/crawler/test_main.py` for `WalkResult` shape

**Verifies:** GH20.AC2.4 (existing tests pass); GH20.AC2.1 reflected in test assertions.

**Files:**
- Modify: `tests/crawler/test_main.py`.

**Implementation:**

Two edit categories:

1. **Subscript reads on walk_roots results.** Every `r[0]` becomes `r.source_path`; every `r[1]` becomes `r.scan_root`. Run:

   ```bash
   grep -nE 'r\[0\]|r\[1\]|results\[[0-9]+\]\[' tests/crawler/test_main.py
   ```

   to enumerate the sites.

2. **Tuple-equality assertions on walk_roots results.** Every `assert (path, root) in results` becomes `assert WalkResult(source_path=path, scan_root=root) in results`. Add `WalkResult` to the import line at the top of the file:

   ```python
   from pipeline.crawler.main import walk_roots, inventory_files, crawl, WalkResult
   ```

   Sites currently include lines 58-59 of `test_main.py` (per codebase verification). Run:

   ```bash
   grep -nE 'in results\b' tests/crawler/test_main.py
   ```

   to find every site.

3. **Mock/stub of walk_roots.** If any test patches `walk_roots` to return a list of tuples (e.g., to short-circuit filesystem traversal), update the patched return value to a list of `WalkResult` instances. The DI-refactor work (GH21) replaces most `@patch` usage with parameter injection in this test file; if GH21 has already merged, those patched returns are now `post_fn` injections instead and the walk_roots test seam is direct (test fixture builds the directory tree and calls `crawl`).

   Run:

   ```bash
   grep -nE 'walk_roots' tests/crawler/test_main.py
   ```

   to confirm whether `walk_roots` is patched anywhere in the tests, and update accordingly.

4. **No other dataclass interactions in `test_main.py`.** The `delivery_data` accumulator is private to `crawl()`; no test reads its shape. The CrawlManifest is read indirectly by tests that load the on-disk JSON — those reads use `json.load(f)` and access dicts, which is unaffected.

**Verification:**

```bash
uv run pytest tests/crawler/test_main.py -v
```

Expected: all tests pass with the same count as before.

**Commit:** with Phase 1 (single commit, see Phase 1 Task 5).
<!-- END_TASK_3 -->
<!-- END_SUBCOMPONENT_B -->

---

## Phase 2 Done When

- `walk_roots` returns `list[WalkResult]` (verified via `inspect.signature`).
- `crawl()` builds `DeliveryAccumulator` instances and reads `manifest.delivery_id` via attribute access.
- `crawl()` writes manifests using `json.dump(dataclasses.asdict(manifest), f, indent=2)` for both delivery and error manifests.
- `tests/crawler/test_main.py` passes with the same number of tests as before; assertions use `WalkResult` shape instead of tuples.
- The on-disk JSON manifest shape is byte-equivalent to the pre-migration shape (key order preserved, file inventory remains a list of dicts).

## Notes for executor

- **Commit cadence:** Phase 2 commits with Phase 1 in a single commit (see Phase 1 Task 5).
- **`delivery_lexicons` stays a tuple.** The design's AC2 only names `delivery_data`. `delivery_lexicons` is a `dict[str, tuple[str, object]]` consumed once via two-tuple destructuring at lines 156, 244, 258. Promoting it to a dataclass would be scope creep with no observable benefit — flagged here so the decision is intentional and documented.
- **`walk_roots` signature interaction with GH19 (type annotations):** GH19 may already have replaced the loose `scan_roots: list` parameter annotation with a typed alias. The Phase 2 edits leave `scan_roots` and `valid_terminals` annotations unchanged; only the return annotation flips to `list[WalkResult]`.
- **Import ordering note:** `dataclasses` is stdlib. The existing `pipeline.crawler.main` import block follows the project pattern: stdlib first, then `pipeline.*`. Insert `import dataclasses` and `from dataclasses import dataclass` in the stdlib block.
- **Subscript audit:** before claiming the phase done, run `grep -nE 'manifest\["|\["delivery_id"\]' src/pipeline/crawler/main.py` and confirm zero matches in the success and sub-delivery branches.
