"""wisefood-mcp — the WiseFood catalog and research tools, as tools.

The companion component `docs/integrations/ai-agents.md` has described for a
while and nobody had written. One implementation, two ways in:

* **As a library.** The Source Integrator agent in FoodScholar imports the
  :class:`~wisefood_mcp.registry.ToolRegistry`, hands its OpenAI-style tool
  schemas to a tool-calling model, and dispatches the model's calls through
  :meth:`~wisefood_mcp.registry.ToolRegistry.call`.
* **As a process.** ``wisefood-mcp`` on the command line serves the same
  registry over the Model Context Protocol, so Claude Desktop, an IDE, or any
  MCP host gets the identical surface.

Three rules the package exists to enforce, stated once here and again where
each is implemented:

1. **The provider executes nothing but web search.** Every tool here runs on
   our side. The one that reaches a model — ``research`` — asks Groq's
   Compound system to search, then parses what it did; it is still our tool,
   recorded like the rest.
2. **Nothing writes to the catalog without an approved proposal.** The write
   tools take a ``proposal_id`` and refuse unless a person has approved it.
   There is no tool that approves.
3. **Licence is evidence, not a verdict.** ``licence_evidence`` returns what
   it found and what that suggests; a person confirms.
"""

from wisefood_mcp.registry import ToolContext, ToolRegistry, build_registry

__all__ = ["ToolContext", "ToolRegistry", "build_registry"]
__version__ = "0.1.0"
