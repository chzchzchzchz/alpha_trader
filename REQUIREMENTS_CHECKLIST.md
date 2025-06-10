# Project Requirements Checklist

Copy of the requirements for alpha_trader compliance:

1. The project MUST compile on Java 17 with mvn clean install from a non-privileged user account.
2. No dependency may require Homebrew or sudo for installation.
3. The root directory name SHALL be alpha_trader.
4. Source files SHALL live under alpha_trader/src/main/java.
5. Test files SHALL live under alpha_trader/src/test/java.
6. Maven groupId SHALL be com.alpha_trader.
7. Maven artifactId SHALL be alpha_trader.
8. Maven version SHALL start at 1.0.0 and increment semver on every tagged release.
9. The project MUST build with zero warnings at the -Xlint:all level.
10. Every public class MUST include Javadoc describing pass/fail behavior.
11. No em-dash characters are allowed in any source, doc, or commit message.
12. A file named .editorconfig MUST enforce spaces (4) and LF endings.
13. A Git pre-commit hook MUST block any new TODO without an associated Jira/issue ID.
14. The package config MUST contain EnvLoader, ConfigValidator, and SecretsManager.
15. EnvLoader MUST abort with exit code 13 on config hash mismatch unless --override is present.
16. The SHA-256 hash file SHALL live at config/config_hash.txt.
17. ConfigValidator MUST reject Alpaca keys not exactly 20 characters long.
18. ConfigValidator MUST reject Alpaca secrets not exactly 40 characters long.
19. ConfigValidator MUST enforce VAR_THRESHOLD ≤ 0.03.
20. SecretsManager MUST expire secrets after 12 hours and throw SECRET_EXPIRED.
21. All environment variables MUST be read from .env located at project root.
22. The data package MUST define immutable class Bar with OHLCV + timestamp.
23. HistoricalCache MUST store a maximum of seven days of 1-min bars.
24. HistoricalCache MUST delete data older than seven days on each cleanupOldData() call.
25. DataIngestor MUST fall back to HistoricalCache if Alpaca REST fails.
26. DataIngestor MUST align every bar timestamp to a whole-minute boundary.
27. FeedValidator MUST flag any bar whose volume is zero while the market is open.
28. FeedValidator MUST pause trading for 60 s after a price outlier event.
29. FeedBackfiller MUST fill missing 1-min gaps within five seconds.
30. Nightly job ChecksumVerifier MUST exit 1 if any file fails the stored hash list.
31. Nightly job ChecksumVerifier MUST log “NO CHECKSUM ERRORS” on success.
32. Strategy skeletons MUST be written by StrategyGenerator into alpha/candidates.
33. Generated strategy class names MUST start with GeneratedStrategy_.
34. All strategies MUST implement alpha.core.BaseStrategy.
35. Backtester MUST run three sliding windows: train 60 d, val 30 d, test 30 d.
36. Backtester MUST fail if out-of-sample Sharpe < 0.7.
37. WalkForwardValidator MUST throw WALK_FORWARD_FAIL if any window fails.
38. MutationTester MUST run 100 variants and require ≥ 95 % Sharpe degradation.
39. BenchmarkShadow MUST compare against SPUS and require +0.2 Sharpe spread.
40. StrategyDeployer MUST verify jarHash before copying to execution/strategies.
41. FillSimulator MUST calibrate base spread and impact coefficient.
42. LatencyLogger MUST keep the last 1 000 latency samples only.
43. LatencyLogger MUST compute the 99th percentile ≤ 500 ms.
44. OrderRouter MUST attach a unique clientOrderId to every order.
45. FailClosedManager MUST set tradingEnabled=false after three consecutive 5xx errors.
46. HaltManager MUST detect halt status via Alpaca every 60 s.
47. PanicSwitch MUST cancel all orders and exit within five seconds on activation.
48. Rolling heartbeat MUST write to heartbeat.txt every two seconds.
49. Sentinel shell script MUST restart the JVM if heartbeat.txt is older than three seconds.
50. ExposureManager MUST block gross exposure > 110 % of equity.
51. ExposureManager MUST block sector exposure > 25 % of equity.
52. VaRCalculator MUST limit parametric VaR95 to < 3 % of equity.
53. ESCalculator MUST limit ES99 to < 5 % of equity.
54. CorrelationGuard MUST fail if average |ρ| > 0.6 among open positions.
55. DrawdownMonitor MUST trigger kill switch on 7-day drawdown > 5 %.
56. StopLossManager MUST set per-trade stop at 1 % of entry price.
57. StressTester MUST halve risk if worst-5 % drawdown > 10 %.
58. MetricsExporter MUST expose pnls_total on /metrics.
59. MetricsExporter MUST expose data_lag_seconds on /metrics.
60. Grafana dashboard JSON MUST be provisioned automatically via docker-compose.
61. AlertDispatcher MUST deliver email via SMTP within 30 s.
62. AlertDispatcher MUST deliver Pushbullet note within 30 s.
63. DailyReporter MUST write a Markdown report at 16:05 ET.
64. DailyReporter report lines MUST match specified regex patterns exactly.
65. CanaryTester MUST run hourly and halt on any exception.
66. Log rotation MUST gzip files > 50 MB and retain 90 days.
67. ConfigHashChecker (security layer) MUST abort with code 13 on mismatch.
68. AuditLogger MUST hash-chain every entry and detect tampering.
69. BackupManager MUST create AES-256 tarball backups daily at 02:00 ET.
70. BackupManager MUST verify restore integrity weekly via chaos_drill.sh.
71. WashSaleGuardian MUST block sells within 30 days of a buy of same symbol.
72. PDTGuard MUST block the 4th day-trade in five rolling trading days.
73. BlotterGenerator MUST produce daily CSV at 23:59 ET.
74. TaxReportGenerator MUST produce FIFO-lot 8949 CSV daily.
75. Default logging level SHALL be INFO; risk alerts log at ERROR.
76. No println debugging allowed in committed source.
77. All timestamps MUST be stored and compared in UTC.
78. Equity calculations MUST use double precision.
79. No reflection‐based magic; classpath scanning is forbidden.
80. No Lombok; explicit getters/setters only where needed.
81. Unit tests SHALL use JUnit 5 exclusively.
82. Mockito MAY be used for mocks but NOT PowerMock.
83. Mutation tests MUST use PIT with default mutator set.
84. Minimum test coverage threshold SHALL ratchet upward each release.
85. GitHub Actions workflow MUST run mvn clean install -q.
86. Workflow MUST run integration tests via mvn verify -q.
87. Workflow MUST run PIT mutation coverage and fail if coverage < 90 %.
88. Release tags MUST follow release-YYYYMMDD-N format.
89. scripts/run.sh MUST run JVM under nice -10.
90. scripts/panic.sh MUST read PID from trading.pid.
91. ops/rollback.sh MUST check out supplied Git tag and rebuild.
92. ops/backup_daily.sh MUST call BackupManager with AES key file.
93. ops/chaos_drill.sh MUST simulate data outage and API 500s.
94. The project MUST contain docs/README.md with quick-start steps.
95. The project MUST contain docs/ARCHITECTURE.md outlining every module.
96. The project MUST contain docs/OPERATIONS.md runbook.
97. README MUST include sample .env with placeholder keys.
98. All shell scripts MUST have #!/usr/bin/env bash.
99. No shell script may contain hard-coded absolute paths.
100. Shell scripts MUST set set -e at the top.
101. SQLite database MUST live at cache/historical.db.
102. SQLite JDBC driver version MUST be pinned to 3.45.0.0 or newer.
103. Prometheus client version MUST be 0.16.0.
104. Jackson databind version MUST be 2.14.3 or newer.
105. JavaMail dependency MUST be jakarta.mail version 2.1.1.
106. The project MAY not include external charting libraries.
107. No GUI components are allowed; CLI and dashboards only.
108. killSwitch.activate() MUST exit with code 2.
109. All exit codes MUST be documented in OPERATIONS.md.
110. HistoricalCache.getBars() MUST return bars sorted ascending.
111. HistoricalCache.upsertBar() MUST use INSERT OR REPLACE.
112. Bar volumes MUST be stored as INTEGER, not REAL, in SQLite.
113. Grafana default admin password MUST be randomized on first start.
114. Grafana MUST be exposed only on localhost.
115. Prometheus scrape interval MUST be 15 s.
116. Prometheus retention MUST be 30 days.
117. LogRotator MUST compress rotated logs with gzip level 6.
118. LogRotator MUST skip rotation if disk free < 1 GB.
119. KillSwitch activation MUST trigger Pushbullet alert.
120. KillSwitch activation MUST write shutdown.reason file.
121. RecoveryManager MUST reconcile positions within two minutes of boot.
122. StateSnapshot file MUST be updated every 60 s.
123. StateSnapshot MUST include open positions and orders.
124. Web requests MUST use Java HttpClient with 3 s connect timeout.
125. Any retry loop MUST implement exponential back-off max 5 attempts.
126. No blocking network calls inside UI threads (none exist).
127. Project MUST compile with --release 17 target.
128. All cryptography MUST use JDK standard libraries.
129. AES keys MUST be 256 bits.
130. Passwords in memory MUST be char[] not String where feasible.
131. No direct JDBC bare statements; prepared statements only.
132. Every SQL statement MUST close its connection in finally/try-with-resources.
133. There shall be exactly one global thread pool per module.
134. Scheduled tasks MUST use ScheduledExecutorService.
135. No Thread.sleep longer than five seconds in production code.
136. Logging MUST use java.util.logging or SLF4J; no System.out prints.
137. Each module MUST have its own logger with category matching package.
138. Log timestamps MUST be ISO-8601 in UTC.
139. Log level DEBUG MUST be disabled in production profile.
140. Release builds MUST be reproducible byte-for-byte.
141. Maven compiler plugin MUST enable parameters=true.
142. Maven Surefire plugin MUST run JUnit5.
143. Maven shade or assembly plugins are forbidden.
144. Only one JAR MUST be produced: alpha_trader-<version>.jar.
145. Strategy JARs MUST be placed in execution/strategies/.
146. Strategy manifest files MUST be placed in alpha/strategy_manifest_<name>.json.
147. Manifest JSON MUST contain fields id, dataSliceHash, date, author.
148. FeatureImportanceLogger output MUST list at least ten features.
149. FeatureImportanceLogger file name MUST start with alpha/feature_importance_.
150. BenchmarkShadow MUST fetch SPUS returns from HistoricalCache if REST unavailable.
151. StressTester MUST run 10 000 paths in < 60 s.
152. StressTester MUST scale position sizes by factor returned.
153. DrawdownMonitor MUST keep a seven-day sliding window only.
154. Pushbullet token MUST be read from .env and not checked into git.
155. SMTP credentials MUST be read from .env.
156. Alerts MUST prefix subject with [alpha_trader].
157. Build script scripts/run.sh MUST write trading.pid.
158. scripts/run.sh MUST pass all CLI args to the JVM.
159. DataIngestor MUST retry primary feed once before fallback.
160. HistoricalCache MUST reject duplicate timestamp/symbol rows.
161. ChecksumVerifier MUST use SHA-256, hex lower-case.
162. No MD5 or SHA-1 hashing is allowed anywhere.
163. Audit log file MUST be security/audit.log.
164. Audit log entries MUST include previous hash and new hash.
165. BackupManager MUST create backups under backups/<YYYY-MM-DD>.tar.enc.
166. Backup passphrase file MUST be security/passphrase.txt.
167. Backups MUST exclude backups/ directory itself.
168. chaos_drill.sh MUST re-enable networking after test.
169. chaos_drill.sh MUST verify system halts on blocked feed.
170. JUnit tests MUST cover at least one failure path per class.
171. Positive unit tests MUST assert against expected exceptions.
172. Mutation coverage MUST be ≥ 90 % by Phase 10.
173. CI pipeline MUST cache Maven dependencies.
174. CI pipeline MUST run mutation tests in a separate job.
175. Release artefacts MUST be uploaded to GitHub Releases.
176. Release notes MUST include commit logs since prior tag.
177. No proprietary dependencies are allowed.
178. All dependencies MUST be Apache 2.0, MIT, or similarly permissive.
179. Dependency versions MUST be pinned; no version ranges.
180. CVE scanning MUST run in CI using trivy.
181. No CVE above HIGH severity may be present in dependencies.
182. Memory usage MUST stay below 512 MB RSS during normal operation.
183. CPU usage MUST stay below 50 % on Apple M2 baseline.
184. JVM MUST start with -Xms128m -Xmx512m.
185. Main loop period MUST be 60 s and aligned to wall clock minute.
186. Project MUST support graceful shutdown on SIGTERM.
187. Graceful shutdown MUST flush logs and close SQLite connections.
188. All cron-style shell scripts MUST be idempotent.
189. Dockerfile (optional) MUST run as non-root user.
190. Dockerfile MUST set USER 1001.
191. Cannot use Docker privileged mode.
192. Java serialization is forbidden; use JSON only.
193. No custom ClassLoader hacks allowed.
194. README quick-start MUST finish in < 5 minutes on clean macOS.
195. README MUST include Prometheus/Grafana one-liner to start stack.
196. README MUST show how to tail logs for errors.
197. CONTRIBUTING.md MUST list code-style and review rules.
198. .gitignore MUST exclude .env, cache/, backups/, and trading.pid.
199. No large binaries (> 20 MB) may be committed.
200. Phase 0 baseline MUST tag as release-phase-0 and remain compile-green forever

