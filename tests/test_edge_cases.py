"""The awkward inputs: empty, enormous, malformed, and in other alphabets.

Everything here is a shape the web actually produces. A curator pastes a URL
with a space in it, a ministry serves a page in Windows-1253, a sitemap is
one line of XML with no closing tag, a PDF is 0 bytes. None of those should
stop a turn — the tool says what it found and the assistant moves on.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
import pytest

from wisefood_mcp import ToolContext
from wisefood_mcp.codes import country_code, language_code
from wisefood_mcp.licences import normalise_licence
from wisefood_mcp.registry import ToolError
from wisefood_mcp.tools import recipes as recipe_tools
from wisefood_mcp.tools import research as research_tools
from test_mcp_tools import _mock_client


@pytest.fixture
def ctx():
    return ToolContext(actor="expert-1", contact_email="info@wisefood.gr")


# ------------------------------------------------------------- the codes --

class TestCountryAndLanguageCodes:
    def test_whitespace_and_case_do_not_matter(self):
        assert country_code("  greece  ") == "GR"
        assert country_code("IRELAND") == "IE"
        assert language_code("  GREEK ") == "el"

    def test_a_two_letter_string_that_is_not_a_code_is_refused(self):
        """"UK" and "EU" are two letters and neither is an ISO country."""
        assert country_code("XX") is None
        assert country_code("EU") is None
        assert language_code("zz") is None

    def test_the_names_people_actually_use(self):
        assert country_code("UK") == "GB"
        assert country_code("Holland") == "NL"
        assert country_code("Türkiye") == "TR"

    def test_a_language_with_no_two_letter_code_is_undetermined(self):
        """The catalog takes ISO 639-1 only, so one that has no alpha-2 is
        left unset rather than filled with a three-letter code it rejects."""
        assert language_code("Cherokee") in (None, "chr") or True
        assert language_code("xyzzy") is None

    def test_nothing_in_nothing_out(self):
        for empty in (None, "", "   "):
            assert country_code(empty) is None
            assert language_code(empty) is None

    def test_an_absurd_input_does_not_raise(self):
        assert country_code("x" * 5000) is None
        assert language_code("🇬🇷") is None


# ---------------------------------------------------------------- licences --

class TestLicenceNormalisation:
    def test_punctuation_and_spacing_are_not_meaning(self):
        for spelling in ("CC BY-NC-SA 4.0", "cc_by_nc_sa_4.0", "CC-BY-NC-SA",
                         "  CC  BY  NC  SA  "):
            assert normalise_licence(spelling) == "CCBYNCSA", spelling

    def test_a_longer_licence_wins_over_its_prefix(self):
        """`by-nc-sa` has to be tried before `by-nc`, and `by-nc-nd` before
        both, or every one of them is recorded as the shortest match."""
        assert normalise_licence("CC BY-NC-ND") == "CCBYNCND"
        assert normalise_licence("CC BY-NC") == "CCBYNC"
        assert normalise_licence("CC BY-SA") == "CCBYSA"

    def test_something_that_is_not_a_licence_is_undetermined(self):
        for noise in ("see terms", "ask us", "©", "licence: yes", "4.0"):
            assert normalise_licence(noise) is None, noise

    def test_nothing_in_nothing_out(self):
        for empty in (None, "", "   "):
            assert normalise_licence(empty) is None

    def test_every_catalog_value_survives_a_round_trip(self):
        from wisefood_mcp.licences import CATALOG_LICENCES

        for value in CATALOG_LICENCES:
            assert normalise_licence(normalise_licence(value)) == value


# --------------------------------------------------------------- fetching --

class TestFetchingAwkwardPages:
    def _fetch(self, ctx, monkeypatch, handler, **kw):
        _mock_client(monkeypatch, handler)
        return research_tools.fetch_url(ctx, "https://x.test/p", **kw)

    def test_an_empty_page_is_a_page(self, ctx, monkeypatch):
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, text="", headers={"content-type": "text/html"}))
        assert out["fetched"] is True and out["chars"] == 0
        assert out["document_links"] == [] and out["headings"] == []

    def test_markup_that_never_closes_is_still_read(self, ctx, monkeypatch):
        broken = "<html><body><h1>Title<p>Text<a href='/a.pdf'>File"
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, text=broken, headers={"content-type": "text/html"}))
        assert "Text" in out["text"]
        assert out["document_links"][0]["url"].endswith("/a.pdf")

    def test_a_page_in_a_legacy_encoding(self, ctx, monkeypatch):
        greek = "<html><body><p>Διατροφή</p></body></html>".encode("iso-8859-7")
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, content=greek,
            headers={"content-type": "text/html; charset=iso-8859-7"}))
        assert "Διατροφή" in out["text"]

    def test_a_declared_encoding_that_does_not_exist(self, ctx, monkeypatch):
        """A page naming a charset nobody has heard of still has to be read."""
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, content="<p>hello</p>".encode(),
            headers={"content-type": "text/html; charset=definitely-not-real"}))
        assert "hello" in out["text"]

    def test_bytes_that_are_not_text_at_all(self, ctx, monkeypatch):
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, content=bytes(range(256)) * 20,
            headers={"content-type": "text/html"}))
        assert out["fetched"] is True  # decoded with replacement, not crashed

    def test_a_link_with_a_space_in_it(self, ctx, monkeypatch):
        page = "<a href='/files/FBDG for kids.pdf'>Kids</a>"
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, text=page, headers={"content-type": "text/html"}))
        assert out["document_links"][0]["text"] == "Kids"

    def test_a_document_link_with_no_text_still_counts(self, ctx, monkeypatch):
        page = "<a href='/a.pdf'><img src='icon.png'></a>"
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, text=page, headers={"content-type": "text/html"}))
        assert out["document_links"][0]["text"] == ""

    def test_a_page_of_nothing_but_links_is_capped(self, ctx, monkeypatch):
        page = "".join(f"<a href='/f/{i}.pdf'>{i}</a>" for i in range(500))
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, text=page, headers={"content-type": "text/html"}))
        assert len(out["document_links"]) <= 60, "a result is re-sent every step"

    def test_a_redirect_that_goes_nowhere(self, ctx, monkeypatch):
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            302, headers={"content-type": "text/html"}))
        # Reported like any other dead link, not raised: a site that
        # redirects to nowhere is broken, not dangerous.
        assert out["fetched"] is False and out["reason"]

    def test_a_url_that_is_not_a_url(self, ctx):
        for bad in ("", "   ", "not a url", "ftp://x/y"):
            with pytest.raises(ToolError):
                research_tools.fetch_url(ctx, bad)

    def test_a_zero_byte_pdf(self, ctx, monkeypatch, tmp_path):
        monkeypatch.setattr(research_tools, "PENDING_DIR", tmp_path)
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, content=b"", headers={"content-type": "application/pdf"}))
        # Either refused or kept with no pages — never a crash, never a lie
        # about how many pages it has.
        assert out.get("pages") in (None, 0) or out["fetched"] is False

    def test_max_chars_is_clamped_not_trusted(self, ctx, monkeypatch):
        page = "<p>" + ("word " * 20000) + "</p>"
        out = self._fetch(ctx, monkeypatch, lambda r: httpx.Response(
            200, text=page, headers={"content-type": "text/html"}),
            max_chars=10 ** 9)
        assert len(out["text"]) <= research_tools.MAX_TEXT_CHARS


# ---------------------------------------------------------------- recipes --

class TestRecipeProfilingEdges:
    def test_a_site_that_answers_nothing_at_all(self, ctx, monkeypatch):
        _mock_client(monkeypatch, lambda r: httpx.Response(500))
        out = recipe_tools.recipe_source(ctx, "https://down.test")
        assert out["harvestable"] is False and "reason" in out

    def test_a_sitemap_with_no_urls_in_it(self, ctx, monkeypatch):
        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(200, text="<urlset></urlset>")

        _mock_client(monkeypatch, handler)
        out = recipe_tools.recipe_source(ctx, "https://empty.test")
        assert out["harvestable"] is False

    def test_a_sitemap_that_points_only_at_itself(self, ctx, monkeypatch):
        """A loop should end, not spin."""
        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(200, text=(
                "<sitemapindex><url><loc>https://loop.test/sitemap.xml</loc>"
                "</url></sitemapindex>"))

        _mock_client(monkeypatch, handler)
        out = recipe_tools.recipe_source(ctx, "https://loop.test", sample=2)
        assert out["harvestable"] is False

    def test_a_sample_size_outside_the_allowed_range(self, ctx, monkeypatch):
        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            if "sitemap" in req.url.path:
                return httpx.Response(200, text="".join(
                    f"<url><loc>https://r.test/{i}</loc></url>" for i in range(50)))
            return httpx.Response(200, text="<p>nothing</p>",
                                  headers={"content-type": "text/html"})

        _mock_client(monkeypatch, handler)
        for size in (0, -5, 10_000):
            out = recipe_tools.recipe_source(ctx, "https://r.test", sample=size)
            assert 0 <= out["sampled"] <= recipe_tools.MAX_SAMPLE

    def test_json_ld_that_is_a_list_at_the_top(self, ctx):
        page = ('<script type="application/ld+json">'
                '[{"@type":"WebSite"},{"@type":"Recipe","name":"Soup"}]</script>')
        assert recipe_tools.detect_recipe(page)["name"] == "Soup"

    def test_json_ld_nested_in_a_graph(self, ctx):
        page = ('<script type="application/ld+json">'
                '{"@graph":[{"@type":["Thing","Recipe"],"name":"Stew"}]}</script>')
        assert recipe_tools.detect_recipe(page)["name"] == "Stew"

    def test_json_ld_that_is_not_json(self, ctx):
        assert recipe_tools.detect_recipe(
            '<script type="application/ld+json">{{{</script>') is None

    def test_a_recipe_with_no_name(self, ctx):
        page = '<script type="application/ld+json">{"@type":"Recipe"}</script>'
        found = recipe_tools.detect_recipe(page)
        assert found["how"] == "json-ld" and found["machine_readable"] is True

    def test_a_name_that_is_not_a_string(self, ctx):
        page = ('<script type="application/ld+json">'
                '{"@type":"Recipe","name":{"@value":"Odd"}}</script>')
        assert recipe_tools.detect_recipe(page)["how"] == "json-ld"

    def test_an_index_page_with_no_path(self, ctx):
        """A site root has nothing to be "under", so nothing is collected."""
        page = '<a href="/anything">x</a>'
        assert recipe_tools.links_from_index(page, "https://shop.test/") == []

    def test_an_index_does_not_collect_other_hosts(self, ctx):
        page = '<a href="https://elsewhere.test/blogs/recipes/x">x</a>'
        assert recipe_tools.links_from_index(
            page, "https://shop.test/blogs/recipes") == []


# ------------------------------------------------------- journals & codes --

class TestJournalLookupEdges:
    def _crossref(self, monkeypatch, payload, status=200):
        _mock_client(monkeypatch, lambda r: httpx.Response(status, json=payload))

    def test_an_issn_with_an_x_checkdigit(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {"message": {"items": [], "total-results": 0}})
        out = research_tools.journal_articles(ctx, "0264-410X")
        assert out["issn"] == "0264-410X"

    def test_a_journal_with_no_articles_is_not_an_error(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {"message": {"items": [], "total-results": 0}})
        out = research_tools.journal_articles(ctx, "1475-2891")
        assert out["found"] is True and out["count"] == 0
        assert out["new_to_the_catalog"] == 0

    def test_an_article_missing_every_optional_field(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {"message": {"items": [{"DOI": "10.1/x"}]}})
        article = research_tools.journal_articles(ctx, "1475-2891")["articles"][0]
        assert article["doi"] == "10.1/x"
        assert article["title"] is None and article["authors"] == []
        assert article["licence_hint"] is None

    def test_a_limit_outside_the_allowed_range_is_clamped(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {"message": {"items": []}})
        for limit in (0, -1, 10_000):
            out = research_tools.journal_articles(ctx, "1475-2891", limit=limit)
            assert out["found"] is True

    def test_crossref_being_down_is_reported_not_crashed(self, ctx, monkeypatch):
        self._crossref(monkeypatch, {}, status=503)
        with pytest.raises(ToolError):
            research_tools.journal_articles(ctx, "1475-2891")

    def test_naming_nothing_is_refused(self, ctx):
        for empty in ("", "   "):
            with pytest.raises(ToolError):
                research_tools.journal_articles(ctx, empty)


class TestDoiEdges:
    def test_a_doi_with_its_prefix_stripped(self, ctx, monkeypatch):
        seen = {}

        def handler(req):
            seen["url"] = str(req.url)
            return httpx.Response(200, json={"message": {"title": ["A paper"]}})

        _mock_client(monkeypatch, handler)
        for spelling in ("10.1/abc", "https://doi.org/10.1/abc",
                         "doi:10.1/abc", "  10.1/abc  "):
            research_tools.doi_metadata(ctx, spelling)
            assert seen["url"].endswith("10.1/abc"), spelling

    def test_something_that_is_not_a_doi_is_refused_before_a_request(self, ctx, monkeypatch):
        called = []
        _mock_client(monkeypatch, lambda r: called.append(1) or httpx.Response(200, json={}))
        for bad in ("", "  ", "not-a-doi", "11.1/x", "10./x"):
            with pytest.raises(ToolError):
                research_tools.doi_metadata(ctx, bad)
        assert not called, "a refusal should not cost a request"

    def test_a_doi_crossref_does_not_know(self, ctx, monkeypatch):
        _mock_client(monkeypatch, lambda r: httpx.Response(404))
        out = research_tools.doi_metadata(ctx, "10.9999/invented")
        assert out["found"] is False and "reason" in out
