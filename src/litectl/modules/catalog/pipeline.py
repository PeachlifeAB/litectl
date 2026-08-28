"""Turn discovery results into workspace files.

Sequences provider serialization, schema regeneration and alias resolution.
Owns no I/O beyond what the adapters it calls perform.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from litectl.modules.catalog.application.ports import (
    ProbeResult,
    Unreachable,
)
from litectl.modules.catalog.domain.aliases import Discovery
from litectl.modules.catalog.domain.diff import (
    ModelDiff,
    diff_models,
    unavailable,
)
from litectl.modules.catalog.domain.models import (
    ModelDescriptor,
    ProviderSpec,
)
from litectl.modules.catalog.domain.serializer import (
    serialize_model_entries,
    serialize_provider_yaml,
)
from litectl.modules.catalog.infrastructure.config import AppConfig
from litectl.modules.catalog.infrastructure.config_reader import (
    read_config_model_groups,
    read_provider_aliases,
    validate_yaml_text,
)

DiscoverFn = Callable[[], ProbeResult]
Registry = dict[str, tuple[ProviderSpec, DiscoverFn]]

PROVIDER_MODELS_FILE = "models.yaml"
LOCAL_PROVIDER = "omlx"


def provider_models_path(cfg: AppConfig, name: str) -> Path:
    """Where a provider's discovered models are recorded."""
    return cfg.providers_dir / name / PROVIDER_MODELS_FILE


def resolve_spec(base: ProviderSpec, detected_base: str | None) -> ProviderSpec:
    """Prefer the endpoint discovery actually reached."""
    return ProviderSpec(
        name=base.name,
        api_base=detected_base or base.api_base,
        api_key_env_var=base.api_key_env_var,
    )


def render_provider(
    cfg: AppConfig, spec: ProviderSpec, models: list[ModelDescriptor]
) -> tuple[Path, str, str]:
    """Serialize one provider file and describe what it holds."""
    content = serialize_provider_yaml(spec, models)
    validate_yaml_text(content)
    chat_count = sum(model.is_chat_model() for model in models)
    source = spec.api_base or "provider default endpoint"
    report = (
        f"Generated providers/{spec.name}/{PROVIDER_MODELS_FILE}"
        f" ({chat_count} models) [{source}]"
    )
    return provider_models_path(cfg, spec.name), content, report


def build_discovery(
    cfg: AppConfig, models: list[ModelDescriptor], previous: list[str]
) -> Discovery:
    """Everything the config update needs to know about available models."""
    discovered = {m.to_alias(LOCAL_PROVIDER) for m in models if m.is_chat_model()}
    configured = read_config_model_groups(cfg.base_dir / "config.yaml")
    return Discovery(
        models=models,
        provider_prefix=LOCAL_PROVIDER,
        previous_discovered=previous,
        available_aliases=(configured - set(previous)) | discovered,
    )


@dataclass
class Rendered:
    """What one pass over the registry produced."""

    outputs: dict[Path, str] = field(default_factory=dict)
    reports: list[str] = field(default_factory=list)
    entries: list[str] = field(default_factory=list)
    local_models: list[ModelDescriptor] = field(default_factory=list)
    diffs: list[ModelDiff] = field(default_factory=list)


def render_all(cfg: AppConfig, registry: Registry, target: str) -> Rendered:
    """Discover every provider and serialize the ones in scope."""
    result = Rendered()
    for name, (base_spec, discover) in registry.items():
        recorded = read_provider_aliases(provider_models_path(cfg, name))
        outcome = discover()
        if isinstance(outcome, Unreachable):
            result.diffs.append(unavailable(name, outcome.reason, recorded))
            continue

        models = list(outcome.models)
        spec = resolve_spec(base_spec, outcome.api_base)
        result.entries.extend(serialize_model_entries(spec, models))
        if name == LOCAL_PROVIDER:
            result.local_models = models
        result.diffs.append(
            diff_models(name, [m.to_alias(name) for m in models], recorded)
        )
        if target in ("all", name):
            path, content, report = render_provider(cfg, spec, models)
            result.outputs[path] = content
            result.reports.append(report)
    return result
