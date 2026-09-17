import json
import httpx
import pytest
from wisefood_mcp import ToolContext
from wisefood_mcp.registry import ToolError
from wisefood_mcp.tools import recipes as recipe_tools
from test_mcp_tools import _mock_client


@pytest.fixture
def ctx():
    return ToolContext(actor="expert-1", contact_email="info@wisefood.gr")


def _page(title):
    return ('<html><head><script type="application/ld+json">'
            + json.dumps({"@context": "https://schema.org",
                          "@graph": [{"@type": "WebPage"},
                                     {"@type": "Recipe", "name": title}]})
            + '</script></head><body>x</body></html>')


class TestProfilingARecipeSite:
    """A recipe collection is a site, not a document.

    The questions are how many recipes there are, whether they are
    machine-readable, and where the importer should start — none of which a
    page answers.
    """

    def test_it_finds_the_recipe_sitemap_over_the_blog_one(self, ctx, monkeypatch):
        """BBC Good Food publishes `-post.xml` and `-recipe.xml` side by side.
        Scoring those equally picks the blog and reports the site as
        unharvestable."""
        def handler(req):
            path = req.url.path
            if path == "/robots.txt":
                return httpx.Response(200, text="Sitemap: https://food.example/sitemap.xml\n")
            if path == "/sitemap.xml":
                return httpx.Response(200, text=(
                    "<sitemapindex>"
                    "<url><loc>https://food.example/2026-Q3-post.xml</loc></url>"
                    "<url><loc>https://food.example/2026-Q3-recipe.xml</loc></url>"
                    "</sitemapindex>"))
            if "recipe.xml" in path:
                return httpx.Response(200, text="".join(
                    f"<url><loc>https://food.example/r/{i}</loc></url>" for i in range(20)))
            if "post.xml" in path:
                return httpx.Response(200, text="".join(
                    f"<url><loc>https://food.example/b/{i}</loc></url>" for i in range(20)))
            if path.startswith("/r/"):
                return httpx.Response(200, text=_page("Pumpkin pie"),
                                      headers={"content-type": "text/html"})
            return httpx.Response(200, text="<html><p>a blog post</p></html>",
                                  headers={"content-type": "text/html"})

        _mock_client(monkeypatch, handler)
        out = recipe_tools.recipe_source(ctx, "https://food.example", sample=4)
        assert out["harvestable"] is True
        assert out["harvest_location"].endswith("recipe.xml")
        assert out["recipe_share"] == 1.0
        assert "Pumpkin pie" in out["sample_titles"]

    def test_it_tries_another_list_when_the_first_has_no_recipes(self, ctx, monkeypatch):
        """Being wrong about which sitemap holds the recipes should cost a few
        requests, not the whole answer."""
        def handler(req):
            path = req.url.path
            if path == "/robots.txt":
                return httpx.Response(404)
            if path == "/sitemap.xml":
                # Named so the ranking prefers the wrong one first.
                return httpx.Response(200, text=(
                    "<sitemapindex>"
                    "<url><loc>https://food.example/recipes-old.xml</loc></url>"
                    "<url><loc>https://food.example/cook.xml</loc></url>"
                    "</sitemapindex>"))
            if "recipes-old" in path:
                return httpx.Response(200, text="".join(
                    f"<url><loc>https://food.example/dead/{i}</loc></url>" for i in range(8)))
            if "cook.xml" in path:
                return httpx.Response(200, text="".join(
                    f"<url><loc>https://food.example/r/{i}</loc></url>" for i in range(8)))
            if path.startswith("/r/"):
                return httpx.Response(200, text=_page("Soda bread"),
                                      headers={"content-type": "text/html"})
            return httpx.Response(200, text="<html>nothing</html>",
                                  headers={"content-type": "text/html"})

        _mock_client(monkeypatch, handler)
        out = recipe_tools.recipe_source(ctx, "https://food.example", sample=3)
        assert out["harvestable"] is True
        assert out["harvest_location"].endswith("cook.xml")
        assert len(out["tried"]) > 1

    def test_a_site_with_no_recipes_is_reported_as_such(self, ctx, monkeypatch):
        """Ten thousand pages and no markup is ten thousand pages of nothing,
        and it is much cheaper to learn here than part-way through an import."""
        def handler(req):
            if req.url.path == "/robots.txt":
                return httpx.Response(404)
            if req.url.path == "/sitemap.xml":
                return httpx.Response(200, text="".join(
                    f"<url><loc>https://food.example/p/{i}</loc></url>" for i in range(50)))
            return httpx.Response(200, text="<html><p>a recipe, in prose</p></html>",
                                  headers={"content-type": "text/html"})

        _mock_client(monkeypatch, handler)
        out = recipe_tools.recipe_source(ctx, "https://food.example", sample=3)
        assert out["harvestable"] is False
        assert out["with_recipes"] == 0 and out["sampled"] == 3

    def test_no_sitemap_at_all_says_what_to_do(self, ctx, monkeypatch):
        def handler(req):
            return httpx.Response(404)
        _mock_client(monkeypatch, handler)
        out = recipe_tools.recipe_source(ctx, "https://food.example")
        assert out["harvestable"] is False and "sitemap" in out["reason"]

    def test_a_sitemap_given_directly_is_used_as_it_is(self, ctx, monkeypatch):
        seen = []

        def handler(req):
            seen.append(req.url.path)
            if "sitemap" in req.url.path:
                return httpx.Response(200, text=(
                    "<url><loc>https://food.example/r/1</loc></url>"))
            return httpx.Response(200, text=_page("Colcannon"),
                                  headers={"content-type": "text/html"})

        _mock_client(monkeypatch, handler)
        out = recipe_tools.recipe_source(ctx, "https://food.example/my-sitemap.xml", sample=1)
        assert out["harvestable"] is True
        assert "/robots.txt" not in seen, "it was handed the list; no need to hunt"

    def test_recipe_markup_is_found_inside_a_graph(self):
        assert recipe_tools.recipe_markup(_page("Barmbrack"))["name"] == "Barmbrack"

    def test_a_page_without_a_recipe_is_not_one(self):
        assert recipe_tools.recipe_markup(
            '<script type="application/ld+json">{"@type":"Article"}</script>') is None

    def test_broken_json_ld_does_not_raise(self):
        assert recipe_tools.recipe_markup(
            '<script type="application/ld+json">{not json</script>') is None

    def test_naming_nothing_is_refused(self, ctx):
        with pytest.raises(ToolError):
            recipe_tools.recipe_source(ctx, "  ")


