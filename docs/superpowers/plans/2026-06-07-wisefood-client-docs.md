# WiseFood Client Documentation (Part A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build production-ready, exampleful Sphinx+MyST documentation for the `wisefood` client (buildable on Read the Docs), plus a reconstructed changelog and the modern-library repo extras (README/AGENTS.md/CONTRIBUTING.md).

**Architecture:** Sphinx with the MyST Markdown parser and the `furo` theme. Hand-written narrative pages (getting-started, concepts, per-resource guides) plus an autodoc/autosummary-generated API reference imported from the package's Google-style docstrings. Verification gate is a clean `sphinx-build -W` (warnings-as-errors) build that successfully imports `wisefood`, with `pytest` still green.

**Tech Stack:** Sphinx, myst-parser, furo, sphinx.ext.{autodoc,napoleon,autosummary,viewcode,intersphinx}, sphinx-copybutton, sphinx-design. Python 3.13 (RTD), package supports ≥3.8.

**Scope note:** This plan covers **Part A only** (docs + changelog + repo extras + the `__version__` fix). Part B (the MCP server) is a separate plan. The docs page `integrations/ai-agents.md` documents `AGENTS.md` now and references the MCP server as a forthcoming/companion feature so the docs build is self-contained without Part B.

**Execution convention:** All work happens on `main` (user requested commit to main). Commit after each task. The build/test commands are the "test" for documentation tasks.

---

## File Structure

Created/modified by this plan:

```
.readthedocs.yaml                 # MODIFY: uncomment python.install block
pyproject.toml                    # MODIFY: add [project.optional-dependencies] docs (no core change in Part A)
src/wisefood/__init__.py          # MODIFY: __version__ -> "0.0.22"
README.md                         # MODIFY: full rewrite with badges
AGENTS.md                         # CREATE
CONTRIBUTING.md                   # CREATE
CHANGELOG.md                      # CREATE (root, Keep a Changelog)
docs/
  requirements.txt                # CREATE
  conf.py                         # CREATE
  index.md                        # CREATE
  installation.md                 # CREATE
  quickstart.md                   # CREATE
  authentication.md               # CREATE
  concepts/
    entities-and-proxies.md       # CREATE
    collections.md                # CREATE
    identifiers-and-urns.md       # CREATE
    search.md                     # CREATE
    error-handling.md             # CREATE
  guides/
    articles.md                   # CREATE
    guides-and-guidelines.md      # CREATE
    textbooks.md                  # CREATE
    artifacts.md                  # CREATE
    fctables.md                   # CREATE
    households-and-members.md     # CREATE
  integrations/
    ai-agents.md                  # CREATE
  reference/
    api.md                        # CREATE
    low-level-http.md             # CREATE
  changelog.md                    # CREATE (includes root CHANGELOG.md via MyST include)
  contributing.md                 # CREATE (includes root CONTRIBUTING.md via MyST include)
```

---

## Task 1: Docs build scaffold (conf.py, requirements, RTD wiring)

**Files:**
- Create: `docs/requirements.txt`
- Create: `docs/conf.py`
- Create: `docs/index.md` (minimal placeholder toctree to make the first build pass)
- Modify: `.readthedocs.yaml`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create `docs/requirements.txt`**

```text
sphinx>=7.0
furo>=2024.1.29
myst-parser>=2.0
sphinx-copybutton>=0.5
sphinx-design>=0.5
# Install the package itself so autodoc can import `wisefood`.
-e ..
```

- [ ] **Step 2: Create `docs/conf.py`**

```python
"""Sphinx configuration for the WiseFood client documentation."""

import os
import sys
from datetime import date

# Make the package importable for autodoc (src/ layout).
sys.path.insert(0, os.path.abspath("../src"))

project = "wisefood-client"
author = "WiseFood"
copyright = f"{date.today().year}, WiseFood"

# Keep in sync with pyproject.toml / src/wisefood/__init__.py.
release = "0.0.22"
version = "0.0.22"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_design",
]

# MyST (Markdown) configuration.
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "linkify",
    "substitution",
]
myst_heading_anchors = 3

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}

autosummary_generate = True
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_typehints = "description"
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# Don't fail the build if optional third-party imports are missing at doc time.
autodoc_mock_imports = ["IPython"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
    "pandas": ("https://pandas.pydata.org/docs/", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "superpowers"]

html_theme = "furo"
html_title = "WiseFood Client"
html_static_path = ["_static"]
```

- [ ] **Step 3: Create a minimal `docs/index.md` so the first build succeeds**

```markdown
# WiseFood Client

```{toctree}
:hidden:
:maxdepth: 2
```

Placeholder — replaced in Task 9.
```

- [ ] **Step 4: Modify `.readthedocs.yaml` — uncomment the `python.install` block**

Replace the commented tail of the file:

