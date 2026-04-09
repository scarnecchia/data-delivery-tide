# SAS-to-Parquet Data Pipeline Spec

## Problem

Healthcare data arrives from data partners as SAS7BDAT files on a network share. The directory structure encodes all metadata (project, workplan, version, QA status) but nothing indexes or watches it. Downstream consumers (Python scripts, Power BI) need to know when new data arrives and whether it's passed QA — both currently require manual inspection.

## Environment

- RHEL (no systemd access, no Docker)
- Python 3.12.5
- Network share filesystem (no cloud, no Databricks)
- No event/webhook system available — must poll
- Cron available for scheduling
- Dependencies: `pyreadstat`, `pyarrow`, `fastapi`, `uvicorn` (all pip-installable wheels)
- Registry backing store: SQLite via stdlib `sqlite3`

## Source Directory Structure

```
requests/<root>/<dpid>/packages/<request_id>/<request_id>_<dpid>_<verid>/msoc
```

Where `<root>` is one of several top-level directories managed via config:
- `qa` — quality assurance package results
- `qm` — MIL quality assurance package results
- `qad` — QA with internal data partner data
- `qmd` — MIL QA with internal data partner data
- (others may be added via config)

### Request ID

The full composite string `soc_qar_wp001` is the **request_id**. It is stored whole as an opaque identifier. Its segments are:
- `soc` = project ID
- `qar` = workplan type (`wp_type`) — **this is where request_type is derived**
- `wp001` = workplan ID (sequential ETL identifier)

The remaining path segments:
- `mkscnr` = data partner ID (`dp_id`)
- `v01` = version (increments on resubmission after QA failure)

So for path: `requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc`
- `root`: `qa` (from config, organizational only)
- `request_id`: `soc_qar_wp001`
- `project`: `soc`
- `wp_type` / `request_type`: `qar`
- `workplan_id`: `wp001`
- `dp_id`: `mkscnr`
- `version`: `v01`

### QA Status Convention

QA status is encoded by folder name at the terminal level:
- `msoc_new` exists → delivery received, QA **in progress**
- `msoc_new` renamed to `msoc` → QA **passed**
- Multiple versions for a single workplan (e.g., v01, v02) indicate resubmissions. Only the version with `msoc` (not `msoc_new`) has passed QA.

### Contents

Each `msoc`/`msoc_new` directory contains dozens to 100+ `.sas7bdat` files.

---

## Configuration

`pipeline/config.json` defines scan roots and any other environment-specific settings. This is the only place where directory roots are enumerated — nothing is hardcoded.

```json
{
  "scan_roots": [
    {
      "path": "/requests/qa",
      "label": "QA Package Results"
    },
    {
      "path": "/requests/qm",
      "label": "MIL QA Package Results"
    },
    {
      "path": "/requests/qad",
      "label": "QA Internal DP Data"
    },
    {
      "path": "/requests/qmd",
      "label": "MIL QA Internal DP Data"
    }
  ],
  "registry_api_url": "http://localhost:8000",
  "output_root": "/output",
  "schema_path": "/pipeline/schema.json",
  "overrides_path": "/pipeline/overrides.json",
  "log_dir": "/pipeline/logs"
}
```

---

## Architecture

Four loosely coupled services. Each runs independently. Services communicate through the registry API and per-stage manifest files — never through direct database access or shared state.

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Crawler    │────▶│  Registry API   │◀────│  Converter   │
│  (scheduled) │     │  (long-running) │     │  (scheduled) │
└─────────────┘     └────────┬────────┘     └─────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   Consumers     │
                    │ (Power BI, etc) │
                    └─────────────────┘
