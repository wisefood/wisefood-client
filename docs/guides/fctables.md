# Food Composition Tables (FCTables)

A **food composition table** (FCT) describes a dataset of foods and their nutrient
content — its provenance, coverage, units, and the schemes it follows. FCTables are
URN-backed (`urn:fctable:<slug>`) and reached through `client.fctables`.

## What it is

| | |
|---|---|
| Entity class | `FCTable` |
| Collection | `client.fctables` |
| Endpoint | `fctables` |
| Identifier | URN (`urn:fctable:<slug>`) |

## Quick example

```python
import os
from wisefood import DataClient, Credentials

client = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)

fct = client.fctables["national-fct-2020"]
print(fct.title, "·", fct.compiling_institution)
print(f"{fct.number_of_entries} entries, {fct.completeness_percent}% complete")
```

## Field reference

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | Read-only. |
| `title` | `str` | |
| `description` | `str` | |
| `status` | `str` | Defaults to `"active"`. |
| `type` | `str` | Defaults to `"food_composition_table"`. |
| `compiling_institution` | `str` | Who produced the table. |
| `database_name` | `str` | |
| `classification_schemes` | `list[str]` | e.g. food grouping schemes. |
| `standardization_schemes` | `list[str]` | |
| `measurement_units` | `list[str]` | |
| `reference_portions` | `list[str]` | |
| `completeness_percent` | `float` | |
| `completeness_description` | `str` | |
| `nutrient_coverage` | `list[str]` | Which nutrients are covered. |
| `data_formats` | `list[str]` | |
| `tasks_supported` | `list[str]` | |
| `number_of_entries` | `int` | |
| `min_nutrients_per_item` | `int` | |
| `max_nutrients_per_item` | `int` | |
| `url` / `license` / `external_id` | `str` | |
| `organization_urn` | `str` | |
| `abstract` / `category` / `content` / `venue` | `str` | |
| `authors` / `tags` | `list[str]` | |
| `language` / `region` | `str` | |
| `creator` / `created_at` / `updated_at` | `str` | Read-only. |

## CRUD walkthrough

```python
# Create
fct = client.fctables.create(
    title="National Food Composition Table 2020",
    compiling_institution="National Nutrition Institute",
    database_name="NFCT-2020",
    measurement_units=["g", "mg", "kcal"],
    number_of_entries=1850,
)

# Update — auto-syncs
fct.completeness_percent = 92.5
fct.nutrient_coverage = ["energy", "protein", "fat", "carbohydrate", "iron"]

# Batch
fct.sync = False
fct.classification_schemes = ["FoodEx2"]
fct.data_formats = ["csv", "json"]
fct.save(only_dirty=True)

# Delete
fct.delete()
```

## Search

```python
hits = client.fctables.search("micronutrients", limit=10)
for t in hits:
    print(t.title, "—", t.number_of_entries, "entries")
```

See [Search](../concepts/search.md) for all parameters.

## Attached files

The underlying dataset files (CSV, spreadsheets, source PDFs) are attached as artifacts:

```python
fct.artifacts.upload("nfct-2020.csv", title="Full dataset (CSV)")
for a in fct.artifacts:
    print(a.title, a.file_size)
```

See [Artifacts](artifacts.md).

## Gotchas

- `id`, `creator`, `created_at`, `updated_at` are read-only.
- List-typed fields (`measurement_units`, `nutrient_coverage`, …) default to empty lists;
  reassign the whole list to change them.
