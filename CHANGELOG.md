# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

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
