# Search

Every WiseFood Data API collection proxy exposes the same `search()` method. Learn it once and it
works for articles, guides, guidelines, textbooks, textbook passages, and FCTables.

```python
results = client.articles.search("mediterranean diet", limit=5)
for a in results:
    print(a.title)
```

`search()` returns a list of **entity proxies**, ready to read or edit like any other
entity (see [Entities & Proxies](entities-and-proxies.md)).

## Parameters

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `q` | `str` | — | The free-text query. |
| `limit` | `int` | `10` | Maximum number of results. |
| `offset` | `int` | `0` | Number of results to skip (paging). |
| `fq` | `list[str]` | `None` | **Filter queries** — exact constraints, ANDed together. |
| `fl` | `list[str]` | `None` | Field list to return (server-side projection). |
| `fields` | `list[str]` | `None` | Alternate field selection passed through to the API. |
| `sort` | `str` | `None` | Sort expression, e.g. `"citation_count desc"`. |
| `facet_limit` | `int` | `50` | Cap on facet values (only sent when changed). |
| `highlight` | `bool` | `False` | Enable snippet highlighting. |
| `highlight_fields` | `list[str]` | `None` | Fields to highlight in. |
| `highlight_pre_tag` | `str` | `"<em>"` | Markup inserted before a match. |
| `highlight_post_tag` | `str` | `"</em>"` | Markup inserted after a match. |

## Filter queries (`fq`)

Filter queries narrow results with exact, field-level constraints and are combined with
AND. They commonly reference URNs and booleans:

```python
hits = client.articles.search(
    "iron deficiency",
    fq=['open_access:true', 'language:en'],
    sort="citation_count desc",
    limit=10,
)
```

## Highlighting

Ask the server to wrap matches so you can render snippets:

```python
hits = client.articles.search(
    "glycemic index",
    highlight=True,
    highlight_fields=["abstract"],
    highlight_pre_tag="<mark>",
    highlight_post_tag="</mark>",
)
```

## Scoped searches

Some relationships have their **own** search that is automatically constrained to a
parent. These have the same signature but are reached through the parent:

```python
# Guidelines within a single guide
guide = client.guides["national-dietary-guidelines-2023"]
guide.guidelines.search("sugar")

# Passages within a single textbook
textbook = client.textbooks["nutrition-science-3e"]
textbook.passages.search("glycemic index")
```

```{warning}
Textbook passages have **no** top-level search or listing — they only exist in the
context of a textbook. Calling `client.textbook_passages.search(...)` raises
`NotImplementedError`; use `textbook.passages.search(...)` or
`client.textbook_passages.by_textbook(urn).search(...)` instead. See
[Textbooks](../guides/textbooks.md).
```
