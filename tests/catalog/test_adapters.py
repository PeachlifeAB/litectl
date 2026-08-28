import litellm
import pytest
from litellm.exceptions import ContextWindowExceededError
from litellm.router import Router

from litectl.modules.catalog.infrastructure.schema import (
    build_config_schema,
)


def test_generated_schema_accepts_entries_without_model_info() -> None:
    import json

    raw = build_config_schema()
    schema = json.loads(raw)
    # ConfigYAML marks model_info required, but its validator defaults it.
    assert "model_info" not in schema["$defs"]["ModelParams"]["required"]
    assert "include" in schema["properties"]

    jsonschema = pytest.importorskip("jsonschema")
    config = {
        "model_list": [{"model_name": "a", "litellm_params": {"model": "openai/a"}}]
    }
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(config)) == []


def test_generated_schema_rejects_unknown_keys() -> None:
    import json

    raw = build_config_schema()
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft202012Validator(json.loads(raw))

    assert list(validator.iter_errors({"router_settings": {"routing_stratgy": "x"}}))
    assert list(validator.iter_errors({"modle_list": []}))
    # Valid despite being absent from UpdateRouterConfig; derived from the
    # Router.__init__ signature rather than a hardcoded list.
    assert not list(
        validator.iter_errors({"router_settings": {"enable_pre_call_checks": True}})
    )
    assert not list(validator.iter_errors({"router_settings": {"max_fallbacks": 3}}))
    # The `.vars` anchor block is gone; unknown top-level keys stay rejected.
    assert list(validator.iter_errors({".vars": {"primary_model": "x"}}))


def test_oversized_prompt_never_calls_incompatible_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls: list[dict[str, object]] = []

    def record_provider_call(**kwargs: object) -> None:
        provider_calls.append(kwargs)
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(litellm, "completion", record_provider_call)
    router = Router(
        model_list=[
            {
                "model_name": "limited",
                "litellm_params": {
                    "model": "openai/limited",
                    "api_key": "test-key",
                    "api_base": "http://unused.invalid/v1",
                },
                "model_info": {"max_input_tokens": 1},
            }
        ],
        enable_pre_call_checks=True,
        num_retries=0,
    )

    with pytest.raises(ContextWindowExceededError):
        router.completion(
            model="limited",
            messages=[{"role": "user", "content": "This prompt exceeds one token."}],
        )

    assert provider_calls == []
