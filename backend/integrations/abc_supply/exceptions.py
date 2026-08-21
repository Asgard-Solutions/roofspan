"""ABC Supply error normalization.

Raw ABC/transport errors are converted into a small set of RoofSpan-facing errors with
user-safe messages. Sanitized technical detail is retained for logs/support; secrets and
tokens are NEVER placed in messages or detail.
"""
from __future__ import annotations


class AbcError(Exception):
    """Base ABC integration error. `user_message` is safe to surface to end users."""

    def __init__(self, user_message: str, *, status: int | None = None, detail: str | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.status = status
        self.detail = detail


class AbcAuthError(AbcError):
    """Token expired / invalid / connection needs re-authorization."""


class AbcNotConfigured(AbcError):
    """ABC integration has not been configured/connected yet."""


class AbcTransportError(AbcError):
    """Could not reach ABC / network failure."""


class AbcRateLimited(AbcError):
    """429 from ABC after bounded retries."""


def normalize_status(status: int, body_text: str | None = None) -> AbcError:
    detail = (body_text or "")[:500]
    if status in (401,):
        return AbcAuthError(
            "Your ABC Supply connection has expired. Please reconnect ABC Supply.",
            status=status,
            detail=detail,
        )
    if status in (403,):
        return AbcAuthError(
            "Your ABC Supply account does not have access to the requested data.",
            status=status,
            detail=detail,
        )
    if status == 429:
        return AbcRateLimited(
            "ABC Supply is temporarily rate-limiting requests. Please try again shortly.",
            status=status,
            detail=detail,
        )
    if status == 400:
        return AbcError("ABC Supply rejected the request. Please review the details and try again.", status=status, detail=detail)
    if status in (404,):
        return AbcError("The requested ABC Supply resource was not found.", status=status, detail=detail)
    return AbcError("ABC Supply is currently unavailable. Please try again shortly.", status=status, detail=detail)