```yaml
# Optionally, but recommended,
# declare the Python requirements required to build your documentation
# See https://docs.readthedocs.io/en/stable/guides/reproducible-builds.html
# python:
#    install:
#    - requirements: docs/requirements.txt
```

with:

```yaml
# Declare the Python requirements required to build the documentation.
# See https://docs.readthedocs.io/en/stable/guides/reproducible-builds.html
python:
  install:
    - requirements: docs/requirements.txt
```

- [ ] **Step 5: Modify `pyproject.toml` — add a docs optional-dependencies group**

After the `dependencies = [...]` line in `[project]`, add a new top-level table:

```toml
[project.optional-dependencies]
docs = [
    "sphinx>=7.0",
    "furo>=2024.1.29",
    "myst-parser>=2.0",
    "sphinx-copybutton>=0.5",
    "sphinx-design>=0.5",
]
```

- [ ] **Step 6: Install the docs toolchain and build**

Run:
```bash
cd /mnt/workspaces/wisefood/wisefood-client
python3 -m pip install -e ".[docs]"
sphinx-build -b html docs docs/_build/html
```
Expected: build finishes; `docs/_build/html/index.html` exists. (Not `-W` yet — placeholder pages come later.)

- [ ] **Step 7: Ignore the build output**

Append to `.gitignore` (only if not already present):
```text
docs/_build/
```

- [ ] **Step 8: Commit**

```bash
git add .readthedocs.yaml pyproject.toml docs/requirements.txt docs/conf.py docs/index.md .gitignore
git commit -m "docs: scaffold Sphinx + MyST + furo build"
```

---

## Task 2: Fix package version

**Files:**
- Modify: `src/wisefood/__init__.py`

- [ ] **Step 1: Update `__version__`**

Change line 7 of `src/wisefood/__init__.py` from:
```python
__version__ = "0.0.1"
```
to:
```python
__version__ = "0.0.22"
```

- [ ] **Step 2: Verify import still works and reports the new version**

Run:
```bash
python3 -c "import wisefood; print(wisefood.__version__)"
```
Expected: `0.0.22`

- [ ] **Step 3: Run the existing test suite to confirm no regression**

Run: `python3 -m pytest -q`
Expected: same pass/skip result as before this change (no new failures).

- [ ] **Step 4: Commit**

```bash
git add src/wisefood/__init__.py
git commit -m "chore: bump __version__ to 0.0.22 to match pyproject"
```

---

## Task 3: Reconstruct CHANGELOG.md

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Re-read git history to map commits to versions**

Run: `git log --oneline --no-merges`
Use the output to group commits into version sections. Known milestones from history:
0.0.3 (early release), 0.0.9 bump, M2M auth, two-client split (Data + Core),
articles/FCTables, artifact management + `download_to`, guides & guidelines,
guide `page[]`, textbook integration (toward 0.0.16), textbook structure bookmarks,
`page_count` on guides, Read the Docs config. Latest = 0.0.22.

- [ ] **Step 2: Write `CHANGELOG.md` (Keep a Changelog format, newest first)**

```markdown
# Changelog

All notable changes to the WiseFood client are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Read the Docs documentation site (Sphinx + MyST), reconstructed changelog, and
  modern-library project files (`README`, `AGENTS.md`, `CONTRIBUTING.md`).

## [0.0.22]

### Added
- `page_count` field on guides.
- Structured textbook bookmark constructors for the textbook structure tree
  (`add_root` / `add_chapter` / `add_section`).
- Read the Docs configuration (`.readthedocs.yaml`).

### Fixed
- Internal consistency fixes around guides and artifact handling.

## [0.0.16]

### Added
- Textbook integration: `Textbook`, `TextbookPassage`, the structure tree, and
  textbook-scoped passage browsing (`textbook.passages`, `passages.page[n]`,
  `bulk_replace`).
- Guide pages accessor (`guide.page[n]`) so guidelines can be fetched per page.

### Changed
- Guides and guidelines updated to match the latest catalog API.

## [0.0.9]

### Added
- Artifact management: upload, parent-bound artifacts, and `download_to` for saving
  files locally without caller boilerplate.
- Support for guides and guidelines.
- Article schema refinements and FCTables support.

### Changed
- Member profile aligns with the API: allergies treated as a top-level field.

## [0.0.3]

### Added
- Two separate clients for the WiseFood platform: the Data API (`DataClient`) and the
  Core API (`Client`).
- Machine-to-machine (client credentials) authentication.
- Household and member management on the Core API.
- Lazy loading of collection entities, search, and AI-enhancement capabilities.
- Base entity/collection proxy classes with IPython autocomplete support.
- Typed API exceptions mapped from the server error envelope.

[Unreleased]: https://github.com/wisefood/wisefood-client/compare/v0.0.22...HEAD
[0.0.22]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.22
[0.0.16]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.16
[0.0.9]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.9
[0.0.3]: https://github.com/wisefood/wisefood-client/releases/tag/v0.0.3
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: add reconstructed CHANGELOG"
```

