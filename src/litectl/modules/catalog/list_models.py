"""List the model groups the workspace currently registers.

Reads recorded provider files rather than querying the proxy. Use
`litectl update` to refresh them.
"""

from __future__ import annotations

from pathlib import Path

from litectl.modules.catalog.infrastructure.config import AppConfig
from litectl.modules.catalog.infrastructure.config_reader import (
    read_provider_aliases,
)
from litectl.modules.catalog.pipeline import provider_models_path


def provider_names(cfg: AppConfig) -> list[str]:
    """Providers that have a recorded models directory, alphabetically."""
    if not cfg.providers_dir.exists():
        return []
    return sorted(path.name for path in cfg.providers_dir.iterdir() if path.is_dir())


def main(base_dir: Path) -> None:
    cfg = AppConfig.from_env(base_dir)
    names = provider_names(cfg)
    if not names:
        print("No providers recorded yet. Run `litectl update`.")
        return

    total = 0
    for name in names:
        aliases = read_provider_aliases(provider_models_path(cfg, name))
        total += len(aliases)
        print(f"\n{name} ({len(aliases)} models)")
        for alias in aliases:
            print(f"  {alias}")

    print(f"\n{total} model group(s) across {len(names)} provider(s).")
