# Loading Dock — Setup Guide

This guide walks through installing, configuring, and running Loading Dock from scratch on a RHEL (or similar Linux) machine. It assumes you have never used Python before but are comfortable with the command line.

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Authentication — Creating Users and Tokens](#4-authentication--creating-users-and-tokens)
5. [Starting the Registry API](#5-starting-the-registry-api)
6. [Running the Converter](#6-running-the-converter)
7. [Running as Background Services](#7-running-as-background-services)
8. [Verifying Everything Works](#8-verifying-everything-works)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

### Python 3.11+

Check your Python version:

```bash
python3 --version
```

You need Python 3.11 or higher. If your system has an older version, install a newer one:

```bash
# RHEL 8/9
sudo dnf install python3.11

# If python3.11 installs alongside the system python, use python3.11 explicitly
# in all commands below instead of python3
```

### Build Tools

Some dependencies (notably `pyreadstat`) compile native extensions. You need a C compiler and Python development headers:

```bash
# RHEL
sudo dnf install gcc gcc-c++ python3.11-devel
```

### Git

```bash
sudo dnf install git
```

---

## 2. Installation

### Clone the Repository

```bash
git clone <your-repo-url> loading-dock
cd loading-dock
```

### Create a Virtual Environment

A virtual environment keeps this project's dependencies separate from the system Python, so installing or upgrading packages here won't break other tools on the machine.

```bash
python3.11 -m venv .venv
```

This creates a `.venv/` directory inside the project.

### Activate the Virtual Environment

```bash
source .venv/bin/activate
```

Your shell prompt changes to show `(.venv)` at the beginning, confirming you're inside the environment. You'll need to run this each time you open a new terminal — or use the watchdog scripts (section 7), which activate it automatically.

All commands below assume the virtual environment is active.

### Install the Package

Install the package in editable mode (so you can pull updates with `git pull` without reinstalling). For a full production deployment that runs the registry API, the converter, and the event consumer:

```bash
pip install -e ".[registry,converter,consumer]"
```

This installs:

| Extra       | What It Provides                                              |
|-------------|---------------------------------------------------------------|
| `registry`  | FastAPI + Uvicorn (the registry API server)                   |
| `converter` | pyreadstat + pyarrow + pandas (SAS-to-Parquet conversion)     |
| `consumer`  | websockets + httpx (event stream client, used by the daemon)  |

If you only need specific components, install just the extras you need. For example, a machine that only runs the API server:

```bash
pip install -e ".[registry]"
```

### Verify Installation

After installation, the following commands should all be available:

```bash
registry-api --help       # (may just start the server — see section 5)
registry-auth --help
registry-convert --help
```

---

## 3. Configuration

### The Configuration File

The pipeline reads its configuration from `pipeline/config.json` by default. You can override this by setting the `PIPELINE_CONFIG` environment variable:

```bash
export PIPELINE_CONFIG=/path/to/your/config.json
```

### Editing the Configuration

#### Fields you'll likely need to change

| Field               | What It Is                                                                                       |
|---------------------|--------------------------------------------------------------------------------------------------|
| `scan_roots`        | Array of directories to crawl. Each entry has `path` (absolute directory on disk), `label` (human-readable name), `lexicon` (which lexicon governs status rules), and `target` (subdirectory name to descend into). See [Scan Roots](#scan-roots) below. |
| `db_path`           | Where the SQLite database is stored. Relative paths are resolved from the project root. |
| `log_dir`           | Where structured JSON logs are written. |
| `output_root`       | Base directory for pipeline output. |
| `registry_api_url`  | The URL where the registry API is reachable. If running everything on one machine, leave as `http://localhost:8000`. |

#### Fields you can leave alone

| Field                          | Default        | What It Does                                                         |
|--------------------------------|----------------|----------------------------------------------------------------------|
| `lexicons_dir`                 | `"lexicons"`   | Path to lexicon JSON files, relative to the config file location.    |
| `dp_id_exclusions`             | `["nsdp"]`     | Directory names to skip during crawling.                             |
| `crawl_manifest_dir`           | (as shown)     | Where the crawler writes JSON manifest files.                        |
| `crawler_version`              | `"1.0.0"`      | Version string embedded in crawler manifests.                        |
| `converter_version`            | `"0.1.0"`      | Version string embedded in Parquet file metadata.                    |
| `converter_chunk_size`         | `100000`       | Number of rows per SAS read chunk / Parquet row group.               |
| `converter_compression`        | `"zstd"`       | Parquet compression codec. Options: `zstd`, `snappy`, `gzip`, `lz4`. |
| `converter_state_path`         | (as shown)     | File where the converter daemon persists its last-processed event sequence number. |
| `converter_cli_batch_size`     | `200`          | How many deliveries the CLI fetches per API page.                    |

### Scan Roots

Each entry in `scan_roots` tells the crawler where to look for deliveries and how to interpret them:

```json
{
  "path": "/requests/qa",
  "label": "QA Package Results",
  "lexicon": "soc.qar",
  "target": "packages"
}
```

- **`path`** — Absolute path to the root directory on the network share.
- **`label`** — A human-readable name, used in logs and API responses.
- **`lexicon`** — The lexicon ID that governs valid statuses, transitions, and derivation rules for deliveries found here. Must match a lexicon file in the `lexicons_dir` directory (e.g., `soc.qar` corresponds to `lexicons/soc/qar.json`).
- **`target`** — The subdirectory name to descend into under each data provider ID.

### Lexicons

Lexicons live in `pipeline/lexicons/` and define the status lifecycle for different delivery types. They ship pre-configured — you don't need to modify them unless you're adding a new delivery type.

The directory structure maps to lexicon IDs:

```
pipeline/lexicons/
├── soc/
│   ├── _base.json      →  soc._base
│   ├── qar.json         →  soc.qar
│   ├── qmr.json         →  soc.qmr
│   └── scdm.json        →  soc.scdm
```

### Directory Permissions

Make sure the user running the pipeline has:

- **Read access** to all `scan_roots[].path` directories and their contents
- **Write access** to `db_path` (and its parent directory — SQLite creates WAL sidecar files)
- **Write access** to `log_dir`
- **Write access** to `crawl_manifest_dir`
- **Write access** to `converter_state_path` parent directory
- **Write access** to the Parquet output locations (which are subdirectories of the source paths, at `{source_path}/parquet/`)

---

## 4. Authentication — Creating Users and Tokens

The registry API uses bearer token authentication. Every API request (except the health check) requires a valid token. Tokens are hashed and stored in the SQLite database — the raw token is only shown once when created, so save it immediately.

Each user has exactly one active token. The CLI commands use "user" and "token" interchangeably — `revoke-user` disables the token, `rotate-token` replaces it.

### Roles

There are three roles, in a hierarchy — higher roles inherit all permissions of lower roles:

| Role    | Permissions                                                      |
|---------|------------------------------------------------------------------|
| `read`  | GET deliveries, GET events, connect to WebSocket event stream    |
| `write` | Everything `read` can do, plus POST/PATCH deliveries, POST events |
| `admin` | Everything `write` can do (reserved for future admin endpoints)   |

### Creating Your First User

Make sure your virtual environment is activated, then:

```bash
registry-auth add-user crawler --role write
```

This prints a raw token to stdout, something like:

```
a1b2c3d4e5f6...
```

**Save this token immediately.** It's never shown again. If you lose it, you'll need to rotate it (see below).

### Typical User Setup

You need at least two tokens:

```bash
# Token for the crawler (needs write access to POST deliveries)
registry-auth add-user crawler --role write

# Token for the converter daemon (needs write access to PATCH deliveries and POST events)
registry-auth add-user converter --role write

# Token for a human or dashboard that only needs to read data
registry-auth add-user dashboard --role read
```

### Setting the Crawler Token

The crawler reads its token from the `REGISTRY_TOKEN` environment variable:

```bash
export REGISTRY_TOKEN="<the-token-from-add-user>"
```

For persistent configuration, add this to a file that gets sourced before running the crawler (e.g., `/etc/profile.d/pipeline.sh` or a `.env` file that your process manager sources).

### Listing Users

```bash
registry-auth list-users
```

Shows all users, their roles, creation dates, and whether they are active or revoked.

### Rotating a Token

If a token is compromised or lost:

```bash
registry-auth rotate-token crawler
```

This revokes the old token and prints a new one. Update `REGISTRY_TOKEN` (or wherever the old token was stored) with the new value.

### Revoking a Token

To permanently disable a user's access without creating a new token:

```bash
registry-auth revoke-user crawler
```

This is idempotent — revoking an already-revoked user does nothing.

---

## 5. Starting the Registry API

The registry API is a web server that manages the delivery database. It must be running before the crawler or converter can operate.

### Foreground (Interactive)

For testing or initial setup, run it in the foreground:

```bash
registry-api
```

The server starts on `http://127.0.0.1:8000` by default (configurable via `api_host` and `api_port` in `config.json`). You'll see Uvicorn's startup log. Press Ctrl+C to stop.

### Verify It's Running

In another terminal:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok"}
```

### Background (Production)

See section 7 for running as a background service with the provided watchdog scripts.

---

## 6. Running the Converter

The converter reads SAS7BDAT files from deliveries registered in the API and writes Parquet files alongside them. It has two modes of operation.

### One-Shot Mode (Backfill)

Use `registry-convert` to process all unconverted deliveries in a single batch and exit:

```bash
registry-convert
```

This drains the backlog: it queries the API for all deliveries that haven't been converted yet, converts them one by one, and exits when none remain.

#### Limiting How Many to Process

```bash
registry-convert --limit 50
```

Processes at most 50 deliveries, then exits. Useful if you want to test or throttle throughput.

#### Sharding Across Multiple Machines

If you have a large backlog and want to spread the work across multiple machines (or multiple processes on one machine):

```bash
# On machine/process 0 of 4:
registry-convert --shard 0/4

# On machine/process 1 of 4:
registry-convert --shard 1/4

# On machine/process 2 of 4:
registry-convert --shard 2/4

# On machine/process 3 of 4:
registry-convert --shard 3/4
```

Each shard deterministically claims a subset of deliveries based on their delivery ID. Shards don't overlap.

#### Re-Attempting Failed Conversions

If some conversions previously failed (e.g., due to a corrupt SAS file or a temporary I/O error), they are skipped by default. To retry them:

```bash
registry-convert --include-failed
```

This clears the error metadata on each failed delivery before re-attempting conversion.

#### Combining Flags

All flags can be combined:

```bash
registry-convert --shard 0/4 --limit 100 --include-failed
```

#### Exit Codes

| Code | Meaning                              |
|------|--------------------------------------|
| 0    | Success — backlog drained            |
| 1    | Error — registry unreachable or conversion failure |
| 2    | Bad arguments (e.g., invalid `--shard` format) |
| 130  | Interrupted by Ctrl+C                |

### Daemon Mode (Event-Driven)

Use `registry-convert-daemon` for continuous operation. It subscribes to the registry's event stream and converts deliveries as they're registered:

```bash
registry-convert-daemon
```

The daemon:

1. On startup, catches up on any events it missed since the last run (using a persisted sequence number in `converter_state_path`).
2. Opens a WebSocket connection to `ws://localhost:8000/ws/events` for real-time events.
3. When it sees a `delivery.created` event, it converts the delivery's SAS files to Parquet.
4. Runs indefinitely until stopped with SIGTERM or SIGINT (Ctrl+C).

The daemon gracefully shuts down: it finishes any in-progress conversion, saves its state, then exits.

### How the Converter Authenticates

The converter daemon (and the CLI) need a token with `write` role to PATCH deliveries and POST events. Set the `REGISTRY_TOKEN` environment variable:

```bash
export REGISTRY_TOKEN="<your-converter-token>"
```

### Where Parquet Files Are Written

For each delivery, the converter creates a `parquet/` subdirectory inside the delivery's source path and writes one `.parquet` file per SAS file:

```
/requests/qa/qapkg/packages/req_001/qapkg_mycompany_v1/msoc/
├── data_file_1.sas7bdat
├── data_file_2.sas7bdat
└── parquet/
    ├── data_file_1.parquet
    └── data_file_2.parquet
```

---

## 7. Running as Background Services

For production, you want the registry API and converter daemon running in the background and restarting automatically if they crash. The project ships two watchdog scripts for this.

### Watchdog Scripts

Both scripts follow the same pattern:

1. Check if the process is already running (via a PID file).
2. If it is, exit silently.
3. If not, start the process in the background, record its PID, and exit.

#### Registry API Watchdog

```bash
pipeline/scripts/ensure_registry.sh
```

- PID file: `pipeline/registry_api.pid`
- Log file: `pipeline/logs/registry_api.log`

#### Converter Daemon Watchdog

```bash
pipeline/scripts/ensure_converter.sh
```

- PID file: `pipeline/registry_converter.pid`
- Log file: `pipeline/logs/registry_converter.log`
- Automatically activates `.venv` if present

### Setting Up Cron

The simplest way to keep both services running is to call the watchdog scripts every minute via cron:

```bash
crontab -e
```

Add these lines (adjust paths to match your installation):

```cron
# Ensure registry API is running
* * * * * cd /path/to/loading-dock && ./pipeline/scripts/ensure_registry.sh

# Ensure converter daemon is running
* * * * * cd /path/to/loading-dock && ./pipeline/scripts/ensure_converter.sh
```

Both `PIPELINE_CONFIG` and `REGISTRY_TOKEN` must be available to the cron environment. Rather than putting tokens inline (they'd be visible in `crontab -l` output), source them from a secured file. Add to the top of your crontab:

```cron
BASH_ENV=/etc/pipeline/.env
```

Or wrap each entry in a shell that sources the env file first. Make sure the `.env` file has restricted permissions (`chmod 600`).

If the process is already running, the script exits immediately (cost: ~0). If it crashed, cron restarts it within a minute.

### Checking Status

To see if the services are running:

```bash
# Check registry API
test -f pipeline/registry_api.pid && kill -0 "$(cat pipeline/registry_api.pid)" 2>/dev/null && echo "running" || echo "stopped"

# Check converter daemon
test -f pipeline/registry_converter.pid && kill -0 "$(cat pipeline/registry_converter.pid)" 2>/dev/null && echo "running" || echo "stopped"
```

### Stopping Services

```bash
# Stop registry API
kill "$(cat pipeline/registry_api.pid)"

# Stop converter daemon (graceful shutdown)
kill "$(cat pipeline/registry_converter.pid)"
```

The converter daemon handles SIGTERM gracefully — it finishes any in-progress conversion before exiting.

### Viewing Logs

```bash
# Follow registry API logs
tail -f pipeline/logs/registry_api.log

# Follow converter daemon logs
tail -f pipeline/logs/registry_converter.log
```

Logs are in JSON format (one JSON object per line), which makes them easy to parse with tools like `jq`:

```bash
tail -f pipeline/logs/registry_converter.log | jq .
```

---

## 8. Verifying Everything Works

After setup, walk through this checklist.

### 1. Authenticated request

```bash
curl -H "Authorization: Bearer <your-read-token>" http://localhost:8000/deliveries
# Expected: {"items": [], "total": 0, "limit": 50, "offset": 0}
```

If you get a `401` response, your token is invalid or revoked. Check with `registry-auth list-users`.

### 3. Run the Crawler

The crawler isn't a long-running service — it runs on a schedule (e.g., via cron) to scan directories and register deliveries. It reads `REGISTRY_TOKEN` and `PIPELINE_CONFIG` from the environment:

```bash
python -m pipeline.crawler.main
```

After it finishes, verify deliveries were registered:

```bash
curl -H "Authorization: Bearer <your-read-token>" http://localhost:8000/deliveries
```

### 4. Run a Test Conversion

If deliveries exist and the converter is running (daemon mode) or you run `registry-convert`, check that Parquet files appear in the expected locations and that `parquet_converted_at` is populated:

```bash
curl -H "Authorization: Bearer <your-read-token>" "http://localhost:8000/deliveries?status=passed"
```

Look for `parquet_converted_at` being non-null in the response.

---

## 9. Troubleshooting

### "Command not found: registry-api"

You're not inside the virtual environment:

```bash
source /path/to/loading-dock/.venv/bin/activate
```

### "ModuleNotFoundError: No module named 'fastapi'"

You installed without the `registry` extra:

```bash
pip install -e ".[registry]"
```

### "ModuleNotFoundError: No module named 'pyreadstat'"

You installed without the `converter` extra:

```bash
pip install -e ".[converter]"
```

### pyreadstat Fails to Build

The `pyreadstat` package compiles native C extensions. Make sure you have:

```bash
sudo dnf install gcc gcc-c++ python3.11-devel
```

### 401 Unauthorized

- Verify the token is correct: `registry-auth list-users` to check the user exists and is not revoked.
- Verify the `Authorization` header format: `Authorization: Bearer <token>` (note the space after `Bearer`).
- If using the converter or crawler, check that `REGISTRY_TOKEN` is set in the environment.

### Database Locked Errors

The database uses SQLite's WAL (Write-Ahead Logging) mode, which lets the API read and write concurrently without blocking. If you still see "database is locked" errors:

- Make sure no other process has an exclusive lock on the database file.
- Check that the `.db-wal` and `.db-shm` sidecar files exist alongside the main `.db` file. Don't delete them while the API is running.

### Converter Daemon Keeps Restarting

Check the log file at `pipeline/logs/registry_converter.log`. Common causes:

- Registry API isn't running (the daemon can't connect to the WebSocket).
- `REGISTRY_TOKEN` isn't set or is invalid.
- `converter_state_path` isn't writable.

### Stale PID File

If a process crashed without cleaning up its PID file, the watchdog script will think it is still running. Remove the stale PID file:

```bash
rm pipeline/registry_api.pid
# or
rm pipeline/registry_converter.pid
```

The next cron tick will restart the service.
