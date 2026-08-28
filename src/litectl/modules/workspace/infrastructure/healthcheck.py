"""Query a running proxy for readiness and a sample completion.

Outbound adapter: HTTP against the local proxy only.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TypeGuard

from litectl.modules.workspace.domain.urls import ensure_http_url

READY_ATTEMPTS = 15
POLL_SECONDS = 1.0
MODELS_TIMEOUT_SECONDS = 1.5
COMPLETION_TIMEOUT_SECONDS = 30
UNAUTHORIZED = 401
WILDCARD_SUFFIX = "/*"
PREFERRED_LOCAL_MODEL = "omlx-llama-3.2-3b"
LOCAL_MODEL_PREFIX = "omlx-"

JsonObject = dict[str, object]


@dataclass(frozen=True)
class Attempt:
    """One readiness poll: either models, or the reason there are none yet."""

    models: tuple[str, ...] = ()
    note: str = ""
    unauthorized: bool = False


def _headers(master_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {master_key}",
        "Content-Type": "application/json",
    }


def _is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _get_json(url: str, master_key: str, timeout: float) -> JsonObject:
    request = urllib.request.Request(ensure_http_url(url), headers=_headers(master_key))
    with urllib.request.urlopen(  # nosec B310: ensure_http_url allows only HTTP(S)
        request, timeout=timeout
    ) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    return parsed if _is_json_object(parsed) else {}


def list_models(url: str, master_key: str) -> Attempt:
    """Ask the proxy which concrete models it has registered."""
    try:
        payload = _get_json(f"{url}/models", master_key, MODELS_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        if error.code == UNAUTHORIZED:
            return Attempt(unauthorized=True, note="master key mismatch")
        return Attempt(note=f"HTTP {error.code}: {error.reason}")
    except (urllib.error.URLError, json.JSONDecodeError):
        return Attempt(note="waiting for proxy")

    data = payload.get("data")
    items = data if isinstance(data, list) else []
    models = tuple(
        model_id
        for item in items
        if _is_json_object(item)
        and isinstance((model_id := item.get("id")), str)
        and not model_id.endswith(WILDCARD_SUFFIX)
    )
    return Attempt(models=models, note="" if models else "awaiting model registry")


def wait_for_models(url: str, master_key: str) -> Attempt:
    """Poll until the proxy registers a concrete model or attempts run out."""
    attempt = Attempt()
    for _ in range(READY_ATTEMPTS):
        attempt = list_models(url, master_key)
        if attempt.models or attempt.unauthorized:
            return attempt
        time.sleep(POLL_SECONDS)
    return attempt


def choose_model(models: tuple[str, ...]) -> str | None:
    preferred = next(
        (model for model in models if PREFERRED_LOCAL_MODEL in model.lower()), None
    )
    if preferred:
        return preferred
    return next(
        (model for model in models if model.startswith(LOCAL_MODEL_PREFIX)), None
    )


def _completion_content(value: object) -> str:
    if not _is_json_object(value):
        raise TypeError("completion response is not an object")
    choices = value.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("completion response has no choices")
    choice = choices[0]
    if not _is_json_object(choice):
        raise TypeError("completion response has no choice object")
    message = choice.get("message")
    if not _is_json_object(message):
        raise TypeError("completion response has no message")
    content = message.get("content")
    if not isinstance(content, str):
        raise TypeError("completion response has no text")
    return content.strip()


def complete(url: str, master_key: str, model: str) -> str:
    """Send one completion and return the reply, or a note about the failure."""
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "user", "content": "Respond with 'Hello World!' only."}
            ],
            "max_tokens": 20,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ensure_http_url(f"{url}/v1/chat/completions"),
        data=body,
        headers=_headers(master_key),
    )
    try:
        with urllib.request.urlopen(  # nosec B310: URL validated above
            request, timeout=COMPLETION_TIMEOUT_SECONDS
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
        return _completion_content(result)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return f"HTTP {error.code}: {detail[:300]}"
    except (OSError, TypeError, ValueError) as error:
        return f"test call notice: {error}"
