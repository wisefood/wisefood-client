# WiseFood Client — Documentation, Changelog & MCP Server (Design)

- **Date:** 2026-06-07
- **Author:** dpetrou (with Claude)
- **Status:** Draft — awaiting review
- **Scope:** Production-ready documentation for the `wisefood` client, a reconstructed
  changelog, modern-library repo extras (README/AGENTS.md/CONTRIBUTING.md), and a
  minimal MCP server exposing the client as LLM tools.

---

## 1. Goals

1. Author **detailed, exampleful, intuitive** documentation for the `wisefood` Python
   client, buildable on Read the Docs (the repo already has `.readthedocs.yaml`
   pointing at Sphinx).
2. Provide a **production-ready changelog** reconstructed from git history.
3. Add the **conventions every modern library has**: a real README with badges,
   `AGENTS.md` for coding agents, `CONTRIBUTING.md`, discoverable changelog.
4. Ship a **minimal MCP server** that exposes the client as tools an LLM/agent can call.

## 2. Non-Goals

- No redesign of the client's public API. Documentation describes the API **as it is**.
  The only code change to the client itself is fixing `__version__` (see §8).
- No new resource types or endpoints.
- The MCP server is intentionally a **first cut**: thin tool wrappers over the existing
  clients, not a full agentic framework.

## 3. Background — what we are documenting

The package ships **two distinct clients** (this duality is the spine of the docs):

| Client | Module | API | Resources (proxies) | Object model |
|--------|--------|-----|---------------------|--------------|
| `DataClient` | `wisefood.client` | Data / Catalog API | `articles`, `artifacts`, `guides`, `guidelines`, `textbooks`, `textbook_passages`, `fctables` | `BaseEntity` + `Field` descriptors, lazy loading, dirty-tracking auto-sync, URN/UUID addressing, search, AI `enhance` |
| `Client` | `wisefood.api_client` | Core API | `households`, `members` (+ member `profile`) | Plain property-based classes (`Household`, `HouseholdMember`, `HouseholdMemberProfile`) |

Both share: `Credentials` (user **or** machine-to-machine, mutually exclusive),
bearer-token auth with auto-refresh + safety margin, connection pooling with retry on
`429/5xx`, clean endpoint joining, and a `requests`-based low-level layer
(`request()`, `get/post/put/patch/delete`, and the `GET/POST/PUT/PATCH/DELETE`
path-parts wrappers).

Key cross-cutting mechanics worth dedicated concept pages:

- **`Field` descriptor** (`entities/base.py`): maps attributes to `data` keys, supports
  `default`/`default_factory`/`read_only`, marks `_dirty_fields`, and **auto-saves on
  write when `sync=True`**. Reading a non-identifier field on a lazy entity triggers
  `refresh()`.
- **`BaseCollectionProxy`**: indexing (`proxy[0]`), slicing (`proxy[1:10]`, returns
  **lazy** proxies via limit/offset), string lookup (`proxy["slug"]` / full URN / UUID),
  iteration, `len()`, `slugs()` and IPython key-completion (`autocomplete.py`).
- **Identifiers/URNs**: URN-backed entities (`urn:article:…`, `urn:guide:…`,
  `urn:textbook:…`, `urn:fctable:…`) vs UUID-backed (`Artifact`, `Guideline`,
  `TextbookPassage` use `IDENTIFIER_FIELD = "id"`). `normalize_identifier` /
  `build_identifier` handle prefixing and slug extraction.
- **Search**: shared `search(q, fl, limit, offset, fq, sort, fields, facet_limit,
  highlight, highlight_fields, highlight_pre_tag, highlight_post_tag)` returning entity
  proxies; specialized overrides for guide-scoped guidelines and textbook-scoped passages.
- **Errors** (`exceptions.py`): `APIError` base + typed subclasses, dual mapping
  (server `code` → exception, then HTTP status → exception), `.retryable`, FastAPI-style
  validation-detail flattening, and the `{success, error:{title,detail,code}, help}`
  envelope.
