"""
A compact, robust HTTP client for the Wisefood Data API.
"""

import base64
from dataclasses import dataclass
import json
import time
from typing import Any, Dict, Optional
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .exceptions import raise_for_api_error


from .entities.articles import ArticlesProxy
from .entities.artifacts import ArtifactsProxy
from .entities.fctables import FCTablesProxy
from .entities.guides import GuidesProxy, GuidelinesProxy
from .entities.textbooks import TextbookPassagesProxy, TextbooksProxy

# -------------------------------
# Credentials Model
# -------------------------------


#: "not looked at yet", distinct from "looked and there was none".
_UNREAD = object()


@dataclass
class Credentials:
    """
    Exactly one of three: user credentials (username & password), client
    credentials (client_id & client_secret), or a caller's ``access_token``.

    The third is **delegation**: a service acting on behalf of the person who
    called it, with that person's rights and no others. It is the only mode
    where this client cannot obtain a token by itself, which is the point —
    see :meth:`WisefoodClient.authenticate`.
    """
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    """A bearer belonging to the caller. Used as given; never refreshed."""

    def __post_init__(self) -> None:
        has_user = bool(self.username or self.password)
        has_client = bool(self.client_id or self.client_secret)
        has_token = bool(self.access_token)

        if sum((has_user, has_client, has_token)) > 1:
            raise ValueError(
                "Provide exactly one of username/password, client_id/client_secret, "
                "or access_token."
            )

        if not has_token and not (self.username and self.password) \
                and not (self.client_id and self.client_secret):
            raise ValueError(
                "Must provide username/password, client_id/client_secret, or access_token."
            )

    @property
    def is_user_credentials(self) -> bool:
        return bool(self.username and self.password)

    @property
    def is_client_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def is_delegated(self) -> bool:
        """Acting as the caller, with the caller's rights."""
        return bool(self.access_token)


# -------------------------------
# Exceptions
# -------------------------------


class WisefoodError(RuntimeError):
    pass


# -------------------------------
# Main Client
# -------------------------------


