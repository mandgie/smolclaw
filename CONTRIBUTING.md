# Contributing to smolclaw

Thanks for your interest in contributing! smolclaw is a small project and every contribution matters.

## Getting Started

```bash
git clone https://github.com/mandgie/smolclaw.git
cd smolclaw

# With uv (recommended — fast, manages venv automatically)
uv sync --extra dev

# Or with pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Development Workflow

1. Create a branch from `main`
2. Make your changes
3. Run checks:
   ```bash
   make check          # lint + format + tests (recommended)
   ```
   Or run individually:
   ```bash
   make lint           # ruff check
   make format         # ruff format
   make test           # pytest with coverage
   ```
4. Commit with a descriptive message (we use [conventional commits](https://www.conventionalcommits.org/))
5. Open a pull request

Run `make help` to see all available targets.

## What to Work On

- Issues labeled `good first issue` are great starting points
- Check the roadmap in [README.md](README.md) for bigger features
- Bug reports and test improvements are always welcome

## Code Style

- We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting
- Target Python 3.11+
- Keep it simple — smolclaw is intentionally lightweight

## Tests

Tests live in `tests/` and use pytest. The Claude SDK is mocked in all tests so you don't need an API key to run them.

```bash
pytest              # run all tests
pytest -x           # stop on first failure
pytest -k "memory"  # run tests matching "memory"
```

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new functionality
- Update the README if you're adding user-facing features
- CI must pass (lint + tests across Python 3.11-3.13)
