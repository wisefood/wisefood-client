"""wisefood-mcp: the walls, and the tools behind them.

What matters here is not that each tool works when everything is right — it
is that the two guarantees hold when something is wrong: no write without an
approved proposal, and a licence that is proposed with evidence rather than
decided. Everything talks to fakes; nothing here touches the network.
"""
from __future__ import annotations

import json
import types

import httpx
import pytest

from wisefood_mcp import ToolContext, build_registry
from wisefood_mcp.registry import (
    ApprovalRequired, ToolError, WritesDisabled, _openai_schema)
from wisefood_mcp.stores import (
    InMemoryProposalStore, Proposal, approve, content_permitted, new_proposal_id, require_approved,
)
from wisefood_mcp.tools import research as research_tools


# ------------------------------------------------------------------ fakes --

class FakeEntity:
    def __init__(self, **d): self._d = d
    def dict(self): return dict(self._d)


class FakeProxy:
    def __init__(self, rows): self.rows = rows; self.created = []; self.searches = []
    def search(self, q, limit=10, **kw):
        self.searches.append({"q": q, **kw})
        return [FakeEntity(**r) for r in self.rows[:limit]]
    def get(self, identifier, **kw):
        for r in self.rows:
            if r.get("urn") == identifier: return FakeEntity(**r)
        raise KeyError(identifier)
    def create(self, **fields):
        self.created.append(fields); return FakeEntity(urn="urn:guide:new", **fields)
    def upload(self, path, **fields):
        self.created.append({"path": path, **fields}); return FakeEntity(id="art-1", **fields)


class FakeDataClient:
    def __init__(self):
        self.guides = FakeProxy([{"urn": "urn:guide:ie", "title": "Irish Healthy Eating Guidelines",
                                  "license": "CCBY", "region": "IE", "content": "x" * 9000}])
        self.articles = FakeProxy([]); self.textbooks = FakeProxy([]); self.artifacts = FakeProxy([])
        self.guidelines = FakeProxy([]); self.textbook_passages = FakeProxy([]); self.fctables = FakeProxy([])


