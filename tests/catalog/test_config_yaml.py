from pathlib import Path

import pytest
import yaml as pyyaml
from ruamel.yaml import YAML

from litectl.modules.catalog.domain.aliases import (
    Discovery,
    UnavailableDefaultError,
)
from litectl.modules.catalog.domain.models import ModelDescriptor
from litectl.modules.catalog.infrastructure.config_yaml import update_config

SEED = """---
include:
  - ./providers/cerebras.yaml
  - ./providers/omlx.yaml
router_settings:
  model_group_alias:
    default_cloud: &cloud cloud-model
    default: *cloud
model_list: []
"""

MODELS = [
    ModelDescriptor("Carnice-27B"),
    ModelDescriptor("Llama-3.2-3B"),
    ModelDescriptor("Llama-3.1-8B"),
    ModelDescriptor("Muse-30B"),
]


def write_seed(path: Path, content: str = SEED) -> None:
    path.write_text(content, encoding="utf-8")


def test_config_update_emits_portable_intent_anchors(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write_seed(path)
    aliases = {"cloud-model"} | {model.to_alias("omlx") for model in MODELS}

    update = update_config(path, Discovery(MODELS, "omlx", [], aliases))

    assert "default_cloud: &cloud cloud-model" in update.content
    assert "default_speed: &speed omlx-llama-3.2-3b" in update.content
    assert "default_quality: &quality omlx-muse-30b" in update.content
    assert "default: *cloud" in update.content
    assert "- *cloud:" not in update.content
    assert "- default:" in update.content
    assert (
        pyyaml.safe_load(update.content)["router_settings"]["model_group_alias"][
            "default"
        ]
        == "cloud-model"
    )


def test_update_preserves_selected_anchor_and_custom_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write_seed(
        path,
        SEED.replace("default: *cloud", "custom_key: retained\n    default: *cloud"),
    )
    first = update_config(
        path,
        Discovery(
            MODELS,
            "omlx",
            [],
            {"cloud-model"} | {model.to_alias("omlx") for model in MODELS},
        ),
    )
    path.write_text(
        first.content.replace("default: *cloud", "default: *speed"), encoding="utf-8"
    )

    second = update_config(
        path,
        Discovery(
            MODELS,
            "omlx",
            [model.to_alias("omlx") for model in MODELS],
            {"cloud-model"} | {model.to_alias("omlx") for model in MODELS},
        ),
    )
    parsed = YAML().load(second.content)
    aliases = parsed["router_settings"]["model_group_alias"]

    assert aliases["default"] is aliases["default_speed"]
    assert aliases["custom_key"] == "retained"


def test_unavailable_custom_default_requires_recovery(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    write_seed(path, SEED.replace("default: *cloud", "default: removed-custom"))

    with pytest.raises(UnavailableDefaultError, match="removed-custom"):
        update_config(
            path,
            Discovery(
                MODELS,
                "omlx",
                [],
                {"cloud-model"} | {model.to_alias("omlx") for model in MODELS},
            ),
        )


def test_selected_preset_self_heals_without_changing_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    write_seed(path)
    old_aliases = {model.to_alias("omlx") for model in MODELS}
    first = update_config(
        path, Discovery(MODELS, "omlx", [], {"cloud-model"} | old_aliases)
    )
    path.write_text(
        first.content.replace("default: *cloud", "default: *speed"), encoding="utf-8"
    )
    replacement_models = [model for model in MODELS if "3.2-3B" not in model.raw_id] + [
        ModelDescriptor("Llama-3.3-4B")
    ]
    new_aliases = {model.to_alias("omlx") for model in replacement_models}

    repaired = update_config(
        path,
        Discovery(
            replacement_models, "omlx", list(old_aliases), {"cloud-model"} | new_aliases
        ),
    )
    parsed = YAML().load(repaired.content)
    aliases = parsed["router_settings"]["model_group_alias"]

    assert aliases["default"] is aliases["default_speed"]
    assert aliases["default_speed"] == "omlx-llama-3.3-4b"
    assert any(
        "default_speed target changed" in warning for warning in repaired.warnings
    )


_BASE_CONFIG_TAIL = """router_settings:
  model_group_alias:
    default_cloud: &cloud cloud-model
    default: *cloud
model_list: []
"""


def _discovery() -> Discovery:
    return Discovery(MODELS, "omlx", [], {"cloud-model"})


def test_update_migrates_broken_callback_reference(tmp_path: Path) -> None:
    """The package-path callback reference could never load; update fixes it."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "---\n"
        "litellm_settings:\n"
        "  drop_params: true\n"
        "  callbacks:\n"
        "    - litectl.litellm_hooks.handler\n"
        "    - my_custom.callbacks.logger\n" + _BASE_CONFIG_TAIL,
        encoding="utf-8",
    )

    update = update_config(path, _discovery())

    assert "litectl.litellm_hooks.handler" not in update.content
    assert "- litectl_hooks.handler" in update.content
    assert "- my_custom.callbacks.logger" in update.content


def test_update_adds_callback_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("---\n" + _BASE_CONFIG_TAIL, encoding="utf-8")

    update = update_config(path, _discovery())

    assert "- litectl_hooks.handler" in update.content
