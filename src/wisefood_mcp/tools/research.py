"""Finding sources and reading them. The only tools that leave the platform.

Three tools, one rule between them: **the provider executes nothing but web
search.** ``fetch_url`` and ``licence_evidence`` run entirely here — plain
HTTP, plain parsing, nothing sent to a model. ``research`` is the exception
the rule allows for: it asks Groq's Compound system to search the web,
because that is the only place web search exists on this platform, then
parses what Compound did into findings with the URLs it visited. From the
integrator's side it is a tool like any other, and it is recorded like one.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import tempfile
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from wisefood_mcp.registry import ToolContext, ToolError, ToolRegistry
from wisefood_mcp.stores import LICENCES

logger = logging.getLogger(__name__)

USER_AGENT = "WiseFood-Integrator/0.1 (+https://wisefood-project.eu; source research)"
FETCH_TIMEOUT = 25.0
MAX_TEXT_CHARS = 20_000
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024

#: Where fetched PDFs wait between ``fetch_url`` and ``upload_artifact``.
#: A handle rather than the bytes, because a 40 MB guide does not belong in a
#: tool result a model has to read.
PENDING_DIR = Path(os.environ.get("WISEFOOD_MCP_PENDING_DIR", tempfile.gettempdir())) / "wisefood-mcp-pending"


# ------------------------------------------------------------- fetch_url --

class _TextExtractor(HTMLParser):
    """Readable text, title, description, canonical and licence links.

    Stdlib rather than a readability library: one fewer dependency in a
    package meant to be installed beside an MCP host, and what the assistant
    needs from a page is its words and its declared licence, not its layout.
    """

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title: str = ""
        self.description: str = ""
        self.canonical: Optional[str] = None
        self.licence_links: List[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and a.get("content"):
                self.description = self.description or a["content"].strip()
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            if "canonical" in rel and a.get("href"):
                self.canonical = a["href"]
            if "license" in rel and a.get("href"):
                self.licence_links.append(a["href"])
        elif tag == "a":
            rel = (a.get("rel") or "").lower()
            href = a.get("href") or ""
            if "license" in rel or "creativecommons.org/licenses" in href or "creativecommons.org/publicdomain" in href:
                self.licence_links.append(href)
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div", "section", "article"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def _robots_allows(client: httpx.Client, url: str) -> bool:
    """Honour robots.txt. A refused page is reported, not circumvented."""
    parts = urlparse(url)
    robots = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        r = client.get(robots, timeout=8.0)
        if r.status_code >= 400:
            return True
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(USER_AGENT, url) and rp.can_fetch("*", url)
    except Exception:  # noqa: BLE001 — an unreachable robots.txt is not a refusal
        return True


def _pending_handle(url: str, data: bytes) -> str:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:20]
    path = PENDING_DIR / f"{digest}.pdf"
    if not path.exists():
        path.write_bytes(data)
    (PENDING_DIR / f"{digest}.json").write_text(json.dumps({"url": url, "bytes": len(data)}))
    return digest


def pending_artifact_path(handle: str) -> Path:
    """Resolve a ``fetch_url`` handle. Refuses anything that is not one."""
    if not re.fullmatch(r"[0-9a-f]{20}", handle or ""):
        raise ToolError("not a pending-artifact handle", handle=handle)
    path = PENDING_DIR / f"{handle}.pdf"
    if not path.exists():
        raise ToolError("that fetched file is no longer available; fetch it again", handle=handle)
    return path


def _pdf_pages(data: bytes) -> Optional[int]:
    try:
        import fitz  # PyMuPDF, present where FoodScholar runs
        with fitz.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        try:
            from pypdf import PdfReader
            import io
            return len(PdfReader(io.BytesIO(data)).pages)
        except Exception:  # noqa: BLE001
            return None


def _pdf_first_text(data: bytes, chars: int = 3000) -> str:
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            out = []
            for page in doc:
                out.append(page.get_text())
                if sum(len(t) for t in out) > chars:
                    break
            return "".join(out)[:chars].strip()
    except Exception:  # noqa: BLE001
        return ""


def fetch_url(ctx: ToolContext, url: str, max_chars: int = MAX_TEXT_CHARS) -> Dict[str, Any]:
    """Fetch a web page or PDF and return what it says.

    Pages come back as readable text with their title, description and any
    licence links found in the markup. PDFs are stored to a pending handle
    for ``upload_artifact`` and come back with page count and first-page text.
    Honours robots.txt: a page a site asks us not to fetch is reported as
    refused, not fetched anyway.

    :param url: an http(s) URL
    :param max_chars: how much page text to return
    """
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ToolError("only http(s) URLs can be fetched", url=url)
    max_chars = max(500, min(int(max_chars), MAX_TEXT_CHARS))

    with httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        if not _robots_allows(client, url):
            return {"url": url, "fetched": False, "reason": "robots.txt disallows fetching this page"}
        try:
            response = client.get(url, timeout=FETCH_TIMEOUT)
        except httpx.HTTPError as exc:
            return {"url": url, "fetched": False, "reason": f"{type(exc).__name__}: {exc}"[:300]}

    final = str(response.url)
    ctype = (response.headers.get("content-type") or "").lower()
    if response.status_code >= 400:
        return {
            "url": final, "fetched": False, "status": response.status_code,
            "reason": "the site refused or has no such page"
            + (" — it may require a real browser" if response.status_code in (403, 429, 503) else ""),
        }

    body = response.content
    if len(body) > MAX_DOWNLOAD_BYTES:
        return {"url": final, "fetched": False, "reason": f"file larger than {MAX_DOWNLOAD_BYTES // (1024*1024)} MB"}

    is_pdf = "application/pdf" in ctype or body[:5] == b"%PDF-" or final.lower().endswith(".pdf")
    if is_pdf:
        handle = _pending_handle(final, body)
        return {
            "url": final, "fetched": True, "kind": "pdf", "bytes": len(body),
            "pages": _pdf_pages(body), "first_page_text": _pdf_first_text(body),
            "pending_artifact": handle,
            "note": "pass pending_artifact to upload_artifact once the proposal is approved",
        }

    parser = _TextExtractor()
    try:
        parser.feed(response.text)
    except Exception:  # noqa: BLE001 — a malformed page is still a page
        pass
    text = parser.text()
    links = [urljoin(final, h) for h in parser.licence_links]
    return {
        "url": final, "fetched": True, "kind": "html",
        "title": html.unescape(parser.title.strip())[:300],
        "description": parser.description[:500],
        "canonical": urljoin(final, parser.canonical) if parser.canonical else None,
        "licence_links": sorted(set(links)),
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
        "chars": len(text),
    }


# ------------------------------------------------------ licence_evidence --

#: Phrases and URL fragments → the catalog's LicenseId. Ordered most specific
#: first so "CC BY-NC-SA" is not read as "CC BY".
_LICENCE_PATTERNS = [
    (r"cc[\s-]*by[\s-]*nc[\s-]*nd|by-nc-nd|attribution[\s-]*non[\s-]*commercial[\s-]*no[\s-]*deriv", "CCBYNCND"),
    (r"cc[\s-]*by[\s-]*nc[\s-]*sa|by-nc-sa|attribution[\s-]*non[\s-]*commercial[\s-]*share[\s-]*alike", "CCBYNCSA"),
    (r"cc[\s-]*by[\s-]*nc\b|by-nc\b|attribution[\s-]*non[\s-]*commercial", "CCBYNC"),
    (r"cc[\s-]*by[\s-]*sa[\s-]*4\.0|by-sa/4\.0|attribution[\s-]*share[\s-]*alike[\s-]*4\.0", "CC-BY-SA-4.0"),
    (r"cc[\s-]*by[\s-]*sa\b|by-sa\b|attribution[\s-]*share[\s-]*alike", "CCBYSA"),
    (r"cc[\s-]*by[\s-]*4\.0|by/4\.0|attribution[\s-]*4\.0", "CC-BY-4.0"),
    (r"cc[\s-]*by\b|creativecommons\.org/licenses/by\b|creative commons attribution", "CCBY"),
    (r"cc0|creativecommons\.org/publicdomain/zero", "CC0"),
    (r"public domain|creativecommons\.org/publicdomain/mark", "public-domain"),
    (r"\bmit license\b", "MIT"),
    (r"apache license,? version 2", "Apache-2.0"),
    (r"gnu general public license|gpl-3", "GPL-3.0"),
]
#: A specific licence makes these generic ones redundant when both match,
#: because the generic pattern is a substring of the specific phrase.
_SUPERSEDED_BY = {
    "CC-BY-4.0": ("CCBY",),
    "CC-BY-SA-4.0": ("CCBYSA", "CCBY"),
    "CCBYSA": ("CCBY",),
    "CCBYNC": ("CCBY",),
    "CCBYNCSA": ("CCBYNC", "CCBYSA", "CCBY"),
    "CCBYNCND": ("CCBYNC", "CCBY"),
}

_PROPRIETARY_PATTERNS = [
    r"all rights reserved", r"©\s*\d{4}", r"copyright\s*©?\s*\d{4}",
    r"may not be reproduced", r"no part of this publication may be",
]
#: Government / IGO open-licence phrasings that map to permissive reuse.
_GOVERNMENT_OPEN = [
    (r"open government licence", "CCBY"),
    (r"crown copyright.*open government", "CCBY"),
    (r"reuse is authorised provided the source is acknowledged", "CCBY"),
    (r"decision 2011/833/eu", "CCBY"),
]


def _scan(text: str) -> List[Dict[str, Any]]:
    """Every licence signal in a text, with the sentence it sat in."""
    found: List[Dict[str, Any]] = []
    low = text.lower()

    def quote_around(match) -> str:
        start = max(0, low.rfind(".", 0, match.start()) + 1)
        end = low.find(".", match.end())
        end = len(text) if end == -1 else end + 1
        return re.sub(r"\s+", " ", text[start:end]).strip()[:300]

    for pattern, licence in _LICENCE_PATTERNS + _GOVERNMENT_OPEN:
        if any(licence in _SUPERSEDED_BY.get(f["licence"], ()) for f in found):
            continue
        for m in re.finditer(pattern, low):
            found.append({"licence": licence, "quote": quote_around(m), "signal": pattern})
            break
    for pattern in _PROPRIETARY_PATTERNS:
        m = re.search(pattern, low)
        if m:
            found.append({"licence": "Proprietary", "quote": quote_around(m), "signal": pattern, "weak": True})
            break
    return found


def _doi_lookups(client: httpx.Client, doi: str, email: Optional[str]) -> List[Dict[str, Any]]:
    """Unpaywall and Crossref — the two places a journal article's licence is a fact."""
    out: List[Dict[str, Any]] = []
    doi = doi.strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
    if email:
        try:
            r = client.get(f"https://api.unpaywall.org/v2/{doi}", params={"email": email}, timeout=15.0)
            if r.status_code == 200:
                d = r.json()
                loc = d.get("best_oa_location") or {}
                lic = (loc.get("license") or "").lower()
                out.append({
                    "where": "unpaywall", "is_oa": d.get("is_oa"), "oa_status": d.get("oa_status"),
                    "license_raw": lic or None, "url": loc.get("url"),
                    "licence": _map_raw(lic) if lic else None,
                })
        except Exception as exc:  # noqa: BLE001
            out.append({"where": "unpaywall", "error": str(exc)[:200]})
    try:
        r = client.get(f"https://api.crossref.org/works/{doi}", timeout=15.0,
                       headers={"User-Agent": f"{USER_AGENT} mailto:{email or 'unknown'}"})
        if r.status_code == 200:
            msg = r.json().get("message", {})
            for lic in msg.get("license") or []:
                url = lic.get("URL") or ""
                out.append({"where": "crossref", "license_url": url, "licence": _map_raw(url),
                            "publisher": msg.get("publisher")})
            if not msg.get("license"):
                out.append({"where": "crossref", "publisher": msg.get("publisher"), "licence": None,
                            "note": "no licence recorded"})
    except Exception as exc:  # noqa: BLE001
        out.append({"where": "crossref", "error": str(exc)[:200]})
    return out