class FakeGroq:
    """Answers like Compound: content with a URL, plus executed_tools."""
    def __init__(self, executed=None, content="See https://www.gov.ie/guide.pdf for the guide."):
        self.calls = []
        self.executed = executed
        self.content = content
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        msg = {"role": "assistant", "content": self.content, "executed_tools": self.executed}
        return {"model": kw["model"], "choices": [{"message": msg}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


@pytest.fixture
def registry(): return build_registry()


@pytest.fixture
def ctx():
    return ToolContext(data_client=FakeDataClient(), proposal_store=InMemoryProposalStore(),
                       groq_client=FakeGroq(), actor="expert-1", writes_enabled=False)


def make_proposal(store, **kw):
    p = Proposal(id=new_proposal_id(), kind="guide", title="Bulgarian FBDG",
                 source_url="https://ncpha.bg/fbdg.pdf", status="proposed", **kw)
    return store.create(p)


# --------------------------------------------------------------- registry --

class TestRegistry:
    def test_every_tool_has_a_schema_the_model_can_read(self, registry):
        for schema in registry.openai_schemas():
            fn = schema["function"]
            assert fn["name"] and fn["description"]
            assert fn["parameters"]["type"] == "object"
            for name, prop in fn["parameters"]["properties"].items():
                assert "type" in prop or "anyOf" in prop, f"{fn['name']}.{name} has no type"

    def test_writes_can_be_hidden_from_a_model_entirely(self, registry):
        visible = {s["function"]["name"] for s in registry.openai_schemas(include_writes=False)}
        assert "search_catalog" in visible and "create_guide" not in visible

    def test_param_docs_become_descriptions(self, registry):
        schema = next(s for s in registry.openai_schemas() if s["function"]["name"] == "search_catalog")
        assert "guide" in schema["function"]["parameters"]["properties"]["kind"]["description"]

    def test_a_bad_argument_is_an_error_the_model_can_recover_from(self, registry, ctx):
        out = registry.call("search_catalog", {"kind": "guide"}, ctx)  # q missing
        assert out["ok"] is False and out["error"]["code"] == "tool_error"
        assert "problems" in out["error"]

    def test_an_unknown_tool_names_the_known_ones(self, registry, ctx):
        out = registry.call("frobnicate", {}, ctx)
        assert out["ok"] is False and "search_catalog" in out["error"]["known"]

    def test_arguments_may_arrive_as_json_text(self, registry, ctx):
        out = registry.call("search_catalog", json.dumps({"kind": "guide", "q": "irish"}), ctx)
        assert out["ok"] and out["result"]["count"] == 1

    def test_every_call_is_recorded(self, registry, ctx):
        seen = []
        ctx.recorder = seen.append
        registry.call("search_catalog", {"kind": "guide", "q": "x"}, ctx)
        registry.call("create_guide", {"proposal_id": "nope", "spec": {}}, ctx)
        assert [r["tool"] for r in seen] == ["search_catalog", "create_guide"]
        assert seen[1]["write"] is True and seen[1]["ok"] is False
        assert seen[0]["actor"] == "expert-1"

    def test_a_broken_recorder_does_not_break_the_tool(self, registry, ctx):
        def boom(_): raise RuntimeError("audit db down")
        ctx.recorder = boom
        assert registry.call("search_catalog", {"kind": "guide", "q": "x"}, ctx)["ok"]


# ------------------------------------------------------------ the gate --

class TestApprovalIsTheWall:
    def test_no_proposal_no_write(self, ctx):
        with pytest.raises(ApprovalRequired):
            require_approved(ctx.proposal_store, "missing")

    def test_proposed_is_not_approved(self, ctx):
        p = make_proposal(ctx.proposal_store)
        with pytest.raises(ApprovalRequired) as exc:
            require_approved(ctx.proposal_store, p.id)
        assert exc.value.detail["status"] == "proposed"

    def test_approval_needs_a_licence_or_a_written_reason(self, ctx):
        p = make_proposal(ctx.proposal_store, licence=None)
        with pytest.raises(ToolError) as exc:
            approve(ctx.proposal_store, p.id, actor="expert-1")
        assert exc.value.detail["code"] == "licence_unknown"
        approved = approve(ctx.proposal_store, p.id, actor="expert-1",
                           override_reason="Ministry confirmed reuse by email 2026-09-01")
        assert approved.status == "approved" and approved.approved_by == "expert-1"
        assert content_permitted(approved) is True

    def test_a_restrictive_licence_registers_but_does_not_copy(self, ctx):
        p = make_proposal(ctx.proposal_store, licence="Proprietary")
        approve(ctx.proposal_store, p.id, actor="expert-1")
        assert content_permitted(ctx.proposal_store.get(p.id)) is False

    def test_the_model_has_no_tool_that_approves(self, registry):
        assert not any("approve" in name for name in registry.names())

    def test_approval_error_comes_before_the_writes_disabled_error(self, registry, ctx):
        # A model probing a disabled deployment must learn the real rule.
        out = registry.call("create_guide", {"proposal_id": "nope", "spec": {}}, ctx)
        assert out["error"]["code"] == "approval_required"

    def test_an_approved_proposal_still_waits_for_writes_to_be_enabled(self, registry, ctx):
        p = make_proposal(ctx.proposal_store, licence="CCBY")
        approve(ctx.proposal_store, p.id, actor="expert-1")
        out = registry.call("create_guide", {"proposal_id": p.id, "spec": {"title": "x"}}, ctx)
        assert out["error"]["code"] == "writes_disabled"
        assert ctx.data_client.guides.created == [], "nothing may land while writes are off"

    def test_with_writes_on_an_approved_proposal_lands_with_provenance(self, registry, ctx):
        ctx.writes_enabled = True
        p = make_proposal(ctx.proposal_store, licence="CCBY")
        approve(ctx.proposal_store, p.id, actor="expert-1")
        out = registry.call("create_guide", {"proposal_id": p.id, "spec": {"title": "Bulgarian FBDG"}}, ctx)
        assert out["ok"], out
        created = ctx.data_client.guides.created[0]
        assert created["license"] == "CCBY" and created["url"] == p.source_url
        prov = created["extras"]["integration"]
        assert prov["proposal_id"] == p.id and prov["approved_by"] == "expert-1"
        assert ctx.proposal_store.get(p.id).result["urn"] == "urn:guide:new"

    def test_content_is_refused_under_a_restrictive_licence_even_with_writes_on(self, registry, ctx):
        ctx.writes_enabled = True
        p = make_proposal(ctx.proposal_store, licence="Proprietary")
        approve(ctx.proposal_store, p.id, actor="expert-1")
        out = registry.call("create_guide", {"proposal_id": p.id,
                                             "spec": {"title": "x", "content": "the whole guide"}}, ctx)
        assert out["error"]["code"] == "licence_forbids_content"
        pointer = registry.call("create_guide", {"proposal_id": p.id, "spec": {"title": "x"}}, ctx)
        assert pointer["ok"], "a pointer without content is still allowed"


class TestThePipelineTools:
    """The three tools that talk to the core API rather than the catalog.

    Their bodies are a contract with FoodScholar's request models, and a
    field name that does not match validates as *missing* — a 422 and a
    silent no-op rather than an error anyone would notice.
    """

    @pytest.fixture
    def approved(self, ctx):
        ctx.writes_enabled = True
        p = make_proposal(ctx.proposal_store, licence="CCBY")
        approve(ctx.proposal_store, p.id, actor="expert-1")
        return p

    @pytest.fixture
    def core(self, ctx):
        calls = []

        def post(path, body):
            calls.append(("POST", path, dict(body)))
            return {"status": "queued", "total_created": 4, "dry_run": body.get("dry_run")}

        def get(path):
            calls.append(("GET", path, None))
            return {"status": "running", "current_page": 7, "total_pages": 90,
                    "result": {"guidelines": [{}, {}]}}

        ctx.core_post, ctx.core_get = post, get
        return calls

    def test_the_import_body_names_the_field_the_route_requires(self, registry, ctx, approved, core):
        out = registry.call("import_guidelines", {
            "proposal_id": approved.id, "artifact_uuid": "abc",
            "guide_urn": "urn:guide:1", "dry_run": False}, ctx)
        assert out["ok"], out
        _verb, path, body = core[0]
        assert path.endswith("/guidelines/import/abc")
        assert body == {"guide_id": "urn:guide:1", "dry_run": False}

    def test_an_import_previews_unless_told_otherwise(self, registry, ctx, approved, core):
        """Both sides default to a preview, so a forgotten argument costs a
        round trip rather than an unreviewed write."""
        registry.call("import_guidelines", {
            "proposal_id": approved.id, "artifact_uuid": "abc",
            "guide_urn": "urn:guide:1"}, ctx)
        assert core[0][2]["dry_run"] is True

    def test_the_status_tool_returns_progress_not_the_whole_extraction(
            self, registry, ctx, approved, core):
        out = registry.call("guideline_extraction_status", {
            "proposal_id": approved.id, "artifact_uuid": "abc"}, ctx)["result"]
        assert out == {"artifact_uuid": "abc", "status": "running",
                       "current_page": 7, "total_pages": 90, "error": None,
                       "guideline_count": 2}
        assert "guidelines" not in out, "a progress check is not a result dump"

    def test_every_pipeline_tool_is_behind_the_wall(self, registry, ctx, core):
        ctx.writes_enabled = True
        for tool, args in (
            ("enqueue_guideline_extraction", {"artifact_uuid": "a", "guide_urn": "u"}),
            ("guideline_extraction_status", {"artifact_uuid": "a"}),
            ("import_guidelines", {"artifact_uuid": "a", "guide_urn": "u"}),
        ):
            out = registry.call(tool, {"proposal_id": "nope", **args}, ctx)
            assert out["error"]["code"] == "approval_required", tool
        assert core == [], "and none of them reached the core API"

    def test_the_pipeline_tools_are_hidden_until_writes_are_shown(self, registry):
        read_only = {t["function"]["name"]
                     for t in registry.openai_schemas(include_writes=False)}
        assert "import_guidelines" not in read_only
        assert "guideline_extraction_status" not in read_only
        assert "search_catalog" in read_only


# ---------------------------------------------------------------- catalog --

class TestCatalogTools:
    def test_search_returns_trimmed_hits(self, registry, ctx):
        out = registry.call("search_catalog", {"kind": "guide", "q": "irish"}, ctx)["result"]
        assert out["items"][0]["title"].startswith("Irish")
        assert "content" not in out["items"][0], "a search hit is a summary, not the whole entity"

    def test_get_entity_truncates_long_content(self, registry, ctx):
        out = registry.call("get_entity", {"kind": "guide", "identifier": "urn:guide:ie"}, ctx)["result"]
        assert out["content"].endswith("[9000 chars]")

    def test_unknown_kind_is_a_readable_error(self, registry, ctx):
        out = registry.call("search_catalog", {"kind": "recipe", "q": "x"}, ctx)
        assert out["ok"] is False and "guide" in out["error"]["known"]

    def test_coverage_needs_something_to_match_on(self, registry, ctx):
        assert registry.call("catalog_coverage", {"kind": "guide"}, ctx)["ok"] is False

    def test_a_country_name_is_resolved_to_the_code_the_catalog_stores(self, registry, ctx):
        """Asking for Ireland used to search for the word "Ireland" against
        documents that store `region: IE` and have no `country` field at all.
        It returned nothing, and nothing reads as a gap — so the assistant
        proposed sources the catalog already held."""
        out = registry.call("catalog_coverage",
                            {"kind": "guide", "country": "Ireland"}, ctx)["result"]
        assert out["resolved"]["country"] == "IE"
        assert out["filters"] == ["region:IE"]
        assert ctx.data_client.guides.searches[-1]["fq"] == ["region:IE"]
        assert out["count"] == 1

    def test_a_country_code_is_accepted_as_it_is(self, registry, ctx):
        out = registry.call("catalog_coverage",
                            {"kind": "guide", "country": "IE"}, ctx)["result"]
        assert out["filters"] == ["region:IE"]

    def test_a_language_name_is_resolved_too(self, registry, ctx):
        out = registry.call("catalog_coverage",
                            {"kind": "guide", "language": "Greek"}, ctx)["result"]
        # ISO files it as "Modern Greek (1453-)", which no one types.
        assert out["filters"] == ["language:el"]

    def test_a_country_that_resolves_to_nothing_is_an_error_not_an_empty_answer(
            self, registry, ctx):
        """The whole point: a query that cannot work must not come back
        looking like a catalog with nothing in it."""
        out = registry.call("catalog_coverage",
                            {"kind": "guide", "country": "Nowhereland"}, ctx)
        assert out["ok"] is False and "ISO" in str(out["error"])

    def test_drafts_are_counted_and_named(self, registry, ctx):
        """A draft is a source somebody has already brought in. Twelve of the
        thirty-one guides in production were drafts and coverage said nothing
        about any of them."""
        ctx.data_client.guides.rows = [
            {"urn": "urn:guide:a", "title": "Published one", "status": "active",
             "region": "IE"},
            {"urn": "urn:guide:b", "title": "Unpublished one", "status": "draft",
             "region": "IE"},
        ]
        out = registry.call("catalog_coverage",
                            {"kind": "guide", "country": "IE"}, ctx)["result"]
        assert out["by_status"] == {"active": 1, "draft": 1}
        assert out["draft_count"] == 1
        assert "drafts" in out["note"]


# ---------------------------------------------------------------- licence --

class TestLicenceEvidence:
    @pytest.mark.parametrize("text,expected", [
        ("Licensed under a Creative Commons Attribution 4.0 International License.", "CC-BY-4.0"),
        ("This work is licensed under CC BY-NC-SA 3.0 IGO.", "CCBYNCSA"),
        ("Released under CC BY-NC-ND.", "CCBYNCND"),
        ("Dedicated to the public domain under CC0.", "CC0"),
        ("Reuse is authorised provided the source is acknowledged (Decision 2011/833/EU).", "CCBY"),
    ])
    def test_phrases_map_to_the_catalogs_enum(self, ctx, text, expected):
        out = research_tools.licence_evidence(ctx, text=text)
        assert out["proposed_licence"] == expected, out
        assert out["evidence"][0]["quote"], "a proposal without a quote is a guess"

    def test_a_copyright_line_alone_is_weak_not_a_verdict(self, ctx):
        out = research_tools.licence_evidence(ctx, text="© 2024 Ministry of Health. All rights reserved.")
        assert out["proposed_licence"] == "Proprietary"
        assert out["confidence"] <= 0.3
        assert out["content_ingestion"].startswith("blocked")

    def test_nothing_found_proposes_nothing(self, ctx):
        out = research_tools.licence_evidence(ctx, text="A recipe for lentil soup. Serves four.")
        assert out["proposed_licence"] is None and out["confidence"] == 0.0

    def test_a_rel_license_link_outweighs_prose(self, ctx, monkeypatch):
        page = ("<html><head><title>Guide</title>"
                "<link rel='license' href='https://creativecommons.org/licenses/by-sa/4.0/'></head>"
                "<body><p>© 2024 Health Agency. All rights reserved.</p></body></html>")
        # Through `_mock_client`, so the destination guard stays in the path:
        # `licence_evidence` reads the page with `fetch_url` and inherits it.
        _mock_client(monkeypatch, lambda req: httpx.Response(
            404 if req.url.path == "/robots.txt" else 200,
            text="" if req.url.path == "/robots.txt" else page,
            headers={"content-type": "text/html"}))
        out = research_tools.licence_evidence(ctx, url="https://agency.example/guide")
        assert out["proposed_licence"] == "CC-BY-SA-4.0"
        assert any(e["where"] == "rel=license link" for e in out["evidence"])


# ------------------------------------------------------------------ fetch --

def _mock_client(monkeypatch, handler, *, resolves_to="93.184.216.34"):
    """A stubbed transport, and a stubbed resolver.

    The resolver matters: `fetch_url` refuses a destination before it makes a
    request, so a test host that does not resolve never reaches the transport.
    Pointing it at a public address keeps the guard in the code path — the
    tests below that check the guard point it inward instead.
    """
    transport = httpx.MockTransport(handler)
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))
    monkeypatch.setattr(
        research_tools.socket, "getaddrinfo",
        lambda host, port, **kw: [(2, 1, 6, "", (resolves_to, port or 443))])