---

## Task 4: Getting-started pages (installation, quickstart, authentication)

**Files:**
- Create: `docs/installation.md`
- Create: `docs/quickstart.md`
- Create: `docs/authentication.md`

- [ ] **Step 1: Write `docs/installation.md`**

Content requirements (write full prose + code blocks):
- `pip install wisefood`; requires Python ≥ 3.8 (docs build/CI uses 3.13).
- Core deps: `requests`, `pandas`. Note `pandas` powers `entity.show()`; IPython enables
  tab-completion in notebooks.
- Dev install: `pip install -e ".[docs]"` and where tests live (`pytest`).
- A `{note}` admonition that examples assume env vars (see Authentication).

- [ ] **Step 2: Write `docs/quickstart.md`**

A 5-minute end-to-end using the **DataClient**, env-var auth, placeholder host
`https://data.wisefood.example`. Must include, as runnable blocks:
```python
import os
from wisefood import DataClient, Credentials

creds = Credentials(
    username=os.environ["WISEFOOD_USERNAME"],
    password=os.environ["WISEFOOD_PASSWORD"],
)
client = DataClient(os.environ.get("WISEFOOD_API_URL", "https://data.wisefood.example"), creds)

# Fetch one article by slug or URN
article = client.articles["some-article-slug"]
print(article.title)

# Search
results = client.articles.search("mediterranean diet", limit=5)
for a in results:
    print(a.title)

# Browse a collection (lazy slice)
first_ten = client.articles[0:10]

# Download an artifact attached to an entity
for art in article.artifacts:
    art.download_to(f"./downloads/{art.title}")
```
Add a `{tip}` cross-link to Authentication and the per-resource guides.

- [ ] **Step 3: Write `docs/authentication.md`**

Cover, with code blocks:
- `Credentials`: user (`username`/`password`) vs machine-to-machine
  (`client_id`/`client_secret`); they are **mutually exclusive** (show the `ValueError`
  cases from `__post_init__`).
- The two clients and their base URLs: `DataClient` (Data API,
  `https://data.wisefood.example`) and `Client` (Core API,
  `https://api.wisefood.example`), both default `api_prefix="/api/v1"`.
- Token lifecycle: auto-authenticate on construction, bearer token with a safety margin,
  transparent refresh via `_ensure_token`. `client.ping()` to check status.
- Constructor knobs: `verify_tls`, `default_timeout`, `pool_connections`,
  `pool_maxsize`; built-in retry on `429/500/502/503/504`.
- Env-var pattern block:
```python
import os
from wisefood import DataClient, Client, Credentials

data = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(
        client_id=os.environ["WISEFOOD_CLIENT_ID"],
        client_secret=os.environ["WISEFOOD_CLIENT_SECRET"],
    ),
)
core = Client(
    os.environ["WISEFOOD_CORE_URL"],
    Credentials(
        username=os.environ["WISEFOOD_USERNAME"],
        password=os.environ["WISEFOOD_PASSWORD"],
    ),
)
```

- [ ] **Step 4: Build to verify the new pages render**

Run: `sphinx-build -b html docs docs/_build/html`
Expected: succeeds (pages may be "not in any toctree" — resolved in Task 9).

- [ ] **Step 5: Commit**

```bash
git add docs/installation.md docs/quickstart.md docs/authentication.md
git commit -m "docs: add installation, quickstart, and authentication pages"
```

---

## Task 5: Concept pages

**Files:**
- Create: `docs/concepts/entities-and-proxies.md`
- Create: `docs/concepts/collections.md`
- Create: `docs/concepts/identifiers-and-urns.md`
- Create: `docs/concepts/search.md`
- Create: `docs/concepts/error-handling.md`

- [ ] **Step 1: Write `docs/concepts/entities-and-proxies.md`**

Explain `BaseEntity` + the `Field` descriptor with examples:
- Fields are thin accessors over `entity.data`; `default` / `default_factory` /
  `read_only`.
- Dirty tracking via `_dirty_fields`; **auto-save on write when `sync=True`** (show
  `article.title = "..."` syncing immediately). Show `entity.sync = False` to batch.
- `save(only_dirty=True)`, `refresh()`, `delete()`, `create(...)`, `enhance(agent=...)`.
- Inspection helpers: `entity.json()`, `entity.dict()`, `entity.show()` (pandas),
  `repr`/`str`.
- IMMUTABLE_FIELDS (`urn`, `id`, `creator`, `created_at`, `updated_at`).

- [ ] **Step 2: Write `docs/concepts/collections.md`**

`BaseCollectionProxy` access patterns, each with a code block:
- `len(client.articles)`, iteration (one fetch per entity),
- `client.articles[0]` (by position), `client.articles[1:10]` (slice → **lazy**
  proxies via limit/offset; explain laziness), `client.articles["slug"]` /
  `["urn:article:..."]` / UUID lookups,