def _map_raw(raw: str) -> Optional[str]:
    hits = _scan(raw)
    strong = [h for h in hits if not h.get("weak")]
    return (strong or hits)[0]["licence"] if (strong or hits) else None


def licence_evidence(ctx: ToolContext, url: Optional[str] = None, doi: Optional[str] = None,
                     text: Optional[str] = None) -> Dict[str, Any]:
    """Gather what a source says about its own licence, and what that suggests.

    Returns evidence — quotes, links, registry lookups — and a *proposed*
    value from the catalog's LicenseId enum with a confidence. It never
    decides: a person confirms in the console, and a source with nothing
    determinable is blocked from ingestion until someone overrides with a
    reason. For a DOI, Unpaywall and Crossref are asked, which is the closest
    thing to a fact this question has.

    :param url: a page or PDF to inspect
    :param doi: a DOI, for journal articles
    :param text: text already in hand (e.g. from fetch_url), to avoid refetching
    """
    if not (url or doi or text):
        raise ToolError("give a url, a doi, or text")
    evidence: List[Dict[str, Any]] = []
    checked: List[str] = []

    with httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        if doi:
            checked.append("doi registries")
            evidence += _doi_lookups(client, doi, ctx.contact_email)
        page_text = text or ""
        licence_links: List[str] = []
        if url and not text:
            fetched = fetch_url(ctx, url, max_chars=MAX_TEXT_CHARS)
            checked.append(f"page {url}")
            if fetched.get("fetched"):
                page_text = fetched.get("text") or fetched.get("first_page_text") or ""
                licence_links = fetched.get("licence_links") or []
            else:
                evidence.append({"where": "page", "error": fetched.get("reason")})
        elif text:
            checked.append("supplied text")

    for link in licence_links:
        mapped = _map_raw(link)
        evidence.append({"where": "rel=license link", "url": link, "licence": mapped})
    for hit in _scan(page_text):
        evidence.append({"where": "page text", **hit})

    votes: Dict[str, float] = {}
    for e in evidence:
        lic = e.get("licence")
        if not lic or lic not in LICENCES:
            continue
        weight = 1.0
        if e.get("where") in ("unpaywall", "crossref", "rel=license link"):
            weight = 2.0
        if e.get("weak"):
            weight = 0.4
        votes[lic] = votes.get(lic, 0) + weight
    proposed, confidence = None, 0.0
    if votes:
        proposed = max(votes, key=votes.get)
        total = sum(votes.values())
        confidence = round(min(0.95, votes[proposed] / total * (0.6 if total < 1 else 1.0)), 2)
        # A lone copyright line is not a licence; it is the absence of one.
        if proposed == "Proprietary" and votes[proposed] <= 0.4:
            confidence = min(confidence, 0.3)

    return {
        "proposed_licence": proposed,
        "confidence": confidence,
        "content_ingestion": (
            "permitted" if proposed in {"CC-BY-4.0", "CC-BY-SA-4.0", "CCBY", "CCBYSA", "CCBYNC",
                                        "CCBYNCSA", "CC0", "public-domain", "MIT", "Apache-2.0", "GPL-3.0"}
            else "blocked until a person confirms or overrides"
        ),
        "evidence": evidence,
        "checked": checked,
        "note": "a proposal, not a decision — confirm in the console",
    }


