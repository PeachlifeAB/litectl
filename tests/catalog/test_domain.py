import pytest
import yaml as pyyaml

from litectl.modules.catalog.domain.models import (
    ModelDescriptor,
    ProviderSpec,
    rank_local_chat_models,
    reconcile_fallback_aliases,
    select_quality_model,
    select_speed_model,
)
from litectl.modules.catalog.domain.serializer import serialize_provider_yaml


def test_model_filtering_excludes_non_chat() -> None:
    assert ModelDescriptor("sample-chat-model-8b").is_chat_model() is True
    assert ModelDescriptor("sample-tts-voice-0.5b").is_chat_model() is False
    assert ModelDescriptor("sample-asr-whisper-v1").is_chat_model() is False
    assert ModelDescriptor("bge-m3-mlx-fp16").is_chat_model() is False
    assert ModelDescriptor("sam3.1-bf16").is_chat_model() is False
    assert ModelDescriptor("Qwen3.8-27B-4bit").is_chat_model() is True


def test_parameter_size_ignores_model_version_and_quantization() -> None:
    # approx, not ==: the values are exact in binary, but the return type is
    # float and an exact comparison would not survive a parser change.
    assert ModelDescriptor(
        "Llama-3.2-3B-Instruct-4bit"
    ).parameter_billions() == pytest.approx(3.0)
    assert ModelDescriptor("Qwen3.8-27B-4bit").parameter_billions() == pytest.approx(
        27.0
    )
    assert ModelDescriptor("gemma-sas").parameter_billions() is None


def test_local_ranking_prefers_balanced_then_larger_models() -> None:
    models = [
        ModelDescriptor("Carnice-27B"),
        ModelDescriptor("Llama-3.1-8B"),
        ModelDescriptor("unknown"),
        ModelDescriptor("Llama-3.2-3B"),
        ModelDescriptor("tiny-1B"),
        ModelDescriptor("Muse-30B"),
    ]
    ranked = rank_local_chat_models(models)

    assert [model.raw_id for model in ranked] == [
        "Llama-3.2-3B",
        "Llama-3.1-8B",
        "Carnice-27B",
        "Muse-30B",
        "tiny-1B",
        "unknown",
    ]
    speed = select_speed_model(models)
    quality = select_quality_model(models)
    assert speed is not None
    assert quality is not None
    assert speed.raw_id == "Llama-3.2-3B"
    assert quality.raw_id == "Muse-30B"


def test_reconciliation_preserves_exclusions_order_and_custom_routes() -> None:
    chain, removed = reconcile_fallback_aliases(
        ["omlx-a", "omlx-b", "omlx-new"],
        ["omlx-b", "custom-route", "omlx-removed"],
        ["omlx-a", "omlx-b", "omlx-removed"],
    )

    assert chain == ["omlx-b", "custom-route", "omlx-new"]
    assert removed == ["omlx-removed"]


def test_unedited_discovery_chain_adopts_smarter_rank() -> None:
    chain, _ = reconcile_fallback_aliases(
        ["omlx-fast", "omlx-slow"],
        ["omlx-slow", "omlx-fast"],
        ["omlx-slow", "omlx-fast"],
    )
    assert chain == ["omlx-fast", "omlx-slow"]


def test_alias_sanitization() -> None:
    assert (
        ModelDescriptor("meta-sample-chat-instruct-mlx").to_alias("mock")
        == "mock-sample-chat"
    )


def test_serialization_output() -> None:
    spec = ProviderSpec("mock", "http://localhost:0/v1", "MOCK_API_KEY")
    yaml_out = serialize_provider_yaml(
        spec,
        [
            ModelDescriptor("sample-chat-model-8b", max_model_len=120_000),
            ModelDescriptor("unknown-chat-model"),
            ModelDescriptor("sample-tts-voice-0.5b"),
        ],
    )
    entries = {
        entry["model_name"]: entry for entry in pyyaml.safe_load(yaml_out)["model_list"]
    }

    assert "sample-tts-voice-0.5b" not in yaml_out
    assert entries["mock-sample-chat-model-8b"]["model_info"] == {
        "max_input_tokens": 120_000
    }
    assert "model_info" not in entries["mock-unknown-chat-model"]
    assert "model_info" not in entries["mock/*"]
    assert "api_base: http://localhost:0/v1" in yaml_out
    assert "api_key: os.environ/MOCK_API_KEY" in yaml_out
