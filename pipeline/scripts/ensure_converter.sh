#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$PIPELINE_DIR")"

PIDFILE="${PIPELINE_DIR}/registry_converter.pid"
LOGFILE="${PIPELINE_DIR}/logs/registry_converter.log"

mkdir -p "$(dirname "$LOGFILE")"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi

cd "$PROJECT_DIR"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

nohup registry-convert-daemon >> "$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
