# QA Registry Implementation Plan — Phase 6: Deployment Scaffolding

**Goal:** Watchdog script and runtime config ready for RHEL deployment.

**Architecture:** PID-based watchdog script that cron runs every minute. If the registry API process isn't running, it starts it. Config.json already created in Phase 2 — this phase adds documentation comments and the scripts directory.

**Tech Stack:** Bash

**Scope:** 6 phases from original design (phase 6 of 6)

**Codebase verified:** 2026-04-09 — greenfield, Phase 2 creates `pipeline/config.json`.

---

## Acceptance Criteria Coverage

This phase implements:

### qa-registry.AC4: Infrastructure
- **qa-registry.AC4.2 Success:** `ensure_registry.sh` is syntactically valid bash

---

<!-- START_TASK_1 -->
### Task 1: Create ensure_registry.sh watchdog script

**Files:**
- Create: `pipeline/scripts/ensure_registry.sh`

**Step 1: Create the directory and file**

Run: `mkdir -p pipeline/scripts`

The script should follow the spec's watchdog pattern:

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(dirname "$SCRIPT_DIR")"

PIDFILE="${PIPELINE_DIR}/registry_api.pid"
LOGFILE="${PIPELINE_DIR}/logs/registry_api.log"

mkdir -p "$(dirname "$LOGFILE")"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi

cd "$PIPELINE_DIR"
nohup registry-api >> "$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
```

Key differences from spec's version:
- Uses `SCRIPT_DIR`/`PIPELINE_DIR` for relative path resolution instead of hardcoded paths
- Uses the `registry-api` entrypoint (installed by pip) instead of `python -m uvicorn`
- Creates the logs directory if it doesn't exist

**Step 2: Make it executable**

Run: `chmod +x pipeline/scripts/ensure_registry.sh`

**Step 3: Verify syntax**

Run: `bash -n pipeline/scripts/ensure_registry.sh`
Expected: No output (exits 0, meaning syntactically valid)

**Step 4: Commit**

```bash
git add pipeline/scripts/ensure_registry.sh
git commit -m "feat: add PID-based watchdog script for registry API"
```
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create output directory placeholder

**Files:**
- Create: `output/.gitkeep`

**Step 1: Create the placeholder**

Create an empty `output/.gitkeep` file so the output directory is tracked in git but its contents are ignored (`.gitignore` already has `output/` — update it to allow `.gitkeep`).

**Step 2: Update .gitignore to allow .gitkeep in output/**

Add to `.gitignore`:
```
!output/.gitkeep
```

**Step 3: Commit**

```bash
git add output/.gitkeep .gitignore
git commit -m "chore: add output directory placeholder"
```
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Final verification

**Step 1: Run full test suite**

Run: `pytest -v`
Expected: All tests pass across all test files

**Step 2: Verify bash syntax**

Run: `bash -n pipeline/scripts/ensure_registry.sh && echo "VALID"`
Expected: `VALID`

**Step 3: Verify package install**

Run: `pip install -e ".[registry,dev]" && python -c "import pipeline; print('OK')"`
Expected: Install succeeds, import works

**Step 4: Verify entrypoint exists**

Run: `which registry-api`
Expected: Path to the entrypoint script

**Step 5: Commit if any fixes needed**

```bash
git add -u
git commit -m "fix: resolve any final issues from deployment scaffolding"
```
<!-- END_TASK_3 -->
