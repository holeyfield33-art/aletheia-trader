# Contributing to Aletheia Trader

Thanks for contributing.

## Development Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
3. Run checks before opening a PR:
   ```bash
   ruff check .
   black .
   isort .
   mypy agents api audit backtesting brokers core dashboard market_watcher risk scripts
   pytest -q
   ```

## Pull Request Guidelines

- Keep changes focused and small.
- Preserve human-in-the-loop paper-trading behavior.
- Keep Aletheia audit integration mandatory for signal/order decisions.
- Add or update tests for behavioral changes.
- Document API or UX changes in README or docstrings.

## Commit Style

Use Conventional Commits when possible:

- `feat:` new feature
- `fix:` bug fix
- `chore:` maintenance
- `docs:` documentation
- `refactor:` internal cleanup
- `test:` test updates
