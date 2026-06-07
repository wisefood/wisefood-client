# Error Handling

The client turns API failures into a small hierarchy of **typed exceptions**, so you can
catch exactly the condition you care about instead of parsing status codes by hand.

## The error envelope

WiseFood error responses follow a consistent shape:

```json
{
  "success": false,
  "error": {
    "title": "NotFoundError",
    "detail": "Article with URN urn:article:hello not found.",
    "code": "resource/not_found"
  },
  "help": "https://data.wisefood.example/api/v1/articles/hello"
}
```

The client inspects every response (`raise_for_api_error`) and, on failure, raises an
appropriate `APIError` subclass — even for `2xx` responses that carry `success: false`.

## The `APIError` base

All client exceptions inherit from `wisefood.exceptions.APIError`, which exposes:

| Attribute | Meaning |
|-----------|---------|
| `status_code` | HTTP status code. |
| `code` | Server error code, e.g. `"resource/not_found"`. |
| `title` | Server error title, e.g. `"NotFoundError"`. |
| `detail` | Human-readable message (validation details are flattened in). |
| `errors` | Nested/structured errors (e.g. field validation). |
| `extra` | Any additional server-provided fields. |
| `help_url` | The top-level `help` link, when present. |
| `response_body` | The raw parsed JSON of the response. |
| `retryable` | `True` for `429`/`503`/`504` and other `5xx` — a retry may help. |

## Exception mapping

The client first maps the server `code`; if there's no match it falls back to the HTTP
status code.

| Server `code` | HTTP status | Exception |
|---------------|-------------|-----------|
| `request/invalid` | 400 | `InvalidError` |
| `auth/unauthorized` | 401 | `AuthenticationError` |
| `auth/forbidden` | 403 | `AuthorizationError` |
| `resource/not_found` | 404 | `NotFoundError` |
| `request/not_allowed` | 405 | `NotAllowedError` |
| `resource/conflict` | 409 | `ConflictError` |
| `request/unprocessable` | 422 | `DataError` |
| `quota/rate_limited` | 429 | `RateLimitError` |
| `server/internal` | 500 | `InternalError` |
| `upstream/bad_gateway` | 502 | `BadGatewayError` |
| `upstream/unavailable` | 503 | `ServiceUnavailableError` |
| `upstream/timeout` | 504 | `GatewayTimeoutError` |

All of these are importable from `wisefood.exceptions`.

## Catching errors

```python
from wisefood.exceptions import NotFoundError, RateLimitError, AuthorizationError

try:
    article = client.articles["does-not-exist"]
except NotFoundError as e:
    print(e.code, "-", e.detail)
    print("More info:", e.help_url)
except AuthorizationError:
    print("You don't have access to this resource.")
except RateLimitError as e:
    if e.retryable:
        ...  # back off and retry
```

```{tip}
The client already retries transient failures (`429`, `500`, `502`, `503`, `504`) with
backoff at the HTTP layer. The `RateLimitError`/`5xx` exceptions surface only when those
automatic retries are exhausted — so a manual retry loop is rarely needed, but
`retryable` is there if you want one.
```

## Validation errors

For `422` responses, FastAPI-style validation details are flattened into a readable
`detail` string while the structured form remains available on `.errors`:

```python
from wisefood.exceptions import DataError

try:
    client.articles.create()   # missing required fields
except DataError as e:
    print(e.detail)   # e.g. "body.title: field required"
    print(e.errors)   # the structured list
```
