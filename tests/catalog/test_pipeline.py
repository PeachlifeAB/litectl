from pathlib import Path

from litectl.modules.catalog.application.ports import Reachable, Unreachable
from litectl.modules.catalog.domain.models import ProviderSpec
from litectl.modules.catalog.infrastructure.config import AppConfig
from litectl.modules.catalog.pipeline import provider_models_path, render_all


def config(root: Path) -> AppConfig:
    return AppConfig(base_dir=root, providers_dir=root / "providers")


def record_model(root: Path) -> None:
    path = root / "providers/omlx/models.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "model_list:\n"
        "  - model_name: omlx-old\n"
        "    litellm_params:\n"
        "      model: openai/old\n",
        encoding="utf-8",
    )


def test_unreachable_provider_retains_recorded_models(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    record_model(tmp_path)
    spec = ProviderSpec("omlx", None, "OMLX_API_KEY")

    rendered = render_all(
        cfg,
        {"omlx": (spec, lambda: Unreachable("endpoint unreachable"))},
        "all",
    )

    assert rendered.outputs == {}
    assert rendered.diffs[0].unavailable_reason == "endpoint unreachable"
    assert rendered.diffs[0].unchanged == ("omlx-old",)


def test_reachable_empty_provider_withdraws_recorded_models(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    record_model(tmp_path)
    spec = ProviderSpec("omlx", None, "OMLX_API_KEY")

    rendered = render_all(
        cfg,
        {"omlx": (spec, lambda: Reachable(None, ()))},
        "all",
    )

    assert rendered.diffs[0].available
    assert rendered.diffs[0].removed == ("omlx-old",)
    assert provider_models_path(cfg, "omlx") in rendered.outputs
