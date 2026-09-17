"""Profiling a recipe source, so a recipe collection has a form.

Every other kind of source in this catalog is a document: a URL points at a
thing you can open, read and judge. A recipe collection is not. It is a site
with some number of recipes spread across it, and the questions a curator has
are "how many, are they machine-readable, and may we use them" — none of
which a page is going to answer.

So this profiles the site the way the harvester will read it: find where the
site lists its own pages, sample a few, and count how many actually carry
schema.org Recipe markup. That last number is the one that matters. A site
with ten thousand pages and no markup is ten thousand pages of nothing, and
finding that out after starting an import is the expensive way.

What comes back is also what the import needs: `harvest_location` is the
sitemap or feed to hand to the recipe harvester.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from wisefood_mcp.registry import ToolContext, ToolError, ToolRegistry
from wisefood_mcp.tools.research import (
    BROWSER_HEADERS, USER_AGENT, _get_following_redirects, check_destination)

logger = logging.getLogger(__name__)

#: Sitemap paths worth trying when robots.txt names none. Ordered by how
#: often they are the right answer.
COMMON_SITEMAPS = (
    "/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml",
    "/sitemap-index.xml", "/feed", "/rss",
)

#: A sitemap whose URL says what it holds, weighted by how much it says. A
#: site that splits its sitemap by content type hands us the recipe one, and
#: harvesting that beats harvesting everything and discarding the rest. The
#: weights matter: BBC Good Food publishes `-post.xml` and `-recipe.xml` side
#: by side, and scoring those equally picks the blog.
RECIPE_HINTS = {
    "recipe": 10, "recipes": 10, "cook": 4, "dish": 3, "meal": 3,
    "post": 1, "posts": 1, "article": 1,
}

#: A sampled share at or above this is a good enough sitemap to stop looking.
GOOD_ENOUGH = 0.4

#: The whole profile, end to end. A slow site with a large sitemap index can
#: otherwise run for minutes while a curator watches a spinner — one took 87
#: seconds before this. What has been sampled by then is reported, with a
#: note saying it stopped early, which is more useful than a perfect answer
#: nobody waited for.
TIME_BUDGET_SECONDS = 45.0

#: How many pages to open when sampling. Enough to tell "most pages are
#: recipes" from "almost none are"; few enough to be polite and quick.
DEFAULT_SAMPLE = 5
MAX_SAMPLE = 15


def _get(client: httpx.Client, url: str, *, browser: bool = True):
    """Fetch, with the destination guard applied to every hop."""
    check_destination(url)
    response, _final = _get_following_redirects(
        client, url, headers=BROWSER_HEADERS if browser else None)
    return response


def _text(response, limit: int = 2_000_000) -> str:
    try:
        return response.read().decode("utf-8", "replace")[:limit]
    finally:
        response.close()


def sitemaps_from_robots(text: str) -> List[str]:
    """`Sitemap:` lines, which is where a site is supposed to say.

    Read even when robots.txt is otherwise ignored: the Sitemap directive is
    a site telling us where its index is, which is help rather than a
    restriction.
    """
    return [m.group(1).strip() for m in
            re.finditer(r"(?im)^\s*sitemap:\s*(\S+)\s*$", text)]


def feeds_from_html(html_text: str, base: str) -> List[str]:
    """RSS and Atom links declared in a page's head."""
    out = []
    for tag in re.findall(r"<link\b[^>]*>", html_text, re.I):
        if not re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            continue
        href = re.search(r'href=["\']([^"\']+)', tag, re.I)
        if href:
            out.append(urljoin(base, href.group(1)))
    return out


def _rank_sitemaps(urls: List[str]) -> List[str]:
    """Recipe-looking sitemaps first, most recent next.

    Ordering is what makes one or two samples enough instead of a dozen: the
    right sitemap is usually the one that says `recipe` in its name, and the
    newest of those is the one whose pages still exist.
    """
    def score(u: str):
        low = u.lower()
        hint = sum(w for h, w in RECIPE_HINTS.items() if h in low)
        # A year in the name orders the quarters without parsing dates.
        recency = "".join(re.findall(r"\d", low))[-6:] or "0"
        return (-hint, -int(recency))
    return sorted(dict.fromkeys(urls), key=score)


