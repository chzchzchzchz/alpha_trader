#!/usr/bin/env bash
set -e

# scripts/sentinel.sh: Monitor heartbeat.txt and restart JVM if stale (>3s)
#
# Usage: ./sentinel.sh
#   No arguments required. Will run continuously until interrupted.
#
# Exit codes:
#   0: Normal exit (on SIGINT/SIGTERM)
#   1: Error condition

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
HEARTBEAT_FILE="${SCRIPT_DIR}/../heartbeat.txt"
MAX_AGE_SECONDS=3

check_heartbeat() {
    if [ ! -f "$HEARTBEAT_FILE" ]; then
        echo "ERROR: Heartbeat file not found at $HEARTBEAT_FILE"
        return 1
    fi

    local current_time
    local file_time
    current_time=$(date +%s)
    file_time=$(date -r "$HEARTBEAT_FILE" +%s)
    local age=$((current_time - file_time))

    if [ "$age" -gt "$MAX_AGE_SECONDS" ]; then
        echo "WARNING: Heartbeat file is $age seconds old (max allowed: $MAX_AGE_SECONDS)"
        return 1
    fi
    return 0
}

restart_trading() {
    echo "Attempting to restart trading process..."
    "$SCRIPT_DIR/panic.sh" --force
    sleep 1
    "$SCRIPT_DIR/run.sh"
}

trap 'echo "Sentinel stopping..."; exit 0' INT TERM

echo "Starting sentinel process..."
echo "Monitoring $HEARTBEAT_FILE (max age: ${MAX_AGE_SECONDS}s)"

while true; do
    if ! check_heartbeat; then
        echo "$(date): Stale heartbeat detected, initiating restart"
        restart_trading
    fi
    sleep 1
done
