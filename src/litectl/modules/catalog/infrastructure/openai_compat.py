"""Fetch models from any OpenAI-compatible provider.

One adapter for every provider: oMLX, Ollama, llama.cpp, LM Studio, Dwarfstar
ds4 and Cerebras all expose `/v1/models`. Only `id` is guaranteed across
servers; payloads may be a bare array or `{"data": [...]}`.

A provider that cannot be reached reports itself unavailable rather than
raising, so one offline endpoint never aborts discovery for the others.
"""

from __future__ import annotations

import json
import urllib.error

from litectl.modules.catalog.application.ports import (
    ProbeResult,
    Reachable,
    Unreachable,
)
from litectl.modules.catalog.domain.models import ModelDescriptor
from litectl.modules.catalog.domain.urls import (
    UnsupportedSchemeError,
    ensure_http_url,
)
from litectl.modules.catalog.infrastructure.base import http_get_json

PLACEHOLDER_KEY = "not-needed"
MODELS_PATH = "/models"
UNAUTHORIZED = 401
PAYMENT_REQUIRED = 402
FORBIDDEN = 403

FETCH_ERRORS = (
    urllib.error.URLError,
    json.JSONDecodeError,
    KeyError,
    UnsupportedSchemeError,
)


def auth_headers(api_key: str | None) -> dict[str, str] | None:
    """Bearer header, or None when the provider needs no key."""
    if api_key and api_key != PLACEHOLDER_KEY:
        return {"Authorization": f"Bearer {api_key}"}
    return None


def to_descriptors(
    payload: list[dict[str, object]],
) -> tuple[ModelDescriptor, ...]:
    """Descriptors for distinct, non-empty ids — in first-seen order."""
    seen: set[str] = set()
    models: list[ModelDescriptor] = []
    for item in payload:
        raw_id = item.get("id")
        if not isinstance(raw_id, str):
            continue
        model_id = raw_id.strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        max_model_len = item.get("max_model_len")
        models.append(
            ModelDescriptor(
                raw_id=model_id,
                max_model_len=max_model_len if isinstance(max_model_len, int) else None,
            )
        )
    return tuple(models)


def _describe(error: Exception) -> str:
    """A short reason suitable for printing next to the provider name.

    Status codes are reported rather than interpreted: providers disagree on
    what 402 means, so the code is shown and the operator decides.
    """
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (UNAUTHORIZED, FORBIDDEN):
            return f"authentication failed (HTTP {error.code})"
        if error.code == PAYMENT_REQUIRED:
            return "provider reports payment or quota required (HTTP 402)"
        return f"HTTP {error.code}"
    if isinstance(error, UnsupportedSchemeError):
        return str(error)
    if isinstance(error, urllib.error.URLError):
        reason = str(error.reason)
        if "refused" in reason:
            return "connection refused"
        if "timed out" in reason:
            return "connection timed out"
        return f"endpoint unreachable ({reason})"
    return "invalid payload"


def fetch_models(
    api_base: str, api_key: str | None = None, timeout_seconds: int = 5
) -> ProbeResult:
    """Ask one provider what it serves, reporting failure rather than raising."""
    try:
        url = ensure_http_url(f"{api_base.rstrip('/')}{MODELS_PATH}")
        payload = http_get_json(
            url, headers=auth_headers(api_key), timeout_seconds=timeout_seconds
        )
    except FETCH_ERRORS as error:
        return Unreachable(_describe(error))
    return Reachable(api_base, to_descriptors(payload))
