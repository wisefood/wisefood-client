# Authentication

Both WiseFood clients authenticate the same way: you hand them a `Credentials` object,
they obtain a bearer token on construction, and they refresh it transparently before it
expires. You never touch tokens directly.

## Credentials

`Credentials` accepts **either** a user login **or** machine-to-machine (M2M) client
credentials. The two are **mutually exclusive** — providing both, or neither, raises a
`ValueError`.

```python
from wisefood import Credentials

# User credentials (a human actor)
user_creds = Credentials(username="you@example.org", password="••••••••")

# Machine-to-machine credentials (an application acting on its own behalf)
app_creds = Credentials(client_id="my-service", client_secret="••••••••")
```

```python
# These both raise ValueError:
Credentials(username="u", password="p", client_id="c", client_secret="s")  # both
Credentials(username="u")                                                   # incomplete
```

You can introspect which mode a credential is in:

```python
user_creds.is_user_credentials     # True
app_creds.is_client_credentials    # True
```

Under the hood, user credentials authenticate against `system/login` and M2M
credentials against `system/mtm`.

## The two APIs and their clients

The WiseFood platform exposes **two distinct APIs** — the **WiseFood API** and the
**WiseFood Data API** — and the package provides one client for each, pointed at its own
base URL. They share the same `Credentials` type and the same authentication machinery.

| Client | Import | Typical base URL | API |
|--------|--------|------------------|-----|
| `DataClient` | `from wisefood import DataClient` | `https://data.wisefood.example` | the WiseFood Data API |
| `Client` | `from wisefood import Client` | `https://api.wisefood.example` | the WiseFood API |

Both default to `api_prefix="/api/v1"`, so requests go to
`<base_url>/api/v1/<endpoint>`.

## Recommended pattern: environment variables

Keep secrets out of code. Read them from the environment:

```python
import os
from wisefood import DataClient, Client, Credentials

# WiseFood Data API with machine-to-machine credentials
data = DataClient(
    os.environ["WISEFOOD_API_URL"],
    Credentials(
        client_id=os.environ["WISEFOOD_CLIENT_ID"],
        client_secret=os.environ["WISEFOOD_CLIENT_SECRET"],
    ),
)

# WiseFood API with a user login
core = Client(
    os.environ["WISEFOOD_CORE_URL"],
    Credentials(
        username=os.environ["WISEFOOD_USERNAME"],
        password=os.environ["WISEFOOD_PASSWORD"],
    ),
)
```

## Token lifecycle

- **On construction**, the client calls `authenticate()` immediately, so a freshly
  created client is ready to use.
- The token is stored with an **automatic safety margin** before its real expiry, so it
  is refreshed slightly early rather than failing mid-request.
- Before every authenticated request the client calls an internal `_ensure_token()` that
  re-authenticates if the token is missing or (nearly) expired.

Check who you are authenticated as at any time:

```python
status = client.ping()
print(status)   # user/client details from system/ping
```

## Connection tuning

Both client constructors accept the same keyword-only knobs:

```python
client = DataClient(
    base_url,
    creds,
    api_prefix="/api/v1",   # API version prefix
    verify_tls=True,        # set False only for trusted dev hosts with self-signed certs
    default_timeout=30.0,   # seconds, per request
    pool_connections=3,     # number of connection pools to cache
    pool_maxsize=3,         # max connections kept per pool (Client defaults to 10)
)
```

Both clients install an automatic **retry policy** for transient failures: up to 3
retries with backoff on HTTP `429`, `500`, `502`, `503`, and `504`. Application-level
errors (4xx other than 429) are surfaced as typed exceptions instead —
see [Error Handling](concepts/error-handling.md).
