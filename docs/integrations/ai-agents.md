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
export WISEFOOD_API_URL="https://data.wisefood.example"   # Data API
export WISEFOOD_CORE_URL="https://api.wisefood.example"   # Core API
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

The server exposes read and write tools across both APIs — searching and fetching
articles, guides and guidelines, textbooks and passages, and FCTables on the Data API,
plus household and member management on the Core API.

```{warning}
**Exposing write tools to an LLM warrants care.** Create/update/enhance/upload and
household/member writes change real data. Run the server against a non-production
environment while iterating, scope its credentials to the minimum required permissions,
and review an agent's intended writes before enabling them in production.
```