class TestRecipesThatAreNotJsonLd:
    """Restricting to schema.org JSON-LD writes off most of the web's home
    cooking. A site publishing microdata, using a WordPress plugin, or simply
    listing ingredients and then a method is still publishing recipes."""

    def test_each_form_is_recognised_and_named(self):
        from wisefood_mcp.tools.recipes import detect_recipe

        cases = {
            '<script type="application/ld+json">{"@type":"Recipe","name":"Fasirt"}</script>': "json-ld",
            '<div itemscope itemtype="https://schema.org/Recipe"><h1>Goulash</h1></div>': "microdata",
            '<div typeof="Recipe"><h1>Stew</h1></div>': "rdfa",
            '<div class="hrecipe"><span class="fn">Soup</span></div>': "microformat",
            '<div class="wprm-recipe-container">x</div>': "plugin",
            "<h2>Ingredients</h2><ul><li>flour</li></ul><h2>Method</h2><p>Mix.</p>": "prose",
        }
        for html_text, how in cases.items():
            found = detect_recipe(html_text)
            assert found and found["how"] == how, html_text[:40]

    def test_which_forms_carry_the_ingredients_as_data(self):
        """Not equally useful: a curator deciding whether to import wants to
        know whether they get data or pages that still have to be read."""
        from wisefood_mcp.tools.recipes import detect_recipe

        assert detect_recipe(
            '<script type="application/ld+json">{"@type":"Recipe"}</script>'
        )["machine_readable"] is True
        assert detect_recipe(
            "<h2>Ingredients</h2><ul><li>x</li></ul><h2>Method</h2><p>y</p>"
        )["machine_readable"] is False

    def test_prose_needs_both_halves(self):
        """"Ingredients" alone appears on any product page."""
        from wisefood_mcp.tools.recipes import detect_recipe

        assert detect_recipe("<h1>About</h1><p>Ingredients sourced locally.</p>") is None
        assert detect_recipe("<h2>Ingredients</h2><ul><li>flour</li></ul>") is None

    def test_a_recipe_in_another_language_is_still_a_recipe(self):
        from wisefood_mcp.tools.recipes import detect_recipe

        greek = "<h2>Υλικά</h2><ul><li>αλεύρι</li></ul><h3>Εκτέλεση</h3><p>x</p>"
        assert detect_recipe(greek)["how"] == "prose"

    def test_the_page_the_curator_gave_is_used_as_the_index(self, ctx, monkeypatch):
        """Asked about `bestofhungary.co.uk/blogs/recipes`, it went to the
        site root, found Shopify's product sitemap and reported that 383
        pages carried no recipes. The nineteen recipes linked from the page
        it was handed all did."""
        from wisefood_mcp.tools.recipes import links_from_index

        page = ('<a href="/blogs/recipes/fasirt">Fasirt</a>'
                '<a href="/blogs/recipes/goulash">Goulash</a>'
                '<a href="/blogs/recipes">the index itself</a>'
                '<a href="/products/paprika">a product</a>'
                '<a href="https://elsewhere.test/x">another site</a>')
        found = links_from_index(page, "https://shop.test/blogs/recipes")
        assert found == ["https://shop.test/blogs/recipes/fasirt",
                         "https://shop.test/blogs/recipes/goulash"]
