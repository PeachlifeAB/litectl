"""Detect a local OpenAI-compatible inference server.

Outbound adapter: the only place install performs network access.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

from litectl.modules.workspace.domain.urls import ensure_http_url

CANDIDATE_PORTS: tuple[int, ...] = (8008, 8080, 11434, 1234, 5000, 8000)
PROBE_TIMEOUT_SECONDS = 0.3
AUTH_STATUS_CODES = frozenset({401, 403})
PLACEHOLDER_KEY = "not-needed"


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of scanning the candidate ports."""

    reachable: bool = False
    port: int | None = None
    needs_auth: bool = False


def _request(port: int, api_key: str | None) -> urllib.request.Request:
    request = urllib.request.Request(
        ensure_http_url(f"http://127.0.0.1:{port}/v1/models")
    )
    if api_key and api_key != PLACEHOLDER_KEY:
        request.add_header("Authorization", f"Bearer {api_key}")
    return request


def probe_port(port: int, api_key: str | None = None) -> ProbeResult:
    """Check one local port for an OpenAI-compatible ``/v1/models`` endpoint."""
    try:
        # URL is a literal http:// loopback address built here, never user input.
        with urllib.request.urlopen(  # nosec B310: literal loopback HTTP URL
            _request(port, api_key), timeout=PROBE_TIMEOUT_SECONDS
        ):
            return ProbeResult(reachable=True, port=port)
    except urllib.error.HTTPError as error:
        if error.code in AUTH_STATUS_CODES:
            return ProbeResult(reachable=True, port=port, needs_auth=True)
        return ProbeResult()
    except urllib.error.URLError:
        # A refused connection is the expected result while scanning.
        return ProbeResult()


def find_local_server(api_key: str | None = None) -> ProbeResult:
    """Return the first candidate port answering, or an unreachable result."""
    for port in CANDIDATE_PORTS:
        result = probe_port(port, api_key)
        if result.reachable:
            return result
    return ProbeResult()
