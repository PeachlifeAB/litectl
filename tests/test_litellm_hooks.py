"""The proxy hook that keeps local chat templates renderable.

Clients like fabric send a single system message with no user turn; the
omlx chat templates reject that outright, and LiteLLM then walks the
fallback chain cold-loading model after model. One pre-call rewrite
fixes every provider at once.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from litectl.litellm_hooks import EnsureUserTurnHandler, ensure_user_turn, handler


def messages(*roles: str) -> list[dict[str, str]]:
    return [{"role": role, "content": f"{role}-body"} for role in roles]


def test_system_only_becomes_user_turn() -> None:
    rewritten = ensure_user_turn(messages("system"))
    assert rewritten == [{"role": "user", "content": "system-body"}]


def test_system_plus_user_is_untouched() -> None:
    original = messages("system", "user")
    assert ensure_user_turn(original) == original


def test_plain_user_request_is_untouched() -> None:
    original = messages("user")
    assert ensure_user_turn(original) == original


def test_missing_or_non_list_messages_returned_unchanged() -> None:
    assert ensure_user_turn(None) is None
    assert ensure_user_turn([]) == []


@pytest.mark.anyio
async def test_handler_rewrites_data_messages() -> None:
    data: dict[str, Any] = {"messages": messages("system"), "model": "default"}
    result = await handler.async_pre_call_hook(
        user_api_key_dict=None, cache=None, data=data, call_type="completion"
    )
    assert result["messages"] == [{"role": "user", "content": "system-body"}]


def test_handler_is_registered_callback() -> None:
    from litellm.integrations.custom_logger import CustomLogger

    assert isinstance(handler, CustomLogger)


def test_litellm_loader_resolves_the_shim_next_to_config(
    tmp_path: Path,
) -> None:
    """The deployed callback must load through LiteLLM's own loader."""
    from importlib.resources import files

    from litellm.proxy.types_utils.utils import get_instance_fn

    shim = (
        files("litectl.resources")
        .joinpath("litectl_hooks.py")
        .read_text(encoding="utf-8")
    )
    (tmp_path / "litectl_hooks.py").write_text(shim, encoding="utf-8")

    loaded = get_instance_fn(
        "litectl_hooks.handler", config_file_path=str(tmp_path / "config.yaml")
    )
    assert isinstance(loaded, EnsureUserTurnHandler)


def test_install_manifest_ships_the_shim() -> None:
    from litectl.modules.workspace.domain.manifest import MANIFEST

    targets = {entry.target for entry in MANIFEST}
    assert "litectl_hooks.py" in targets


@pytest.mark.parametrize(
    ("label", "text", "interpolate"),
    [
        ("resource", None, True),
        ("seed", None, False),
    ],
)
def test_shipped_config_callbacks_all_resolve(
    tmp_path: Path, label: str, text: str | None, interpolate: bool
) -> None:
    """Every callback the shipped configs register must load via LiteLLM."""
    from importlib.resources import files

    from litellm.proxy.types_utils.utils import get_instance_fn
    from ruamel.yaml import YAML

    from litectl.modules.workspace.domain.settings import Settings
    from litectl.modules.workspace.infrastructure.filesystem import render
    from litectl.serve import ensure_callback_shim

    if text is None:
        text = (
            files("litectl.resources")
            .joinpath("config.yaml")
            .read_text(encoding="utf-8")
        )
    if interpolate:
        sample = Settings(master_key="sk-local-test")
        text = render(text, sample.as_template_values())
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")
    ensure_callback_shim(tmp_path)

    document = YAML(typ="safe").load(text)
    callbacks = document["litellm_settings"]["callbacks"]

    assert callbacks, f"{label} config lost its callbacks"
    for entry in callbacks:
        assert get_instance_fn(entry, config_file_path=str(tmp_path / "config.yaml"))