- **Resource-specific richness**:
  - *Guides*: `guide.guidelines` (guide-scoped proxy with `by_guide` endpoint + scoped
    search), `guide.page[n]` / `by_page(n)`.
  - *Textbooks*: the **structure tree** (`structure_tree.add_root/add_chapter/
    add_section`, `add_root`/`set_root`, attribute & key navigation, `find`),
    `textbook.passages` (textbook-scoped), `passages.page[n]`, and
    `passages.bulk_replace(...)`.
  - *Artifacts*: UUID-addressed, bound to a `parent_urn`; `upload`,
    `download`/`download_to`, parent-bound proxy via `entity.artifacts`.
  - *Households/Members*: `households.me()`, CRUD, member `profile` with auto-syncing
    dietary groups / allergies / nutritional preferences / properties.

## 4. Toolchain decisions (confirmed)

- **Sphinx + MyST-Parser** — pages written in Markdown (`.md`), matching the existing
  `sphinx: configuration: docs/conf.py` in `.readthedocs.yaml`.
- **Theme:** `furo` (modern, responsive, dark-mode, well-suited to API docs).
- **Extensions:** `myst_parser`, `sphinx.ext.autodoc`, `sphinx.ext.napoleon`
  (docstrings are Google-style), `sphinx.ext.autosummary`, `sphinx.ext.viewcode`,
  `sphinx.ext.intersphinx` (cross-link `requests` & `pandas`), `sphinx_copybutton`,
  `sphinx_design`.
- **Both prose + autodoc:** hand-written narrative/tutorial pages **and** an
  autogenerated API reference from docstrings.
- **Examples:** read `WISEFOOD_API_URL` / `WISEFOOD_USERNAME` / `WISEFOOD_PASSWORD`
  (and `WISEFOOD_CLIENT_ID` / `WISEFOOD_CLIENT_SECRET` for M2M) from env; use
  placeholder hosts like `https://data.wisefood.example`. No real secrets.
- **Reproducible builds:** add `docs/requirements.txt` and **uncomment the
  `python.install` block** in `.readthedocs.yaml` so RTD installs the package (required
  for autodoc to import `wisefood`) plus the docs requirements.

## 5. Documentation structure (`docs/`)

```
docs/
  conf.py
  requirements.txt
  index.md
  installation.md
  quickstart.md
  authentication.md
  concepts/
    entities-and-proxies.md
    collections.md
    identifiers-and-urns.md
    search.md
    error-handling.md
  guides/
    articles.md
    guides-and-guidelines.md
    textbooks.md
    artifacts.md
    fctables.md
    households-and-members.md
  integrations/
    ai-agents.md          # AGENTS.md + the MCP server
  reference/
    api.md                # autosummary/autodoc over all modules
    low-level-http.md
  changelog.md            # include/symlink of root CHANGELOG content
  contributing.md
```

**Per-resource guide template** (consistent across all `guides/*`):
*What it is → Quick example → Field reference table → CRUD walkthrough → Search →
Resource-specific features → Gotchas.*

**Landing page (`index.md`)** covers: what the client is, the two-client model
(table from §3), install one-liner, a short quickstart, and the `toctree`.

## 6. Changelog

- File: **`CHANGELOG.md`** at the repo root, **Keep a Changelog** format, newest first,
  reconstructed from `git log` and mapped onto releases up to **0.0.22**.
- Grouped by version with `Added / Changed / Fixed` sections derived from commit
  messages (e.g. M2M auth, two-client split, articles/FCTables, artifact management +
  `download_to`, guides & guidelines, guide `page[]`, textbook integration & structure
  bookmarks, `page_count`, RTD config).
- Surfaced in docs via `docs/changelog.md` and linked from the README.

## 7. Modern-library repo extras

- **README.md** — replace the 2-line stub with: badges (PyPI version, Python versions,
  Read the Docs, license), one-paragraph pitch, install, a quickstart for **each**
  client, the two-client table, and links to docs / changelog / contributing.
- **AGENTS.md** (repo root) — guidance for coding agents: repo layout, the two-client
  model, where entities/proxies live, build/test commands (`Makefile`, `pytest`),
  doc-build command, conventions (Field descriptors, dirty-tracking, env-var auth in
  examples), and "don't commit secrets."
- **CONTRIBUTING.md** — dev install, running `tests/`, building docs locally,
  changelog discipline, versioning note.

## 8. Client code change (minimal, in-scope)

- **`src/wisefood/__init__.py`**: `__version__` is currently `"0.0.1"` while
  `pyproject.toml` is `0.0.22`. Update `__version__` → `"0.0.22"` so docs (autodoc/
  `release`) and package metadata agree. No other behavioral change.

## 9. Part B — Minimal MCP server

