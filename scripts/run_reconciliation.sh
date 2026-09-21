#!/bin/bash
cd "$HOME/alpha_trader"
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi
exec python3 "$HOME/alpha_trader/position_reconciliation.py"
