# Contributing

Thanks for contributing to the WiseFood client!

## Development setup

```bash
git clone https://github.com/wisefood/wisefood-client
cd wisefood-client
python -m venv .venv && source .venv/bin/activate
pip install -e ".[docs]"
```

## Running the tests

```bash
pytest
```

Tests live in `tests/`. Unit tests should not hit the network — mock the client. The
`test_*_live.py` scripts at the repo root are manual, credentialed smoke tests and are
**not** part of the automated suite.

## Building the docs

```bash
sphinx-build -W -b html docs docs/_build/html
open docs/_build/html/index.html
```

The build treats warnings as errors and imports the package for autodoc, so keep
docstrings valid.

## Conventions

- Follow the patterns in [`AGENTS.md`](https://github.com/wisefood/wisefood-client/blob/main/AGENTS.md).
- Keep `src/wisefood/__init__.py` `__version__` aligned with `pyproject.toml`.
- Add a `CHANGELOG.md` entry under `[Unreleased]` for user-visible changes.
- Examples and tests read credentials from `WISEFOOD_*` env vars; never commit secrets.

## Pull requests

- Keep changes focused; one logical change per PR.
- Ensure `pytest` and the docs build both pass before opening a PR.
