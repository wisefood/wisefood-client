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
    # Article identity. `doi` in particular is what makes "do we already hold
    # this paper?" an exact question rather than a fuzzy title match.
    "doi", "venue", "publication_year", "authors",
)


#: Where the catalog keeps the country. Not `country` — that field does not
#: exist on these documents, and searching a country's *name* matched nothing
#: while quietly reading as "the catalog holds none of these".
REGION_FIELD = "region"


def country_code(value: str) -> Optional[str]:
    """An ISO 3166-1 alpha-2 code from a name, a code, or nothing.

    Accepts what a person or a model would actually type — "Ireland", "IE",
    "ie", "IRL" — because the alternative is a query that returns zero and
    means nothing went wrong.
    """
    text = (value or "").strip()
    if not text:
        return None
    if len(text) == 2 and text.isalpha():
        return text.upper()
    try:
        import pycountry
    except ImportError:  # pragma: no cover - pycountry ships with the extra
        return text.upper() if len(text) == 2 else None
    found = pycountry.countries.get(alpha_2=text.upper()) \
        or pycountry.countries.get(alpha_3=text.upper())
    if found is None:
        try:
            matches = pycountry.countries.search_fuzzy(text)
        except LookupError:
            return None
        found = matches[0] if matches else None
    return found.alpha_2 if found else None


def language_code(value: str) -> Optional[str]:
    """An ISO 639-1 code from a language name or code."""
    text = (value or "").strip()
    if not text:
        return None
    if len(text) == 2 and text.isalpha():
        return text.lower()
    try:
        import pycountry
    except ImportError:  # pragma: no cover
        return None
    found = pycountry.languages.get(alpha_2=text.lower()) \
        or pycountry.languages.get(alpha_3=text.lower()) \
        or pycountry.languages.get(name=text.title())
    if found is None:
        # ISO's own name for a language is often not the one anybody uses —
        # Greek is filed as "Modern Greek (1453-)" — so an exact name lookup
        # fails on exactly the languages this catalog is full of. There is no
        # fuzzy search for languages, so match the name's leading word.
        # Only entries that *have* a two-letter code can answer this, and
        # among those the shortest matching name is the living language:
        # "Modern Greek (1453-)" over "Ancient Greek (to 1453)".
        wanted = text.lower()
        candidates = [
            e for e in pycountry.languages
            if getattr(e, "alpha_2", None)
            and (wanted in getattr(e, "name", "").lower().split(" (")[0].split()
                 or getattr(e, "name", "").lower().split(" (")[0] == wanted)
        ]
        found = min(candidates, key=lambda e: len(e.name)) if candidates else None
    return getattr(found, "alpha_2", None) if found else None


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
    catalog has none than when it has three.

    Country and language are matched as structured filters on the codes the
    catalog stores, not as words in a search. Give either form — "Ireland" or
    "IE", "Bulgarian" or "bg" — and it is normalised before the query runs.

    Drafts count. A source sitting in the catalog unpublished is still a
    source somebody has already brought in, and proposing it again is
    duplicated work for the curator who did.

    :param kind: guide | article | textbook | fctable
    :param country: a name or an ISO code — "Ireland" and "IE" both work
    :param population_group: e.g. "adults", "pregnant women", "children"
    :param language: a name or an ISO code — "Bulgarian" and "bg" both work
    """
    proxy = _proxy(ctx, kind)
    if not any((country, population_group, language)):
        raise ToolError("give at least one of country, population_group, language")

    filters: List[str] = []
    resolved: Dict[str, Any] = {}
    if country:
        code = country_code(country)
        if code is None:
            raise ToolError(
                f"{country!r} is not a country I can resolve to an ISO code",
                hint="give the country's name or its two-letter ISO 3166 code")
        filters.append(f"{REGION_FIELD}:{code}")
        resolved["country"] = code
    if language:
        code = language_code(language)
        if code is None:
            raise ToolError(
                f"{language!r} is not a language I can resolve to an ISO code",
                hint="give the language's name or its two-letter ISO 639-1 code")
        filters.append(f"language:{code}")
        resolved["language"] = code

    # The population group has no code and no single field — it is `audience`
    # on some kinds and `target_audiences` on others — so it stays a search
    # term. Said in the result, because a term and a filter are not the same
    # promise.
    q = population_group or "*"
    hits = proxy.search(q, limit=50, fq=filters or None)
    items = [_summarise(h, ("urn", "title", "country", "region", "language",
                            "audience", "status", "review_status",
                            "publication_date", "license")) for h in hits]

    by_status: Dict[str, int] = {}
    for item in items:
        by_status[item.get("status") or "unknown"] = \
            by_status.get(item.get("status") or "unknown", 0) + 1
    drafts = [i for i in items if i.get("status") == "draft"]

    return {
        "kind": kind,
        "filters": filters,
        "resolved": resolved,
        "searched_for": population_group or None,
        "count": len(items),
        "by_status": by_status,
        "draft_count": len(drafts),
        "items": items,
        "note": (
            "country and language are exact filters on the catalog's ISO codes; "
            "the population group, if given, is a text search. Counts include "
            "drafts — an unpublished entry is still already held, so check "
            "`by_status` before calling something a gap."
        ),
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
