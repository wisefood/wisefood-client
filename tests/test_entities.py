import types
import pytest

from wisefood.entities.articles import Article, ArticlesProxy

from conftest import DummyClient, StubResponse


def test_field_defaults_and_factory(dummy_client: DummyClient):
    # Include title in data to avoid lazy-fetch triggering
    article = Article(client=dummy_client, data={"urn": "urn:article:test", "title": ""}, sync=False)
    assert article.title == ""  # default value

    # default_factory values are persisted to data once accessed
    assert article.authors == []
    assert "authors" in article.data and article.data["authors"] == []


def test_read_only_field_is_protected(dummy_client: DummyClient):
    article = Article(client=dummy_client, data={"urn": "urn:article:test"}, sync=False)
    with pytest.raises(AttributeError):
        article.id = "123"


def test_get_and_create_use_normalized_urns(dummy_client: DummyClient):
    # normalize_urn returns just the slug, so endpoint is articles/abc
    dummy_client.queue_response(
        "get",
        "articles/abc",
        StubResponse(200, {"result": {"urn": "urn:article:abc", "title": "Hello"}}),
    )
    fetched = Article.get(dummy_client, "abc")
    assert fetched.urn == "urn:article:abc"
    assert fetched.data["title"] == "Hello"

    dummy_client.queue_response(
        "post",
        "articles",
        StubResponse(200, {"result": {"urn": "urn:article:new", "title": "New"}}),
    )
    created = Article.create(dummy_client, urn="new", title="New")
    assert created.urn == "urn:article:new"
    assert created.data["title"] == "New"


def test_refresh_and_delete(dummy_client: DummyClient):
    article = Article(
        client=dummy_client,
        data={"urn": "urn:article:one", "title": "Stale"},
        sync=False,
    )
    dummy_client.queue_response(
        "get",
        "articles/urn:article:one",
        StubResponse(200, {"result": {"urn": "urn:article:one", "title": "Fresh"}}),
    )
    article.refresh()
    assert article.data["title"] == "Fresh"

    article.delete()
    assert ("delete", "articles/urn:article:one", {}) in dummy_client.calls


def test_save_only_dirty_sends_changed_fields(dummy_client: DummyClient):
    article = Article(
        client=dummy_client,
        data={
            "urn": "urn:article:one",
            "id": "123",
            "creator": "alice",
            "created_at": "t1",
            "updated_at": "t1",
            "title": "Old",
            "content": "Body",
        },
        sync=False,
    )

    article.title = "New"

    dummy_client.queue_response(
        "patch",
        "articles/urn:article:one",
        StubResponse(200, {"result": {"urn": "urn:article:one", "title": "New"}}),
    )

    article.save(only_dirty=True)

    method, endpoint, json_body, _kwargs = dummy_client.calls[-1]
    assert method == "patch"
    assert endpoint == "articles/urn:article:one"
    assert json_body == {"title": "New"}
    assert article._dirty_fields == set()


def test_collection_proxy_len_iter_and_slice(monkeypatch):
    proxy = ArticlesProxy(client=None)  # type: ignore[arg-type]

    def fetch(self, limit, offset=0):
        return [f"urn:article:{i}" for i in range(offset, offset + limit)]

    def get_entity(self, urn, lazy=False):
        return f"entity:{urn}"

    monkeypatch.setattr(proxy, "_fetch_urns", types.MethodType(fetch, proxy))
    monkeypatch.setattr(proxy, "_get_entity", types.MethodType(get_entity, proxy))

    assert len(proxy) == proxy.DEFAULT_PAGE_SIZE
    assert list(proxy)[:3] == ["entity:urn:article:0", "entity:urn:article:1", "entity:urn:article:2"]

    slice_result = proxy[1:3]
    assert slice_result == ["entity:urn:article:1", "entity:urn:article:2"]


def test_collection_proxy_string_lookup_and_fuzzy(monkeypatch):
    proxy = ArticlesProxy(client=None)  # type: ignore[arg-type]
    proxy._urns = [
        "urn:article:alpha",
        "urn:article:beta",
        "urn:article:alphabet",
    ]

    def get_entity(self, urn, lazy=False):
        return f"entity:{urn}"

    monkeypatch.setattr(proxy, "_get_entity", types.MethodType(get_entity, proxy))

    # slug resolution - finds in cache, returns entity
    assert proxy["alpha"] == "entity:urn:article:alpha"
    # full URN - finds in cache, returns entity
    assert proxy["urn:article:beta"] == "entity:urn:article:beta"
    # "alph" is not in cache, so it tries to fetch from API directly
    # (fuzzy search was removed - now it fetches by slug/urn directly)
    assert proxy["alph"] == "entity:alph"


def test_slugs_exposes_known_slugs(monkeypatch):
    proxy = ArticlesProxy(client=None)  # type: ignore[arg-type]

    def fetch(self, limit, offset=0):
        return ["urn:article:first", "urn:article:second"]

    monkeypatch.setattr(proxy, "_fetch_urns", types.MethodType(fetch, proxy))
    assert proxy.slugs() == ["first", "second"]


def test_collection_proxy_create_returns_entity_and_updates_index(dummy_client: DummyClient):
    proxy = ArticlesProxy(client=dummy_client)
    proxy._urns = ["urn:article:existing"]

    dummy_client.queue_response(
        "post",
        "articles",
        StubResponse(200, {"result": {"urn": "urn:article:new", "title": "New"}}),
    )

    created = proxy.create(urn="new", title="New")

    # returns a typed entity proxy
    assert isinstance(created, Article)
    assert created.urn == "urn:article:new"

    # request was sent via the proxy's client
    method, endpoint, body, _kwargs = dummy_client.calls[-1]
    assert (method, endpoint) == ("post", "articles")
    # normalize_urn returns just the slug
    assert body["urn"] == "new"

    # cached index is refreshed
    assert "urn:article:new" in proxy._urns
