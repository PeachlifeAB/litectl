"""CLI composition root for transactional model discovery updates."""

from __future__ import annotations

import sys
from pathlib import Path

from .api.discover import review
from .api.prompts import prompt_for_recovery
from .application.ports import (
    ProbeResult,
    Unreachable,
)
from .domain.aliases import (
    Discovery,
    UnavailableDefaultError,
)
from .domain.models import ProviderSpec
from .infrastructure.config import PROVIDER_SPECS, AppConfig
from .infrastructure.config_reader import (
    read_provider_aliases,
    validate_config_text,
    validate_yaml_text,
)
from .infrastructure.config_yaml import (
    ConfigUpdate,
    update_config,
)
from .infrastructure.openai_compat import fetch_models
from .infrastructure.schema import build_config_schema
from .infrastructure.storage import FileStorageAdapter
from .pipeline import (
    LOCAL_PROVIDER,
    DiscoverFn,
    Registry,
    Rendered,
    build_discovery,
    provider_models_path,
    render_all,
)


def _discover_fn(cfg: AppConfig, name: str) -> DiscoverFn:
    def discover() -> ProbeResult:
        return discover_openai_compatible(cfg.api_base(name), cfg.api_key(name))

    return discover


def build_registry(cfg: AppConfig) -> Registry:
    """Every provider, discovered through the same OpenAI-compatible path."""
    return {
        name: (ProviderSpec(name, cfg.api_base(name), key_env), _discover_fn(cfg, name))
        for name, (_base_env, key_env, _default) in PROVIDER_SPECS.items()
    }


def discover_openai_compatible(
    api_base: str | None, api_key: str | None
) -> ProbeResult:
    if not api_base:
        return Unreachable("no api base configured")
    return fetch_models(api_base, api_key)


def build_config_update(cfg: AppConfig, discovery: Discovery) -> ConfigUpdate:
    """Update config.yaml, asking for a replacement if the default vanished."""
    path = cfg.base_dir / "config.yaml"
    try:
        return update_config(path, discovery)
    except UnavailableDefaultError as error:
        return update_config(path, discovery, prompt_for_recovery(error))


def parse_args(argv: list[str]) -> tuple[str, bool]:
    """Split the provider target from the --yes flag."""
    assume_yes = "--yes" in argv or "-y" in argv
    positional = [a for a in argv if not a.startswith("-")]
    return (positional[0] if positional else "all"), assume_yes


def main(base_dir: Path, argv: list[str] | None = None) -> int:
    target, assume_yes = parse_args([] if argv is None else argv)
    cfg = AppConfig.from_env(base_dir)
    registry = build_registry(cfg)
    if target not in ("all", *registry):
        print(
            f"Unknown provider '{target}'. Available: all, {', '.join(registry)}",
            file=sys.stderr,
        )
        return 1

    previous = read_provider_aliases(provider_models_path(cfg, LOCAL_PROVIDER))
    rendered = render_all(cfg, registry, target)
    if not review(rendered.diffs, assume_yes):
        return 0

    schema_json = build_config_schema()
    discovery = build_discovery(cfg, rendered.local_models, previous)
    update = build_config_update(cfg, discovery)
    validate_yaml_text(update.content)
    validate_config_text(update.content, schema_json)
    rendered.outputs[cfg.base_dir / "config.yaml"] = update.content

    FileStorageAdapter.write_batch(rendered.outputs)
    report_results(rendered, update.warnings, discovery)
    return 0


def report_results(
    rendered: Rendered,
    warnings: tuple[str, ...],
    discovery: Discovery,
) -> None:
    for report in rendered.reports:
        print(report)
    for warning in warnings:
        print(f"WARN  {warning}")
    routes = sum(line.lstrip().startswith("- model_name:") for line in rendered.entries)
    print(f"Generated config.yaml ({routes} model routes)")
    print(
        "Fallbacks for the cloud model group:"
        f" {len(discovery.available_aliases)} model(s)"
    )
