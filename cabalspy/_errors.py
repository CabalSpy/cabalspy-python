"""Exception hierarchy for the CabalSpy SDK.

Every failure raised by this library is a subclass of :class:`CabalSpyError`, so
callers can branch on the kind of failure instead of parsing message strings.
"""

from __future__ import annotations

from typing import Any


class CabalSpyError(Exception):
    """Base class for every error raised by this library."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "unknown_error",
        request_id: str | None = None,
        docs: str | None = None,
        parameter: str | None = None,
        allowed: list[Any] | None = None,
        rate_limit: "RateLimit | None" = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        self.docs = docs
        self.parameter = parameter
        self.allowed = allowed
        self.rate_limit = rate_limit or RateLimit()

    def __str__(self) -> str:
        parts = [self.message]
        if self.code and self.code != "unknown_error":
            parts.append(f"(code={self.code}")
            if self.parameter:
                parts[-1] += f", parameter={self.parameter}"
            if self.request_id:
                parts[-1] += f", request_id={self.request_id}"
            parts[-1] += ")"
        return " ".join(parts)


class BadRequestError(CabalSpyError):
    """400 — missing_parameter, invalid_parameter or invalid_body."""


class AuthenticationError(CabalSpyError):
    """401 — missing_api_key."""


class PermissionError_(CabalSpyError):
    """403 — invalid_api_key."""


class InsufficientCreditsError(PermissionError_):
    """403 — insufficient_credits. Separate so billing can be handled on its own."""


class NotFoundError(CabalSpyError):
    """404 — wallet_not_found or token_not_found."""


class RateLimitError(CabalSpyError):
    """429 — rate_limit_exceeded."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(CabalSpyError):
    """5xx — internal_error or service_unavailable."""


class APIConnectionError(CabalSpyError):
    """Network failure, timeout or aborted connection."""


class InvalidResponseError(CabalSpyError):
    """The response was not valid JSON, or did not have the expected envelope."""


class RateLimit:
    """Rate limit state parsed from the X-RateLimit-* response headers."""

    __slots__ = ("limit", "remaining", "reset")

    def __init__(
        self,
        limit: int | None = None,
        remaining: int | None = None,
        reset: int | None = None,
    ) -> None:
        self.limit = limit
        self.remaining = remaining
        #: Unix seconds at which the current minute window resets.
        self.reset = reset

    def __repr__(self) -> str:
        return f"RateLimit(limit={self.limit}, remaining={self.remaining}, reset={self.reset})"


def error_from_status(
    status: int,
    body: dict[str, Any] | None,
    rate_limit: RateLimit,
    retry_after: float | None,
    fallback: str,
) -> CabalSpyError:
    """Maps an HTTP status and error body onto the right exception class."""
    body = body or {}
    kwargs: dict[str, Any] = {
        "status": status,
        "code": body.get("code") or f"http_{status}",
        "request_id": body.get("request_id"),
        "docs": body.get("docs"),
        "parameter": body.get("parameter"),
        "allowed": body.get("allowed"),
        "rate_limit": rate_limit,
    }
    message = body.get("message") or fallback

    if status == 400:
        return BadRequestError(message, **kwargs)
    if status == 401:
        return AuthenticationError(message, **kwargs)
    if status == 403:
        if body.get("code") == "insufficient_credits":
            return InsufficientCreditsError(message, **kwargs)
        return PermissionError_(message, **kwargs)
    if status == 404:
        return NotFoundError(message, **kwargs)
    if status == 429:
        return RateLimitError(message, retry_after=retry_after, **kwargs)
    if status >= 500:
        return ServerError(message, **kwargs)
    return CabalSpyError(message, **kwargs)


def is_retryable(exc: BaseException) -> bool:
    """True for failures where retrying with backoff is worthwhile."""
    return isinstance(exc, (RateLimitError, ServerError, APIConnectionError))
