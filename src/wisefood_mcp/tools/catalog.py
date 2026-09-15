"""Reading the catalog. Always available, never gated.

These wrap ``wisefood.DataClient`` and hand back plain dicts trimmed to what a
model can use — a whole entity with every enrichment field attached is
thousands of tokens of which the assistant reads the title.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from wisefood_mcp.registry import ToolContext, ToolError, ToolRegistry

#: Catalog kinds → the DataClient proxy that serves them. Recipe collections
#: have no proxy in the client yet (see the plan, Phase 5).
PROXIES = {
    "guide": "guides",
    "guideline": "guidelines",
    "article": "articles",
    "textbook": "textbooks",
    "textbook_passage": "textbook_passages",
    "fctable": "fctables",
    "artifact": "artifacts",
}

#: What a search hit is reduced to. Enough to recognise, cite and decide.
SUMMARY_FIELDS = (
    "urn", "id", "title", "short_title", "description", "url", "license",
    "language", "region", "country", "audience", "publisher", "organization_urn",
    "publication_date", "status", "review_status", "tags", "topics",
)


def _proxy(ctx: ToolContext, kind: str):
    if ctx.data_client is None:
        raise ToolError("no catalog client is configured")
    name = PROXIES.get(kind)
    if not name:
        raise ToolError(f"unknown catalog kind {kind!r}", known=sorted(PROXIES))
    proxy = getattr(ctx.data_client, name, None)
    if proxy is None:
        raise ToolError(f"the catalog client has no {name!r} proxy")
    return proxy


def _summarise(entity: Any, fields: tuple = SUMMARY_FIELDS) -> Dict[str, Any]:
    data = entity.dict() if hasattr(entity, "dict") else dict(entity)
    return {k: data[k] for k in fields if k in data and data[k] not in (None, "", [], {})}


def search_catalog(ctx: ToolContext, kind: str, q: str, limit: int = 10) -> Dict[str, Any]:
    """Search the catalog for entities of one kind.

    :param kind: guide | guideline | article | textbook | textbook_passage | fctable | artifact
    :param q: free-text query; titles, descriptions and content are searched
    :param limit: how many hits to return, at most 50
    """
    proxy = _proxy(ctx, kind)
    limit = max(1, min(int(limit), 50))
    hits = proxy.search(q, limit=limit)
    items = [_summarise(h) for h in hits]
    return {"kind": kind, "query": q, "count": len(items), "items": items}


def get_entity(ctx: ToolContext, kind: str, identifier: str) -> Dict[str, Any]:
    """Fetch one catalog entity in full.

    :param kind: guide | guideline | article | textbook | textbook_passage | fctable | artifact
    :param identifier: the entity's urn or id
    """
    proxy = _proxy(ctx, kind)
    entity = proxy.get(identifier)
    data = entity.dict() if hasattr(entity, "dict") else dict(entity)
    # Content bodies can run to megabytes; a model asked to *decide* about an
    # entity needs to know it has content, not read all of it.
    for key in ("content", "text", "body"):
        value = data.get(key)
        if isinstance(value, str) and len(value) > 4000:
            data[key] = value[:4000] + f"… [{len(value)} chars]"
    return data


def catalog_coverage(ctx: ToolContext, kind: str, country: Optional[str] = None,
                     population_group: Optional[str] = None,
                     language: Optional[str] = None) -> Dict[str, Any]:
    """What the catalog already holds for a country, population or language.

    The ranking needs this: a Bulgarian adult guide is worth more when the
    catalog has none than when it has three. The match is a search, so it is
    approximate — the result names what was matched so a reader can judge.

    :param kind: guide | article | textbook | fctable
    :param country: e.g. "Bulgaria"
    :param population_group: e.g. "adults", "pregnant women", "children"
    :param language: e.g. "Bulgarian"
    """
    proxy = _proxy(ctx, kind)
    terms = [t for t in (country, population_group, language) if t]
    if not terms:
        raise ToolError("give at least one of country, population_group, language")
    q = " ".join(terms)
    hits = proxy.search(q, limit=25)
    items = [_summarise(h, ("urn", "title", "country", "region", "language", "audience",
                            "publication_date", "license")) for h in hits]
    return {
        "kind": kind, "matched_on": q, "count": len(items), "items": items,
        "note": "approximate: a text search over the catalog, not a structured filter",
    }


def list_organizations(ctx: ToolContext, q: Optional[str] = None) -> Dict[str, Any]:
    """Organisations the catalog knows — publishers, ministries, institutes.

    A new guide should point at an existing organisation where one exists.

    :param q: optional filter on the name
    """
    if ctx.data_client is None:
        raise ToolError("no catalog client is configured")
    getter = getattr(ctx.data_client, "get", None)
    if getter is None:
        raise ToolError("the catalog client cannot list organisations")
    response = getter("/organizations", params={"limit": 200})
    payload = response.json() if hasattr(response, "json") else response
    rows = payload.get("result", payload) if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("results") or []
    items = [_summarise(r, ("urn", "title", "name", "country", "url", "type")) for r in rows]
    if q:
        needle = q.lower()
        items = [i for i in items if needle in " ".join(str(v) for v in i.values()).lower()]
    return {"count": len(items), "items": items}


def register(registry: ToolRegistry) -> None:
    registry.register(search_catalog)
    registry.register(get_entity)
    registry.register(catalog_coverage)
    registry.register(list_organizations)
