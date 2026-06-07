# Entities & Proxies

Almost everything you touch on the **WiseFood Data API** is an *entity proxy*: a thin, typed
Python object wrapping a single record's JSON. Understanding this one model unlocks every
resource — articles, guides, textbooks, FCTables, and artifacts all behave the same way.

```{note}
This page describes the **WiseFood Data API** object model (`DataClient`). The
**WiseFood API**
(`Client` → households/members) uses a simpler property-based model documented in
[Households & Members](../guides/households-and-members.md).
```

## What an entity is

Every WiseFood Data API record is represented by a subclass of `BaseEntity`. The raw JSON lives
in `entity.data`; the typed attributes you use are **descriptors** that read and write
keys in that dict.

```python
article = client.articles["some-article-slug"]

article.title          # -> reads entity.data["title"]
article.dict()         # -> the full underlying dict
article.json()         # -> pretty-prints the JSON payload
article.show()         # -> tabular view via pandas (transposed)
repr(article)          # -> <Article urn='...'>
```

## The `Field` descriptor

Attributes are declared on each entity class with `Field`, which maps an attribute name
to a key in `entity.data`:

```python
class Article(BaseEntity):
    title: str = Field("title", default="")
    keywords: list = Field("keywords", default_factory=list)
    id: str = Field("id", read_only=True)
```

- `default` / `default_factory` — value returned when the key is absent.
- `read_only=True` — assigning to the attribute raises `AttributeError`. System fields
  (`id`, `urn`, `creator`, `created_at`, `updated_at`, and often `type`) are read-only.

## Auto-sync on write

By default an entity has `sync=True`. **Assigning to a field immediately PATCHes the
change to the API:**

```python
article.title = "A clearer title"   # <-- sent to the server right away
```

Each write also records the key in `entity._dirty_fields`. To batch several edits into a
single request, disable auto-sync, make your changes, then save:

```python
article.sync = False
article.title = "New title"
article.description = "New description"
article.save(only_dirty=True)       # one PATCH with just the changed fields
```

`save()` never sends immutable fields (`IMMUTABLE_FIELDS`), so system-managed values are
preserved.

## Lazy loading

Some proxies hand you an entity that contains **only its identifier** (for example, a
sliced collection — see [Collections](collections.md)). The moment you read any field
other than the identifier, the proxy fetches the full record automatically:

```python
lazy = client.articles[0:50]        # 50 lazy proxies, no per-item API calls
first = lazy[0]
first.title                         # <-- triggers a fetch for just this entity
```

## CRUD operations

Through a collection proxy:

```python
# Create
art = client.articles.create(title="A new study", doi="10.1234/example")

# Read
art = client.articles["a-new-study"]

# Update (auto-sync, or batch with save())
art.status = "active"

# Refresh from server
art.refresh()

# Delete
art.delete()
```

## AI enhancement

Many entities support server-side enrichment by an AI agent. The call returns the
updated entity:

```python
# Via the collection proxy
enhanced = client.articles.enhance("summarizer", identifier="a-new-study")

# Or on a loaded entity
article.enhance_self(agent="summarizer")
```

## Inspection helpers

| Method | What it does |
|--------|--------------|
| `entity.dict()` | Returns the full underlying `data` dict. |
| `entity.json()` | Pretty-prints the JSON payload to stdout. |
| `entity.show()` | Prints a transposed pandas table of all fields. |
| `entity.identifier` | The value of the identifier field (`urn` or `id`). |
| `entity.urn` | The URN (raises if the entity has none). |

## Read-only / immutable fields

Every entity defines `IMMUTABLE_FIELDS`, which by default includes `urn`, `id`,
`creator`, `created_at`, and `updated_at`. Some entities extend it — e.g. guides and
textbooks also make `type` immutable. These are never sent on `save()` and assigning to a
`read_only` field raises `AttributeError`.