class DataClient:
    """
    HTTP client for the Wisefood Data API with automatic authentication and resource proxies.

    This client handles all communication with the Wisefood Data API, providing:
    - Automatic authentication using username/password or client credentials
    - Token refresh when expired
    - Connection pooling and retry logic
    - Clean endpoint URL construction
    - Resource-specific proxies (articles, artifacts, guides, guidelines, textbooks, textbook passages, fctables) for convenient data access

    Args:
        base_url: Base URL of the Wisefood Data API (e.g., 'https://data.wisefood.com')
        credentials: Credentials object containing either username/password or client_id/client_secret
        api_prefix: API version prefix (default: '/api/v1')
        verify_tls: Whether to verify SSL/TLS certificates (default: True)
        default_timeout: Default request timeout in seconds (default: 30.0)
        pool_connections: Number of connection pools to cache (default: 3)
        pool_maxsize: Maximum number of connections to save in the pool (default: 3)

    Attributes:
        articles: ArticlesProxy for accessing scientific articles
        artifacts: ArtifactsProxy for accessing artifact files and metadata
        guides: GuidesProxy for accessing dietary guides
        guidelines: GuidelinesProxy for accessing extracted guide rules
        textbooks: TextbooksProxy for accessing textbooks
        textbook_passages: TextbookPassagesProxy for accessing extracted textbook passages
        fctables: FCTablesProxy for accessing food composition tables

    Example:
        >>> creds = Credentials(username='user@example.com', password='secret')
        >>> client = DataClient('https://data.wisefood.com', creds)
        >>> # Access resources through proxies
        >>> article = client.articles.get(123)
        >>> # Or make direct API calls
        >>> response = client.GET('articles', 'search', q='nutrition')
    """

    def __init__(
        self,
        base_url: str,
        credentials: Credentials,
        *,
        api_prefix: str = "/api/v1",
        verify_tls: bool = True,
        default_timeout: float = 30.0,
        pool_connections: int = 3,
        pool_maxsize: int = 3,
    ) -> None:

        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix.strip("/")
        self.credentials = credentials
        self.verify_tls = verify_tls
        self.default_timeout = default_timeout

        #: Memoised `exp` of a delegated token; `_UNREAD` until looked at.
        self._delegated_exp: Any = _UNREAD

        self._session = requests.Session()

        # Configure connection pooling
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        self._token: Optional[str] = None
        self._token_expiry_ts: float = 0.0

        # Authenticate immediately — except when delegated, where there is
        # nothing to authenticate with: the caller's token is the credential,
        # and it is checked on first use rather than at construction.
        if self.credentials.is_delegated:
            self._token = self.credentials.access_token
        else:
            self.authenticate()


        # Proxies for API resource groups
        self.articles = ArticlesProxy(self)
        self.artifacts = ArtifactsProxy(self)
        self.guides = GuidesProxy(self)
        self.guidelines = GuidelinesProxy(self)
        self.textbooks = TextbooksProxy(self)
        self.textbook_passages = TextbookPassagesProxy(self)
        self.fctables = FCTablesProxy(self)

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _join(self, base: str, path: str) -> str:
        """
        Join base and path cleanly without stripping segments.

        Args:
            base: Base URL or path
            path: Path to append

        Returns:
            Properly joined URL path
        """
        return urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))

    @property
    def api_base(self) -> str:
        """
        Get the full API base URL combining base_url and api_prefix.

        Returns:
            Complete API base URL (e.g., 'https://data.wisefood.com/api/v1')
        """
        return self._join(self.base_url, self.api_prefix)

    def endpoint(self, endpoint: str) -> str:
        """
        Construct absolute URL for an API endpoint.

        Args:
            endpoint: Relative endpoint path (e.g., 'articles/123' or '/articles/123')

        Returns:
            Complete URL (e.g., 'https://data.wisefood.com/api/v1/articles/123')
        """
        return self._join(self.api_base, endpoint)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> None:
        """
        Authenticate with the API and store bearer token with expiry timestamp.

        Uses either username/password (user credentials) or client_id/client_secret
        (machine-to-machine credentials) depending on the credentials type.

        The token is stored internally with an automatic safety margin before expiry
        to ensure requests don't fail due to token expiration.

        Raises:
            WisefoodError: If authentication fails or response is invalid
        """

        if self.credentials.is_delegated:
            # There is nothing to authenticate with, and that is the guarantee:
            # a delegated client holds one person's token and must never be
            # able to obtain a stronger one. Falling back to anything else here
            # would silently turn "act as this curator" into "act as the
            # service account", which is the exact privilege escalation
            # delegation exists to prevent.
            raise WisefoodError(
                "This client acts on behalf of a caller and cannot authenticate "
                "on its own. The caller's token has expired or was rejected; a "
                "new one has to come from them."
            )

        if self.credentials.is_client_credentials:
            url = self.endpoint("system/mtm")
            payload = {
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
            }
        else:
            url = self.endpoint("system/login")
            payload = {
                "username": self.credentials.username,
                "password": self.credentials.password,
            }

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

    def ping(self) -> Dict[str, Any]:
        """
        Check authentication status and get user/client information.

        Returns:
            Dictionary containing authentication status and user/client details

        Example:
            >>> status = client.ping()
            >>> print(status.get('username'))
        """
        return self.GET("system/ping").json().get("result", {})

    def _ensure_token(self) -> None:
        """
        Ensure a valid authentication token exists, refreshing if necessary.

        Automatically re-authenticates if the token is missing or expired —
        except when delegated, where there is nothing to re-authenticate with
        and an expiry is reported rather than worked around.
        """
        if self.credentials.is_delegated:
            self._token = self.credentials.access_token
            if self._delegated_expiry() is not None and time.time() >= self._delegated_expiry():
                raise WisefoodError(
                    "The caller's token has expired; ask them to retry so a "
                    "fresh one is used."
                )
            return
        if not self._token or time.time() >= self._token_expiry_ts:
            self.authenticate()

    def _delegated_expiry(self) -> Optional[float]:
        """The `exp` claim of the delegated token, if it has a readable one.

        Read, not verified: verifying is the API's job and we have no keys.
        This only decides whether to fail here with a clear message or let the
        request come back 401, and an unreadable token simply gets the latter.
        """
        if self._delegated_exp is not _UNREAD:
            return self._delegated_exp
        self._delegated_exp = None
        token = self.credentials.access_token or ""
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            exp = claims.get("exp")
            if exp is not None:
                self._delegated_exp = float(exp)
        except Exception:  # noqa: BLE001 — an opaque token is not an error here
            pass
        return self._delegated_exp

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
        """
        Low-level HTTP request method with automatic authentication.

        Args:
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            endpoint: API endpoint path relative to api_base
            auth: Whether to include authentication token (default: True)
            timeout: Request timeout in seconds (uses default_timeout if None)
            headers: Additional HTTP headers to include
            params: Query parameters for the request
            **kwargs: Additional arguments passed to requests (e.g., json, data)

        Returns:
            requests.Response object

        Raises:
            ValueError: If GET/DELETE request includes a request body
            WisefoodError: If the API returns an error response

        Example:
            >>> response = client.request('GET', 'articles/123')
            >>> response = client.request('POST', 'articles', json={'title': 'Study'})
        """
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

        # GET/DELETE must not have request bodies, but other request options such
        # as `stream=True` are valid and needed for artifact downloads.
        body_kwargs = {"json", "data", "files"}
        if method.upper() in {"GET", "DELETE"} and any(
            key in kwargs for key in body_kwargs
        ):
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
        raise_for_api_error(resp)

        return resp

    # ------------------------------------------------------------------
    # API-relative HTTP verbs
    # ------------------------------------------------------------------

    def get(self, endpoint: str, **params: Any) -> requests.Response:
        """
        Perform a GET request to the specified endpoint.

        Args:
            endpoint: API endpoint path
            **params: Query parameters as keyword arguments

        Returns:
            requests.Response object

        Example:
            >>> response = client.get('articles/search', q='nutrition', limit=10)
        """
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint: str, **kwargs: Any) -> requests.Response:
        """
        Perform a POST request to the specified endpoint.

        Args:
            endpoint: API endpoint path
            **kwargs: Request arguments (typically json=dict or data=dict)

        Returns:
            requests.Response object

        Example:
            >>> response = client.post('articles', json={'title': 'Study', 'doi': '10.1234/example'})
        """
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs: Any) -> requests.Response:
        """
        Perform a PUT request to the specified endpoint.

        Args:
            endpoint: API endpoint path
            **kwargs: Request arguments (typically json=dict or data=dict)

        Returns:
            requests.Response object

        Example:
            >>> response = client.put('articles/123', json={'title': 'Updated Study'})
        """
        return self.request("PUT", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs: Any) -> requests.Response:
        """
        Perform a PATCH request to the specified endpoint.

        Args:
            endpoint: API endpoint path
            **kwargs: Request arguments (typically json=dict or data=dict)

        Returns:
            requests.Response object

        Example:
            >>> response = client.patch('articles/123', json={'status': 'published'})
        """
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs: Any) -> requests.Response:
        """
        Perform a DELETE request to the specified endpoint.

        Args:
            endpoint: API endpoint path
            **kwargs: Request arguments (typically params for query parameters)

        Returns:
            requests.Response object

        Example:
            >>> response = client.delete('articles/123')
        """
        return self.request("DELETE", endpoint, **kwargs)

    # ------------------------------------------------------------------
    # Wrappers
    # ------------------------------------------------------------------

    def GET(self, *parts, **params) -> requests.Response:
        """
        Convenient GET request with path parts as separate arguments.

        Args:
            *parts: URL path segments that will be joined with '/'
            **params: Query parameters as keyword arguments

        Returns:
            requests.Response object

        Example:
            >>> response = client.GET('articles', 'search', q='nutrition', limit=10)
            # Equivalent to: GET /api/v1/articles/search?q=nutrition&limit=10
        """
        endpoint = "/".join(str(p) for p in parts)
        return self.get(endpoint, params=params)

    def POST(self, *parts, params=None, **json) -> requests.Response:
        """
        Convenient POST request with path parts and JSON body.

        Args:
            *parts: URL path segments that will be joined with '/'
            params: Optional query parameters
            **json: JSON body fields as keyword arguments

        Returns:
            requests.Response object

        Example:
            >>> response = client.POST('articles', title='Study', doi='10.1234/example')
            # Equivalent to: POST /api/v1/articles with JSON body
        """
        endpoint = "/".join(str(p) for p in parts)
        return self.post(endpoint, params=params, json=json)

    def PUT(self, *parts, params=None, **json) -> requests.Response:
        """
        Convenient PUT request with path parts and JSON body.

        Args:
            *parts: URL path segments that will be joined with '/'
            params: Optional query parameters
            **json: JSON body fields as keyword arguments

        Returns:
            requests.Response object

        Example:
            >>> response = client.PUT('articles', '123', title='Updated Study')
            # Equivalent to: PUT /api/v1/articles/123 with JSON body
        """
        endpoint = "/".join(str(p) for p in parts)
        return self.put(endpoint, params=params, json=json)

    def PATCH(self, *parts, params=None, **json) -> requests.Response:
        """
        Convenient PATCH request with path parts and JSON body.

        Args:
            *parts: URL path segments that will be joined with '/'
            params: Optional query parameters
            **json: JSON body fields as keyword arguments

        Returns:
            requests.Response object

        Example:
            >>> response = client.PATCH('articles', '123', status='published')
            # Equivalent to: PATCH /api/v1/articles/123 with JSON body
        """
        endpoint = "/".join(str(p) for p in parts)
        return self.patch(endpoint, params=params, json=json)

    def DELETE(self, *parts, **params) -> requests.Response:
        """
        Convenient DELETE request with path parts as separate arguments.

        Args:
            *parts: URL path segments that will be joined with '/'
            **params: Query parameters as keyword arguments

        Returns:
            requests.Response object

        Example:
            >>> response = client.DELETE('articles', '123')
            # Equivalent to: DELETE /api/v1/articles/123
        """
        endpoint = "/".join(str(p) for p in parts)
        return self.delete(endpoint, params=params)
