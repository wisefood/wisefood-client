# Installation

The WiseFood client is a small, dependency-light Python package distributed on PyPI.

## Requirements

- **Python ≥ 3.8** (the documentation and CI builds run on Python 3.13).
- Runtime dependencies, installed automatically:
  - [`requests`](https://requests.readthedocs.io/) — the underlying HTTP layer.
  - [`pandas`](https://pandas.pydata.org/) — powers the tabular `entity.show()` helper.

## Install from PyPI

```bash
pip install wisefood
```

This gives you both clients:

```python
from wisefood import DataClient, Client, Credentials
```

- `DataClient` talks to the **WiseFood Data API** (articles, artifacts, guides,
  guidelines, textbooks, textbook passages, FCTables).
- `Client` talks to the **WiseFood API** (households, members, profiles).

## Optional: nicer interactive experience

If you work in [IPython](https://ipython.org/) or Jupyter, install it to get
**tab-completion of entity slugs** inside collection proxies
(see [Collections](concepts/collections.md)):

```bash
pip install ipython
```

```python
client.articles["med<TAB>"   # completes to known article slugs
```

## Development install

To work on the client or build the documentation locally, install the package in
editable mode together with the `docs` extra:

```bash
git clone https://github.com/wisefood/wisefood-client
cd wisefood-client
python -m venv .venv && source .venv/bin/activate
pip install -e ".[docs]"
```

Run the test suite with:

```bash
pytest
```

Build the docs with:

```bash
sphinx-build -W -b html docs docs/_build/html
```

See [Contributing](contributing.md) for the full workflow.

```{note}
Every example in this documentation reads credentials and base URLs from environment
variables (`WISEFOOD_API_URL`, `WISEFOOD_USERNAME`, `WISEFOOD_PASSWORD`, and for
machine-to-machine auth `WISEFOOD_CLIENT_ID` / `WISEFOOD_CLIENT_SECRET`) and uses
placeholder hosts such as `https://data.wisefood.example`. Never hard-code real
secrets. See [Authentication](authentication.md).
```
