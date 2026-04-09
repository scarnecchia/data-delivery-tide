#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$PIPELINE_DIR")"

PIDFILE="${PIPELINE_DIR}/registry_api.pid"
LOGFILE="${PIPELINE_DIR}/logs/registry_api.log"

mkdir -p "$(dirname "$LOGFILE")"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi

cd "$PROJECT_DIR"
nohup registry-api >> "$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
