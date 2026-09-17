"""One tool definition, every consumer.

A tool is a plain function whose first parameter is the :class:`ToolContext`
and whose remaining parameters are typed keyword arguments. From that single
definition the registry produces:

* an OpenAI-style function schema, which is what Groq's tool-calling models
  (and APISIX's ``ai-proxy-multi`` route) consume via ``bind_tools``;
* a dispatcher that validates the model's arguments, injects the context, runs
  the tool, and hands back something JSON-serialisable — including a
  structured error the model can read and recover from, because an exception
  that escapes here ends the whole run over a typo in one argument;
* a context-free callable with the original signature minus ``ctx``, which is
  what FastMCP introspects when the same tools are served over MCP.

Keeping the schema derived rather than hand-written is the point: a tool
whose documentation and whose contract can drift apart will.
"""
from __future__ import annotations

import functools
import inspect
import json
import logging
import time
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, get_args, get_origin

from pydantic import BaseModel, ValidationError, create_model

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """A failure the model should be told about rather than crashed by."""

    code = "tool_error"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.detail = detail

    def to_result(self) -> Dict[str, Any]:
        return {"error": {"code": self.code, "message": str(self), **self.detail}}


class ApprovalRequired(ToolError):
    """A write was attempted on a proposal nobody has approved."""

    code = "approval_required"


class WritesDisabled(ToolError):
    """Writes are wired but this deployment has them switched off."""

    code = "writes_disabled"


@dataclass
class ToolContext:
    """Everything a tool may need, supplied by whoever hosts the registry.

    The agent in FoodScholar and the standalone ``wisefood-mcp`` process fill
    this in differently — an in-process store versus an HTTP one, a shared
    Groq pool versus a fresh client — and the tools cannot tell which.
    """

    data_client: Any = None
    """A ``wisefood.DataClient``. Read tools need it; write tools need it too."""
    groq_client: Any = None
    """A ``groq.Groq``. Only ``research`` uses it, and only for Compound."""
    proposal_store: Any = None
    """Implements :class:`wisefood_mcp.stores.ProposalStore`."""
    core_post: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None
    """POST to the core API (extraction, import). The host decides transport."""
    core_get: Optional[Callable[[str], Dict[str, Any]]] = None
    """GET from the core API — job status while an extraction runs."""
    writes_enabled: bool = False
    """Phase 1 ships with this False. Every write tool checks it."""
    research_model: str = "groq/compound"
    inference_model: Optional[str] = None
    """Model for reading rules out of a source. Falls back to the research
    model; a deployment usually wants a plain tool-calling model here, since
    Compound's value is its web search and inference does not search."""
    actor: Optional[str] = None
    """Who is driving — a Keycloak ``sub``. Recorded on everything created."""
    contact_email: Optional[str] = None
    """Unpaywall asks for one. Ours, not a user's."""
    recorder: Optional[Callable[[Dict[str, Any]], None]] = None
    """Called with an audit record after every tool call, if set."""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., Any]
    args_model: type[BaseModel]
    write: bool = False
    """Marks tools that change the catalog. Listed separately, gated in code."""


def _json_type(annotation: Any) -> Dict[str, Any]:
    """A JSON-schema fragment for the argument types tools actually use."""
    origin = get_origin(annotation)
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is dict or origin is dict:
        return {"type": "object"}
    if origin in (list, List):
        (inner,) = get_args(annotation) or (str,)
        return {"type": "array", "items": _json_type(inner)}
    if origin is typing.Union:
        members = [a for a in get_args(annotation) if a is not type(None)]
        if len(members) == 1:
            return _json_type(members[0])
        return {"anyOf": [_json_type(m) for m in members]}
    if origin is typing.Literal:
        return {"type": "string", "enum": list(get_args(annotation))}
    return {"type": "string"}


def _args_model(fn: Callable[..., Any]) -> type[BaseModel]:
    """A pydantic model of the tool's arguments, minus the context."""
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    fields: Dict[str, Any] = {}
    for name, param in list(sig.parameters.items())[1:]:  # skip ctx
        annotation = hints.get(name, str)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)
    return create_model(f"{fn.__name__}_args", **fields)  # type: ignore[call-overload]


def _openai_schema(spec: ToolSpec) -> Dict[str, Any]:
    sig = inspect.signature(spec.fn)
    hints = typing.get_type_hints(spec.fn)
    properties: Dict[str, Any] = {}
    required: List[str] = []
    doc_lines = {}
    # ``:param name: text`` lines in the docstring become argument descriptions.
    for line in (spec.fn.__doc__ or "").splitlines():
        line = line.strip()
        if line.startswith(":param "):
            key, _, text = line[7:].partition(":")
            doc_lines[key.strip()] = text.strip()
    for name, param in list(sig.parameters.items())[1:]:
        prop = _json_type(hints.get(name, str))
        if name in doc_lines:
            prop["description"] = doc_lines[name]
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)
    summary = (spec.fn.__doc__ or spec.description).strip().split("\n\n")[0].strip()
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description or summary,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