- `.slugs()` and IPython bracket tab-completion (`client.articles["pre<TAB>`).

- [ ] **Step 3: Write `docs/concepts/identifiers-and-urns.md`**

- URN-backed entities (`Article`, `Guide`, `Textbook`, `FCTable`) with `URN_PREFIX`
  (`urn:article:` etc.) vs UUID-backed (`Artifact`, `Guideline`, `TextbookPassage`,
  `IDENTIFIER_FIELD = "id"`).
- `normalize_identifier` / `build_identifier` behavior (prefix strip/add, slug from URN).
- When to pass a slug vs a full URN vs a UUID. Show `entity.urn` and `entity.identifier`.

- [ ] **Step 4: Write `docs/concepts/search.md`**

Document the shared `search()` signature with a parameter table and examples:
- `q`, `limit`, `offset`, `fq` (filter queries, list), `fl`/`fields` (field lists),
  `sort`, `facet_limit`, and highlighting (`highlight`, `highlight_fields`,
  `highlight_pre_tag`, `highlight_post_tag`).
- Example with filters + highlighting:
```python
hits = client.articles.search(
    "iron deficiency",
    fq=['open_access:true'],
    sort="citation_count desc",
    limit=10,
    highlight=True,
    highlight_fields=["abstract"],
)
```
- Note that results are entity proxies; cross-link to the resource-specific scoped
  searches (guidelines-by-guide, passages-by-textbook).

- [ ] **Step 5: Write `docs/concepts/error-handling.md`**

- The error envelope `{success:false, error:{title,detail,code}, help}`.
- `APIError` base + `.status_code`, `.code`, `.title`, `.detail`, `.errors`,
  `.help_url`, `.retryable`.
- A mapping table: server `code` → exception and HTTP status → exception (from
  `_CODE_TO_EXCEPTION` / `_STATUS_TO_EXCEPTION`): e.g. `resource/not_found` / 404 →
  `NotFoundError`, `auth/unauthorized` / 401 → `AuthenticationError`, `quota/rate_limited`
  / 429 → `RateLimitError`, etc.
- Example:
```python
from wisefood.exceptions import NotFoundError, RateLimitError

try:
    client.articles["does-not-exist"]
except NotFoundError as e:
    print(e.code, e.detail, e.help_url)
except RateLimitError as e:
    if e.retryable:
        ...  # back off and retry
```

- [ ] **Step 6: Build to verify**

Run: `sphinx-build -b html docs docs/_build/html`
Expected: succeeds.

- [ ] **Step 7: Commit**

```bash
git add docs/concepts
git commit -m "docs: add core concept pages (entities, collections, identifiers, search, errors)"
```

---

## Task 6: Resource guides — Data API (articles, guides, textbooks, artifacts, fctables)

**Files:**
- Create: `docs/guides/articles.md`
- Create: `docs/guides/guides-and-guidelines.md`
- Create: `docs/guides/textbooks.md`
- Create: `docs/guides/artifacts.md`
- Create: `docs/guides/fctables.md`

Each page follows the template: **What it is → Quick example → Field reference table →
CRUD walkthrough → Search → Resource-specific features → Gotchas.** Field tables come
from the entity classes (see source). Use env-var auth + placeholder hosts.

- [ ] **Step 1: Write `docs/guides/articles.md`**

- Entity: `Article`, `ENDPOINT="articles"`, `URN_PREFIX="urn:article:"`.
- Field table (key fields): `id` (ro), `title`, `description`, `status`, `type`,
  `keywords`, `topics`, `doi`, `url`, `abstract`, `content`, `authors`, `tags`,
  `ai_tags`, `publication_year`, `open_access`, `citation_count`, `key_takeaways`,
  `ai_key_takeaways`, `creator`/`created_at`/`updated_at` (ro), `extras`.
- CRUD: `client.articles.create(title=..., doi=...)`, edit + auto-sync, `save`, `delete`.
- Search example; `enhance(agent="...")` for AI enrichment.
- Gotchas: read-only system fields; `sync=False` for batching.

- [ ] **Step 2: Write `docs/guides/guides-and-guidelines.md`**

- `Guide` (`urn:guide:`) and `Guideline` (`id`-backed, `ENDPOINT="guidelines"`).
- Field tables for both (Guide: `title`, `short_title`, `issuing_authority`,
  `responsible_ministry`, `document_type`, `legal_status`, `target_audiences`,
  `evidence_basis`, `publication_year`, `page_count`, `identifiers`, …; `type` is
  read-only. Guideline: `guide_urn` (ro), `rule_text`, `sequence_no`, `page_no`,
  `action_type`, `target_populations`, `frequency`, `quantity`, `food_groups`,
  `source_refs`, …).
