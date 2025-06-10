# Architecture Overview

This document outlines the modules and their responsibilities in alpha_trader.

- **config**: Handles environment loading, config validation, and secret management.
- **data**: Manages immutable Bar objects, HistoricalCache, and data ingestion.
- **strategy**: Contains strategy skeletons and base interfaces.
- **execution**: Handles order routing, fill simulation, and risk management.
- **monitoring**: Exposes metrics, logging, and alerting.
- **ops**: Backup, restore, and operational scripts.
- **testing**: JUnit 5 unit tests, mutation testing with PIT, test stubs for every class.
- **ci**: GitHub Actions workflow for build, test, mutation coverage, and shellcheck.
- **metrics**: Prometheus metrics endpoint via MetricsExporter.
- **security-validation**: ConfigValidator, config hash checking, and tamper detection.

## Flow

Source ➔ Unit tests (JUnit 5) ➔ Mutation tests (PIT) ➔ Docker-free deployment.

Each module is designed for testability and separation of concerns.
