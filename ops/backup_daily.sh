#!/usr/bin/env bash
set -e

# ops/backup_daily.sh: Call BackupManager with AES key file
KEY_FILE="$(dirname "$0")/../security/passphrase.txt"
cd "$(dirname "$0")/.."
java -cp "build/classes:lib/*" com.alpha_trader.execution.BackupManager "$KEY_FILE"

