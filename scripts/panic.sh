#!/usr/bin/env bash
set -e

# scripts/panic.sh: Emergency kill switch that cancels all orders and exits trading
#
# Usage: ./panic.sh [--force]
#   --force: Skip confirmation prompt
#
# Exit codes:
#   0: Successfully stopped trading
#   1: Error or user cancelled

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PID_FILE="${SCRIPT_DIR}/../trading.pid"

if [[ "$1" != "--force" ]]; then
    echo "⚠️  WARNING: This will immediately cancel all orders and stop trading"
    read -p "Are you sure? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled by user"
        exit 1
    fi
fi

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Sending SIGTERM to process $PID..."
        kill -TERM "$PID"
        echo "Waiting for process to exit..."
        for i in {1..5}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                echo "Process terminated successfully"
                rm -f "$PID_FILE"
                exit 0
            fi
            sleep 1
        done
        echo "Process did not exit gracefully, sending SIGKILL..."
        kill -9 "$PID"
        rm -f "$PID_FILE"
    else
        echo "Process $PID not found, cleaning up stale PID file"
        rm -f "$PID_FILE"
    fi
else
    echo "No PID file found at $PID_FILE"
fi

echo "Trading stopped"