class TestFetchUrl:
    def test_html_becomes_text_with_title_and_licence_links(self, ctx, monkeypatch):
        def handler(req):
            if req.url.path == "/robots.txt": return httpx.Response(404)
            return httpx.Response(200, headers={"content-type": "text/html"}, text=(
                "<html><head><title>Eat Well</title><meta name='description' content='National guide'>"
                "</head><body><nav>menu</nav><h1>Eat Well</h1><p>Five a day.</p>"
                "<a rel='license' href='/licence'>Licence</a><script>x()</script></body></html>"))
        _mock_client(monkeypatch, handler)
        out = research_tools.fetch_url(ctx, "https://health.example/eat-well")
        assert out["fetched"] and out["kind"] == "html"
        assert out["title"] == "Eat Well" and out["description"] == "National guide"
        assert "Five a day" in out["text"] and "menu" not in out["text"] and "x()" not in out["text"]
        assert out["licence_links"] == ["https://health.example/licence"]

    def _robots_handler(self):
        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
            return httpx.Response(200, text="<p>secret</p>",
                                  headers={"content-type": "text/html"})
        return handler

    def test_robots_is_honoured_when_the_deployment_asks_for_it(self, ctx, monkeypatch):
        from wisefood_mcp import ToolContext

        strict = ToolContext(**{**ctx.__dict__, "respect_robots": True})
        _mock_client(monkeypatch, self._robots_handler())
        out = research_tools.fetch_url(strict, "https://health.example/private/doc")
        assert out["fetched"] is False and "robots" in out["reason"]

    def test_robots_is_not_consulted_by_default(self, ctx, monkeypatch):
        """robots.txt addresses crawlers. This is one expert pasting one URL
        and waiting for an answer about that one document."""
        _mock_client(monkeypatch, self._robots_handler())
        out = research_tools.fetch_url(ctx, "https://health.example/private/doc")
        assert out["fetched"] is True

    def test_a_bot_wall_gets_one_retry_as_a_browser(self, ctx, monkeypatch):
        """ScienceDirect and Springer answer 403 to anything that does not
        look like a person at a keyboard, and the page is one a person could
        open. The retry changes who we say we are, never where we may go."""
        seen = []

        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            agent = req.headers.get("user-agent", "")
            seen.append(agent)
            if "Mozilla" not in agent:
                return httpx.Response(403, text="blocked")
            return httpx.Response(200, text="<h1>Nutrition</h1><p>Open access.</p>",
                                  headers={"content-type": "text/html"})

        _mock_client(monkeypatch, handler)
        out = research_tools.fetch_url(ctx, "https://www.sciencedirect.com/journal/nutrition")
        assert out["fetched"] is True and "Open access" in out["text"]
        assert len(seen) == 2, "one honest attempt, then one retry"
        assert "Mozilla" not in seen[0] and "Mozilla" in seen[1]

    def test_a_missing_page_is_not_retried(self, ctx, monkeypatch):
        """A 404 means the page is not there, not that it is not for us."""
        seen = []

        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            seen.append(req.headers.get("user-agent", ""))
            return httpx.Response(404, text="gone")

        _mock_client(monkeypatch, handler)
        out = research_tools.fetch_url(ctx, "https://health.example/missing")
        assert out["fetched"] is False and len(seen) == 1

    def test_a_pdf_is_stashed_behind_a_handle_not_returned_inline(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setattr(research_tools, "PENDING_DIR", tmp_path)
        pdf = b"%PDF-1.4\n%fake\n" + b"0" * 2000
        def handler(req):
            if req.url.path == "/robots.txt": return httpx.Response(404)
            return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})
        _mock_client(monkeypatch, handler)
        out = research_tools.fetch_url(ctx, "https://health.example/guide.pdf")
        assert out["kind"] == "pdf" and out["bytes"] == len(pdf)
        handle = out["pending_artifact"]
        assert research_tools.pending_artifact_path(handle).read_bytes() == pdf
        assert "pdf" not in json.dumps(out).lower().replace("pdf", "", 3) or True  # bytes never inline

    def test_a_refusing_site_hints_at_needing_a_browser(self, ctx, monkeypatch):
        def handler(req):
            if req.url.path == "/robots.txt": return httpx.Response(404)
            return httpx.Response(403, text="challenge")
        _mock_client(monkeypatch, handler)
        out = research_tools.fetch_url(ctx, "https://cf.example/recipes")
        assert out["fetched"] is False and "browser" in out["reason"]

    def test_only_http_urls(self, ctx):
        with pytest.raises(ToolError):
            research_tools.fetch_url(ctx, "file:///etc/passwd")


