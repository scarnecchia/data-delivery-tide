# Issue #25: Mark Integration Tests with @pytest.mark.integration

## Summary

Three test files contain tests that exercise real pyreadstat and pyarrow on disk —
`tests/converter/test_engine.py`, `tests/converter/test_convert.py`, and
`tests/test_end_to_end_converter.py`. These tests are currently unmarked, meaning
`pytest -m "not integration"` cannot exclude them and will warn about unknown markers
once #18 lands.

This change adds `@pytest.mark.integration` to the affected test classes. No logic
changes. No new fixtures. Requires #18 to declare the marker in `pyproject.toml` first.

## Definition of Done

- All tests listed below carry `@pytest.mark.integration`
- `pytest -m "not integration"` runs cleanly with no warnings and skips these tests
- `pytest -m integration` runs only the marked tests and they all pass
- No previously passing tests are broken

## Tests to Mark

### `tests/converter/test_engine.py`

| Class | Notes |
|---|---|
| `TestConvertOneIntegration` | Uses `sas_fixture_factory` + `sav_chunk_iter_factory` backed by real pyreadstat/pyarrow; writes and reads real Parquet files |

### `tests/converter/test_convert.py`

| Class | Notes |
|---|---|
| `TestConvertSasToParquetHappyPath` | All methods use `sas_fixture_factory` + `sav_chunk_iter_factory`; reads Parquet metadata via pyarrow |
| `TestConvertAtomicWrite` | Two of three methods use `sas_fixture_factory`; `test_source_missing_leaves_no_tmp_file` calls real pyreadstat directly via a missing-file path |
| `TestConvertSchemaStability` | Uses `sas_fixture_factory` + `sav_chunk_iter_factory`; verifies multi-chunk schema consistency |

### `tests/test_end_to_end_converter.py`

| Class | Notes |
|---|---|
| `TestEndToEndConverter` | Drives full crawler → registry → converter chain; calls real pyreadstat via `pyreadstat.write_sav` in the fixture and `read_file_in_chunks` in the test body |

## Dependency

**Blocked by #18.** That issue adds `markers = ["integration: tests that hit the filesystem or network"]` to `[tool.pytest.ini_options]` in `pyproject.toml`. Without it, `@pytest.mark.integration` produces an `PytestUnknownMarkWarning` and `-m` filtering is unreliable.

## Borderline Cases

**`TestConvertAtomicWrite.test_exception_during_write_cleans_up_tmp`** — uses
`sas_fixture_factory` to get a real `.sav` file on disk, but the `chunk_iter_factory`
is a fake that yields one chunk then raises. The test still touches the real filesystem
and real pyreadstat (via the fixture write), so it stays in the class and inherits the
marker.

**`TestConvertAtomicWrite.test_source_missing_leaves_no_tmp_file`** — no
`sas_fixture_factory`, but imports `pyreadstat.PyreadstatError` and calls
`convert_sas_to_parquet` against a nonexistent path, exercising real pyreadstat error
handling. Integration marker is correct.

**`TestConvertSchemaDrift`** — not listed in the issue. Its tests use hand-rolled
`chunk_iter_factory` stubs, no `sas_fixture_factory` or `sav_chunk_iter_factory`. It
does not exercise real I/O. Do **not** mark it.

## Effort Estimate

Small. Mechanical: add one decorator per class (five classes across three files). The
only judgement call is the borderline analysis above, which is resolved here.
