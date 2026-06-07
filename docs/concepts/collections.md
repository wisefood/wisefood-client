# Collections

Each WiseFood Data API resource is exposed on the client as a **collection proxy** —
`client.articles`, `client.guides`, `client.textbooks`, `client.fctables`, and so on.
A collection proxy behaves like a smart, lazily-loaded Python container.

All collection proxies subclass `BaseCollectionProxy`, so they share the access patterns
below.

## Length and iteration

```python
len(client.articles)            # number of entities in the first index page

for article in client.articles: # one API fetch per entity
    print(article.title)
```

```{note}
`len()` and iteration are backed by an initial **index page** (default 100 identifiers).
They reflect that page, not necessarily the entire remote collection. For large datasets,
prefer [search](search.md) or explicit slicing with `limit`/`offset`.
```

## Access by position

```python
first = client.articles[0]      # entity at index 0 (from the cached index page)
```

## Slicing → lazy proxies

A slice is translated into a `limit`/`offset` request and returns **lazy** proxies. No
per-entity data is fetched until you read a field:

```python
page = client.articles[0:10]    # one list request; 10 lazy proxies
page = client.articles[20:40]   # offset=20, limit=20

for a in page:
    print(a.title)              # each access fetches that single entity
```

Constraints (they raise rather than silently doing the wrong thing):

- Open-ended slices (`client.articles[10:]`) are **not** supported — always give a stop.
- Steps other than 1 (`client.articles[0:10:2]`) are **not** supported.

## Access by identifier

Strings are resolved as a slug, a full URN, or a UUID, depending on the resource:

```python
client.articles["some-article-slug"]          # slug for a URN-backed resource
client.articles["urn:article:some-slug"]       # full URN
client.artifacts["3f2c…-uuid"]                 # UUID for an ID-backed resource
```

If the identifier is already in the cached index it is reused; otherwise the proxy
fetches it directly from the API. See
[Identifiers & URNs](identifiers-and-urns.md) for how slugs, URNs, and UUIDs relate.

## Explicit `get` with optional laziness

```python
art = client.articles.get("some-article-slug")              # fetch now
art = client.articles.get("some-article-slug", lazy=True)   # defer until first field access
```

## Tab-completion in IPython / Jupyter

Collection proxies expose `slugs()` and integrate with IPython's completion protocol, so
you can tab-complete known identifiers inside brackets:

```python
client.articles.slugs()         # list of completion-friendly identifiers

# In IPython/Jupyter:
client.articles["med<TAB>"      # completes to matching article slugs
```

This requires IPython to be installed (see [Installation](../installation.md)).