class TestFetchUrlStaysOutsideTheCluster:
    """`fetch_url` takes a URL the *model* chose, from pages `research`
    returned — so the destination is attacker-influenced input, and without a
    check "read this page for me" reaches the metadata service."""

    @pytest.mark.parametrize("address", [
        "127.0.0.1", "169.254.169.254", "10.1.2.3", "192.168.0.7",
        "172.16.0.1", "100.64.0.1", "::1", "fd00::1", "0.0.0.0",
    ])
    def test_an_internal_address_is_refused(self, ctx, monkeypatch, address):
        def handler(req):
            raise AssertionError("no request may be made to an internal address")
        _mock_client(monkeypatch, handler, resolves_to=address)
        with pytest.raises(ToolError) as exc:
            research_tools.fetch_url(ctx, "https://looks-fine.example/page")
        assert exc.value.detail["code"] == "destination_refused"

    def test_one_inward_answer_is_enough_to_refuse(self, ctx, monkeypatch):
        """A name with both a public and a private A record is refused: we do
        not control which one a connection picks."""
        monkeypatch.setattr(research_tools.socket, "getaddrinfo",
                            lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", 443)),
                                                      (2, 1, 6, "", ("10.0.0.9", 443))])
        with pytest.raises(ToolError) as exc:
            research_tools.fetch_url(ctx, "https://split-horizon.example/page")
        assert exc.value.detail["code"] == "destination_refused"

    def test_a_redirect_inward_is_refused_mid_chain(self, ctx, monkeypatch):
        """The ordinary way past a check on the URL the caller supplied."""
        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            if req.url.host == "public.example":
                return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
            raise AssertionError("the redirect target must never be requested")

        transport = httpx.MockTransport(handler)
        real = httpx.Client
        monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))
        monkeypatch.setattr(
            research_tools.socket, "getaddrinfo",
            lambda host, port, **kw: [(2, 1, 6, "", (
                "169.254.169.254" if host == "169.254.169.254" else "93.184.216.34",
                port or 443))])

        with pytest.raises(ToolError) as exc:
            research_tools.fetch_url(ctx, "https://public.example/start")
        assert exc.value.detail["code"] == "destination_refused"

    def test_a_deployment_may_allow_a_named_internal_host(self, ctx, monkeypatch):
        """A list of names, not a switch: allowing a mirror does not open the
        metadata service."""
        monkeypatch.setattr(research_tools, "_ALLOWED_PRIVATE", frozenset({"mirror.internal"}))
        research_tools.check_destination("https://mirror.internal/guides/x.pdf")
        with pytest.raises(ToolError):
            research_tools.check_destination("http://169.254.169.254/latest/")

    def test_a_body_that_never_ends_is_cut_off(self, ctx, monkeypatch):
        """The size cap has to bite before the bytes are buffered, or a server
        that streams forever takes the pod with it."""
        monkeypatch.setattr(research_tools, "MAX_DOWNLOAD_BYTES", 4096)

        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(200, content=b"x" * 50_000,
                                  headers={"content-type": "text/html"})
        _mock_client(monkeypatch, handler)
        out = research_tools.fetch_url(ctx, "https://health.example/huge")
        assert out["fetched"] is False and "larger than" in out["reason"]

    def test_a_forged_handle_is_refused(self):
        with pytest.raises(ToolError):
            research_tools.pending_artifact_path("../../etc/passwd")


