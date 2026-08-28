"""Report whether a freshly installed proxy actually serves a request.

Inbound adapter: all console output for the post-install check.
"""

from __future__ import annotations

from pathlib import Path

from litectl.modules.workspace.infrastructure.healthcheck import (
    choose_model,
    complete,
    wait_for_models,
)
from litectl.modules.workspace.infrastructure.service import LOG_NAMES

LOG_TAIL_CHARS = 1500


def tail(path: Path, limit: int = LOG_TAIL_CHARS) -> str:
    if not path.exists():
        return f"({path.name} not created)"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return f"({path.name} is empty)"
    return text[-limit:]


def print_logs(state_dir: Path) -> None:
    for name in LOG_NAMES:
        print(f"\n--- [ {name} ] ---")
        print(tail(state_dir / name))


def verify(state_dir: Path, master_key: str, port: str) -> bool:
    """Check the proxy answers, then run one completion. False if unusable."""
    url = f"http://127.0.0.1:{port}"
    print(f"\n⏳ Checking LiteLLM proxy status on {url} ...")

    attempt = wait_for_models(url, master_key)
    if attempt.unauthorized:
        print(
            "✗ HTTP 401 Unauthorized: master key mismatch with the proxy environment."
        )
        print_logs(state_dir)
        return False
    if not attempt.models:
        print(
            "ℹ No concrete chat models registered."
            " Check providers, or run `litectl update`."
        )
        print_logs(state_dir)
        return False

    model = choose_model(attempt.models)
    if model is None:
        print("✓ Proxy ready. No local chat model is available for a smoke request.")
        print_logs(state_dir)
        return True
    print(f"✓ Proxy ready. Discovered {len(attempt.models)} model(s). Testing: {model}")
    print(f"\n❯ Running Hello World check on model: '{model}'")
    print(f"✓ Response:\n  {complete(url, master_key, model)}")
    print_logs(state_dir)
    return True
