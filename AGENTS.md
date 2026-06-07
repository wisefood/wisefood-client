# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`wisefood` is a Python client for the WiseFood platform, which exposes **two distinct
APIs**. The package provides one client for each:

- `wisefood.client.DataClient` — the **WiseFood Data API** (articles, artifacts, guides,
  guidelines, textbooks, textbook passages, fctables).
- `wisefood.api_client.Client` — the **WiseFood API** (households, members, profiles).

Both are constructed with a `wisefood.Credentials` (user **or** machine-to-machine).

## Layout

- `src/wisefood/client.py` — `DataClient` + HTTP core.
- `src/wisefood/api_client.py` — `Client` (WiseFood API) + HTTP core.
- `src/wisefood/entities/` — entity classes and collection proxies.
  - `base.py` — `BaseEntity`, the `Field` descriptor, `BaseCollectionProxy`.
  - `articles.py`, `guides.py`, `textbooks.py`, `artifacts.py`, `fctables.py`,
    `households.py`.
- `src/wisefood/exceptions.py` — `APIError` hierarchy + response-envelope mapping.
- `src/wisefood/autocomplete.py` — IPython tab-completion for collections.
- `tests/` — pytest suite. `docs/` — Sphinx + MyST documentation.

## Build & test

```bash
pip install -e ".[docs]"     # client + docs toolchain
pytest                       # run the test suite
sphinx-build -W -b html docs docs/_build/html   # build docs (warnings = errors)
```

## Conventions

- Entity attributes are declared with the `Field` descriptor over `entity.data`.
- Writes auto-save when `sync=True` (the default). Use `sync=False` to batch, then
  `save()`.
- System fields (`id`, `urn`, `creator`, `created_at`, `updated_at`, often `type`) are
  read-only.
- URN-backed entities use `URN_PREFIX`; some entities (artifacts, guidelines, passages)
  are UUID-backed (`IDENTIFIER_FIELD = "id"`).
- In examples and tests, read credentials/URLs from `WISEFOOD_*` environment variables.
  **Never commit real secrets.**
- Keep `src/wisefood/__init__.py` `__version__` in sync with `pyproject.toml`.
- Update `CHANGELOG.md` for user-visible changes.