- Relationship navigation:
```python
guide = client.guides["national-dietary-guidelines-2023"]
for g in guide.guidelines:            # guide-scoped guidelines
    print(g.sequence_no, g.rule_text)

page_rules = guide.page[12]           # guidelines on page 12
guide.guidelines.search("sugar")      # scoped search
guide.guidelines.create(rule_text="...", page_no=3)
```
- Gotchas: `guide.guidelines` raises if a guideline doesn't belong to the guide; `type`
  immutable.

- [ ] **Step 3: Write `docs/guides/textbooks.md`** (the deep one)

- `Textbook` (`urn:textbook:`) and `TextbookPassage` (`id`-backed,
  `ENDPOINT="textbook-passages"`).
- Field tables (Textbook: `title`, `subtitle`, `authors`, `editors`, `publisher`,
  `edition`, `isbn10`, `isbn13`, `doi`, `topics`, `keywords`, `audience`,
  `review_status`, `visibility`, `applicability_status`, `publication_year`,
  `page_count`, `structure_tree`, …. Passage: `textbook_urn` (ro), `artifact_id` (ro),
  `page_no`, `sequence_no`, `text`, `char_start`, `char_end`, `structure_node_id` (ro),
  `structure_path` (ro), `extractor_name`, `extractor_run_id`).
- **Structure tree** — requires exactly one associated artifact; show:
```python
tb = client.textbooks["nutrition-science-3e"]
tree = tb.structure_tree
ch1 = tree.add_chapter(id="ch1", title="Macronutrients", page_start=1, page_end=40)
ch1.add_section(id="ch1-2", title="Proteins", page_start=12, page_end=25)
# Navigation:
tree.find("ch1-2")
tree["ch1"]            # by id
tree.ch1.proteins      # by attribute (slugified id/title)
tree.to_dict()
```
Explain auto-`artifact_id` resolution and the "exactly one artifact" requirement
(`_resolve_textbook_artifact_id`), and that edits auto-save when `sync=True`.
- **Passages**:
```python
tb.passages.search("glycemic index")
tb.page[37]                       # passages on page 37
tb.passages.bulk_replace(
    page_count=420,
    structure_tree=tree.to_dict(),
    passages=[{"page_no": 1, "sequence_no": 0, "text": "..."}],
)
```
- Gotchas: top-level `textbook_passages.search()` / listing is **not** supported — must
  be textbook-scoped (show the `NotImplementedError` guidance); passages belong to a
  single textbook.

- [ ] **Step 4: Write `docs/guides/artifacts.md`**

- `Artifact`: UUID-addressed (`IDENTIFIER_FIELD="id"`), bound to a `parent_urn`.
- Field table: `id`/`parent_urn`/`type` (ro), `title`, `description`, `file_url`,
  `file_s3_url`, `file_type`, `file_size`, `language`.
- Upload + download:
```python
art = client.artifacts.upload(
    "report.pdf",
    parent_urn="urn:guide:national-dietary-guidelines-2023",
    title="Source PDF",
)
client.artifacts.download_to(art.id, "./out/report.pdf")
art.download(stream=True)          # raw streamed requests.Response
```
- Parent-bound proxy:
```python
guide = client.guides["national-dietary-guidelines-2023"]
guide.artifacts.upload("appendix.pdf", title="Appendix")
for a in guide.artifacts:
    print(a.title, a.file_size)
```
- Gotchas: `save` always includes `file_type`; downloads stream to disk via
  `download_to`; artifact must belong to the parent.

- [ ] **Step 5: Write `docs/guides/fctables.md`**

- `FCTable` (`urn:fctable:`): food composition tables.
- Field table: `title`, `compiling_institution`, `database_name`,
  `classification_schemes`, `standardization_schemes`, `measurement_units`,
  `reference_portions`, `completeness_percent`, `nutrient_coverage`, `data_formats`,
  `tasks_supported`, `number_of_entries`, `min/max_nutrients_per_item`, …
- CRUD + search examples; attaching artifacts (source files) via `fctable.artifacts`.

- [ ] **Step 6: Build to verify**

Run: `sphinx-build -b html docs docs/_build/html`
Expected: succeeds.

- [ ] **Step 7: Commit**

```bash
git add docs/guides/articles.md docs/guides/guides-and-guidelines.md docs/guides/textbooks.md docs/guides/artifacts.md docs/guides/fctables.md
git commit -m "docs: add Data API resource guides"
```

---

## Task 7: Resource guide — Core API (households & members) + integrations page

**Files:**
- Create: `docs/guides/households-and-members.md`
- Create: `docs/integrations/ai-agents.md`

- [ ] **Step 1: Write `docs/guides/households-and-members.md`**

Uses the **`Client`** (Core API), not `DataClient`. Cover:
- `client.households.me()`, `.get(id)`, `.list(limit, offset)`, `.create(name, region,
  metadata, members)`, `.update(id, **fields)`, `.delete(id)`.
- `Household`: `name`/`region`/`metadata` setters auto-sync; `household.members`,
  `household.add_member(name, age_group, ...)`.
