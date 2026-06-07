# Quickstart

This page gets you from zero to reading and searching real data in about five minutes,
using the **`DataClient`** (the WiseFood Data API).

## 1. Set your credentials

The client never hard-codes secrets. Export them as environment variables first:

```bash
export WISEFOOD_API_URL="https://data.wisefood.example"
export WISEFOOD_USERNAME="you@example.org"
export WISEFOOD_PASSWORD="••••••••"
```

(For machine-to-machine credentials, see [Authentication](authentication.md).)

## 2. Create a client

```python
import os
from wisefood import DataClient, Credentials

creds = Credentials(
    username=os.environ["WISEFOOD_USERNAME"],
    password=os.environ["WISEFOOD_PASSWORD"],
)
client = DataClient(
    os.environ.get("WISEFOOD_API_URL", "https://data.wisefood.example"),
    creds,
)
```

The client authenticates immediately on construction and refreshes its token
automatically as needed — you never manage tokens by hand.

## 3. Fetch a single entity

Collections are indexable by slug or full URN:

```python
article = client.articles["some-article-slug"]
print(article.title)
print(article.doi, article.publication_year)
```

## 4. Search

Every WiseFood Data API resource shares the same search interface
(see [Search](concepts/search.md)):

```python
results = client.articles.search("mediterranean diet", limit=5)
for a in results:
    print(a.title)
```

## 5. Browse a collection

Slicing returns **lazy** proxies — entities are only fetched from the API when you
actually read a field (see [Collections](concepts/collections.md)):

```python
first_ten = client.articles[0:10]   # lazy: no per-item fetch yet
print(len(client.articles))         # total known in the first index page
for a in first_ten:
    print(a.title)                  # each access fetches that entity
```

## 6. Download an attached file

Entities can carry **artifacts** (PDFs, datasets, …). Stream one straight to disk:

```python
for art in article.artifacts:
    art.download_to(f"./downloads/{art.title}")
```

## Next steps

```{tip}
- Learn how authentication and the two clients work in [Authentication](authentication.md).
- Understand the entity/proxy model in [Entities & Proxies](concepts/entities-and-proxies.md).
- Dive into a specific resource under **Resource Guides**, e.g.
  [Articles](guides/articles.md) or [Textbooks](guides/textbooks.md).
```
