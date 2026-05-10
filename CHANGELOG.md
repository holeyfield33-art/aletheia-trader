# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

### Added
- Full `market_watcher` package with orchestrator, data feeds, regime detector, signal generator, alerts, and monitoring modules.
- `core/aletheia_guard.py` to centralize Aletheia Core audit enforcement for watcher decisions and signal publishing.
- WebSocket stream endpoint for watcher events: `/v1/market-watcher/stream`.
- Sentiment provider health endpoint: `/v1/market-watcher/sentiment-health`.
- Thread-safe hook lifecycle management with register/unregister IDs.
- Sentiment provider failover policy with provider failure counters and cooldown blocking.

### Changed
- `agents/market_watcher.py` is now a compatibility shim delegating to the `market_watcher` package.
- Dashboard navigation and experience updated around **Live Market Watcher**.
- Project packaging metadata expanded to include `core` and `market_watcher` packages.

### Fixed
- Circular import risk between `agents` and `market_watcher` entrypoints.
- CI formatting/type-check drift for watcher and dashboard integration.

## [1.0.1] - 2026-05-10

### Added
- MIT `LICENSE`.
- GitHub Actions CI workflow for lint, type-checking, and tests.
- `CONTRIBUTING.md`, `SECURITY.md`, `.streamlit/config.toml`, and `CHANGELOG.md`.
- Project metadata and tool configuration via `pyproject.toml`.

### Changed
- Strengthened API request validation for symbols, prices, quantity, and status filtering.
- Improved JSON persistence with lock-based access and atomic writes.
- Modernized Docker Compose to run API + dashboard services with health checks.
- Expanded README with quickstart, roadmap, integration guidance, and troubleshooting.
