# Guides & Guidelines

A **guide** is a dietary-guidance document (e.g. a national dietary guideline). Each
guide contains many **guidelines** — the individual, structured rules extracted from it.
Guides are URN-backed; guidelines are UUID-backed and always belong to a guide.

## What they are

| | Guide | Guideline |
|---|-------|-----------|
| Entity class | `Guide` | `Guideline` |
| Collection | `client.guides` | `client.guidelines` |
| Endpoint | `guides` | `guidelines` |
| Identifier | URN (`urn:guide:<slug>`) | UUID (`id`) |
| Belongs to | — | a guide (`guide_urn`) |

## Quick example

```python
import os
from wisefood import DataClient, Credentials

client = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)

guide = client.guides["national-dietary-guidelines-2023"]
print(guide.title, "·", guide.issuing_authority)

for rule in guide.guidelines:
    print(rule.sequence_no, rule.rule_text)
```

## Field reference — `Guide`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Read-only. |
| `title` / `short_title` | `str` | |
| `description` | `str` | |
| `status` | `str` | Defaults to `"active"`. |
| `type` | `str` | `"guide"`, **read-only/immutable**. |
| `tags` | `list[str]` | |
| `url` / `license` / `language` | `str` | |
| `region` | `str` | |
| `organization_urn` | `str` | |
| `content` | `str` | |
| `topic` / `audience` | `str` | |
| `issuing_authority` | `str` | |
| `responsible_ministry` | `str` | |
| `document_type` / `legal_status` | `str` | |
| `target_audiences` | `list[str]` | |
| `graphical_model` | `str` | |
| `evidence_basis` | `str` | |
| `notes` | `str` | |
| `review_status` / `verifier_user_id` | `str` | |
| `visibility` | `str` | |
| `applicability_status` / `applicability_start_date` / `applicability_end_date` | `str` | |
| `publication_date` / `publication_year` | `str` / `int` | |
| `page_count` | `int` | |
| `identifiers` | `list[dict]` | External identifiers. |
| `revision` | `dict` | |
| `creator` / `created_at` / `updated_at` | `str` | Read-only. |

## Field reference — `Guideline`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Read-only. |
| `guide_urn` | `str` | Read-only — the owning guide. |
| `guide_region` | `str` | Read-only. |
| `title` | `str` | |
| `rule_text` | `str` | The rule itself. |
| `sequence_no` | `int` | Order within the guide. |
| `page_no` | `int` | Source page. |
| `action_type` | `str` | |
| `target_populations` | `list` | |
| `frequency` | `Any` | |
| `quantity` | `dict` | |
| `food_groups` | `list` | |
| `source_refs` | `list[dict]` | |
| `notes` | `str` | |
| `status` / `review_status` / `visibility` | `str` | |
| `applicability_*` | `str` | |
| `creator` / `created_at` / `updated_at` | `str` | Read-only. |

## CRUD walkthrough

```python
# Create a guide
guide = client.guides.create(
    title="National Dietary Guidelines 2023",
    issuing_authority="Ministry of Health",
    region="GR",
)

# Edit (auto-syncs)
guide.audience = "general public"

# Add a guideline to this guide (scoped — guide_urn is set for you)
rule = guide.guidelines.create(
    rule_text="Eat at least 400 g of fruit and vegetables per day.",
    sequence_no=1,
    page_no=12,
)

# Delete
rule.delete()
guide.delete()
```

## Navigating a guide's guidelines

`guide.guidelines` is a **guide-scoped** collection (it queries the
`guidelines/by-guide/<urn>` endpoint and rejects guidelines from other guides):

```python
for rule in guide.guidelines:            # iterate the guide's rules
    print(rule.sequence_no, rule.rule_text)

guide.guidelines.search("sugar")          # scoped full-text search
guide.guidelines["<guideline-uuid>"]      # direct lookup, validated against this guide
```

### Guidelines by page

Two equivalent ways to get every guideline on a given source page:

```python
page_12 = guide.page[12]                  # convenient index syntax
page_12 = guide.guidelines.by_page(12)    # explicit method
```

## Search

The top-level `client.guidelines.search(...)` and `client.guides.search(...)` work like
any other resource ([Search](../concepts/search.md)). For rules within a single guide,
prefer the scoped `guide.guidelines.search(...)` shown above.

## Gotchas

- A guide's `type` is **immutable** (`urn`, `id`, timestamps, and `creator` are too).
- `guide.guidelines[...]` raises `KeyError` if the guideline belongs to a different
  guide.
- `guide.page[n]` and `by_page(n)` require a non-negative integer page number.
