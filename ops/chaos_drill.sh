#!/usr/bin/env bash
set -e

# ops/chaos_drill.sh: Simulate data outage and API 500s, re-enable networking, verify halt
# Block outbound network (simulate outage)
sudo ifconfig lo0 down || true
sleep 10
# Simulate API 500s (user should have a mock or test endpoint)
# ...
# Re-enable networking
echo "Re-enabling networking..."
sudo ifconfig lo0 up || true
# Check for halt (e.g., check for shutdown.reason or process exit)
if [ -f "shutdown.reason" ]; then
  echo "System halted as expected."
else
  echo "System did not halt as expected!" >&2
  exit 1
fi