# --------------------------------------------------------------- research --

RESEARCH_SYSTEM = (
    "You are a research assistant for a public-health nutrition platform. "
    "Search the web to answer the request. Prefer official, primary sources: "
    "national health ministries, public health agencies, WHO/EFSA/FAO, "
    "universities, peer-reviewed journals. For each source you find, give the "
    "exact URL, the publisher or issuing body, the language, the year if known, "
    "and whether it is a PDF or a web page. Say plainly when you could not find "
    "something. Do not invent URLs."
)


def research(ctx: ToolContext, query: str, max_results: int = 8) -> Dict[str, Any]:
    """Search the web for sources and return what was found, with URLs.

    Runs on Groq's Compound system, which searches and visits pages on its own
    initiative — the one thing on this platform a provider executes. The
    result carries every URL Compound visited and the snippets it saw, so the
    integrator can cite them and ``fetch_url`` can read them properly.

    :param query: what to look for — e.g. "Bulgaria national dietary guidelines adults official PDF"
    :param max_results: cap on findings returned
    """
    if ctx.groq_client is None:
        raise ToolError("no Groq client is configured; research needs one")
    max_results = max(1, min(int(max_results), 20))

    completion = ctx.groq_client.chat.completions.create(
        model=ctx.research_model,
        messages=[
            {"role": "system", "content": RESEARCH_SYSTEM},
            {"role": "user", "content": query},
        ],
        max_tokens=1200,
        temperature=0.2,
    )
    data = completion.model_dump() if hasattr(completion, "model_dump") else completion
    message = data["choices"][0]["message"]
    executed = message.get("executed_tools") or []

    findings: List[Dict[str, Any]] = []
    seen = set()
    tools_used: List[str] = []
    for tool in executed:
        tools_used.append(tool.get("type") or "tool")
        sr = tool.get("search_results") or {}
        for item in (sr.get("results") or []):
            u = item.get("url")
            if u and u not in seen:
                seen.add(u)
                findings.append({
                    "url": u, "title": item.get("title"),
                    "snippet": (item.get("content") or "")[:500],
                    "score": item.get("score"), "via": "search",
                })
        for item in (tool.get("browser_results") or []):
            u = item.get("url") if isinstance(item, dict) else None
            if u and u not in seen:
                seen.add(u)
                findings.append({"url": u, "title": item.get("title"),
                                 "snippet": (item.get("content") or "")[:500], "via": "visit"})
    # URLs the model wrote in its answer but the tool records did not carry.
    for u in re.findall(r"https?://[^\s)\]>\"']+", message.get("content") or ""):
        u = u.rstrip(".,;")
        if u not in seen:
            seen.add(u)
            findings.append({"url": u, "via": "answer"})

    usage = data.get("usage") or {}
    return {
        "query": query,
        "answer": (message.get("content") or "").strip(),
        "findings": findings[:max_results],
        "tools_used": sorted(set(tools_used)),
        "model": data.get("model", ctx.research_model),
        "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage},
        "note": "URLs are leads, not verified sources — fetch_url and licence_evidence before proposing",
    }


def register(registry: ToolRegistry) -> None:
    registry.register(research)
    registry.register(fetch_url)
    registry.register(licence_evidence)
