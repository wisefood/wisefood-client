# Using WiseFood with AI Agents

The WiseFood client is a convenient backbone for AI and agentic workflows: its proxies
return plain dictionaries (`entity.dict()`), its search is one method call, and its
errors are typed. This page covers two integration points — guidance for **coding
agents** working in the repository, and a runtime **MCP server** that exposes the client
as tools an LLM can call.

## Coding agents and `AGENTS.md`

The repository ships an [`AGENTS.md`](https://github.com/wisefood/wisefood-client/blob/main/AGENTS.md)
at its root. It's a short, structured brief that tells AI coding assistants (Claude Code,
Cursor, and similar) how to work here: the two-client model, where entities and proxies
live, the build/test commands, and the project conventions (Field descriptors,
dirty-tracking auto-sync, env-var credentials, never committing secrets).

If you're building your own tools on top of the client, the entity dictionaries make it
trivial to expose capabilities to an LLM:

```python
def search_articles_tool(query: str) -> list[dict]:
    """Return the top article matches as plain dicts (LLM-friendly)."""
    return [a.dict() for a in client.articles.search(query, limit=5)]
```

## The WiseFood MCP server

A companion **[Model Context Protocol](https://modelcontextprotocol.io)** server exposes
the WiseFood clients as MCP tools, so an MCP-capable assistant can search the catalog,
fetch entities, and manage households directly.

```{note}
The MCP server is delivered as a companion component of this project. Once installed it
runs as a console command and is configured with the **same** `WISEFOOD_*` environment
variables used throughout this documentation.
```

### Configuration

The server reads its credentials and endpoints from the environment (machine-to-machine
credentials preferred):

```bash
export WISEFOOD_API_URL="https://data.wisefood.example"   # WiseFood Data API
export WISEFOOD_CORE_URL="https://api.wisefood.example"   # WiseFood API
export WISEFOOD_CLIENT_ID="my-service"
export WISEFOOD_CLIENT_SECRET="••••••••"
# (or WISEFOOD_USERNAME / WISEFOOD_PASSWORD for user credentials)
```

### Running it

```bash
wisefood-mcp
```

### Wiring it into an MCP client

Point your MCP-capable assistant at the command, passing the environment through. A
typical client configuration looks like:

```json
{
  "mcpServers": {
    "wisefood": {
      "command": "wisefood-mcp",
      "env": {
        "WISEFOOD_API_URL": "https://data.wisefood.example",
        "WISEFOOD_CORE_URL": "https://api.wisefood.example",
        "WISEFOOD_CLIENT_ID": "my-service",
        "WISEFOOD_CLIENT_SECRET": "••••••••"
      }
    }
  }
}
```

### Tool surface

Three groups. The first two are always available; the third is gated.

| group | tool | what it does |
|---|---|---|
| catalog | `search_catalog(kind, q, limit)` | search guides, guidelines, articles, textbooks, passages, food-composition tables or artifacts; hits come back trimmed to what identifies them |
| catalog | `get_entity(kind, identifier)` | one entity in full (long content bodies are truncated with their length) |
| catalog | `catalog_coverage(kind, country?, population_group?, language?)` | what the catalog already holds for a country / population / language — approximate, and says so |
| catalog | `list_organizations(q?)` | publishers, ministries and institutes the catalog knows |
| research | `research(query, max_results)` | web search via Groq's Compound system; returns findings with every URL visited and the snippets seen |
| research | `fetch_url(url, max_chars)` | a page as readable text with its title and licence links, or a PDF stored behind a handle with its page count and first-page text; honours `robots.txt` |
| research | `licence_evidence(url? \| doi? \| text?)` | quotes, `rel="license"` links and — for a DOI — Unpaywall and Crossref, plus a *proposed* value from the catalog's `LicenseId` enum with a confidence |
| write (gated) | `create_guide` · `create_textbook` · `create_article` · `upload_artifact` · `enqueue_guideline_extraction` · `import_guidelines` | every one takes a `proposal_id` and refuses unless a person has approved that proposal; a restrictive licence allows a pointer (title, URL, publisher) but not content; all of them also require `WISEFOOD_MCP_WRITES_ENABLED=true` |

Three rules the server enforces rather than asks for:

1. **The provider executes nothing but web search.** Every tool runs on our
   side; `research` is the one that reaches a model, and it is still our
   tool, recorded like the rest.
2. **Nothing writes to the catalog without an approved proposal**, and there
   is no tool that approves — that happens in the WiseFood console.
3. **Licence is evidence, not a verdict.** `licence_evidence` reports what it
   found and what that suggests; a person confirms.

Install with the extra and run as documented above:

```bash
pip install "wisefood[mcp]"
GROQ_API_KEY=… WISEFOOD_API_URL=… WISEFOOD_CLIENT_ID=… WISEFOOD_CLIENT_SECRET=… wisefood-mcp
```

The same tools are importable as a library — `from wisefood_mcp import
build_registry` gives OpenAI-style schemas for `bind_tools` and a dispatcher
for the model's calls — which is how the Source Integrator in FoodScholar
uses them.

