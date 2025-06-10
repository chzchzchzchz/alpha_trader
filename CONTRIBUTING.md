# Contributing to alpha_trader

## Code Style
- Use 4 spaces for indentation (enforced by .editorconfig).
- Use LF (Unix) line endings.
- No println or print debugging in committed code.
- All timestamps must be in UTC.
- All dependencies must be pinned to specific versions.
- No proprietary dependencies; only permissive licenses (Apache 2.0, MIT, etc.).

## Review Rules
- All new TODOs must include a Jira/issue ID.
- All public classes must have Javadoc (Java) or docstrings (Python).
- All exit codes must be documented in docs/OPERATIONS.md.
- All shell scripts must start with #!/usr/bin/env bash and set -e.
- No hard-coded absolute paths in scripts.
- All environment variables must be read from .env at project root.
- All secrets and credentials must be read from .env and not checked into git.
- All new code must include tests covering at least one failure path.
- No large binaries (>20MB) may be committed.

## Commit Messages
- No em-dash (—) characters allowed.
- Release tags must follow release-YYYYMMDD-N format.

## Pre-commit Hook
- A pre-commit hook must block any new TODO without an associated Jira/issue ID.

## Testing
- Java: Use JUnit 5 only. Mockito allowed, PowerMock not allowed.
- Python: Use pytest or unittest.
- Mutation coverage must be ≥ 90% by Phase 10.

## Documentation
- Update docs/README.md, docs/ARCHITECTURE.md, and docs/OPERATIONS.md as needed.

## Pull Request Hard Rules
- Every PR must include the generated JUnit test stub plus real tests for new/changed classes.
- PIT mutation coverage must be at least 85% (build fails otherwise).
- All shell scripts must pass shellcheck (see CI workflow).
- No PR may introduce config changes without a corresponding hash validation.
