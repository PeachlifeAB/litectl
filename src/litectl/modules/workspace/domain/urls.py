"""URL validation for the local proxy and provider endpoints.

Provider base URLs come from the environment, so they are untrusted input.
urllib honours `file:` and custom schemes, which would turn a mistyped or
hostile base URL into a local file read; only http and https are allowed.
"""

from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsupportedSchemeError(ValueError):
    """Raised when a URL uses a scheme that must never be opened."""

    def __init__(self, url: str, scheme: str) -> None:
        allowed = ", ".join(sorted(ALLOWED_SCHEMES))
        super().__init__(
            f"refusing to open {scheme or 'scheme-less'} URL: {url!r};"
            f" allowed: {allowed}"
        )
        self.url = url
        self.scheme = scheme


def ensure_http_url(url: str) -> str:
    """Return ``url`` unchanged, or raise if its scheme is not http(s)."""
    scheme = urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsupportedSchemeError(url, scheme)
    return url
