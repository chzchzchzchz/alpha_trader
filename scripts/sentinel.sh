#!/usr/bin/env bash
set -e

# Sentinel: Restart JVM if heartbeat.txt is older than 3 seconds
HEARTBEAT="$(dirname "$0")/../heartbeat.txt"
JVM_PID_FILE="$(dirname "$0")/../trading.pid"

if [ ! -f "$HEARTBEAT" ]; then
  echo "No heartbeat file found. Restarting JVM."
  # TODO: Insert JVM restart command here
  exit 1
fi

AGE=$(($(date +%s) - $(date -r "$HEARTBEAT" +%s)))
if [ "$AGE" -gt 3 ]; then
  echo "Heartbeat too old ($AGE s). Restarting JVM."
  # TODO: Insert JVM restart command here
  exit 1
fi

echo "Heartbeat is fresh ($AGE s). No action needed."

