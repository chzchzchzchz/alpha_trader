# OPERATIONS.md

## Exit Codes

- 2: killSwitch.activate() triggered
- 13: EnvLoader or ConfigHashChecker config hash mismatch
- 1: ChecksumVerifier file hash failure
- SECRET_EXPIRED: SecretsManager secret expired
- WALK_FORWARD_FAIL: WalkForwardValidator window failure

## Runbook

- To start trading: `scripts/run.sh`
- To stop trading: `scripts/panic.sh`
- To backup: `ops/backup_daily.sh`
- To restore: `ops/rollback.sh <tag>`
- To run chaos drill: `ops/chaos_drill.sh`

## Metrics Endpoint
- Start metrics endpoint: `java -jar app.jar --metrics-port 9091`

## Manual Log Rotation
- Run manual log rotation: `java -cp app.jar com.alpha_trader.execution.LogRotator /var/log/alpha`

See README.md for more details.
