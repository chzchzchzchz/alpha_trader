#!/bin/bash
cd "$HOME/alpha_trader"
for pidfile in logs/*.pid; do
    [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
done
pkill -f "research_agent.py" 2>/dev/null || true
pkill -f "debate_team.py" 2>/dev/null || true
pkill -f "executor_v18.py" 2>/dev/null || true
pkill -f "position_manager.py" 2>/dev/null || true
pkill -f "weather_oracle" 2>/dev/null || true
pkill -f "self_improve.py" 2>/dev/null || true
echo "Agents stopped."