- `client.members`: `.get(id)`, `.list(household_id, ...)`, `.create(household_id, name,
  age_group, image_url)`, `.delete(id)`.
- `HouseholdMember`: `name`/`age_group`/`image_url` setters auto-sync; `member.profile`
  (auto-fetched) with auto-syncing `dietary_groups`, `allergies`,
  `nutritional_preferences`, `properties`.
- Worked example adapted from `examples/household_management.py` (env-var auth,
  placeholder host `https://api.wisefood.example`):
```python
import os
from wisefood import Client, Credentials

client = Client(
    os.environ["WISEFOOD_CORE_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)
household = client.households.me()
member = household.add_member(name="Alex", age_group="adult")
member.profile.dietary_groups = ["vegetarian", "gluten_free"]
member.profile.allergies = ["shellfish"]
```
- Include the **dietary-group catalog** (omnivore/vegetarian/vegan/keto/… list from the
  example) and the age-group options.
- Gotcha: auto-sync issues a PATCH per assignment — group related updates in a single
  dict assignment where it matters.

- [ ] **Step 2: Write `docs/integrations/ai-agents.md`**

Two sections:
- **AGENTS.md** — explain the repo ships an `AGENTS.md` for coding agents and summarize
  what it contains (link to it). Brief example of using the client to back an LLM tool:
```python
def search_articles_tool(query: str) -> list[dict]:
    return [a.dict() for a in client.articles.search(query, limit=5)]
```
- **MCP server** — describe the companion MCP server that exposes the WiseFood clients
  as MCP tools (run with `wisefood-mcp`, configured via the same `WISEFOOD_*` env vars),
  with a `{note}` that it is delivered as a separate component and a security note that
  write tools (create/enhance/upload, household/member writes) should be exposed to LLMs
  with care. (No code from Part B is required for this page to build.)

- [ ] **Step 3: Build to verify**

Run: `sphinx-build -b html docs docs/_build/html`
Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add docs/guides/households-and-members.md docs/integrations/ai-agents.md
git commit -m "docs: add households/members guide and AI-agents integration page"
```

---

## Task 8: API reference + low-level HTTP pages

**Files:**
- Create: `docs/reference/api.md`
- Create: `docs/reference/low-level-http.md`

- [ ] **Step 1: Write `docs/reference/api.md` (autodoc)**

```markdown
# API Reference

Auto-generated from the package docstrings.

## Clients

```{eval-rst}
.. automodule:: wisefood.client
   :members:
   :show-inheritance:

.. automodule:: wisefood.api_client
   :members:
   :show-inheritance:
```

## Entities & Proxies

```{eval-rst}
.. automodule:: wisefood.entities.base
   :members:
   :show-inheritance:

.. automodule:: wisefood.entities.articles
   :members:

.. automodule:: wisefood.entities.guides
   :members:

.. automodule:: wisefood.entities.textbooks
   :members:

.. automodule:: wisefood.entities.artifacts
   :members:

.. automodule:: wisefood.entities.fctables
   :members:

.. automodule:: wisefood.entities.households
   :members:
```

## Exceptions

```{eval-rst}
.. automodule:: wisefood.exceptions
   :members:
   :show-inheritance:
```
```

- [ ] **Step 2: Write `docs/reference/low-level-http.md`**

Document the low-level layer shared by both clients (with code blocks):
- `request(method, endpoint, *, auth, timeout, headers, params, **kwargs)` — bodies
  forbidden on GET/DELETE.
- Lowercase verbs: `get/post/put/patch/delete(endpoint, ...)`.
- Path-parts wrappers: `GET/POST/PUT/PATCH/DELETE(*parts, **params|**json)`:
```python
resp = client.GET("articles", "search", q="nutrition", limit=10)
resp = client.POST("articles", title="Study", doi="10.1234/example")
```
- `endpoint()`/`api_base` URL construction; when to drop to this layer vs. proxies.

- [ ] **Step 3: Build with autodoc and confirm modules import**

Run: `sphinx-build -b html docs docs/_build/html`
Expected: succeeds; reference page shows class/method signatures (confirms `wisefood`
imported cleanly — `IPython` is mocked in `conf.py`).

- [ ] **Step 4: Commit**

```bash
git add docs/reference/api.md docs/reference/low-level-http.md
git commit -m "docs: add autodoc API reference and low-level HTTP page"
```

---

## Task 9: Landing page, toctree wiring, changelog/contributing includes, strict build

**Files:**
- Modify: `docs/index.md`
- Create: `docs/changelog.md`
- Create: `docs/contributing.md`

- [ ] **Step 1: Replace `docs/index.md` with the real landing page + master toctree**

```markdown
# WiseFood Client

A small, robust Python client for accessing and populating the data infrastructure of
the **WiseFood** platform.

The package ships **two clients**:

