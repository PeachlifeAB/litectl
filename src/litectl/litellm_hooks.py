"""Proxy callback that keeps local chat templates renderable.

Some clients (fabric) send a single system message with no user turn.
The local chat templates reject that outright ("No user query found in
messages"), and LiteLLM then walks the fallback chain, cold-loading one
model after another. One pre-call rewrite fixes every provider at once.

Registered in the generated config as::

    litellm_settings:
      callbacks:
        - litectl.litellm_hooks.handler
"""

from __future__ import annotations

from typing import Any

from litellm.integrations.custom_logger import CustomLogger

USER_ROLE = "user"


def ensure_user_turn(
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Turn a system-only conversation into a user turn, in place.

    Everything else — any request that already has a user message, or an
    empty/absent list — is returned untouched.
    """
    if not messages:
        return messages
    if any(message.get("role") == USER_ROLE for message in messages):
        return messages
    messages[0]["role"] = "user"
    return messages


class EnsureUserTurnHandler(CustomLogger):
    async def async_pre_call_hook(
        self,
        user_api_key_dict: Any,  # noqa: ARG002 — LiteLLM hook signature
        cache: Any,  # noqa: ARG002
        data: dict[str, Any],
        call_type: str,  # noqa: ARG002
    ) -> dict[str, Any]:
        ensure_user_turn(data.get("messages"))
        return data


handler = EnsureUserTurnHandler()