```

### Service 1: Registry API

Long-running HTTP service. Single source of truth for pipeline state.

**Implementation**: FastAPI + uvicorn, backed by SQLite. Kept alive via cron watchdog (see Deployment section).

**Why an API and not direct SQLite access**: Loose coupling. No consumer knows or cares about the backing store. Swap SQLite for postgres later without touching any other service. Concurrent access is handled by the API, not by hoping SQLite's file locking behaves across network shares.

**Endpoints**:

```
GET    /deliveries                  — list all, with query filters
GET    /deliveries/{delivery_id}    — single delivery detail
GET    /deliveries/actionable       — qa_status=passed, not yet converted
POST   /deliveries                  — upsert (crawler calls this)
PATCH  /deliveries/{delivery_id}    — update status fields (converter calls this)
GET    /health                      — liveness check
```

Query filters on `GET /deliveries`:
- `dp_id`, `project`, `request_type`, `workplan_id`, `request_id` — exact match
- `qa_status` — filter by pending/passed
- `converted` — boolean, has parquet_converted_at been set
- `version` — exact match or `latest` (returns highest version per workplan per dp)
- `scan_root` — filter by source root directory

**Data model**:

```sql
CREATE TABLE deliveries (
    delivery_id          TEXT PRIMARY KEY,  -- deterministic hash of source_path
    request_id           TEXT NOT NULL,     -- composite: soc_qar_wp001
    project              TEXT NOT NULL,     -- parsed from request_id
    request_type         TEXT NOT NULL,     -- parsed from wp_type in request_id
    workplan_id          TEXT NOT NULL,     -- parsed from request_id
    dp_id                TEXT NOT NULL,
    version              TEXT NOT NULL,
    scan_root            TEXT NOT NULL,     -- which configured root this came from
    qa_status            TEXT NOT NULL CHECK (qa_status IN ('pending', 'passed')),
    first_seen_at        TEXT NOT NULL,     -- ISO 8601
    qa_passed_at         TEXT,              -- ISO 8601, NULL until passed
    parquet_converted_at TEXT,              -- ISO 8601, NULL until converted
    file_count           INTEGER,
    total_bytes          INTEGER,
    source_path          TEXT NOT NULL UNIQUE,
    output_path          TEXT               -- set by converter after writing parquet
);

CREATE INDEX idx_actionable ON deliveries (qa_status, parquet_converted_at);
CREATE INDEX idx_dp_wp ON deliveries (dp_id, workplan_id);
CREATE INDEX idx_request_id ON deliveries (request_id);
```

### Service 2: Crawler

Scheduled poller (cron or Task Scheduler). Iterates over configured `scan_roots`, walks each directory tree, parses path metadata, detects QA status, and reports findings to the registry API.

**Responsibilities**:
- Iterate `scan_roots` from config
- Parse path segments into structured metadata (request_id stored whole, components extracted)
- Detect QA status from folder naming (`msoc` vs `msoc_new`)
- Count files and total bytes in each delivery directory
- POST to registry API to upsert deliveries
- Write a crawl manifest per delivery

**Must be idempotent** — safe to re-run at any interval without side effects.

**State transitions reported to registry**:
- New path with `msoc_new` → POST with `qa_status: "pending"`
- `msoc_new` renamed to `msoc` → POST with `qa_status: "passed"`
- New version appears → new POST (previous version unchanged)

**Crawl manifest** (written per delivery):

```json
{
  "crawled_at": "2026-04-09T14:30:00Z",
  "source_path": "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc",
  "scan_root": "/requests/qa",
  "parsed": {
    "request_id": "soc_qar_wp001",
    "project": "soc",
    "request_type": "qar",
    "workplan_id": "wp001",
    "dp_id": "mkscnr",
    "version": "v01"
  },
  "qa_status": "passed",
  "files": [
    {
      "filename": "enrollment.sas7bdat",
      "size_bytes": 1048576,
      "modified_at": "2026-04-08T09:15:00Z"
    }
  ],
  "file_count": 47,
  "total_bytes": 2147483648
}
```

### Service 3: Converter

Scheduled process. Queries registry API for actionable deliveries, converts SAS to parquet, reports completion back to registry.

**Trigger**: Queries `GET /deliveries/actionable` for rows where `qa_status = 'passed' AND parquet_converted_at IS NULL`.

**For each actionable delivery**:
1. Read all `.sas7bdat` files from `msoc/` using `pyreadstat`
2. Load `schema.json` for type mapping reference
3. Apply type overrides from `overrides.json` if present
4. Write `.parquet` files to output directory using `pyarrow`
5. Write a convert manifest to the output directory
6. PATCH registry with `parquet_converted_at` and `output_path`

**Must be idempotent and resumable** — if it crashes mid-conversion, unconverted deliveries remain actionable on next run.

**Type mapping** (from schema.json, generated by SAS):
- `type = 2` (char) → `STRING`
- `type = 1` with date format (DATE, MMDDYY, YYMMDD, etc.) → `DATE32`
- `type = 1` with datetime format (DATETIME, E8601DT, etc.) → `TIMESTAMP`
- `type = 1` with time format (TIME, HHMM, etc.) → `TIME32`
- `type = 1`, `formatd = 0`, `length <= 4` → `INT32`
- `type = 1`, `formatd = 0`, `length <= 8` → `INT64`
- Otherwise → `DOUBLE`

The converter treats `inferred_parquet_type` as a default. `overrides.json` takes precedence, keyed by `memname.name`:

```json
{
  "ENROLLMENT.CUSTOM_FLAG": "STRING",
  "DEMOGRAPHIC.AGE_BAND": "STRING"
}
```

**Convert manifest** (written to output directory alongside parquet files):

```
output/<dp_id>/<workplan_id>/<version>/convert_manifest.json
```

```json
{
  "converted_at": "2026-04-09T15:00:00Z",
  "delivery_id": "abc123...",
  "request_id": "soc_qar_wp001",
  "source_path": "/requests/qa/mkscnr/packages/soc_qar_wp001/soc_qar_wp001_mkscnr_v01/msoc",
  "schema_version": "schema.json sha256:abcdef...",
  "overrides_applied": {
    "ENROLLMENT.CUSTOM_FLAG": "STRING"
  },
  "tables": [
    {
      "source_file": "enrollment.sas7bdat",
      "output_file": "enrollment.parquet",
      "row_count": 1250000,
      "column_count": 45,
      "columns": [
        {
          "name": "ENR_START_DATE",
          "sas_type": "numeric",
          "sas_format": "DATE9.",
          "parquet_type": "DATE32",
          "null_count": 0
        }
      ],
      "warnings": []
    }
  ]
}
```

### Service 4: Consumers (Power BI, future services)

Any downstream consumer reads:
- **Parquet files** from the output directory for data
- **Registry API** for pipeline state (what's delivered, passed, converted, stale)
- **Convert manifests** for per-delivery audit detail (row counts, column mappings, warnings)

Consumers never touch the source directory or SQLite file directly.

---

## Schema Generation (SAS-side, run separately)

This step runs in SAS, not Python. It produces `schema.json` which the converter consumes.

```sas
proc contents data=MYLIB._ALL_ noprint
    out=work._meta(keep=memname name type length format formatl formatd varnum label);
