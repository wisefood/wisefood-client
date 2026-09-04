# wisefood-client

[![PyPI version](https://img.shields.io/pypi/v/wisefood.svg)](https://pypi.org/project/wisefood/)
[![Python versions](https://img.shields.io/pypi/pyversions/wisefood.svg)](https://pypi.org/project/wisefood/)
[![Documentation Status](https://readthedocs.org/projects/wisefood-client/badge/?version=latest)](https://wisefood-client.readthedocs.io/en/latest/)
[![License](https://img.shields.io/badge/license-see%20LICENSE-blue.svg)](LICENSE)

A small, robust Python client for accessing and populating the data infrastructure of the
**WiseFood** platform.

The WiseFood platform exposes **two distinct APIs**, and this package ships **one client
for each**:

- **`DataClient`** — the **WiseFood Data API**: articles, artifacts, guides, guidelines,
  textbooks, textbook passages, and food-composition tables (FCTables).
- **`Client`** — the **WiseFood API**: households, members, and member profiles.

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

## Usage telemetry

The client reports which SDK operations you call, whether they succeeded and how
long they took, so platform usage reports account for scripts and notebooks and
not only the web app. It never sends your arguments, your results, or anything
you passed in.

```python
client.analytics.track("feature.used", app="catalog", feature="bulk-import")
client.feedback.submit(target_type="article", target_id=urn, rating="up",
                       comment="the extraction looks right")
print(client.analytics.session_id)   # groups everything this client did
```

Turn it off with the environment variable or the constructor:

```bash
export WISEFOOD_TELEMETRY=0
```

```python
client = Client(url, credentials, telemetry=False)
```

It is queued and sent on a background thread, so it never blocks or raises into
your code, and it switches itself off against a deployment whose gateway does
not accept it. `client.analytics.flush()` sends what is queued and keeps going;
`close()` stops it, and runs automatically at exit.

## Documentation

Full docs (concepts, per-resource guides, API reference) live at
**https://wisefood-client.readthedocs.io**.

- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Guidance for AI coding agents](AGENTS.md)

## License

See [LICENSE](LICENSE).
