"""``wisefood-mcp`` — the tools over the Model Context Protocol.

The process the client docs have described since before it existed. Reads
its configuration from the environment exactly as documented there, builds a
:class:`~wisefood_mcp.registry.ToolContext`, and serves every tool in the
registry. Writes are served too but stay gated: the approval check still
applies, and ``WISEFOOD_MCP_WRITES_ENABLED`` must be set for them to run.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from wisefood_mcp.registry import ToolContext, build_registry
from wisefood_mcp.stores import InMemoryProposalStore

logger = logging.getLogger("wisefood_mcp")


def _bool(name: str, default: bool = False) -> bool:
    return (os.environ.get(name) or str(default)).strip().lower() in ("1", "true", "yes")


def context_from_env() -> ToolContext:
    """The documented environment, turned into a tool context.

    Missing pieces disable the tools that need them rather than failing at
    startup: a host that only wants to search the catalog should not need a
    Groq key, and one that only wants research should not need catalog
    credentials.
    """
    data_client = None
    api_url = os.environ.get("WISEFOOD_API_URL")
    if api_url:
        try:
            from wisefood.client import Credentials, DataClient

            creds = Credentials(
                username=os.environ.get("WISEFOOD_USERNAME"),
                password=os.environ.get("WISEFOOD_PASSWORD"),
                client_id=os.environ.get("WISEFOOD_CLIENT_ID"),
                client_secret=os.environ.get("WISEFOOD_CLIENT_SECRET"),
            )
            data_client = DataClient(base_url=api_url, credentials=creds)
        except Exception:  # noqa: BLE001
            logger.warning("catalog client not configured", exc_info=True)

    groq_client = None
    if os.environ.get("GROQ_API_KEY"):
        try:
            from groq import Groq

            groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
        except Exception:  # noqa: BLE001
            logger.warning("Groq client not configured", exc_info=True)

    core_url = os.environ.get("WISEFOOD_CORE_URL")
    core_post = _core_poster(core_url, data_client) if core_url and data_client is not None else None

    return ToolContext(
        data_client=data_client,
        groq_client=groq_client,
        proposal_store=InMemoryProposalStore(),
        core_post=core_post,
        writes_enabled=_bool("WISEFOOD_MCP_WRITES_ENABLED", False),
        research_model=os.environ.get("WISEFOOD_MCP_RESEARCH_MODEL", "groq/compound"),
        actor=os.environ.get("WISEFOOD_CLIENT_ID") or os.environ.get("WISEFOOD_USERNAME"),
        contact_email=os.environ.get("WISEFOOD_MCP_CONTACT_EMAIL"),
    )


def _core_poster(core_url: str, data_client: Any):
    """POST to the core API with the catalog client's bearer token."""
    import httpx

    def core_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        token = getattr(data_client, "token", None) or getattr(data_client, "_token", None)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = httpx.post(core_url.rstrip("/") + path, json=body, headers=headers, timeout=60.0)
        r.raise_for_status()
        return r.json()

    return core_post


def build_server(ctx: ToolContext | None = None):
    """An MCP server (SDK 2.x) with every registry tool attached.

    ``mcp`` 2.x renamed ``FastMCP`` to ``MCPServer``; the extra pins ``>=2``
    so a host on the 1.x line gets a clear install-time refusal rather than
    an import error at first use.
    """
    from mcp.server.mcpserver import MCPServer

    ctx = ctx or context_from_env()
    registry = build_registry()
    server = MCPServer(name="wisefood", instructions=(
        "Tools over the WiseFood data catalog and source research. Read tools "
        "are open; write tools require an approved proposal and are disabled "
        "unless the host enables them. The provider executes only web search."
    ))
    for spec in registry.specs():
        server.add_tool(registry.mcp_callable(spec, ctx), name=spec.name,
                        description=spec.description)
    return server


def main() -> None:
    logging.basicConfig(level=os.environ.get("WISEFOOD_MCP_LOG_LEVEL", "INFO"))
    build_server().run("stdio")


if __name__ == "__main__":
    main()
