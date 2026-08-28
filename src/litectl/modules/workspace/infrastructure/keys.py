"""Resolve settings and API keys from the environment and existing config."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

_CLIENT_KEY_PATTERN = re.compile(r"^LITELLM_API_KEY=(sk-local-\w+)", re.MULTILINE)


def config_environment_value(config_path: Path, key: str) -> str:
    """Read one LiteLLM `environment_variables` value from config.yaml."""
    if not config_path.exists():
        return ""
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    environment = parsed.get("environment_variables")
    if not isinstance(environment, dict):
        return ""
    value = environment.get(key, "")
    return str(value).strip() if value is not None else ""


def resolve_setting(
    base_dir: Path,
    key: str,
    default: str = "",
    environment: Mapping[str, str] = os.environ,
) -> str:
    """Resolve a setting from process environment, config.yaml, then default."""
    from_environment = environment.get(key, "").strip()
    if from_environment:
        return from_environment
    return config_environment_value(base_dir / "config.yaml", key) or default


def client_saved_master_key(home_dir: Path) -> str:
    """Return the master key a configured client still holds, if any."""
    fabric_env = home_dir / ".config/fabric/.env"
    if not fabric_env.exists():
        return ""
    match = _CLIENT_KEY_PATTERN.search(fabric_env.read_text(encoding="utf-8"))
    return match.group(1) if match else ""
