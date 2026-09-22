from __future__ import annotations

import locale
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from litectl.modules.catalog import cli as catalog
from litectl.modules.catalog.application.ports import Reachable, Unreachable
from litectl.modules.catalog.domain.models import ModelDescriptor
from litectl.modules.catalog.infrastructure.config_yaml import ConfigUpdate
from litectl.modules.catalog.infrastructure.storage import FileStorageAdapter

CONFIG = """---
include:
  - ./providers/omlx/models.yaml
router_settings:
  model_group_alias:
    default_cloud: &cloud cloud-model
    default: *cloud
  fallbacks:
    - default:
        - omlx-old
        - custom-route
model_list: []
"""


def write_workspace(path: Path) -> None:
    provider = path / "providers/omlx/models.yaml"
    provider.parent.mkdir(parents=True)
    provider.write_text("model_list:\n  - model_name: omlx-old\n", encoding="utf-8")
    (path / "config.yaml").write_text(CONFIG, encoding="utf-8")


def test_reconcile_local_models_prunes_vanished_recorded_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workspace(tmp_path)
    monkeypatch.setenv("OMLX_API_BASE", "http://127.0.0.1:8008/v1")
    monkeypatch.setattr(
        catalog,
        "discover_openai_compatible",
        lambda _base, _key: Reachable(
            "http://127.0.0.1:8008/v1", (ModelDescriptor("New-4B"),)
        ),
    )

    warnings = catalog.reconcile_local_models(tmp_path)

    config = YAML().load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    fallbacks = config["router_settings"]["fallbacks"][0]["default"]
    assert fallbacks == ["custom-route", "omlx-new-4b"]
    assert warnings == ["unavailable fallback removed: omlx-old"]


def test_reconcile_local_models_does_not_rewrite_unchanged_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workspace(tmp_path)
    original = (tmp_path / "config.yaml").read_text(encoding="utf-8") + "# café\n"
    (tmp_path / "config.yaml").write_text(original, encoding="utf-8")
    monkeypatch.setenv("OMLX_API_BASE", "http://127.0.0.1:8008/v1")
    monkeypatch.setattr(
        catalog,
        "discover_openai_compatible",
        lambda _base, _key: Reachable(
            "http://127.0.0.1:8008/v1", (ModelDescriptor("Old"),)
        ),
    )
    monkeypatch.setattr(
        catalog,
        "update_config",
        lambda *_args: ConfigUpdate(original, ()),
    )
    writes: list[dict[Path, str]] = []
    monkeypatch.setattr(
        FileStorageAdapter,
        "write_batch",
        lambda batch: writes.append(batch),
    )
    previous_locale = locale.setlocale(locale.LC_CTYPE)
    try:
        locale.setlocale(locale.LC_CTYPE, "C")
        assert catalog.reconcile_local_models(tmp_path) == []
    finally:
        locale.setlocale(locale.LC_CTYPE, previous_locale)
    assert writes == []


def test_reconcile_local_models_keeps_config_when_provider_is_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workspace(tmp_path)
    original = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    monkeypatch.setenv("OMLX_API_BASE", "http://127.0.0.1:8008/v1")
    monkeypatch.setattr(
        catalog,
        "discover_openai_compatible",
        lambda _base, _key: Unreachable("connection refused"),
    )

    warnings = catalog.reconcile_local_models(tmp_path)

    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == original
    assert warnings == ["local model sync skipped: connection refused"]


def test_reconcile_local_models_uses_recorded_base_when_env_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = tmp_path / "providers/omlx/models.yaml"
    provider.parent.mkdir(parents=True)
    provider.write_text(
        "model_list:\n"
        "  - model_name: omlx-old\n"
        "    litellm_params:\n"
        "      model: openai/Old-4B\n"
        "      api_base: http://127.0.0.1:8008/v1\n",
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.delenv("OMLX_API_BASE", raising=False)
    bases: list[str | None] = []

    def discover(base: str | None, _key: str | None) -> Reachable:
        bases.append(base)
        return Reachable(base, (ModelDescriptor("New-4B"),))

    monkeypatch.setattr(catalog, "discover_openai_compatible", discover)

    warnings = catalog.reconcile_local_models(tmp_path)

    assert bases == ["http://127.0.0.1:8008/v1"]
    assert warnings == ["unavailable fallback removed: omlx-old"]


def test_reconcile_local_models_uses_recorded_key_when_env_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workspace(tmp_path)
    (tmp_path / "config.yaml").write_text(
        CONFIG.replace(
            "include:",
            "environment_variables:\n  OMLX_API_KEY: omlx-recorded\ninclude:",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OMLX_API_BASE", "http://127.0.0.1:8008/v1")
    monkeypatch.delenv("OMLX_API_KEY", raising=False)
    keys: list[str | None] = []

    def discover(_base: str | None, key: str | None) -> Reachable:
        keys.append(key)
        return Reachable(_base, (ModelDescriptor("New-4B"),))

    monkeypatch.setattr(catalog, "discover_openai_compatible", discover)

    catalog.reconcile_local_models(tmp_path)

    assert keys == ["omlx-recorded"]


def test_reconcile_local_models_does_not_probe_cloud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_workspace(tmp_path)
    calls: list[tuple[str | None, str | None]] = []
    monkeypatch.setenv("OMLX_API_BASE", "http://127.0.0.1:8008/v1")
    monkeypatch.setenv("OMLX_API_KEY", "local-key")
    monkeypatch.setenv("CEREBRAS_API_BASE", "https://api.cerebras.ai/v1")
    monkeypatch.setenv("CEREBRAS_API_KEY", "cloud-key")

    def discover(base: str | None, key: str | None) -> Reachable:
        calls.append((base, key))
        return Reachable(base, (ModelDescriptor("New-4B"),))

    monkeypatch.setattr(catalog, "discover_openai_compatible", discover)

    catalog.reconcile_local_models(tmp_path)

    assert calls == [("http://127.0.0.1:8008/v1", "local-key")]