class ToolRegistry:
    """The tools, and the one place they are called from."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, fn: Callable[..., Any], *, name: Optional[str] = None,
                 description: Optional[str] = None, write: bool = False) -> ToolSpec:
        spec = ToolSpec(
            name=name or fn.__name__,
            description=(description or (fn.__doc__ or "").strip().split("\n")[0]),
            fn=fn,
            args_model=_args_model(fn),
            write=write,
        )
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} registered twice")
        self._tools[spec.name] = spec
        return spec

    def tool(self, *, name: Optional[str] = None, description: Optional[str] = None,
             write: bool = False):
        def decorate(fn):
            self.register(fn, name=name, description=description, write=write)
            return fn
        return decorate

    # ---------------------------------------------------------------- views --
    def names(self) -> List[str]:
        return list(self._tools)

    def specs(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"no tool named {name!r}", known=self.names()) from None

    def openai_schemas(self, *, include_writes: bool = True) -> List[Dict[str, Any]]:
        """What ``bind_tools`` wants. Writes can be left out of a model's view
        entirely — a model that cannot see a tool cannot try it."""
        return [
            _openai_schema(s) for s in self._tools.values()
            if include_writes or not s.write
        ]

    def mcp_callable(self, spec: ToolSpec, ctx: ToolContext) -> Callable[..., Any]:
        """The tool with ``ctx`` already bound, keeping its signature so FastMCP
        can introspect it."""
        # The tool modules use ``from __future__ import annotations``, so the
        # signature's annotations are strings ("Dict[str, Any]") that an MCP
        # host's pydantic introspection cannot resolve outside their module.
        # Rebuild every parameter with the real type, resolved here.
        hints = typing.get_type_hints(spec.fn)
        sig = inspect.signature(spec.fn)
        params = [
            p.replace(annotation=hints.get(p.name, p.annotation))
            for p in list(sig.parameters.values())[1:]
        ]
        outer = sig.replace(parameters=params,
                            return_annotation=hints.get("return", Dict[str, Any]))

        @functools.wraps(spec.fn)
        def bound(**kwargs: Any) -> Any:
            return self.call(spec.name, kwargs, ctx)

        bound.__signature__ = outer  # type: ignore[attr-defined]
        bound.__annotations__ = {p.name: p.annotation for p in params}
        bound.__annotations__["return"] = outer.return_annotation
        return bound

    # ------------------------------------------------------------- dispatch --
    def call(self, name: str, args: Any, ctx: ToolContext) -> Dict[str, Any]:
        """Run one tool the way a model asked for it.

        Never raises for a tool's own failure: the model gets a structured
        error and can decide what to do, which is the difference between an
        agent that recovers from a 404 and one that dies on it. Host failures
        — a missing client — still surface as errors in the result, because
        they are also something the run should say out loud.
        """
        started = time.perf_counter()
        spec = None
        try:
            spec = self.get(name)
            if isinstance(args, str):
                args = json.loads(args or "{}")
            parsed = spec.args_model(**(args or {}))
            result = spec.fn(ctx, **parsed.model_dump())
            outcome = {"ok": True, "result": result}
        except ValidationError as exc:
            outcome = {"ok": False, **ToolError(
                "arguments did not match the tool's contract",
                problems=json.loads(exc.json()),
            ).to_result()}
        except ToolError as exc:
            outcome = {"ok": False, **exc.to_result()}
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.warning("tool %s failed", name, exc_info=True)
            outcome = {"ok": False, **ToolError(
                f"{type(exc).__name__}: {exc}"[:500]).to_result()}

        record = {
            "tool": name,
            "write": bool(spec and spec.write),
            "arguments": args if isinstance(args, dict) else {"raw": str(args)[:2000]},
            "ok": outcome["ok"],
            "error": outcome.get("error"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "actor": ctx.actor,
        }
        if ctx.recorder is not None:
            try:
                ctx.recorder({**record, "result": outcome.get("result")})
            except Exception:  # noqa: BLE001 — auditing must not break the tool
                logger.warning("tool recorder failed for %s", name, exc_info=True)
        return outcome


def build_registry() -> ToolRegistry:
    """The full WiseFood tool surface, registered in a stable order."""
    from wisefood_mcp.tools import catalog, research, writes

    registry = ToolRegistry()
    catalog.register(registry)
    research.register(registry)
    writes.register(registry)
    return registry
