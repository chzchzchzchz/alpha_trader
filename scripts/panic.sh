#!/usr/bin/env bash
set -e

# scripts/panic.sh: Read PID from trading.pid and send SIGTERM
PID_FILE="$(dirname "$0")/../trading.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "PID file not found!" >&2
  exit 1
fi
PID=$(cat "$PID_FILE")
kill -TERM "$PID"