| Client | Import | API | Resources |
|--------|--------|-----|-----------|
| `DataClient` | `from wisefood import DataClient` | Data / Catalog API | articles, artifacts, guides, guidelines, textbooks, textbook passages, FCTables |
| `Client` | `from wisefood import Client` | Core API | households, members, profiles |

Both authenticate the same way (user **or** machine-to-machine credentials) and share a
retrying, connection-pooled HTTP core.

```bash
pip install wisefood
```

```python
import os
from wisefood import DataClient, Credentials

client = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(username=os.environ["WISEFOOD_USERNAME"],
                password=os.environ["WISEFOOD_PASSWORD"]),
)
print(client.articles.search("mediterranean diet", limit=5))
```

```{toctree}
:caption: Getting Started
:maxdepth: 2

installation
quickstart
authentication
```

```{toctree}
:caption: Core Concepts
:maxdepth: 2

concepts/entities-and-proxies
concepts/collections
concepts/identifiers-and-urns
concepts/search
concepts/error-handling
```

```{toctree}
:caption: Resource Guides
:maxdepth: 2

guides/articles
guides/guides-and-guidelines
guides/textbooks
guides/artifacts
guides/fctables
guides/households-and-members
```

```{toctree}
:caption: Integrations
:maxdepth: 2

integrations/ai-agents
```

```{toctree}
:caption: Reference
:maxdepth: 2

reference/api
reference/low-level-http
changelog
contributing
```
```

- [ ] **Step 2: Create `docs/changelog.md` (include the root CHANGELOG)**

```markdown
# Changelog

```{include} ../CHANGELOG.md
:start-line: 1
```
```

- [ ] **Step 3: Create `docs/contributing.md` (include the root CONTRIBUTING)**

```markdown
# Contributing

```{include} ../CONTRIBUTING.md
:start-line: 1
```
```

(Task 11 creates `CONTRIBUTING.md`; if running tasks out of order, create it first.)

- [ ] **Step 4: Strict build — warnings are errors**

Run: `sphinx-build -W --keep-going -b html docs docs/_build/html`
Expected: **succeeds with zero warnings.** Fix any "document isn't included in any
toctree", broken cross-reference, or duplicate-label warnings before continuing.

- [ ] **Step 5: Commit**

```bash
git add docs/index.md docs/changelog.md docs/contributing.md
git commit -m "docs: wire toctree, landing page, changelog and contributing includes"
```

---

## Task 10: README rewrite with badges

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite `README.md`**

```markdown
# wisefood-client

