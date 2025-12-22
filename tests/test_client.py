import pytest

from wisefood.client import DataClient, Credentials, WisefoodError

from conftest import StubResponse


def build_client(monkeypatch, stub_session):
    monkeypatch.setattr("wisefood.client.requests.Session", lambda: stub_session)
    return DataClient("https://api.example.com", Credentials("user", "pass"))


def test_authenticate_success(monkeypatch, stub_session, frozen_time):
    stub_session.post_response = StubResponse(
        200, {"result": {"token": "abc123", "expires_in": 120}}
    )
    client = build_client(monkeypatch, stub_session)

    assert client._token == "abc123"
    # safety_margin = 10% of expires_in = 12
    assert client._token_expiry_ts == pytest.approx(frozen_time + 120 - 12)

    assert stub_session.post_calls[0]["url"] == "https://api.example.com/api/v1/system/login"
    assert stub_session.post_calls[0]["json"] == {"username": "user", "password": "pass"}


def test_authenticate_fails_without_token(monkeypatch, stub_session):
    stub_session.post_response = StubResponse(200, {"result": {}})
    with pytest.raises(WisefoodError, match="missing token"):
        build_client(monkeypatch, stub_session)


def test_authenticate_http_error(monkeypatch, stub_session):
    stub_session.post_response = StubResponse(401, {"error": "bad"}, text="bad creds")
    with pytest.raises(WisefoodError, match="Authentication failed"):
        build_client(monkeypatch, stub_session)


def test_ensure_token_refreshes(monkeypatch, stub_session, frozen_time):
    stub_session.post_response = StubResponse(
        200, {"result": {"token": "initial", "expires_in": 5}}
    )
    client = build_client(monkeypatch, stub_session)

    calls = []

    def fake_authenticate():
        calls.append("auth")
        client._token = "refreshed"
        client._token_expiry_ts = frozen_time + 50

    client.authenticate = fake_authenticate  # type: ignore[method-assign]
    client._token = None
    client._token_expiry_ts = 0

    client._ensure_token()
    assert calls == ["auth"]
    assert client._token == "refreshed"


def test_request_adds_auth_and_merges_headers(monkeypatch, stub_session, frozen_time):
    stub_session.post_response = StubResponse(
        200, {"result": {"token": "auth-token", "expires_in": 120}}
    )
    client = build_client(monkeypatch, stub_session)

    called_with = {}

    def fake_raise_for_api_error(resp):
        called_with["resp"] = resp

    monkeypatch.setattr("wisefood.client.raise_for_api_error", fake_raise_for_api_error)
    stub_session.request_response = StubResponse(200, {"ok": True})

    resp = client.request(
        "POST",
        "items",
        headers={"Authorization": "override", "X-Test": "yes"},
        json={"hello": "world"},
    )

    assert resp is stub_session.request_response
    req = stub_session.request_calls[0]
    assert req["headers"]["Authorization"] == "Bearer auth-token"
    assert req["headers"]["X-Test"] == "yes"
    assert req["kwargs"]["json"] == {"hello": "world"}
    assert called_with["resp"] is stub_session.request_response


def test_request_without_auth(monkeypatch, stub_session):
    stub_session.post_response = StubResponse(
        200, {"result": {"token": "auth-token", "expires_in": 120}}
    )
    client = build_client(monkeypatch, stub_session)

    def boom():
        raise RuntimeError("should not be called")

    client._ensure_token = boom  # type: ignore[assignment]
    stub_session.request_response = StubResponse(200, {"ok": True})
    monkeypatch.setattr("wisefood.client.raise_for_api_error", lambda resp: None)

    client.request("GET", "items", auth=False, params={"a": 1})
    req = stub_session.request_calls[0]
    assert "Authorization" not in req["headers"]
    assert req["params"] == {"a": 1}


def test_request_rejects_body_for_get(monkeypatch, stub_session):
    stub_session.post_response = StubResponse(
        200, {"result": {"token": "auth-token", "expires_in": 120}}
    )
    client = build_client(monkeypatch, stub_session)

    with pytest.raises(ValueError):
        client.request("GET", "items", json={"a": 1})
