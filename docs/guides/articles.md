# Articles

Articles are scientific publications and similar long-form sources in the WiseFood
catalog. They are URN-backed (`urn:article:<slug>`) and reached through
`client.articles`.

## What it is

| | |
|---|---|
| Entity class | `Article` |
| Collection | `client.articles` |
| Endpoint | `articles` |
| Identifier | URN (`urn:article:<slug>`) |

## Quick example

```python
import os
from wisefood import DataClient, Credentials

client = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)

article = client.articles["mediterranean-diet-review-2021"]
print(article.title)
print(article.doi, "·", article.publication_year)
for t in article.key_takeaways:
    print("-", t)
```

## Field reference

Commonly used fields (all are accessors over `entity.data`; read-only ones are managed by
the server):

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Read-only. |
| `title` | `str` | |
| `description` | `str` | |
| `status` | `str` | Defaults to `"active"`. |
| `type` | `str` | Defaults to `"article"`. |
| `keywords` | `list[str]` | |
| `topics` | `list[str]` | |
| `doi` | `str` | Digital Object Identifier. |
| `url` | `str` | |
| `external_id` | `str` | |
| `abstract` | `str` | |
| `content` | `str` | Full text, when available. |
| `venue` | `str` | Journal / conference. |
| `publication_year` | `int \| str` | |
| `open_access` | `bool` | |
| `citation_count` | `int` | |
| `reference_count` | `int` | |
| `influential_citation_count` | `int` | |
| `authors` | `list[str]` | |
| `tags` | `list[str]` | |
| `ai_tags` | `list[str]` | Machine-generated. |
| `language` | `str` | |
| `region` | `str` | |
| `key_takeaways` | `list[str]` | |
| `ai_key_takeaways` | `list[str]` | Machine-generated. |
| `license` | `str` | |
| `organization_urn` | `str` | |
| `creator` / `created_at` / `updated_at` | `str` | Read-only. |
| `extras` | `dict` | Free-form extra metadata. |

There are additional annotation/targeting fields (`reader_group`, `age_group`,
`population_group`, `geographic_context`, `biological_model`, `study_type`,
`hard_exclusion_flags`, `annotation_confidence`, `category`, `ai_category`,
`embedded_at`) — inspect any record with `article.show()` to see everything present.

## CRUD walkthrough

```python
# Create
article = client.articles.create(
    title="A randomized trial of the Mediterranean diet",
    doi="10.1234/example",
    authors=["A. Researcher", "B. Scientist"],
    publication_year=2021,
)

# Update — auto-syncs immediately (sync=True by default)
article.status = "active"
article.tags = ["cardiology", "nutrition"]

# Batch several edits into one request
article.sync = False
article.abstract = "We compared ..."
article.open_access = True
article.save(only_dirty=True)

# Reload from the server
article.refresh()

# Delete
article.delete()
```

## Search

```python
hits = client.articles.search(
    "mediterranean diet cardiovascular",
    fq=['open_access:true'],
    sort="citation_count desc",
    limit=10,
    highlight=True,
    highlight_fields=["abstract"],
)
for a in hits:
    print(a.citation_count, a.title)
```

See [Search](../concepts/search.md) for the full parameter list.

## AI enhancement

Ask a server-side agent to enrich an article (e.g. generate takeaways or tags). The
updated entity is returned:

```python
enhanced = client.articles.enhance("summarizer", identifier="a-randomized-trial-...")
print(enhanced.ai_key_takeaways)

# Or in place, on a loaded entity:
article.enhance_self(agent="summarizer")
```

## Attached files

Articles can carry artifacts (e.g. the source PDF):

```python
for art in article.artifacts:
    art.download_to(f"./downloads/{art.title}.pdf")
```

See [Artifacts](artifacts.md).

## Gotchas

- `id`, `creator`, `created_at`, `updated_at` are read-only — assigning raises
  `AttributeError`.
- With the default `sync=True`, **every** attribute assignment is a separate PATCH. Set
  `sync=False` and call `save(only_dirty=True)` to batch related edits.
- `keywords`, `topics`, `authors`, `tags` default to empty lists — reassign the whole
  list to change them.
