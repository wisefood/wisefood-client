"""
A compact, robust HTTP client for the Wisefood API (systemic operations).
"""

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .exceptions import raise_for_api_error
from .entities.households import HouseholdsProxy, MembersProxy


# -------------------------------
# Credentials Model
# -------------------------------



@dataclass
class Credentials:
    """
    Either user credentials (username & password) OR client credentials
    (client_id & client_secret) must be provided. They are mutually exclusive.
    """
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

    def __post_init__(self) -> None:
        has_user = bool(self.username or self.password)
        has_client = bool(self.client_id or self.client_secret)

        if has_user and has_client:
            raise ValueError("Provide either username/password OR client_id/client_secret, not both.")

        if not (self.username and self.password) and not (self.client_id and self.client_secret):
            raise ValueError("Must provide either username/password OR client_id/client_secret.")

    @property
    def is_user_credentials(self) -> bool:
        return bool(self.username and self.password)

    @property
    def is_client_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)


# -------------------------------
# Exceptions
# -------------------------------


class WisefoodError(RuntimeError):
    pass


# -------------------------------
# Main Client
# -------------------------------


class Client:
    """
    HTTP client for the Wisefood API with automatic authentication and token management.

    This client handles all communication with the Wisefood API, including:
    - Automatic authentication using username/password or client credentials
    - Token refresh when expired
    - Connection pooling and retry logic
    - Clean endpoint URL construction

    Args:
        base_url: Base URL of the Wisefood API (e.g., 'https://api.wisefood.com')
        credentials: Credentials object containing either username/password or client_id/client_secret
        api_prefix: API version prefix (default: '/api/v1')
        verify_tls: Whether to verify SSL/TLS certificates (default: True)
        default_timeout: Default request timeout in seconds (default: 30.0)
        pool_connections: Number of connection pools to cache (default: 3)
        pool_maxsize: Maximum number of connections to save in the pool (default: 10)

    Example:
        >>> creds = Credentials(username='user@example.com', password='secret')
        >>> client = Client('https://api.wisefood.com', creds)
        >>> response = client.GET('foods', 'search', q='apple')
        >>> foods = response.json()
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
        pool_maxsize: int = 10,
    ) -> None:

        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix.strip("/")
        self.credentials = credentials
        self.verify_tls = verify_tls
        self.default_timeout = default_timeout

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

        # Authenticate immediately
        self.authenticate()

        # Proxies for API resource groups
        self.households = HouseholdsProxy(self)
        self.members = MembersProxy(self)

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
            Complete API base URL (e.g., 'https://api.wisefood.com/api/v1')
        """
        return self._join(self.base_url, self.api_prefix)

    def endpoint(self, endpoint: str) -> str:
        """
        Construct absolute URL for an API endpoint.

        Args:
            endpoint: Relative endpoint path (e.g., 'foods/123' or '/foods/123')

        Returns:
            Complete URL (e.g., 'https://api.wisefood.com/api/v1/foods/123')
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
        """
        Ensure a valid authentication token exists, refreshing if necessary.

        Automatically re-authenticates if the token is missing or expired.
        """
        if not self._token or time.time() >= self._token_expiry_ts:
            self.authenticate()

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
            ValueError: If GET/DELETE request includes a body
            WisefoodError: If the API returns an error response

        Example:
            >>> response = client.request('GET', 'foods/123')
            >>> response = client.request('POST', 'foods', json={'name': 'Apple'})
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
            >>> response = client.get('foods/search', q='apple', limit=10)
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
            >>> response = client.post('foods', json={'name': 'Apple', 'calories': 95})
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
            >>> response = client.put('foods/123', json={'name': 'Green Apple'})
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
            >>> response = client.patch('foods/123', json={'calories': 100})
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
            >>> response = client.delete('foods/123')
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
            >>> response = client.GET('foods', 'search', q='apple', limit=10)
            # Equivalent to: GET /api/v1/foods/search?q=apple&limit=10
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
            >>> response = client.POST('foods', name='Apple', calories=95)
            # Equivalent to: POST /api/v1/foods with JSON body
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
            >>> response = client.PUT('foods', '123', name='Green Apple')
            # Equivalent to: PUT /api/v1/foods/123 with JSON body
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
            >>> response = client.PATCH('foods', '123', calories=100)
            # Equivalent to: PATCH /api/v1/foods/123 with JSON body
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
            >>> response = client.DELETE('foods', '123')
            # Equivalent to: DELETE /api/v1/foods/123
        """
        endpoint = "/".join(str(p) for p in parts)
        return self.delete(endpoint, params=params)
