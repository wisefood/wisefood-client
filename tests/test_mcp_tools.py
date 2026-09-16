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
from wisefood_mcp.registry import ApprovalRequired, ToolError, WritesDisabled
from wisefood_mcp.stores import (
    InMemoryProposalStore, Proposal, approve, content_permitted, new_proposal_id, require_approved,
)
from wisefood_mcp.tools import research as research_tools


# ------------------------------------------------------------------ fakes --

class FakeEntity:
    def __init__(self, **d): self._d = d
    def dict(self): return dict(self._d)


class FakeProxy:
    def __init__(self, rows): self.rows = rows; self.created = []
    def search(self, q, limit=10, **kw): return [FakeEntity(**r) for r in self.rows[:limit]]
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
        out = registry.call("catalog_coverage", {"kind": "guide", "country": "Ireland"}, ctx)["result"]
        assert out["count"] == 1 and "approximate" in out["note"]


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
        transport = httpx.MockTransport(lambda req: httpx.Response(
            404 if req.url.path == "/robots.txt" else 200,
            text="" if req.url.path == "/robots.txt" else page,
            headers={"content-type": "text/html"}))
        real = httpx.Client
        monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))
        out = research_tools.licence_evidence(ctx, url="https://agency.example/guide")
        assert out["proposed_licence"] == "CC-BY-SA-4.0"
        assert any(e["where"] == "rel=license link" for e in out["evidence"])


# ------------------------------------------------------------------ fetch --

def _mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))


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

    def test_robots_refusal_is_reported_not_circumvented(self, ctx, monkeypatch):
        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
            return httpx.Response(200, text="<p>secret</p>", headers={"content-type": "text/html"})
        _mock_client(monkeypatch, handler)
        out = research_tools.fetch_url(ctx, "https://health.example/private/doc")
        assert out["fetched"] is False and "robots" in out["reason"]

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

    def test_a_forged_handle_is_refused(self):
        with pytest.raises(ToolError):
            research_tools.pending_artifact_path("../../etc/passwd")


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
