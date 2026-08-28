from __future__ import annotations

import json
import os
import urllib.request

import pytest

from litectl.modules.workspace.domain.settings import PLACEHOLDER_KEY

OMLX_API_BASE = "http://127.0.0.1:8008/v1"
OMLX_MODEL = "Llama-3.2-3B-Instruct-4bit"


def local_request(
    path: str, body: dict[str, object] | None = None
) -> dict[str, object]:
    api_key = os.environ.get("OMLX_API_KEY", PLACEHOLDER_KEY)
    if os.environ.get("RUN_LOCAL_LLM_TESTS") != "1":
        pytest.skip("set RUN_LOCAL_LLM_TESTS=1 to exercise local oMLX")
    request = urllib.request.Request(
        f"{OMLX_API_BASE}/{path}",
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
        value = json.loads(response.read().decode())
    assert isinstance(value, dict)
    return value


def test_local_llama_3_2_3b_completion() -> None:
    models = local_request("models")
    data = models.get("data")
    assert isinstance(data, list)
    model_ids = {
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    assert OMLX_MODEL in model_ids

    completion = local_request(
        "chat/completions",
        {
            "model": OMLX_MODEL,
            "messages": [{"role": "user", "content": "Reply with OK only."}],
            "max_tokens": 4,
        },
    )

    assert completion.get("choices")