A first-cut [Model Context Protocol](https://modelcontextprotocol.io) server exposing
the WiseFood clients as tools an LLM/agent can call.

### 9.1 Placement & packaging
- New package: **`src/wisefood/mcp/`**
  - `__init__.py`
  - `server.py` — server construction, tool registration, `main()` entry point.
  - `tools.py` (optional split) — tool definitions/handlers grouped by resource.
- **`mcp` added as a core dependency** in `pyproject.toml` `dependencies`.
- Console entry point: `wisefood-mcp = "wisefood.mcp.server:main"` under
  `[project.scripts]`.
- Transport: **stdio** (the standard MCP transport for local agent integration).

### 9.2 Authentication
- **Env vars, M2M preferred.** At startup the server reads:
  - `WISEFOOD_API_URL` (Data API base), `WISEFOOD_CORE_URL` (Core API base; may default
    to the same host/prefix if unset).
  - `WISEFOOD_CLIENT_ID` + `WISEFOOD_CLIENT_SECRET` (preferred), else
    `WISEFOOD_USERNAME` + `WISEFOOD_PASSWORD`.
- Builds one `DataClient` and one `Client` once at startup; reuses them across calls.
  Missing/invalid config → clear startup error.

### 9.3 Tools (first cut — **both** Data + Core)

Data API (via `DataClient`):
- `search_articles`, `get_article`, `create_article`, `enhance_article`
- `search_guides`, `get_guide`, `get_guide_guidelines` (incl. by-page)
- `search_guidelines`
- `search_textbooks`, `get_textbook`, `get_textbook_structure`,
  `search_textbook_passages`, `get_textbook_page`
- `search_fctables`, `get_fctable`
- `list_artifacts`, `get_artifact` (download returns metadata + URL, not raw bytes over
  MCP)

Core API (via `Client`):
- `get_my_household`, `get_household`, `list_households`, `create_household`
- `get_member`, `list_members`, `create_member`, `get_member_profile`,
  `update_member_profile`

Each tool: JSON-schema input (typed args), returns the entity's `dict()` / serialized
result, and maps `APIError` to a clean MCP error message. Write tools are included per
the "Everything" decision; the docs page will note that exposing write tools to an LLM
warrants caution.

### 9.4 Tests
- `tests/test_mcp.py`: assert the expected tool set is registered, and that dispatching
  a representative tool calls the underlying client method with the right arguments
  (clients mocked — no network).

### 9.5 Docs integration
- `docs/integrations/ai-agents.md` documents **both** `AGENTS.md` (for coding agents in
  the repo) and the **MCP server** (install/run, env-var config, the tool catalog, an
  example MCP client config snippet, and security notes on write tools).

## 10. Testing & verification

- **Docs build:** `sphinx-build -W -b html docs docs/_build/html` must succeed with no
  warnings-as-errors (autodoc imports `wisefood`).
- **Existing tests** continue to pass (`pytest`). MCP server adds `tests/test_mcp.py`.
- **Links/examples:** code blocks reviewed for accuracy against the real API surface;
  examples use env vars + placeholder hosts.

## 11. Risks / open considerations

- **Autodoc import:** RTD must install the package; handled by uncommenting
  `python.install` and listing the package in `docs/requirements.txt` (`-e ..` or the
  built package).
- **`mcp` as a core dependency** increases the base install footprint for users who only
  want the client. Accepted per decision; revisit as an optional extra later if needed.
- **MCP write tools via LLM**: flagged in docs; no extra guardrails beyond the API's own
  auth/permission model in this first cut.
- **`Client` Core API base URL**: example/`api_client` defaults differ from the Data
  API; the auth page and MCP config will make the two base URLs explicit.

## 12. Deliverables checklist

- [ ] `docs/conf.py`, `docs/requirements.txt`, all pages in §5
- [ ] `.readthedocs.yaml` `python.install` block uncommented
- [ ] `CHANGELOG.md` (root) + `docs/changelog.md`
- [ ] `README.md` rewrite with badges
- [ ] `AGENTS.md`, `CONTRIBUTING.md`
- [ ] `src/wisefood/__init__.py` `__version__ = "0.0.22"`
- [ ] `src/wisefood/mcp/` server + `[project.scripts]` + `mcp` dependency
- [ ] `tests/test_mcp.py`
- [ ] Local docs build passes; `pytest` passes
```