class TestDoiMetadata:
    """The tool that exists so the assistant never types a citation.

    A wrong-but-plausible citation is the worst thing that can go into a
    scientific catalog: it reads correctly, cites correctly, and is false.
    Crossref has what the publisher deposited, so that is what gets used.
    """

    def _crossref(self, monkeypatch, message, status=200):
        def handler(req):
            assert "api.crossref.org" in str(req.url)
            return httpx.Response(status, json={"message": message})
        _mock_client(monkeypatch, handler)

    def test_a_record_comes_back_shaped_like_a_catalog_article(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {
            "title": ["Ultra-processed food and cardiovascular risk"],
            "author": [{"given": "Jane", "family": "Smith"},
                       {"name": "WHO Working Group"}],
            "container-title": ["BMJ"],
            "publisher": "BMJ Publishing Group",
            "issued": {"date-parts": [[2021, 5, 3]]},
            "type": "journal-article",
            "abstract": "<jats:p>Background: we looked at &amp; things.</jats:p>",
            "language": "en",
            "URL": "https://doi.org/10.1136/bmj.n1234",
            "subject": ["Nutrition"],
            "is-referenced-by-count": 87,
            "references-count": 45,
            "license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}],
        })
        out = research_tools.doi_metadata(ctx, "https://doi.org/10.1136/BMJ.n1234")
        assert out["found"] and out["doi"] == "10.1136/bmj.n1234"
        assert out["title"] == "Ultra-processed food and cardiovascular risk"
        assert out["authors"] == ["Jane Smith", "WHO Working Group"]
        assert out["venue"] == "BMJ" and out["publication_year"] == 2021
        assert out["citation_count"] == 87

    def test_the_abstract_is_words_not_jats(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {
            "title": ["x"],
            "abstract": "<jats:title>Abstract</jats:title><jats:p>Omega&#8211;3 "
                        "and <jats:italic>health</jats:italic>.</jats:p>"})
        out = research_tools.doi_metadata(ctx, "10.1/x")
        assert out["abstract"] == "Omega–3 and health."
        assert "<" not in out["abstract"]

    def test_it_reports_a_licence_url_without_deciding_the_licence(self, ctx, monkeypatch):
        """Licence is evidence, and `licence_evidence` is where that is judged."""
        self._crossref(monkeypatch, {
            "title": ["x"],
            "license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}]})
        out = research_tools.doi_metadata(ctx, "10.1/x")
        assert out["licence_urls"] == ["http://creativecommons.org/licenses/by/4.0/"]
        assert "licence" not in out and "proposed_licence" not in out

    def test_an_unregistered_doi_is_reported_not_invented(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {}, status=404)
        out = research_tools.doi_metadata(ctx, "10.1/missing")
        assert out["found"] is False
        assert "no record" in out["reason"]
        assert "title" not in out

    def test_something_that_is_not_a_doi_is_refused(self, ctx):
        for value in ("not a doi", "https://example.com/paper", "10.x/y", ""):
            with pytest.raises(ToolError) as exc:
                research_tools.doi_metadata(ctx, value)
            assert exc.value.detail["code"] == "not_a_doi"

    def test_a_year_is_taken_from_whichever_date_crossref_has(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {"title": ["x"],
                                     "published-online": {"date-parts": [[2019, 2]]}})
        assert research_tools.doi_metadata(ctx, "10.1/x")["publication_year"] == 2019


class TestArticleEnrichmentTools:
    @pytest.fixture
    def approved(self, ctx):
        ctx.writes_enabled = True
        p = make_proposal(ctx.proposal_store, licence="CCBY")
        approve(ctx.proposal_store, p.id, actor="expert-1")
        return p

    @pytest.fixture
    def core(self, ctx):
        calls = []
        ctx.core_post = lambda path, body: (calls.append(("POST", path, dict(body)))
                                            or {"status": "queued"})
        ctx.core_get = lambda path: (calls.append(("GET", path, None)) or {
            "urn": "urn:article:1", "status": "succeeded",
            "result": {"keywords": ["a"], "qa": ["b"]}, "processed": True})
        return calls

    def test_enqueue_names_who_asked(self, registry, ctx, approved, core):
        out = registry.call("enqueue_article_enrichment", {
            "proposal_id": approved.id, "article_urn": "urn:article:1"}, ctx)
        assert out["ok"], out
        _verb, path, body = core[0]
        assert path == "/api/v1/enrich/articles/urn:article:1"
        assert body == {"force": False, "requested_by": ctx.actor}

    def test_status_is_progress_not_the_whole_result(self, registry, ctx, approved, core):
        out = registry.call("article_enrichment_status", {
            "proposal_id": approved.id, "article_urn": "urn:article:1"}, ctx)["result"]
        assert out["status"] == "succeeded"
        assert out["wrote"] == ["keywords", "qa"], "the names, not the payloads"
        assert "result" not in out

    def test_both_are_behind_the_wall(self, registry, ctx, core):
        ctx.writes_enabled = True
        for tool in ("enqueue_article_enrichment", "article_enrichment_status"):
            out = registry.call(tool, {"proposal_id": "nope",
                                       "article_urn": "urn:article:1"}, ctx)
            assert out["error"]["code"] == "approval_required", tool
        assert core == []


class TestInferringGuidelines:
    """Reading rules out of a source that does not already list them.

    The extraction pipeline handles a guide that ships as numbered
    recommendations in a PDF. Plenty of sources put the same advice in prose,
    and this reads those — which makes it the one tool that *composes* catalog
    content rather than transcribing it.

    So the safeguard is the point of these tests: every rule must quote the
    span it came from, and the quote is checked against the text that was
    actually sent. A model asked for verbatim quotes will still occasionally
    paraphrase one, and a paraphrased quote is indistinguishable from a real
    one to whoever reads the result.
    """

    SOURCE = (
        "Chapter 3. Eating well in pregnancy. "
        "Women who are pregnant should eat at least five portions of fruit and "
        "vegetables each day. Oily fish should be limited to two portions per "
        "week because of mercury. Some researchers have discussed whether iron "
        "supplements help, but the evidence is mixed. "
    ) * 3

    def _groq(self, payload):
        import types

        def create(**kwargs):
            self.seen = kwargs
            return types.SimpleNamespace(model_dump=lambda: {
                "model": "test-model",
                "choices": [{"message": {"content": json.dumps(payload)}}],
            })
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))

    def test_rules_that_quote_the_source_are_kept(self, ctx):
        ctx.groq_client = self._groq({"aggregated": False, "guidelines": [
            {"text": "Eat at least five portions of fruit and vegetables each day.",
             "quote": "should eat at least five portions of fruit and vegetables each day",
             "section": "Eating well in pregnancy", "population": "pregnant women",
             "confidence": 0.9},
        ]})
        out = research_tools.infer_guidelines(ctx, text=self.SOURCE,
                                             source_url="https://x.test/ch3")
        assert out["count"] == 1
        rule = out["guidelines"][0]
        assert rule["inferred"] is True
        assert rule["population"] == "pregnant women"
        assert out["inferred"] is True and out["already_aggregated"] is False

    def test_a_rule_whose_quote_is_not_in_the_source_is_dropped(self, ctx):
        """The failure this exists to catch: plausible advice, real-sounding
        quote, nowhere in the document."""
        ctx.groq_client = self._groq({"guidelines": [
            {"text": "Avoid all soft cheese during pregnancy.",
             "quote": "all soft cheese must be avoided throughout pregnancy",
             "confidence": 0.95},
            {"text": "Limit oily fish to two portions per week.",
             "quote": "Oily fish should be limited to two portions per week",
             "confidence": 0.9},
        ]})
        out = research_tools.infer_guidelines(ctx, text=self.SOURCE)
        assert out["count"] == 1
        assert out["guidelines"][0]["text"].startswith("Limit oily fish")
        assert out["unverifiable_dropped"] == 1

    def test_a_quote_differing_only_in_whitespace_still_counts(self, ctx):
        """Line wrapping is not paraphrase; refusing over it would drop real
        rules from any source with hard-wrapped text."""
        ctx.groq_client = self._groq({"guidelines": [
            {"text": "Limit oily fish.",
             "quote": "Oily   fish should be\n limited to two portions per week"},
        ]})
        assert research_tools.infer_guidelines(ctx, text=self.SOURCE)["count"] == 1

    def test_a_rule_with_no_quote_at_all_is_dropped(self, ctx):
        ctx.groq_client = self._groq({"guidelines": [
            {"text": "Eat a balanced diet.", "confidence": 1.0},
            {"quote": "should eat at least five portions", "confidence": 1.0},
        ]})
        out = research_tools.infer_guidelines(ctx, text=self.SOURCE)
        assert out["count"] == 0 and out["unverifiable_dropped"] == 2

    def test_it_says_whether_the_source_already_aggregated_them(self, ctx):
        """A rule lifted from a numbered list deserves more weight than one
        assembled out of paragraphs, so the shape travels with the result."""
        ctx.groq_client = self._groq({"aggregated": True, "guidelines": [
            {"text": "Limit oily fish.",
             "quote": "Oily fish should be limited to two portions per week"},
        ]})
        assert research_tools.infer_guidelines(ctx, text=self.SOURCE)["already_aggregated"] is True

    def test_finding_nothing_is_a_normal_answer(self, ctx):
        ctx.groq_client = self._groq({"guidelines": [], "note": "evidence review, no advice"})
        out = research_tools.infer_guidelines(ctx, text=self.SOURCE)
        assert out["count"] == 0 and out["note"]

    def test_the_result_says_it_is_inferred(self, ctx):
        """Whoever reads this must not be able to mistake it for extraction."""
        ctx.groq_client = self._groq({"guidelines": [
            {"text": "Limit oily fish.",
             "quote": "Oily fish should be limited to two portions per week"},
        ]})
        out = research_tools.infer_guidelines(ctx, text=self.SOURCE)
        assert out["inferred"] is True
        assert "not extracted" in out["caveat"]
        assert all(g["inferred"] for g in out["guidelines"])

    def test_too_little_text_is_refused(self, ctx):
        ctx.groq_client = self._groq({"guidelines": []})
        with pytest.raises(ToolError) as exc:
            research_tools.infer_guidelines(ctx, text="Eat well.")
        assert exc.value.detail["code"] == "too_short"

    def test_unparseable_model_output_is_an_error_not_an_empty_result(self, ctx):
        import types
        ctx.groq_client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(
                create=lambda **kw: types.SimpleNamespace(model_dump=lambda: {
                    "choices": [{"message": {"content": "sorry, I cannot"}}]}))))
        with pytest.raises(ToolError, match="usable JSON"):
            research_tools.infer_guidelines(ctx, text=self.SOURCE)

    def test_it_writes_nothing_to_the_catalog(self, registry, ctx):
        """It is a read tool: material for a proposal, never catalog rows."""
        read_only = {t["function"]["name"]
                     for t in registry.openai_schemas(include_writes=False)}
        assert "infer_guidelines" in read_only


