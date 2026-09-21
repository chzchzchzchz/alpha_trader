#!/bin/bash
# chaos_drill.sh — weekly health check and failure simulation
# Runs as cron: 0 3 * * 0 (Sunday 3am)

set -euo pipefail

AGENT_DIR="$HOME/alpha_trader"
LOGDIR="$AGENT_DIR/logs"
DRILL_LOG="$LOGDIR/chaos_$(date +%Y-%m-%d).txt"
exec > >(tee -a "$DRILL_LOG") 2>&1

echo "=== CHAOS DRILL START $(date) ==="

# 1. Verify all 6 agents are running via PID files
agents=(research_agent debate_team executor_v18 self_improve weather_oracle position_manager)
for a in "${agents[@]}"; do
    pidfile="$LOGDIR/${a}.pid"
    if [ -f "$pidfile" ]; then
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "✅ $a running (PID $pid)"
        else
            echo "❌ $a NOT running (stale PID $pid)"
        fi
    else
        echo "❌ $a missing PID file"
    fi
done

# 2. Check DB connectivity and writeability
echo "Checking database..."
if sqlite3 "$AGENT_DIR/data/autonomous.db" "SELECT 1" > /dev/null; then
    echo "✅ DB accessible"
    # Try write a test row to health table (create if not exists)
    sqlite3 "$AGENT_DIR/data/autonomous.db" <<'SQL'
        CREATE TABLE IF NOT EXISTS health_checks (
            ts INTEGER, message TEXT
        );
        INSERT INTO health_checks VALUES (strftime('%s','now'), 'chaos_drill_ok');
SQL
    echo "✅ DB write test ok"
else
    echo "❌ DB inaccessible"
fi

# 3. Check Kalshi API health (via get_balance)
echo "Checking Kalshi API..."
python3 -c "
import os, sys
sys.path.insert(0, '$AGENT_DIR')
from kalshi.client import KalshiClient
client = KalshiClient(
    key_id=os.getenv('KALSHI_API_KEY_ID'),
    private_key_path=os.path.expanduser(os.getenv('KALSHI_API_KEY_FILE','~/.kalshi/private_key.pem')),
    demo=os.getenv('KALSHI_DEMO','true').lower()=='true'
)
try:
    bal = client.get_balance()
    print(f'✅ API ok | Balance: {bal}')
except Exception as e:
    print(f'❌ API failed: {e}')
" || echo "❌ API check crashed"

# 4. Scan recent logs for repeated exceptions (>5 in last 10 min)
echo "Scanning logs for crash patterns..."
log_files=("$LOGDIR/executor_v18.log" "$LOGDIR/research_agent.log" "$LOGDIR/debate_team.log")
for log in "${log_files[@]}"; do
    if [ -f "$log" ]; then
        count=$(tail -n 1000 "$log" | grep -i 'exception\|error' | wc -l)
        if [ "$count" -gt 5 ]; then
            echo "⚠️  $log has $count error lines in last 1000"
        else
            echo "✅ $log clean"
        fi
    else
        echo "❌ $log missing"
    fi
done

# 5. Simulate recovery: attempt to restart any dead agents
echo "Restarting dead agents..."
./scripts/start_alpha_trader.sh

# 6. Disk space and inodes
df_h=$(df -h "$AGENT_DIR" | tail -1)
echo "Disk: $df_h"
df_i=$(df -i "$AGENT_DIR" | tail -1)
echo "Inodes: $df_i"

echo "=== CHAOS DRILL END $(date) ==="
