#!/bin/bash
# Start all alpha_trader agents
cd "$HOME/alpha_trader"
mkdir -p logs

start_agent() {
    local script=$1
    local name=$2
    local log="logs/${name}.log"
    local pid="logs/${name}.pid"
    echo "Starting $name..."
    nohup python3 "$script" > "$log" 2>&1 &
    echo $! > "$pid"
    sleep 1
}

start_agent "research_agent.py" "research_agent"
start_agent "debate_team.py" "debate_team"
start_agent "executor_v18.py" "executor_v18"
start_agent "self_improve.py" "self_improve"
start_agent "weather_oracle_v22.py" "weather_oracle"
start_agent "position_manager.py" "position_manager"

echo "All agents launched."
