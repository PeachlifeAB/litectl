"""Network probe utilities for the discovery adapter."""

from __future__ import annotations

import json
import urllib.request
from typing import TypeGuard

from litectl.modules.catalog.domain.urls import ensure_http_url

JsonObject = dict[str, object]


def is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def model_data(payload: object) -> list[JsonObject]:
    """Model records from either payload shape servers actually return.

    OpenAI-compatible servers answer `{"data": [...]}`; some answer with a
    bare array. Both are the same catalog.
    """
    if isinstance(payload, list):
        return [item for item in payload if is_json_object(item)]
    if not is_json_object(payload):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if is_json_object(item)]


def http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 5,
) -> list[JsonObject]:
    ensure_http_url(url)
    req = urllib.request.Request(url, headers=headers or {})
    # Scheme validated above; only http(s) reaches here.
    with urllib.request.urlopen(  # nosec B310: ensure_http_url allows only HTTP(S)
        req, timeout=timeout_seconds
    ) as resp:
        return model_data(json.loads(resp.read().decode("utf-8")))