def _page_urls(xml_or_text: str, base: str, limit: int = 2000) -> List[str]:
    """Page URLs from a sitemap, sitemap index, feed, or a plain list."""
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_or_text, re.I)
    if not locs:
        locs = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', xml_or_text, re.I)
    if not locs:
        locs = re.findall(r"https?://\S+", xml_or_text)
    return [urljoin(base, u) for u in locs[:limit]]


def recipe_markup(html_text: str) -> Optional[Dict[str, Any]]:
    """The schema.org Recipe published as JSON-LD, if there is one.

    The richest form and the only one that states ingredients and steps as
    data. `detect_recipe` covers the rest.
    """
    for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html_text, re.I | re.S):
        try:
            data = json.loads(block.strip())
        except (ValueError, TypeError):
            continue
        for node in _walk(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(str(t).lower() == "recipe" for t in types if t):
                return node
    return None


#: How a page can say "this is a recipe", richest first. JSON-LD states the
#: ingredients and steps as data; a WordPress plugin renders them in known
#: classes; prose has to be read. They are not equally useful, so the profile
#: reports which was found rather than collapsing them into a yes.
MARKUP_FORMS = (
    ("microdata", re.compile(
        r'item(?:type|scope)[^>]*schema\.org/Recipe', re.I)),
    ("rdfa", re.compile(r'typeof=["\'][^"\']*\bRecipe\b', re.I)),
    ("microformat", re.compile(r'class=["\'][^"\']*\bh-?recipe\b', re.I)),
    ("plugin", re.compile(
        r'\b(wprm-recipe|tasty-recipes|easyrecipe|mv-create|zlrecipe)\b', re.I)),
)

#: Prose, as a last resort: a page that lists ingredients and then says what
#: to do with them is a recipe whatever its markup. Both are required —
#: "ingredients" alone appears on any product page.
_INGREDIENTS = re.compile(r">\s*(ingredients|υλικά|zutaten|ingr[ée]dients|"
                          r"hozz[aá]val[oó]k|ingredienti)\b", re.I)
_METHOD = re.compile(r">\s*(method|instructions|directions|preparation|steps|"
                     r"εκτέλεση|zubereitung|pr[ée]paration|elk[eé]sz[ií]t[eé]s)\b", re.I)


def _titled(html_text: str) -> Optional[str]:
    found = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    return " ".join(found.group(1).split())[:120] if found else None


def detect_recipe(html_text: str) -> Optional[Dict[str, Any]]:
    """Whether this page is a recipe, and how it says so.

    Not only JSON-LD. A site that publishes its recipes as microdata, with a
    WordPress plugin, or simply as a heading of ingredients followed by a
    method is still publishing recipes — refusing those would have written
    off most of the web's home cooking, and the importer can be pointed at
    them knowing what it is dealing with.
    """
    structured = recipe_markup(html_text)
    if structured:
        name = structured.get("name")
        return {"how": "json-ld",
                "name": name if isinstance(name, str) else _titled(html_text),
                "machine_readable": True}

    for how, pattern in MARKUP_FORMS:
        if pattern.search(html_text):
            return {"how": how, "name": _titled(html_text),
                    # Structured enough for a parser to find the parts, but
                    # not self-describing the way JSON-LD is.
                    "machine_readable": how in ("microdata", "rdfa")}

    if _INGREDIENTS.search(html_text) and _METHOD.search(html_text):
        return {"how": "prose", "name": _titled(html_text),
                "machine_readable": False}
    return None


def _walk(data: Any):
    """Every dict in a JSON-LD document, including inside @graph and lists."""
    if isinstance(data, dict):
        yield data
        for value in data.values():
            if isinstance(value, (dict, list)):
                yield from _walk(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk(item)


def _sample(client: httpx.Client, pages: List[str], sample: int,
            deadline: Optional[float] = None):
    """Open a spread of pages and count the ones carrying Recipe markup.

    Sampled across the list rather than from the front: the head of a sitemap
    is usually the site's about and contact pages, which would make every
    site look unharvestable.
    """
    step = max(1, len(pages) // sample)
    checked, found, titles, forms = 0, 0, [], {}
    for page in pages[::step][:sample]:
        if deadline is not None and time.monotonic() > deadline:
            break
        try:
            response = _get(client, page)
        except (ToolError, httpx.HTTPError):
            continue
        if response is None or response.status_code >= 400:
            if response is not None:
                response.close()
            continue
        recipe = detect_recipe(_text(response, 600_000))
        checked += 1
        if recipe:
            found += 1
            forms[recipe["how"]] = forms.get(recipe["how"], 0) + 1
            name = recipe.get("name")
            if isinstance(name, str) and name.strip():
                titles.append(name.strip()[:120])
    return checked, found, titles, forms


def links_from_index(html_text: str, base: str) -> List[str]:
    """Same-host links that sit under the given page's path.

    The page a curator hands over is usually the recipe index itself, and it
    is a better list than anything a sitemap will give: asked about
    `bestofhungary.co.uk/blogs/recipes`, the tool went to the site root,
    found Shopify's product sitemap and reported that 383 pages carried no
    recipes. The nineteen recipes linked from the page it was given all did.
    """
    here = urlparse(base)
    prefix = here.path.rstrip("/")
    found = []
    for href in re.findall(r'href=["\']([^"\'#]+)', html_text, re.I):
        absolute = urljoin(base, href)
        parts = urlparse(absolute)
        if parts.netloc != here.netloc or not parts.scheme.startswith("http"):
            continue
        path = parts.path.rstrip("/")
        # Under the index, and not the index itself.
        if prefix and path.startswith(prefix + "/") and path != prefix:
            found.append(absolute.split("?")[0])
    return list(dict.fromkeys(found))


def recipe_source(ctx: ToolContext, url: str,
                  sample: int = DEFAULT_SAMPLE) -> Dict[str, Any]:
    """Profile a recipe website: is it harvestable, and how much is there?

    A recipe collection has no single page to read, so this reads the site
    the way the harvester will. It finds where the site lists its own pages,
    opens a few of them, and counts how many carry schema.org Recipe markup.

    Use it before proposing an `rcollection`. The share of sampled pages that
    carry markup is the number worth quoting to a curator: a site with ten
    thousand pages and no markup is ten thousand pages of nothing, and that
    is much cheaper to learn here than part-way through an import.

    `harvest_location` is what the recipe importer takes — the sitemap or
    feed, not the homepage.

    :param url: the site, or a sitemap or feed if you already have one
    :param sample: how many pages to open, at most 15
    """
    sample = max(1, min(int(sample), MAX_SAMPLE))
    target = (url or "").strip()
    if not target:
        raise ToolError("give the address of a recipe site")
    if "://" not in target:
        target = f"https://{target}"
    check_destination(target)

    parts = urlparse(target)
    origin = f"{parts.scheme}://{parts.netloc}"
    deadline = time.monotonic() + TIME_BUDGET_SECONDS
    given_index = None
    found: Dict[str, Any] = {
        "url": target, "origin": origin, "checked": [], "notes": [],
    }

    with httpx.Client(follow_redirects=False,
                      headers={"User-Agent": USER_AGENT}) as client:
        candidates: List[str] = []

        # Given a sitemap or feed outright, use it and skip the hunt.
        looks_like_index = bool(re.search(r"(sitemap|feed|rss|atom)", target, re.I))
        if looks_like_index:
            candidates = [target]
        else:
            # The page we were given, first. A curator who pastes a recipe
            # index has already done the hard part; going to the site root
            # and guessing throws that away.
            if urlparse(target).path.strip("/"):
                try:
                    index = _get(client, target)
                    if index is not None and index.status_code < 400:
                        listed = links_from_index(_text(index, 1_000_000), target)
                        if listed:
                            found["checked"].append("the page you gave")
                            given_index = (target, listed)
                    elif index is not None:
                        index.close()
                except (ToolError, httpx.HTTPError):
                    pass

            try:
                robots = _get(client, f"{origin}/robots.txt")
                if robots is not None and robots.status_code < 400:
                    candidates += sitemaps_from_robots(_text(robots, 200_000))
                    found["checked"].append("robots.txt")
                elif robots is not None:
                    robots.close()
            except (ToolError, httpx.HTTPError):
                pass

            if not candidates:
                try:
                    home = _get(client, target)
                    if home is not None and home.status_code < 400:
                        body = _text(home, 400_000)
                        candidates += feeds_from_html(body, target)
                        found["checked"].append("the homepage's feed links")
                    elif home is not None:
                        home.close()
                except (ToolError, httpx.HTTPError):
                    pass

            candidates += [f"{origin}{path}" for path in COMMON_SITEMAPS]

        # Collect every list of pages the site offers, stepping into an
        # index rather than sampling the index itself.
        options: List[tuple] = []
        if given_index:
            options.append(given_index)
        for candidate in _rank_sitemaps(candidates)[:8]:
            if deadline and time.monotonic() > deadline:
                found["notes"].append("stopped looking for more lists: out of time")
                break
            try:
                response = _get(client, candidate)
            except (ToolError, httpx.HTTPError):
                continue
            if response is None or response.status_code >= 400:
                if response is not None:
                    response.close()
                continue
            urls = _page_urls(_text(response, 2_000_000), candidate)
            if not urls:
                continue
            if all(re.search(r"\.xml(\.gz)?($|\?)", u, re.I) for u in urls[:5]):
                found["notes"].append("followed a sitemap index")
                for nested in _rank_sitemaps(urls)[:4]:
                    try:
                        inner = _get(client, nested)
                    except (ToolError, httpx.HTTPError):
                        continue
                    if inner is None or inner.status_code >= 400:
                        if inner is not None:
                            inner.close()
                        continue
                    nested_urls = _page_urls(_text(inner, 2_000_000), nested)
                    if nested_urls:
                        options.append((nested, nested_urls))
                continue
            options.append((candidate, urls))

        if not options:
            return {
                **found, "harvestable": False,
                "reason": ("no sitemap or feed found — the recipe importer needs "
                           "one. Look for a sitemap link in the site's footer or "
                           "robots.txt, and pass that address instead."),
            }

        # Sample each list in turn and keep the best. One guess is not enough:
        # a site that splits recipes from blog posts will hand over whichever
        # the ranking preferred, and being wrong about that once should cost a
        # few requests rather than the whole answer.
        best = {"location": None, "pages": [], "checked": 0,
                "with_markup": 0, "titles": [], "share": 0.0, "forms": {}}
        tried = []
        for location, pages in options[:4]:
            if time.monotonic() > deadline and best["location"]:
                found["notes"].append("stopped sampling: out of time")
                break
            checked, with_markup, titles, forms = _sample(
                client, pages, sample, deadline)
            share = (with_markup / checked) if checked else 0.0
            tried.append({"location": location, "sampled": checked,
                          "with_recipes": with_markup})
            # `>=` on the first list, so a site where nothing has markup
            # still reports what was looked at. Saying "sampled nothing" when
            # three pages were opened hides the evidence for the answer.
            if best["location"] is None or share > best["share"]:
                best = {"location": location, "pages": pages, "checked": checked,
                        "with_markup": with_markup, "titles": titles,
                        "share": share, "forms": forms}
            if share >= GOOD_ENOUGH:
                break
        if len(tried) > 1:
            found["notes"].append(
                f"sampled {len(tried)} lists and kept the one with the most recipes")
        found["tried"] = tried

    location = best["location"]
    pages = best["pages"]
    checked, with_markup = best["checked"], best["with_markup"]
    titles, forms = best["titles"], best.get("forms") or {}
    share = (with_markup / checked) if checked else 0.0
    return {
        **found,
        "harvestable": with_markup > 0,
        "harvest_location": location,
        "pages_listed": len(pages),
        "sampled": checked,
        "with_recipes": with_markup,
        # Which forms, because they are not equally useful: JSON-LD and
        # microdata state the ingredients and steps, a plugin renders them in
        # known classes, and prose has to be read. A curator deciding whether
        # to import wants to know which of those they are getting.
        "published_as": forms,
        "machine_readable": sum(
            n for how, n in forms.items() if how in ("json-ld", "microdata")),
        "recipe_share": round(share, 2),
        "sample_titles": titles[:5],
        # An estimate, and labelled as one: the sample is small and a site
        # does not have to be uniform.
        "estimated_recipes": int(len(pages) * share) if checked else None,
        "note": (
            "estimated_recipes is pages_listed scaled by the sampled share and "
            "is an estimate, not a count. published_as says how the recipes are "
            "expressed: json-ld and microdata carry ingredients and steps as "
            "data, a plugin renders them in known classes, and prose has to be "
            "read — all are importable, but say which when you propose it. Run "
            "licence_evidence on the site's terms first, because a recipe "
            "corpus is content and copying it in needs a licence that permits "
            "that."
        ),
    }


def register(registry: ToolRegistry) -> None:
    registry.register(recipe_source)
