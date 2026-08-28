"""JSON Schema derived from the installed LiteLLM package."""

from __future__ import annotations

import json
from typing import cast

JsonObject = dict[str, object]


def build_config_schema() -> str:
    from litellm.proxy._types import ConfigYAML

    schema = cast(JsonObject, ConfigYAML.model_json_schema())
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "LiteLLMConfig"

    definitions = cast(JsonObject, schema.get("$defs", {}))
    model_params = cast(JsonObject, definitions.get("ModelParams", {}))
    required = model_params.get("required")
    if isinstance(required, list):
        model_params["required"] = [item for item in required if item != "model_info"]

    properties = cast(JsonObject, schema.setdefault("properties", {}))
    properties["include"] = {
        "type": "array",
        "description": "Config files merged into this one.",
        "items": {"type": "string"},
    }

    _widen_router_settings(schema)
    _forbid_unknown_properties(schema)
    return json.dumps(schema, indent=2) + "\n"


# Router.__init__ params that configure the object rather than routing
# behaviour; they belong to caching/Redis plumbing, not config.yaml.
NON_CONFIG_ROUTER_PARAMS = frozenset(
    {
        "self",
        "model_list",
        "assistants_config",
        "search_tools",
        "guardrail_list",
        "redis_url",
        "redis_host",
        "redis_port",
        "redis_password",
        "redis_db",
        "cache_responses",
        "cache_kwargs",
        "caching_groups",
        "client_ttl",
        "polling_interval",
        "alerting_config",
        "router_general_settings",
    }
)

_JSON_TYPES: dict[object, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
    dict: "object",
    list: "array",
}


def _json_type_of(annotation: object) -> JsonObject | None:
    """Best-effort JSON Schema fragment for a Python annotation."""
    import typing

    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return {"enum": [a for a in typing.get_args(annotation) if isinstance(a, str)]}

    if origin is typing.Union:
        inner = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _json_type_of(inner[0]) if len(inner) == 1 else None

    name = _JSON_TYPES.get(origin or annotation)
    return {"type": name} if name else None


def _widen_router_settings(schema: JsonObject) -> None:
    """Add router settings that UpdateRouterConfig omits.

    UpdateRouterConfig only covers what `router.update_settings()` can change
    at runtime, so valid config keys such as enable_pre_call_checks are
    absent. Router.__init__ is where these settings are actually consumed, so
    its signature is derived from rather than hardcoded: upgrading LiteLLM and
    re-running `litectl update` picks up new keys without hardcoding.
    """
    definitions = cast(JsonObject, schema.get("$defs", {}))
    router = cast(JsonObject, definitions.get("UpdateRouterConfig", {}))
    if not router:
        return

    try:
        import inspect

        from litellm.router import Router

        parameters = inspect.signature(Router.__init__).parameters
    except (ImportError, TypeError):
        return

    properties = cast(JsonObject, router.setdefault("properties", {}))
    for name, parameter in parameters.items():
        if (
            name in NON_CONFIG_ROUTER_PARAMS
            or name in properties
            or name.startswith("_")
        ):
            continue
        fragment = _json_type_of(parameter.annotation)
        if fragment:
            properties[name] = fragment


def _forbid_unknown_properties(node: object) -> None:
    """Reject unknown keys so typos surface in the editor.

    Applied after widening, since several valid router keys are missing from
    the generated definitions.
    """
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node.setdefault("additionalProperties", False)
        for value in node.values():
            _forbid_unknown_properties(value)
    elif isinstance(node, list):
        for value in node:
            _forbid_unknown_properties(value)