[![PyPI version](https://img.shields.io/pypi/v/wisefood.svg)](https://pypi.org/project/wisefood/)
[![Python versions](https://img.shields.io/pypi/pyversions/wisefood.svg)](https://pypi.org/project/wisefood/)
[![Documentation Status](https://readthedocs.org/projects/wisefood-client/badge/?version=latest)](https://wisefood-client.readthedocs.io/en/latest/)
[![License](https://img.shields.io/badge/license-see%20LICENSE-blue.svg)](LICENSE)

A small, robust Python client for accessing and populating the data infrastructure of the
**WiseFood** platform.

It ships **two clients**:

- **`DataClient`** — the Data / Catalog API: articles, artifacts, guides, guidelines,
  textbooks, textbook passages, and food-composition tables (FCTables).
- **`Client`** — the Core API: households, members, and member profiles.

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

## Documentation

Full docs (concepts, per-resource guides, API reference) live at
**https://wisefood-client.readthedocs.io**.

- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Guidance for AI coding agents](AGENTS.md)

## License

See [LICENSE](LICENSE).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README with badges and quickstart"
```

---

## Task 11: AGENTS.md and CONTRIBUTING.md

**Files:**
- Create: `AGENTS.md`
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: Create `AGENTS.md`**

```markdown
# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`wisefood` is a Python client for the WiseFood platform. It exposes **two clients**:

- `wisefood.client.DataClient` — Data / Catalog API (articles, artifacts, guides,
  guidelines, textbooks, textbook passages, fctables).
- `wisefood.api_client.Client` — Core API (households, members, profiles).

Both are constructed with a `wisefood.Credentials` (user **or** machine-to-machine).

## Layout

- `src/wisefood/client.py` — `DataClient` + HTTP core.
- `src/wisefood/api_client.py` — `Client` (Core API) + HTTP core.
- `src/wisefood/entities/` — entity classes and collection proxies.
  - `base.py` — `BaseEntity`, the `Field` descriptor, `BaseCollectionProxy`.
  - `articles.py`, `guides.py`, `textbooks.py`, `artifacts.py`, `fctables.py`,
    `households.py`.
- `src/wisefood/exceptions.py` — `APIError` hierarchy + response-envelope mapping.
- `src/wisefood/autocomplete.py` — IPython tab-completion for collections.
- `tests/` — pytest suite. `docs/` — Sphinx + MyST documentation.

## Build & test

```bash
pip install -e ".[docs]"     # client + docs toolchain
pytest                       # run the test suite
sphinx-build -W -b html docs docs/_build/html   # build docs (warnings = errors)
```

## Conventions

- Entity attributes are declared with the `Field` descriptor over `entity.data`.
- Writes auto-save when `sync=True` (the default). Use `sync=False` to batch, then
  `save()`.
- System fields (`id`, `urn`, `creator`, `created_at`, `updated_at`, often `type`) are
  read-only.
- URN-backed entities use `URN_PREFIX`; some entities (artifacts, guidelines, passages)
  are UUID-backed (`IDENTIFIER_FIELD = "id"`).
- In examples and tests, read credentials/URLs from `WISEFOOD_*` environment variables.
  **Never commit real secrets.**
- Keep `src/wisefood/__init__.py` `__version__` in sync with `pyproject.toml`.
- Update `CHANGELOG.md` for user-visible changes.
```

- [ ] **Step 2: Create `CONTRIBUTING.md`**

```markdown
# Contributing

Thanks for contributing to the WiseFood client!

## Development setup

```bash
git clone https://github.com/wisefood/wisefood-client
cd wisefood-client
python -m venv .venv && source .venv/bin/activate
pip install -e ".[docs]"
```

## Running the tests

```bash
pytest
```

Tests live in `tests/`. Unit tests should not hit the network — mock the client. The
`test_*_live.py` scripts at the repo root are manual, credentialed smoke tests and are
**not** part of the automated suite.

## Building the docs

```bash
sphinx-build -W -b html docs docs/_build/html
open docs/_build/html/index.html
```

The build treats warnings as errors and imports the package for autodoc, so keep
docstrings valid.

## Conventions

- Follow the patterns in `AGENTS.md`.
- Keep `src/wisefood/__init__.py` `__version__` aligned with `pyproject.toml`.
- Add a `CHANGELOG.md` entry under `[Unreleased]` for user-visible changes.
- Examples and tests read credentials from `WISEFOOD_*` env vars; never commit secrets.

## Pull requests

- Keep changes focused; one logical change per PR.
- Ensure `pytest` and the docs build both pass before opening a PR.
```

- [ ] **Step 3: Build docs to confirm the changelog/contributing includes resolve**

Run: `sphinx-build -W --keep-going -b html docs docs/_build/html`
Expected: succeeds with zero warnings (now that `CONTRIBUTING.md` exists for the include
in `docs/contributing.md`).

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md CONTRIBUTING.md
git commit -m "docs: add AGENTS.md and CONTRIBUTING.md"
```

---

## Task 12: Final verification

- [ ] **Step 1: Clean strict docs build**

Run:
```bash
rm -rf docs/_build
sphinx-build -W --keep-going -b html docs docs/_build/html
```
Expected: exit 0, zero warnings, `docs/_build/html/index.html` present, sidebar shows all
sections, API reference shows real signatures.

- [ ] **Step 2: Test suite still green**

Run: `python3 -m pytest -q`
Expected: no new failures vs. baseline (Task 2).

- [ ] **Step 3: Confirm version consistency**

Run:
```bash
python3 -c "import wisefood; print(wisefood.__version__)"
grep '^version' pyproject.toml
```
Expected: both report `0.0.22`.

- [ ] **Step 4: Final commit (if anything outstanding)**

```bash
git status
git add -A && git commit -m "docs: finalize WiseFood client documentation" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage (Part A):**
- Sphinx+MyST+furo+extensions+requirements+RTD `python.install` → Task 1. ✓
- Env-var/placeholder examples → enforced in Tasks 2,4–7,10. ✓
- All §5 pages (index, installation, quickstart, authentication; 5 concepts; 6 guides;
  integrations/ai-agents; reference api + low-level-http; changelog; contributing) →
  Tasks 4–9. ✓
- Changelog reconstructed to 0.0.22 → Task 3 (+ docs include Task 9). ✓
- README with badges → Task 10. ✓
- AGENTS.md, CONTRIBUTING.md → Task 11. ✓
- `__version__` → 0.0.22 → Task 2. ✓
- AI-agents page references MCP server without depending on Part B code → Task 7. ✓

**Placeholder scan:** Pages whose full text is long are specified by explicit content
requirements + the exact source fields/methods to document and required code blocks;
all literal files (conf.py, CHANGELOG, README, AGENTS, CONTRIBUTING, index, reference,
includes) are given verbatim. No "TBD/handle edge cases" steps.

**Type/name consistency:** Method/field names used in guides match the source
(`download_to`, `bulk_replace`, `structure_tree.add_chapter`, `guide.page[n]`,
`households.me`, `profile.dietary_groups`, `enhance(agent=...)`). Env vars consistent:
`WISEFOOD_API_URL` (Data), `WISEFOOD_CORE_URL` (Core), `WISEFOOD_USERNAME/PASSWORD`,
`WISEFOOD_CLIENT_ID/SECRET`. Version `0.0.22` consistent across conf.py, Task 2, Task 12.
```
