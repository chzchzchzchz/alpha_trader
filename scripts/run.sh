#!/usr/bin/env bash
set -e

# scripts/run.sh: Run JVM under nice -10, write trading.pid, pass all CLI args
PID_FILE="$(dirname "$0")/../trading.pid"
JAR="$(dirname "$0")/../build/classes"
LIB="$(dirname "$0")/../lib/*"
MAIN_CLASS="com.alpha_trader.Main"

# Start JVM under nice -10
nohup nice -10 java -Xms128m -Xmx512m -cp "$JAR:$LIB" $MAIN_CLASS "$@" > /dev/null 2>&1 &
echo $! > "$PID_FILE"

