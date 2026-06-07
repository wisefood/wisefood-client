# wisefood-client

[![PyPI version](https://img.shields.io/pypi/v/wisefood.svg)](https://pypi.org/project/wisefood/)
[![Python versions](https://img.shields.io/pypi/pyversions/wisefood.svg)](https://pypi.org/project/wisefood/)
[![Documentation Status](https://readthedocs.org/projects/wisefood-client/badge/?version=latest)](https://wisefood-client.readthedocs.io/en/latest/)
[![License](https://img.shields.io/badge/license-see%20LICENSE-blue.svg)](LICENSE)

A small, robust Python client for accessing and populating the data infrastructure of the
**WiseFood** platform.

It ships **two clients**:

- **`DataClient`** — the Data / Catalog API: articles, artifacts, guides, guidelines,
  textbooks, textbook passages, and food-composition tables (FCTables).
- **`Client`** — the Core API: households, members, and member profiles.

## Install

```bash
pip install wisefood
```

## Quickstart

```python
import os
from wisefood import DataClient, Credentials

client = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)

article = client.articles["some-article-slug"]
print(article.title)

for hit in client.articles.search("mediterranean diet", limit=5):
    print(hit.title)
```

Machine-to-machine auth uses `client_id` / `client_secret` instead of username/password.

## Documentation

Full docs (concepts, per-resource guides, API reference) live at
**https://wisefood-client.readthedocs.io**.

- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Guidance for AI coding agents](AGENTS.md)

## License

See [LICENSE](LICENSE).
