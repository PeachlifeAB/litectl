"""Pure domain serializer for LiteLLM provider YAML configurations."""

from __future__ import annotations

from litectl.modules.catalog.domain.models import (
    ModelDescriptor,
    ProviderSpec,
)

ROUTE_PREFIX = "openai"


def serialize_model_entries(
    spec: ProviderSpec, models: list[ModelDescriptor]
) -> list[str]:
    lines: list[str] = []

    def emit(
        model_name: str,
        target_model: str,
        max_input_tokens: int | None = None,
    ) -> None:
        lines.append(f"  - model_name: {model_name}")
        lines.append("    litellm_params:")
        lines.append(f"      model: {target_model}")
        if spec.api_base:
            lines.append(f"      api_base: {spec.api_base}")
        lines.append(f"      api_key: os.environ/{spec.api_key_env_var}")
        if max_input_tokens is not None:
            lines.append("    model_info:")
            lines.append(f"      max_input_tokens: {max_input_tokens}")
        lines.append("")

    for model in (m for m in models if m.is_chat_model()):
        emit(
            model.to_alias(spec.name),
            f"{ROUTE_PREFIX}/{model.raw_id}",
            model.max_model_len,
        )

    emit(f'"{spec.name}/*"', f'"{ROUTE_PREFIX}/*"')
    return lines


def serialize_provider_yaml(spec: ProviderSpec, models: list[ModelDescriptor]) -> str:
    lines = ["model_list:"]
    lines.extend(serialize_model_entries(spec, models))
    return "\n".join(lines)