run;

proc sort data=work._meta;
    by memname varnum;
run;

data work._schema;
    set work._meta;
    length sas_type $7 inferred_parquet_type $20;

    sas_type = ifc(type = 1, 'numeric', 'char');
    _fmt = upcase(compress(format, ' .0123456789'));

    if type = 2 then
        inferred_parquet_type = 'STRING';
    else if _fmt in ('DATE' 'MMDDYY' 'YYMMDD' 'DDMMYY' 'MONYY'
                      'JULDAY' 'JULIAN' 'WORDDATE' 'WEEKDATE'
                      'EURDFDD' 'EURDFDE' 'EURDFDN' 'EURDFDT')
        then inferred_parquet_type = 'DATE32';
    else if _fmt in ('DATETIME' 'DATEAMPM' 'DTDATE' 'DTMONYY'
                      'DTWKDATX' 'DTYEAR' 'EURDFDT' 'NLDATM'
                      'E8601DT' 'B8601DT')
        then inferred_parquet_type = 'TIMESTAMP';
    else if _fmt in ('TIME' 'HHMM' 'MMSS' 'TOD' 'HOUR'
                      'E8601TM' 'B8601TM')
        then inferred_parquet_type = 'TIME32';
    else if formatd = 0 and length <= 4 then
        inferred_parquet_type = 'INT32';
    else if formatd = 0 and length <= 8 then
        inferred_parquet_type = 'INT64';
    else
        inferred_parquet_type = 'DOUBLE';

    drop type _fmt;
run;

proc json out="/path/to/pipeline/schema.json" pretty;
    export work._schema / nosastags;
run;
```

---

## Filesystem Layout

```
requests/                           ← existing source data (read-only to pipeline)
├── qa/                             ← scan root (from config)
│   └── <dpid>/
│       └── packages/
│           └── <request_id>/
│               └── <request_id>_<dpid>_<verid>/
│                   ├── msoc/               ← QA passed
│                   │   └── *.sas7bdat
│                   └── msoc_new/           ← QA in progress
│                       └── *.sas7bdat
├── qm/                             ← scan root (from config)
├── qad/                            ← scan root (from config)
└── qmd/                            ← scan root (from config)

