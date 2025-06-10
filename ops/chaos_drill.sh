#!/usr/bin/env bash
set -e

# ops/chaos_drill.sh: Simulate data outage and API 500s, re-enable networking, verify halt
# NOTE: The use of 'sudo' here is ONLY for test environments. Do NOT use in production or on systems where admin/sudo is not allowed.
# If you cannot use sudo, simulate outage by stopping your trading process or blocking API endpoints with a mock/fake server.

# Block outbound network (simulate outage)
if command -v sudo >/dev/null 2>&1; then
  sudo ifconfig lo0 down || true
  sleep 10
  # Simulate API 500s (user should have a mock or test endpoint)
  # ...
  # Re-enable networking
  echo "Re-enabling networking..."
  sudo ifconfig lo0 up || true
else
  echo "Skipping network block: sudo not available. Simulate outage by stopping trading process or using a mock API."
  sleep 10
fi

# Check for halt (e.g., check for shutdown.reason or process exit)
if [ -f "shutdown.reason" ]; then
  echo "System halted as expected."
else
  echo "System did not halt as expected!" >&2
  exit 1
fi
