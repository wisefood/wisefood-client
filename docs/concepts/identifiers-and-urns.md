# Identifiers & URNs

WiseFood entities are addressed in one of two ways, and knowing which is which saves a
lot of confusion when fetching, linking, and filtering.

## Two kinds of identifiers

| Style | Identifier field | Looks like | Entities |
|-------|------------------|------------|----------|
| **URN-backed** | `urn` | `urn:article:some-slug` | `Article`, `Guide`, `Textbook`, `FCTable` |
| **UUID-backed** | `id` | `3f2c1a90-…` | `Artifact`, `Guideline`, `TextbookPassage` |

URN-backed entities declare a `URN_PREFIX` such as `urn:article:`, `urn:guide:`,
`urn:textbook:`, or `urn:fctable:`. UUID-backed entities set
`IDENTIFIER_FIELD = "id"` and are typically **bound to a parent** (an artifact belongs to
a `parent_urn`; a guideline to a `guide_urn`; a passage to a `textbook_urn`).

## Slugs vs. full URNs

For URN-backed resources you can use either the **slug** (the part after the prefix) or
the **full URN** — the client normalizes between them:

```python
client.guides["national-dietary-guidelines-2023"]            # slug
client.guides["urn:guide:national-dietary-guidelines-2023"]  # full URN — same entity
```

Two helpers (used internally, occasionally handy directly) do the conversion:

```python
from wisefood.entities.guides import Guide

Guide.normalize_identifier("urn:guide:national-dietary-guidelines-2023")
# -> "national-dietary-guidelines-2023"   (strips the prefix → slug)

Guide.build_identifier("national-dietary-guidelines-2023")
# -> "urn:guide:national-dietary-guidelines-2023"   (adds the prefix → full URN)
```

For UUID-backed resources there is no prefix; you pass the UUID as-is.

## Reading an entity's identifier

```python
article.identifier   # the value of the identifier field (urn or id)
article.urn          # the URN specifically (raises AttributeError if absent)
```

## Why it matters

- **Linking entities:** relationships are expressed by URN — e.g. an artifact's
  `parent_urn`, a guideline's `guide_urn`, a passage's `textbook_urn`.
- **Filtering in search:** filter queries (`fq`) reference URNs, e.g.
  `fq=['guide_urn:"urn:guide:national-dietary-guidelines-2023"']`
  (see [Search](search.md)).
- **Scoped collections:** `guide.guidelines`, `textbook.passages`, and
  `entity.artifacts` are bound to the parent's URN and will reject members that belong to
  a different parent.