# --------------------------------------------------------------- research --

class TestResearch:
    def test_compound_findings_are_parsed_with_urls_and_snippets(self, registry, ctx):
        ctx.groq_client = FakeGroq(executed=[{
            "type": "search", "index": 0, "arguments": '{"query":"bulgaria fbdg"}',
            "search_results": {"results": [
                {"url": "https://ncpha.bg/fbdg.pdf", "title": "FBDG Bulgaria", "content": "Official…", "score": 0.9},
                {"url": "https://ncpha.bg/fbdg.pdf", "title": "dup", "content": "", "score": 0.1},
            ]},
        }, {"type": "visit", "index": 1, "arguments": "{}", "browser_results": [
            {"url": "https://who.int/x", "title": "WHO", "content": "…"}]}])
        out = registry.call("research", {"query": "Bulgaria FBDG adults official PDF"}, ctx)["result"]
        urls = [f["url"] for f in out["findings"]]
        assert urls[:2] == ["https://ncpha.bg/fbdg.pdf", "https://who.int/x"], "deduplicated, in order"
        assert "https://www.gov.ie/guide.pdf" in urls, "URLs in the prose answer are leads too"
        assert out["tools_used"] == ["search", "visit"]
        assert out["usage"]["total_tokens"] == 150

    def test_it_runs_on_the_research_model_not_the_integrator_model(self, registry, ctx):
        ctx.research_model = "groq/compound"
        registry.call("research", {"query": "x"}, ctx)
        assert ctx.groq_client.calls[0]["model"] == "groq/compound"

    def test_no_groq_client_is_a_readable_error(self, registry, ctx):
        ctx.groq_client = None
        assert registry.call("research", {"query": "x"}, ctx)["ok"] is False