pipeline/                           ← pipeline infrastructure
├── config.json                     ← scan roots, paths, API URL
├── registry.db                     ← SQLite backing store (only registry API touches this)
├── schema.json                     ← generated by SAS, consumed by converter
├── overrides.json                  ← manual type mapping overrides
├── crawl_manifests/                ← crawl manifests (if source dirs are read-only)
│   └── <delivery_id>.json
├── scripts/
│   └── ensure_registry.sh          ← cron watchdog for API process
├── logs/
├── registry_api/                   ← FastAPI service
│   ├── main.py
│   ├── models.py
│   └── db.py
├── crawler/
│   ├── main.py
│   └── parser.py                   ← path parsing logic, isolated for testing
└── converter/
    ├── main.py
    └── type_mapping.py             ← schema + override resolution, isolated for testing

output/                             ← parquet output (consumers read from here)
└── <dp_id>/
    └── <workplan_id>/
        └── <version>/
            ├── <table>.parquet
            └── convert_manifest.json
```

---

## Parsing Constraints

- `dp_id`: always 3-8 alphanumeric characters (`[a-zA-Z0-9]{3,8}`). Some specific values may need exclusion — handle via hardcoded exclusion list in parser config.
- `version`: always `v` followed by digits (`v\d+`).
- `request_id` extraction: given a directory name like `soc_qar_wp001_mkscnr_v01`, match `_[a-zA-Z0-9]{3,8}_v\d+$` from the right. Everything before that match is the `request_id`.

---

## Deployment

RHEL with no systemd access. All process management is cron-based.

### Registry API (persistent process via cron watchdog)

A cron job runs every minute and starts the API if it's not already running. Max one minute downtime on crash.

**Crontab entry**:
```
* * * * * /path/to/pipeline/scripts/ensure_registry.sh >> /path/to/pipeline/logs/watchdog.log 2>&1
```

**Watchdog script** (`pipeline/scripts/ensure_registry.sh`):
```bash
#!/bin/bash
PIDFILE="/path/to/pipeline/registry_api.pid"
LOGFILE="/path/to/pipeline/logs/registry_api.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi

cd /path/to/pipeline
nohup python -m uvicorn registry_api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    >> "$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
```

### Crawler (scheduled via cron)

Runs at a configured interval. Frequency depends on how fast new data needs to be detected — hourly is a reasonable default.

```
0 * * * * cd /path/to/pipeline && python -m crawler.main >> /path/to/pipeline/logs/crawler.log 2>&1
```

### Converter (scheduled via cron)

Runs after crawler, or on its own schedule. Only processes deliveries the registry reports as actionable, so running it when there's nothing to convert is a no-op.

```
30 * * * * cd /path/to/pipeline && python -m converter.main >> /path/to/pipeline/logs/converter.log 2>&1
```

### Retry behaviour

The crawler and converter must handle the registry API being temporarily unavailable (e.g., during the ≤1 minute restart window). Both should retry HTTP calls with exponential backoff — 3 attempts, 2s/4s/8s delays. If the API is unreachable after retries, log the failure and exit cleanly. The next cron invocation will pick up where it left off since both services are idempotent.

### Filesystem layout (updated with scripts)

```
pipeline/
├── scripts/
│   └── ensure_registry.sh          ← cron watchdog for API process
├── ...
```

---

## Open Questions

- **File integrity**: No validation that SAS7BDAT files in `msoc` are complete or uncorrupted before conversion. Consider row-count sanity check or file-size comparison against crawl manifest.
- **Retraction**: Can a version be retracted after QA pass? If so, registry needs a `retracted` status and the converter should skip or remove output.
- **Schema drift**: If a data partner changes column names or types between versions, the converter needs to detect and flag it. Compare against schema.json and emit a warning in the convert manifest.
- **Lineage**: No column-level lineage tracking from source SAS to output parquet yet. Convert manifest captures the mapping per delivery but there's no cross-delivery lineage graph.
- **Logging**: Each service should log to `pipeline/logs/` with rotation. Structured logging (JSON lines) recommended.
- **Crawl manifest location**: If source directories are read-only, crawl manifests go to `pipeline/crawl_manifests/<delivery_id>.json`. If writable, they can live alongside the data at `<source_path>/crawl_manifest.json`.
- **Registry API auth**: Currently unauthenticated. Fine for internal network share use. If the API becomes accessible beyond the immediate team, add token auth.
- **dp_id exclusions**: Some dp_id values may need to be excluded from parsing. Maintain an exclusion list in config.
