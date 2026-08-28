"""Resolve user paths once at the CLI boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

APP_DIR_NAME = "litectl"


def config_dir(
    explicit: str | None = None,
    environment: Mapping[str, str] = os.environ,
    home_dir: Path | None = None,
) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured_file = environment.get("CONFIG_FILE_PATH")
    if configured_file:
        return Path(configured_file).expanduser().resolve().parent
    home = Path.home() if home_dir is None else home_dir
    root = environment.get("XDG_CONFIG_HOME") or str(home / ".config")
    return Path(root).expanduser().resolve() / APP_DIR_NAME


def state_dir(
    environment: Mapping[str, str] = os.environ,
    home_dir: Path | None = None,
) -> Path:
    home = Path.home() if home_dir is None else home_dir
    root = environment.get("XDG_STATE_HOME") or str(home / ".local/state")
    return Path(root).expanduser().resolve() / APP_DIR_NAME