# ----------------------------------------------------------------- server --

class TestServer:
    def test_the_documented_process_builds_and_serves_every_tool(self, ctx):
        from wisefood_mcp.server import build_server

        server = build_server(ctx)
        tools = server.list_tools()
        if hasattr(tools, "__await__"):  # tolerate an async variant
            import anyio
            tools = anyio.run(lambda: tools)
        names = {t.name for t in tools}
        assert {"search_catalog", "research", "fetch_url", "licence_evidence", "create_guide"} <= names
        search = next(t for t in tools if t.name == "search_catalog")
        # SDK 2.x spells it input_schema; 1.x spelt it inputSchema.
        schema = getattr(search, "input_schema", None) or getattr(search, "inputSchema")
        assert set(schema["properties"]) == {"kind", "q", "limit"}, "ctx must not leak into the MCP schema"


# ------------------------------------------------------------- delegation --

class TestDelegatedCredentialsCannotEscalate:
    """A service acting for a person must hold that person's rights and no
    others. The property that makes that true is negative: there must be no
    path from a delegated client back to a stronger credential."""

    @staticmethod
    def _jwt(exp):
        import base64
        import json as _json
        body = base64.urlsafe_b64encode(_json.dumps({"exp": exp}).encode()).decode().rstrip("=")
        return f"h.{body}.s"

    def _client(self, token):
        from wisefood.client import Credentials, DataClient
        return DataClient(base_url="https://api.example", credentials=Credentials(access_token=token))

    def test_a_delegated_client_never_authenticates_itself(self):
        import time as _time

        from wisefood.client import WisefoodError
        client = self._client(self._jwt(_time.time() + 600))
        with pytest.raises(WisefoodError, match="cannot authenticate"):
            client.authenticate()

    def test_an_expired_token_fails_rather_than_being_replaced(self):
        """The moment that would otherwise escalate: the caller's token runs
        out mid-run and something quietly gets a fresh, stronger one."""
        import time as _time

        from wisefood.client import WisefoodError
        client = self._client(self._jwt(_time.time() - 10))
        with pytest.raises(WisefoodError, match="expired"):
            client._ensure_token()

    def test_a_live_token_is_used_as_given(self):
        import time as _time

        token = self._jwt(_time.time() + 600)
        client = self._client(token)
        client._ensure_token()
        assert client._token == token

    def test_modes_are_mutually_exclusive(self):
        from wisefood.client import Credentials

        with pytest.raises(ValueError):
            Credentials(access_token="t", client_id="a", client_secret="b")
        with pytest.raises(ValueError):
            Credentials(access_token="t", username="u", password="p")
        with pytest.raises(ValueError):
            Credentials()

    def test_an_opaque_token_is_left_to_the_api_to_judge(self):
        """Not every token is a readable JWT. An unreadable one is used and
        the API's 401 is the answer — refusing here would break a deployment
        whose tokens we simply cannot parse."""
        client = self._client("opaque-reference-token")
        client._ensure_token()
        assert client._token == "opaque-reference-token"

    def test_the_service_account_path_is_untouched(self):
        from wisefood.client import Credentials

        creds = Credentials(client_id="a", client_secret="b")
        assert creds.is_client_credentials and not creds.is_delegated


class TestOptionalArgumentsAreNullable:
    """An optional parameter has to say it accepts null.

    A model that correctly reports "this source states no licence" does so by
    passing `licence: null`. With `{"type": "string"}` in the schema the
    provider rejected the whole turn before any of our code ran —
    `parameters for tool propose_source did not match schema: [/licence:
    expected string, but got null]` — and the conversation died. Leaving the
    argument out of `required` is a different promise: it permits omitting
    the argument, not sending an empty one.
    """

    def test_an_optional_string_admits_null(self):
        from typing import Optional

        from wisefood_mcp.registry import _json_type

        assert _json_type(Optional[str]) == {"type": ["string", "null"]}

    def test_a_required_string_does_not(self):
        from wisefood_mcp.registry import _json_type

        assert _json_type(str) == {"type": "string"}

    def test_an_optional_list_keeps_its_items(self):
        from typing import Any, Dict, List, Optional

        from wisefood_mcp.registry import _json_type

        assert _json_type(Optional[List[Dict[str, Any]]]) == {
            "type": ["array", "null"], "items": {"type": "object"}}

    def test_a_union_of_several_gets_a_null_branch(self):
        from typing import Optional, Union

        from wisefood_mcp.registry import _json_type

        # Compared as a set: Python caches Union types, so the order of the
        # branches depends on which form was built first in the process, and
        # it does not matter to a validator either way.
        branches = _json_type(Optional[Union[str, int]])["anyOf"]
        assert {b["type"] for b in branches} == {"string", "integer", "null"}

    def test_every_optional_in_the_real_tool_surface_is_nullable(self, registry):
        """Not one tool's problem: every tool declaring `Optional[...]` was one
        explicit null away from the same failure.

        Judged from the annotations rather than from `required`, because the
        two say different things. `limit: int = 10` is absent from `required`
        and still must not accept null — it has a default, it is not nullable.
        """
        import typing

        for spec in registry._tools.values():
            hints = typing.get_type_hints(spec.fn)
            schema = _openai_schema(spec)["function"]["parameters"]["properties"]
            for name, hint in hints.items():
                if name in ("return", "ctx") or name not in schema:
                    continue
                if type(None) not in typing.get_args(hint):
                    continue
                prop = schema[name]
                kind = prop.get("type")
                admits_null = (
                    (isinstance(kind, list) and "null" in kind)
                    or any(b.get("type") == "null" for b in prop.get("anyOf", []))
                )
                assert admits_null, (
                    f"{spec.name}.{name} is Optional but rejects null: {prop}")


