#!/bin/bash
# Wrapper for autonomous_loop with proper env loading
cd "$HOME/alpha_trader"
# Load .env if exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi
# Run the loop
exec python3 "$HOME/alpha_trader/autonomous_loop.py" --live
