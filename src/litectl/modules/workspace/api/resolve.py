"""Resolve install settings from the environment, probing and prompting as needed.

Inbound adapter: sequences the key lookup, the local-server probe and the
prompts. Each step is separately testable; the original single function mixed
all three and scored 13 cyclomatic complexity.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from litectl.modules.workspace.api.prompts import (
    ask_cerebras_key,
    ask_omlx_key,
)
from litectl.modules.workspace.domain.settings import (
    DEFAULT_PORT,
    PLACEHOLDER_KEY,
    Settings,
)
from litectl.modules.workspace.infrastructure.keys import (
    client_saved_master_key,
    resolve_setting,
)
from litectl.modules.workspace.infrastructure.probe import find_local_server

MASTER_KEY_BYTES = 16
DEFAULT_CEREBRAS_API_BASE = "https://api.cerebras.ai/v1"


def mint_master_key() -> str:
    return f"sk-local-{secrets.token_hex(MASTER_KEY_BYTES)}"


def resolve_master_key(base_dir: Path, home_dir: Path) -> str:
    """Reuse an existing master key before minting a new one.

    A reinstall that mints a fresh key leaves every configured client holding
    a stale one, so an existing value always wins.
    """
    return (
        resolve_setting(base_dir, "LITELLM_MASTER_KEY")
        or client_saved_master_key(home_dir)
        or mint_master_key()
    )


def read_settings(base_dir: Path, home_dir: Path) -> Settings:
    """Collect settings from the environment and any existing workspace."""
    return Settings(
        master_key=resolve_master_key(base_dir, home_dir),
        port=resolve_setting(base_dir, "LITELLM_PORT", DEFAULT_PORT),
        omlx_base=resolve_setting(base_dir, "OMLX_API_BASE"),
        omlx_key=resolve_setting(base_dir, "OMLX_API_KEY", PLACEHOLDER_KEY),
        cerebras_base=resolve_setting(
            base_dir, "CEREBRAS_API_BASE", DEFAULT_CEREBRAS_API_BASE
        ),
        cerebras_key=resolve_setting(base_dir, "CEREBRAS_API_KEY"),
    )


def ensure_provider(settings: Settings, interactive: bool = True) -> Settings:
    """Make sure at least one provider is reachable, asking only when needed.

    A configured base URL is taken at its word; otherwise the local ports are
    probed. An authenticated server prompts for its key, and finding nothing
    local prompts for a cloud key instead.
    """
    if settings.omlx_base:
        return settings

    probe = find_local_server(settings.omlx_key)
    if probe.reachable and probe.needs_auth and interactive and probe.port is not None:
        key = ask_omlx_key(probe.port)
        return settings.with_omlx_key(key) if key else settings
    if probe.reachable:
        return settings
    if not settings.cerebras_key and interactive:
        key = ask_cerebras_key()
        return settings.with_cerebras_key(key) if key else settings
    return settings


def resolve(base_dir: Path, home_dir: Path, interactive: bool = True) -> Settings:
    """Full settings resolution for an install."""
    return ensure_provider(read_settings(base_dir, home_dir), interactive)