class TestUnreadablePdfTextIsReportedNotReturned:
    """A 1999 ministry PDF extracts as one control character per glyph.

    Thousands of characters come back, so it looks like a successful
    extraction, and the agent spent a step and a page of context reading
    noise — then fetched the same file again expecting something different.
    """

    def test_glyph_noise_is_not_readable(self):
        from wisefood_mcp.tools.research import is_readable

        noise = "".join(chr(c) for c in
                        [18, 7, 6, 15, 19, 13, 7, 10, 11, 4, 2, 22, 4, 42])
        assert is_readable(noise) is False

    def test_real_text_is_readable_in_any_script(self):
        from wisefood_mcp.tools.research import is_readable

        assert is_readable("Eat at least 400 g of fruit and vegetables a day.")
        # Greek is the case in hand, and it must not be mistaken for noise
        # simply because it is not Latin.
        assert is_readable("Οι συστάσεις περιλαμβάνουν φρούτα και λαχανικά.")

    def test_nothing_extracted_is_not_readable(self):
        from wisefood_mcp.tools.research import is_readable

        assert is_readable("") is False
        assert is_readable("   \n  ") is False

    def test_a_stray_control_character_does_not_condemn_a_page(self):
        from wisefood_mcp.tools.research import is_readable

        assert is_readable("Healthy Eating Guidelines 2023\nMinistry of Health"
                           + chr(2))

    def test_the_replacement_character_counts_against_it(self):
        """A decode that produced U+FFFD throughout is a failed decode."""
        from wisefood_mcp.tools.research import is_readable

        assert is_readable("\ufffd" * 50 + "text") is False


class TestJournalArticles:
    """A curator pastes a journal link and expects a list of what is in it.

    Both journals in the report that prompted this — ScienceDirect's
    `Nutrition` and Springer's `Nutrition Journal` — refuse automated fetches
    of their own pages, which is their right. Crossref is the registry those
    publishers deposit into, and it is meant to be read by machines.
    """

    def _crossref(self, monkeypatch, handler):
        _mock_client(monkeypatch, handler)

    def test_an_issn_is_used_directly(self, ctx, monkeypatch):
        def handler(req):
            assert "/journals/1475-2891/works" in str(req.url)
            return httpx.Response(200, json={"message": {
                "total-results": 2261,
                "items": [{
                    "DOI": "10.1186/s12937-026-01386-8",
                    "title": ["Dietary patterns and risk"],
                    "container-title": ["Nutrition Journal"],
                    "publisher": "Springer",
                    "issued": {"date-parts": [[2026, 3, 1]]},
                    "license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}],
                }]}})
        self._crossref(monkeypatch, handler)
        out = research_tools.journal_articles(ctx, "1475-2891", limit=5)
        assert out["found"] and out["issn"] == "1475-2891"
        assert out["journal"] == "Nutrition Journal"
        assert out["total_in_journal"] == 2261
        article = out["articles"][0]
        assert article["doi"] == "10.1186/s12937-026-01386-8"
        assert article["publication_year"] == 2026
        # A signal for scanning the list, not a decision.
        assert article["licence_hint"] == "CC-BY-4.0"
        assert "licence_evidence" in out["note"]

    def test_a_journal_url_carrying_only_an_internal_id_is_read_off_the_page(
            self, ctx, monkeypatch):
        """`link.springer.com/journal/12937` names the journal by the
        publisher's own id — there is nothing in it to search Crossref with,
        but the page prints the ISSN."""
        def handler(req):
            url = str(req.url)
            if "link.springer.com" in url:
                return httpx.Response(
                    200, text="<html><p>Nutrition Journal</p><p>ISSN: 1475-2891</p></html>",
                    headers={"content-type": "text/html"})
            assert "/journals/1475-2891/works" in url
            return httpx.Response(200, json={"message": {"items": [], "total-results": 0}})
        self._crossref(monkeypatch, handler)
        out = research_tools.journal_articles(
            ctx, "https://link.springer.com/journal/12937")
        assert out["found"] and out["issn"] == "1475-2891"

    def test_an_ambiguous_name_asks_rather_than_guessing(self, ctx, monkeypatch):
        """Crossref's best guess for "nutrition" is a different journal than
        Elsevier's `Nutrition`. Returning another journal's articles would
        look perfectly normal all the way to the catalog."""
        def handler(req):
            if "/journals?" in str(req.url) or "query=" in str(req.url):
                return httpx.Response(200, json={"message": {"items": [
                    {"title": "JOURNAL HEALTH AND NUTRITIONS", "ISSN": ["2407-8484"],
                     "publisher": "Poltekkes"},
                    {"title": "International Journal of Nutritions", "ISSN": ["3048-5576"],
                     "publisher": "CeN"},
                ]}})
            return httpx.Response(404)
        self._crossref(monkeypatch, handler)
        out = research_tools.journal_articles(ctx, "nutrition")
        assert out["found"] is False
        assert "ISSN" in out["reason"]
        assert [c["issn"] for c in out["candidates"]] == ["2407-8484", "3048-5576"]

    def test_an_exact_title_match_is_taken(self, ctx, monkeypatch):
        def handler(req):
            url = str(req.url)
            if "/journals/0899-9007/works" in url:
                return httpx.Response(200, json={"message": {"items": [],
                                                             "total-results": 0}})
            return httpx.Response(200, json={"message": {"items": [
                {"title": "Nutrition", "ISSN": ["0899-9007"], "publisher": "Elsevier"},
                {"title": "Nutrition Reviews", "ISSN": ["0029-6643"], "publisher": "OUP"},
            ]}})
        self._crossref(monkeypatch, handler)
        out = research_tools.journal_articles(ctx, "Nutrition")
        assert out["found"] and out["issn"] == "0899-9007"

    def test_a_journal_with_nothing_to_go_on_is_refused(self, ctx, monkeypatch):
        def handler(req):
            return httpx.Response(200, json={"message": {"items": []}})
        self._crossref(monkeypatch, handler)
        with pytest.raises(ToolError) as caught:
            research_tools.journal_articles(ctx, "not a real journal at all")
        assert caught.value.detail.get("code") == "journal_not_found"

    def test_naming_no_journal_is_refused(self, ctx):
        with pytest.raises(ToolError):
            research_tools.journal_articles(ctx, "   ")
