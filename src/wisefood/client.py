"""
A compact, robust HTTP client for the Wisefood Data API.
"""

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional
import urllib.parse
import requests


# -------------------------------
# Credentials Model
# -------------------------------


@dataclass
class Credentials:
    username: str
    password: str


# -------------------------------
# Exceptions
# -------------------------------


class WisefoodError(RuntimeError):
    pass


# -------------------------------
# Main Client
# -------------------------------


class Client:
    def __init__(
        self,
        base_url: str,
        credentials: Credentials,
        *,
        api_prefix: str = "/api/v1",
        verify_tls: bool = True,
        default_timeout: float = 30.0,
    ) -> None:

        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix.strip("/")
        self.credentials = credentials
        self.verify_tls = verify_tls
        self.default_timeout = default_timeout

        self._session = requests.Session()
        self._token: Optional[str] = None
        self._token_expiry_ts: float = 0.0

        # Authenticate immediately
        self.authenticate()

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _join(self, base: str, path: str) -> str:
        """Join base and path cleanly without stripping segments."""
        return urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))

    @property
    def api_base(self) -> str:
        return self._join(self.base_url, self.api_prefix)

    def endpoint(self, endpoint: str) -> str:
        """Return absolute URL for API endpoint."""
        return self._join(self.api_base, endpoint)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> None:
        """Login and store bearer token + expiry timestamp."""

        payload = {
            "username": self.credentials.username,
            "password": self.credentials.password,
        }

        url = self.endpoint("system/login")
        resp = self._session.post(
            url,
            json=payload,
            verify=self.verify_tls,
            timeout=self.default_timeout,
        )

        if resp.status_code != 200:
            raise WisefoodError(
                f"Authentication failed ({resp.status_code}): {resp.text}"
            )

        data = resp.json().get("result", {})
        token = data.get("token") or data.get("access_token") or data.get("jwt")

        if not token:
            raise WisefoodError("Authentication response missing token field.")

        expires_in = float(data.get("expires_in", 3600))
        now = time.time()
        safety_margin = min(60, max(10, expires_in * 0.1))

        self._token = token
        self._token_expiry_ts = now + expires_in - safety_margin

    def _ensure_token(self) -> None:
        if not self._token or time.time() >= self._token_expiry_ts:
            self.authenticate()

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        auth=True,
        timeout=None,
        headers=None,
        params=None,
        **kwargs,
    ):
        url = self.endpoint(endpoint)

        req_headers: Dict[str, str] = {}
        if auth:
            self._ensure_token()
            req_headers["Authorization"] = f"Bearer {self._token}"

        # Merge headers but avoid overriding Authorization
        if headers:
            filtered = {
                k: v
                for k, v in headers.items()
                if not (auth and k.lower() == "authorization")
            }
            req_headers.update(filtered)

        # GET/DELETE must not have bodies
        if kwargs and method.upper() in {"GET", "DELETE"}:
            raise ValueError("GET and DELETE requests cannot include a request body.")

        resp = self._session.request(
            method.upper(),
            url,
            headers=req_headers,
            params=params,                
            verify=self.verify_tls,
            timeout=self.default_timeout if timeout is None else timeout,
            **kwargs,
        )

        return resp

    # ------------------------------------------------------------------
    # API-relative HTTP verbs
    # ------------------------------------------------------------------

    def get(self, endpoint: str, **params: Any) -> requests.Response:
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs: Any) -> requests.Response:
        return self.request("PUT", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs: Any) -> requests.Response:
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", endpoint, **kwargs)

    # ------------------------------------------------------------------
    # Optional STELAR-style uppercase helpers
    # ------------------------------------------------------------------

    def GET(self, *parts, **params) -> requests.Response:
        endpoint = "/".join(str(p) for p in parts)
        return self.get(endpoint, params=params)

    def POST(self, *parts, params=None, **json) -> requests.Response:
        endpoint = "/".join(str(p) for p in parts)
        return self.post(endpoint, params=params, json=json)

    def PUT(self, *parts, params=None, **json) -> requests.Response:
        endpoint = "/".join(str(p) for p in parts)
        return self.put(endpoint, params=params, json=json)

    def PATCH(self, *parts, params=None, **json) -> requests.Response:
        endpoint = "/".join(str(p) for p in parts)
        return self.patch(endpoint, params=params, json=json)

    def DELETE(self, *parts, **params) -> requests.Response:
        endpoint = "/".join(str(p) for p in parts)
        return self.delete(endpoint, params=params)
