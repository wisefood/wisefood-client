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
import ipaddress
import json
import logging
import os
import re
import socket
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

#: How many redirects a fetch will follow. Each hop is re-checked, which is
#: the point — a public URL that 302s to 169.254.169.254 is the standard way
#: past a check that only looked at what the caller typed.
MAX_REDIRECTS = 5

#: Hostnames a deployment has decided are fine to reach despite resolving
#: privately — an internal mirror, say. Empty by default, and it is a list of
#: names rather than a switch, so turning one on does not open the rest.
_ALLOWED_PRIVATE = frozenset(
    h.strip().lower() for h in
    os.environ.get("WISEFOOD_MCP_ALLOWED_PRIVATE_HOSTS", "").split(",") if h.strip()
)


# --------------------------------------------------------- where we may go --

def _address_is_public(ip: str) -> bool:
    """Is this an address on the internet, rather than one of ours?

    Everything private, loopback, link-local, multicast, reserved or
    unspecified is refused. 100.64.0.0/10 is named separately because Python
    does not count carrier-grade NAT as private and plenty of clusters sit
    inside it.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if (address.is_private or address.is_loopback or address.is_link_local
            or address.is_multicast or address.is_reserved
            or address.is_unspecified):
        return False
    if address.version == 4 and address in ipaddress.ip_network("100.64.0.0/10"):
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        return _address_is_public(str(address.ipv4_mapped))
    return True


def check_destination(url: str) -> None:
    """Refuse a URL that points inside the cluster. Raises, never returns False.

    This is the control that stops `fetch_url` being a hole in the network:
    the tool takes a URL the *model* chose, and the model chose it from web
    pages that `research` returned, so the destination is attacker-influenced
    input. Without this, "read this page for me" reaches the metadata service,
    Redis, Keycloak and the gateway's own internal port, and hands the body
    back into the conversation.

    Every name is resolved and every address it resolves to must be public —
    one A record pointing inward is enough to refuse, since we do not control
    which one a connection would pick.

    Residual risk, stated rather than papered over: the connection is made by
    hostname afterwards, so a name that changes its answer between this check
    and the request (DNS rebinding) is not closed by it. Closing that needs
    connecting to the pinned address with SNI overridden, which is a bigger
    change than this; the check still removes the whole class of one-shot
    attacks, and the allowlist below is the supported way to reach something
    internal on purpose.
    """
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("only http(s) URLs can be fetched", url=url)

    host = parts.hostname.lower()
    if host in _ALLOWED_PRIVATE:
        return

    try:
        resolved = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                      proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ToolError(f"that host does not resolve: {exc}", url=url) from exc

    addresses = {info[4][0] for info in resolved}
    if not addresses:
        raise ToolError("that host does not resolve", url=url)
    for address in addresses:
        if not _address_is_public(address):
            raise ToolError(
                "that address is inside the platform's own network and will not "
                "be fetched; only public pages can be read",
                url=url, resolved=address, code="destination_refused",
            )


def _get_following_redirects(client: httpx.Client, url: str):
    """GET, following redirects ourselves so every hop is checked.

    Returns the streamed response and the final URL, or ``(None, url)`` if the
    chain went on too long. Raises :class:`ToolError` the moment a hop points
    somewhere we may not go, rather than reporting it as an ordinary failure:
    being redirected at the metadata service is not a broken link.
    """
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        request = client.build_request("GET", current, timeout=FETCH_TIMEOUT)
        response = client.send(request, stream=True)
        if response.status_code not in (301, 302, 303, 307, 308):
            return response, str(response.url)
        location = response.headers.get("location")
        response.close()
        if not location:
            raise ToolError("that site redirected without saying where", url=current)
        current = urljoin(current, location)
        check_destination(current)
    return None, current


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


#: Content types we keep whole rather than reading as text, and the extension
#: each is stored under. A food composition table is a spreadsheet, and
#: running one through an HTML text extractor produces confident nonsense.
KEEPABLE = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "application/csv": ".csv",
}

#: The same decision from the URL, for servers that answer everything
#: `application/octet-stream`.
KEEPABLE_SUFFIXES = (".pdf", ".xlsx", ".xls", ".ods", ".csv", ".tsv")


def _keepable_extension(content_type: str, url: str, body: bytes) -> Optional[str]:
    """Which extension to stash this under, or None to read it as a page."""
    base = (content_type or "").split(";")[0].strip().lower()
    if base in KEEPABLE:
        return KEEPABLE[base]
    lowered = url.lower().split("?")[0]
    for suffix in KEEPABLE_SUFFIXES:
        if lowered.endswith(suffix):
            return suffix
    if body[:5] == b"%PDF-":
        return ".pdf"
    # XLSX and ODS are both zip containers; CSV is indistinguishable from text
    # and is only recognised by its type or its name, above.
    if body[:2] == b"PK" and ("sheet" in base or "opendocument" in base):
        return ".xlsx"
    return None


def _pending_handle(url: str, data: bytes, extension: str = ".pdf") -> str:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:20]
    path = PENDING_DIR / f"{digest}{extension}"
    if not path.exists():
        path.write_bytes(data)
    (PENDING_DIR / f"{digest}.json").write_text(
        json.dumps({"url": url, "bytes": len(data), "extension": extension}))
    return digest


def pending_artifact_path(handle: str) -> Path:
    """Resolve a ``fetch_url`` handle. Refuses anything that is not one.

    The handle names a file whose extension depends on what was fetched, so
    this looks for whichever one is there rather than assuming PDF — a
    spreadsheet is as much a source document as a guide is.
    """
    if not re.fullmatch(r"[0-9a-f]{20}", handle or ""):
        raise ToolError("not a pending-artifact handle", handle=handle)
    for candidate in sorted(PENDING_DIR.glob(f"{handle}.*")):
        if candidate.suffix != ".json":
            return candidate
    raise ToolError("that fetched file is no longer available; fetch it again",
                    handle=handle)


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
    check_destination(url)
    max_chars = max(500, min(int(max_chars), MAX_TEXT_CHARS))

    # Redirects are followed by hand so each hop can be checked. `httpx`'s own
    # following would take a public URL to a private one without asking, which
    # is the ordinary way past a check on the URL the caller supplied.
    with httpx.Client(follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        if not _robots_allows(client, url):
            return {"url": url, "fetched": False, "reason": "robots.txt disallows fetching this page"}
        try:
            response, final = _get_following_redirects(client, url)
        except ToolError:
            raise
        except httpx.HTTPError as exc:
            return {"url": url, "fetched": False, "reason": f"{type(exc).__name__}: {exc}"[:300]}
        if response is None:
            return {"url": url, "fetched": False,
                    "reason": f"more than {MAX_REDIRECTS} redirects"}

        ctype = (response.headers.get("content-type") or "").lower()
        if response.status_code >= 400:
            response.close()
            return {
                "url": final, "fetched": False, "status": response.status_code,
                "reason": "the site refused or has no such page"
                + (" — it may require a real browser" if response.status_code in (403, 429, 503) else ""),
            }

        # Read in chunks and stop at the ceiling. `response.content` would
        # buffer the whole body first, so the size limit only applied after
        # the memory had already been spent — a server that streams forever
        # could take the pod down with it.
        chunks, total = [], 0
        oversize = False
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                oversize = True
                break
            chunks.append(chunk)
        response.close()

    if oversize:
        return {"url": final, "fetched": False,
                "reason": f"file larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB"}
    body = b"".join(chunks)

    extension = _keepable_extension(ctype, final, body)
    if extension:
        handle = _pending_handle(final, body, extension)
        kept = {
            "url": final, "fetched": True, "bytes": len(body),
            "kind": "pdf" if extension == ".pdf" else "spreadsheet",
            "format": extension.lstrip("."),
            "pending_artifact": handle,
            "note": "pass pending_artifact to upload_artifact once the proposal is approved",
        }
        if extension == ".pdf":
            kept["pages"] = _pdf_pages(body)
            kept["first_page_text"] = _pdf_first_text(body)
        return kept

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




# ----------------------------------------------------------- doi_metadata --

def normalise_doi(value: str) -> str:
    """A bare DOI, from whatever a person or a page pasted."""
    doi = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:"):
        doi = doi.removeprefix(prefix)
    return doi.strip().strip(".")


def _crossref_abstract(raw: Optional[str]) -> Optional[str]:
    """Crossref abstracts arrive as JATS XML. Return the words.

    Not a parser — a tag strip. The abstract is read by a person deciding
    whether an article is worth having, and `<jats:p>` in the middle of it
    helps nobody.
    """
    if not raw:
        return None
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # An inline tag becomes a space, so `<italic>health</italic>.` would leave
    # "health ." — abstracts are full of inline markup, so this is every
    # sentence rather than an edge case.
    text = re.sub(r"\s+([,.;:!?)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"^abstract\s*[:.]?\s*", "", text, flags=re.I)
    return text or None


def _crossref_authors(items: Any) -> List[str]:
    out: List[str] = []
    for person in items or []:
        if not isinstance(person, dict):
            continue
        name = person.get("name") or " ".join(
            part for part in (person.get("given"), person.get("family")) if part)
        if name:
            out.append(name.strip())
    return out


def _crossref_year(message: Dict[str, Any]) -> Optional[int]:
    for key in ("issued", "published-print", "published-online", "created"):
        parts = ((message.get(key) or {}).get("date-parts") or [[]])[0]
        if parts and parts[0]:
            try:
                return int(parts[0])
            except (TypeError, ValueError):
                continue
    return None


def doi_metadata(ctx: ToolContext, doi: str) -> Dict[str, Any]:
    """Look up an article's bibliographic record by DOI, from Crossref.

    Use this before proposing any article. An assistant that types a citation
    out of a search result invents authors and years that look right; one that
    reads the registration agency's own record does not. What comes back here
    is what the publisher deposited, and it is what belongs on the catalog
    entry.

    Returns the fields a catalog article takes — title, authors, venue, year,
    abstract, publisher, type — plus the counts that help rank it. It does not
    decide the licence: `licence_evidence` does that, with its evidence.

    :param doi: a DOI, with or without the https://doi.org/ prefix
    """
    bare = normalise_doi(doi)
    # Deliberately loose: "10." then digits then a suffix. Registrant codes are
    # four or five digits in practice, but nothing guarantees that, and the two
    # failure modes are not equal — rejecting a real DOI blocks the work, while
    # letting an odd one through costs one request that answers "no record".
    if not re.match(r"^10\.\d+/\S+$", bare):
        raise ToolError("that does not look like a DOI", doi=doi, code="not_a_doi")

    email = ctx.contact_email
    with httpx.Client(follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        try:
            response = client.get(
                f"https://api.crossref.org/works/{bare}", timeout=20.0,
                headers={"User-Agent": f"{USER_AGENT} mailto:{email or 'unknown'}"})
        except httpx.HTTPError as exc:
            raise ToolError(f"Crossref could not be reached: {exc}"[:300], doi=bare) from exc

    if response.status_code == 404:
        return {"doi": bare, "found": False,
                "reason": "Crossref has no record of that DOI — check it, or the "
                          "work may be registered with another agency such as DataCite"}
    if response.status_code != 200:
        raise ToolError(f"Crossref answered {response.status_code}", doi=bare)

    message = (response.json() or {}).get("message") or {}
    titles = message.get("title") or []
    containers = message.get("container-title") or []
    return {
        "doi": bare,
        "found": True,
        "title": (titles[0] if titles else None),
        "authors": _crossref_authors(message.get("author")),
        "venue": (containers[0] if containers else None),
        "publisher": message.get("publisher"),
        "publication_year": _crossref_year(message),
        "type": message.get("type"),
        "abstract": _crossref_abstract(message.get("abstract")),
        "language": message.get("language"),
        "url": message.get("URL") or f"https://doi.org/{bare}",
        "subjects": message.get("subject") or [],
        "citation_count": message.get("is-referenced-by-count"),
        "reference_count": message.get("references-count"),
        # Named, not resolved: a licence is evidence, and `licence_evidence`
        # is where that judgement is made and recorded.
        "licence_urls": [lic.get("URL") for lic in (message.get("license") or [])
                         if lic.get("URL")],
        "note": "run licence_evidence on this DOI before proposing it",
    }


def register(registry: ToolRegistry) -> None:
    registry.register(research)
    registry.register(fetch_url)
    registry.register(licence_evidence)
    registry.register(doi_metadata)
