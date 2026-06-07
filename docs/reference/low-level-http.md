# Low-Level HTTP

Most of the time you'll use the resource proxies and entities. But both clients
(`DataClient` and `Client`) also expose the raw HTTP layer they're built on — useful for
endpoints the proxies don't cover yet, or for quick one-off calls.

Every method here handles authentication (token injection + refresh), TLS, timeouts,
connection pooling, retries, and error raising for you. They return a
`requests.Response`.

## When to drop to this layer

- The endpoint isn't wrapped by a proxy/entity.
- You want full control over the raw response (headers, status, streaming).
- You're prototyping against a new endpoint.

Otherwise prefer the typed proxies — they parse responses into entities and keep caches
consistent.

## The core method

```python
client.request(method, endpoint, *, auth=True, timeout=None,
               headers=None, params=None, **kwargs)
```

- `method` — `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, or `"DELETE"`.
- `endpoint` — path relative to the API base, e.g. `"articles/123"`.
- `auth` — include the bearer token (default `True`).
- `params` — query parameters; `**kwargs` are passed to `requests` (`json=`, `data=`,
  `files=`, `stream=`, …).
- **GET/DELETE may not carry a body** — passing `json`/`data`/`files` raises
  `ValueError`.

## Endpoint-relative verbs

Thin wrappers over `request()` that take a single endpoint string:

```python
client.get("articles/search", q="nutrition", limit=10)   # kwargs → query params
client.post("articles", json={"title": "Study"})
client.put("articles/123", json={"title": "Updated"})
client.patch("articles/123", json={"status": "published"})
client.delete("articles/123")
```

## Path-parts wrappers (uppercase)

The uppercase variants join path segments for you and treat keyword arguments as the
query string (`GET`/`DELETE`) or the JSON body (`POST`/`PUT`/`PATCH`):

```python
# GET /api/v1/articles/search?q=nutrition&limit=10
resp = client.GET("articles", "search", q="nutrition", limit=10)

# POST /api/v1/articles  with JSON body {"title": ..., "doi": ...}
resp = client.POST("articles", title="Study", doi="10.1234/example")

# PUT /api/v1/articles/123  with JSON body
resp = client.PUT("articles", "123", title="Updated Study")

# PATCH /api/v1/articles/123  with JSON body
resp = client.PATCH("articles", "123", status="published")

# DELETE /api/v1/articles/123
resp = client.DELETE("articles", "123")

# POST/PUT/PATCH also accept query params via params=
resp = client.POST("articles", params={"dry_run": "true"}, title="Study")
```

## URL construction

```python
client.api_base                      # e.g. https://data.wisefood.example/api/v1
client.endpoint("articles/123")      # e.g. https://data.wisefood.example/api/v1/articles/123
```

## Errors

Every call runs the response through `raise_for_api_error`, so failures surface as typed
exceptions — see [Error Handling](../concepts/error-handling.md).
