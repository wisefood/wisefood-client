# Textbooks

A **textbook** is a long structured document. Alongside its metadata it carries a
**structure tree** (its table of contents — chapters, sections) and a set of
**passages** (the extracted text, addressable by page). Textbooks are URN-backed;
passages are UUID-backed and always belong to a textbook.

## What they are

| | Textbook | TextbookPassage |
|---|----------|-----------------|
| Entity class | `Textbook` | `TextbookPassage` |
| Collection | `client.textbooks` | `client.textbook_passages` |
| Endpoint | `textbooks` | `textbook-passages` |
| Identifier | URN (`urn:textbook:<slug>`) | UUID (`id`) |
| Belongs to | — | a textbook (`textbook_urn`) |

```{important}
Structure-tree and passage operations require the textbook to have **exactly one**
associated artifact (the source file). With zero or several artifacts, those operations
raise a `ValueError` telling you so.
```

## Quick example

```python
import os
from wisefood import DataClient, Credentials

client = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)

tb = client.textbooks["nutrition-science-3e"]
print(tb.title, "·", tb.publisher, tb.edition)

for passage in tb.page[37]:        # passages on page 37
    print(passage.sequence_no, passage.text[:80])
```

## Field reference — `Textbook`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Read-only. |
| `title` / `subtitle` | `str` | |
| `description` | `str` | |
| `status` | `str` | Defaults to `"draft"`. |
| `type` | `str` | `"textbook"`, **immutable**. |
| `tags` / `topics` / `keywords` | `list[str]` | |
| `authors` / `editors` | `list[str]` | |
| `publisher` / `edition` | `str` | |
| `isbn10` / `isbn13` / `doi` | `str` | |
| `url` / `license` / `language` | `str` | |
| `audience` / `region` | `str` | |
| `review_status` | `str` | Defaults to `"unreviewed"`. |
| `visibility` | `str` | Defaults to `"internal"`. |
| `applicability_status` | `str` | Defaults to `"unknown"`. |
| `applicability_start_date` / `applicability_end_date` | `str` | |
| `publication_date` / `publication_year` | `str` / `int` | |
| `page_count` | `int` | |
| `structure_tree` | tree helper | See below. |
| `organization_urn` | `str` | |
| `creator` / `created_at` / `updated_at` | `str` | Read-only. |

## Field reference — `TextbookPassage`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Read-only. |
| `textbook_urn` | `str` | Read-only. |
| `artifact_id` | `str` | Read-only. |
| `page_no` / `sequence_no` | `int` | |
| `text` | `str` | The passage text. |
| `char_start` / `char_end` | `int` | Offsets within the page/document. |
| `structure_node_id` | `str` | Read-only — the tree node this passage sits under. |
| `structure_path` | `list[str]` | Read-only — path from the root. |
| `extractor_name` / `extractor_run_id` | `str` | Provenance of the extraction. |
| `creator` / `created_at` / `updated_at` | `str` | Read-only. |

## The structure tree

`textbook.structure_tree` is a live helper for building and navigating the table of
contents. Constructing nodes automatically fills in the textbook's single `artifact_id`,
and (with `sync=True`) each change is saved back to the API.

### Building it

```python
tb = client.textbooks["nutrition-science-3e"]
tree = tb.structure_tree

# Add a top-level chapter
ch1 = tree.add_chapter(id="ch1", title="Macronutrients", page_start=1, page_end=40)

# Nest sections under it
ch1.add_section(id="ch1-1", title="Carbohydrates", page_start=1, page_end=11)
ch1.add_section(id="ch1-2", title="Proteins", page_start=12, page_end=25)

# add_root / set_root let you control roots explicitly (set_root clears first)
root = tree.set_root(id="book", title="Nutrition Science", kind="book", page_start=1)
root.add_chapter(id="ch1", title="Macronutrients", page_start=1, page_end=40)
```

`add_child(...)` is the general form; `add_chapter` / `add_section` are convenience
wrappers that set `kind` for you.

### Navigating it

```python
tree.find("ch1-2")        # depth-first search by node id → node or None
tree["ch1"]               # subscript by id (raises KeyError if missing)
tree.ch1                  # attribute access by slugified id/title
tree.ch1.proteins         # drill down by attribute
node.children             # list of child nodes
node.title, node.kind, node.page_start, node.page_end
tree.to_dict()            # plain dict snapshot of the whole tree
```

### Replacing it wholesale

```python
tb.structure_tree = {
    "roots": [
        {"id": "ch1", "title": "Macronutrients", "kind": "chapter",
         "page_start": 1, "page_end": 40, "children": []},
    ]
}
```

## Passages

`textbook.passages` is a **textbook-scoped** collection (it queries
`textbook-passages/by-textbook/<urn>`).

```python
tb.passages.search("glycemic index")     # scoped full-text search
tb.passages.by_page(37)                   # all passages on page 37
tb.page[37]                               # same thing, index syntax
tb.passages["<passage-uuid>"]             # direct lookup, validated against this textbook
```

### Bulk replace

Replace a textbook's passages (and optionally its structure tree and page count) in one
call — useful right after a fresh extraction:

```python
tb.passages.bulk_replace(
    page_count=420,
    structure_tree=tb.structure_tree.to_dict(),
    passages=[
        {"page_no": 1, "sequence_no": 0, "text": "Chapter 1. Macronutrients ..."},
        {"page_no": 1, "sequence_no": 1, "text": "Carbohydrates are ..."},
    ],
    extractor_name="pdf-extractor",
    extractor_run_id="run-2024-001",
)
```

The `artifact_id` is resolved from the textbook automatically when the proxy is bound to
a loaded textbook; pass it explicitly otherwise.

## Gotchas

- **No top-level passage browsing.** `client.textbook_passages.search(...)` and listing
  raise `NotImplementedError` — passages only exist within a textbook. Use
  `tb.passages...` or `client.textbook_passages.by_textbook(urn)`.
- Structure/passage operations need **exactly one** associated artifact; otherwise you
  get a clear `ValueError`.
- `type` is immutable; `textbook_urn`, `artifact_id`, `structure_node_id`, and
  `structure_path` on passages are read-only.
- `by_page(n)` requires `n >= 1`.
