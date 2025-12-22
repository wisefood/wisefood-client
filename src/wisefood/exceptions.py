from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class APIError(Exception):
    """
    Base client-side API error.

    Mirrors the server-side structure:
        {
          "success": false,
          "error": {
              "title": "...",
              "detail": "...",
              "code": "resource/not_found",
              ...
          },
          "help": "http://.../api/v1/articles/hello"
        }
    """

    status_code: int
    detail: str = ""
    code: Optional[str] = None          # e.g. "resource/not_found"
    title: Optional[str] = None         # e.g. "NotFoundError"
    errors: Any = None                  # nested errors (validation etc.)
    extra: Dict[str, Any] = None        # extra info from server
    help_url: Optional[str] = None      # value of top-level 'help' field
    response_body: Any = None           # raw parsed JSON of the response

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}
        # Default message for Exception.__str__
        msg = self.detail or self.title or f"HTTP {self.status_code}"
        super().__init__(msg)

    @property
    def retryable(self) -> bool:
        """Whether a retry might make sense (for client backoff logic)."""
        return (
            self.status_code in (429, 503, 504)
            or 500 <= self.status_code < 600
        )


# -------------------------------------------------
# Typed client-side exceptions
# -------------------------------------------------

class InvalidError(APIError):
    pass


class DataError(APIError):
    pass


class AuthenticationError(APIError):
    pass


class AuthorizationError(APIError):
    pass


class NotFoundError(APIError):
    pass


class NotAllowedError(APIError):
    pass


class ConflictError(APIError):
    pass


class RateLimitError(APIError):
    pass


class InternalError(APIError):
    pass


class BadGatewayError(APIError):
    pass


class ServiceUnavailableError(APIError):
    pass


class GatewayTimeoutError(APIError):
    pass


# -------------------------------------------------
# Mapping helpers
# -------------------------------------------------

# Map server-side `code` → specific client exception
_CODE_TO_EXCEPTION = {
    "request/invalid": InvalidError,
    "request/unprocessable": DataError,
    "auth/unauthorized": AuthenticationError,
    "auth/forbidden": AuthorizationError,
    "resource/not_found": NotFoundError,
    "request/not_allowed": NotAllowedError,
    "resource/conflict": ConflictError,
    "quota/rate_limited": RateLimitError,
    "server/internal": InternalError,
    "upstream/bad_gateway": BadGatewayError,
    "upstream/unavailable": ServiceUnavailableError,
    "upstream/timeout": GatewayTimeoutError,
}

# Fallback mapping by HTTP status code
_STATUS_TO_EXCEPTION = {
    400: InvalidError,
    401: AuthenticationError,
    403: AuthorizationError,
    404: NotFoundError,
    405: NotAllowedError,
    409: ConflictError,
    422: DataError,
    429: RateLimitError,
    500: InternalError,
    502: BadGatewayError,
    503: ServiceUnavailableError,
    504: GatewayTimeoutError,
}


def _pick_exception_class(status_code: int, code: Optional[str]) -> type[APIError]:
    if code and code in _CODE_TO_EXCEPTION:
        return _CODE_TO_EXCEPTION[code]
    if status_code in _STATUS_TO_EXCEPTION:
        return _STATUS_TO_EXCEPTION[status_code]
    return APIError


def _format_detail(detail: Any) -> str:
    """
    Turn common validation-detail shapes into a readable string.

    FastAPI-style validation errors often look like:
        {"detail": [{"loc": ["body", "field"], "msg": "field required", ...}, ...]}
    """
    if isinstance(detail, str):
        return detail

    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = item.get("loc") or []
                loc_str = ".".join(str(p) for p in loc) if loc else ""
                msg = item.get("msg") or item.get("message") or str(item)
                parts.append(f"{loc_str}: {msg}" if loc_str else str(msg))
            else:
                parts.append(str(item))
        return "; ".join(parts)

    return str(detail)


def error_from_response(response) -> APIError:
    """
    Build a concrete APIError subclass from a `requests.Response`.

    Expected Wisefood error payload shape:
        {
          "success": false,
          "error": {
            "title": "NotFoundError",
            "detail": "Article with URN urn:article:hello not found.",
            "code": "resource/not_found",
            ... maybe other keys ...
          },
          "help": "http://.../api/v1/articles/hello"
        }

    If the body is not JSON or doesn't match the envelope, we still
    build a generic APIError with whatever information we can.
    """

    status_code = response.status_code

    body: Any
    try:
        body = response.json()
    except Exception:
        # Non-JSON error
        return APIError(
            status_code=status_code,
            detail=response.text or f"HTTP {status_code}",
            response_body=None,
        )

    success = body.get("success")
    error_block = body.get("error") if isinstance(body, dict) else None
    help_url = body.get("help") if isinstance(body, dict) else None

    # If the envelope is not there, fall back to generic
    if success is not False or not isinstance(error_block, dict):
        # Special-case validation errors (422) that might not use the envelope
        if status_code == 422 and isinstance(body, dict) and "detail" in body:
            detail = _format_detail(body.get("detail", ""))
            return DataError(
                status_code=status_code,
                detail=detail,
                errors=body.get("detail"),
                extra={k: v for k, v in body.items() if k != "detail"},
                response_body=body,
                help_url=help_url,
            )

        return APIError(
            status_code=status_code,
            detail=str(body),
            response_body=body,
            help_url=help_url,
        )

    # Extract structured fields from the error block
    title = error_block.get("title")
    detail = error_block.get("detail", "")
    code = error_block.get("code")
    errors = error_block.get("errors")  # optional

    # Surface validation error details in the exception message
    formatted_errors = _format_detail(errors) if errors else ""
    if status_code == 422 and formatted_errors:
        detail = f"{detail}: {formatted_errors}" if detail else formatted_errors

    extra = {
        k: v
        for k, v in error_block.items()
        if k not in {"title", "detail", "code", "errors"}
    }

    exc_cls = _pick_exception_class(status_code, code)

    return exc_cls(
        status_code=status_code,
        detail=detail,
        code=code,
        title=title,
        errors=errors,
        extra=extra,
        help_url=help_url,
        response_body=body,
    )


def raise_for_api_error(response) -> None:
    """
    Inspect a `requests.Response` and raise a suitable APIError subclass
    if the Wisefood API indicates failure.

    Usage in your client:

        resp = self.get(\"articles/hello\")
        raise_for_api_error(resp)
        data = resp.json()[\"result\"]

    Behavior:
    - If HTTP status is 2xx and `success` is True → returns silently.
    - If HTTP status >= 400 or `success` is False → raises APIError subclass.
    """
    status = response.status_code

    # 2xx → might still be envelope-based error, so we check body
    try:
        body = response.json()
    except Exception:
        if status >= 400:
            raise error_from_response(response)
        return

    if isinstance(body, dict) and "success" in body:
        if body.get("success") is True and status < 400:
            return
        # success is False or HTTP error
        raise error_from_response(response)

    # No `success` field; rely on HTTP status
    if status >= 400:
        raise error_from_response(response)
