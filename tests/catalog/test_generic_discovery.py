"""Generic OpenAI-compatible discovery: one adapter, no subprocesses, no scans."""

from __future__ import annotations

import io
import socket
import subprocess  # nosec B404: monkeypatched to assert it never runs
import urllib.error
from email.message import Message

import pytest

from litectl.modules.catalog.application.ports import Reachable, Unreachable
from litectl.modules.catalog.cli import build_registry, discover_openai_compatible
from litectl.modules.catalog.domain.models import ModelDescriptor, ProviderSpec
from litectl.modules.catalog.domain.serializer import serialize_model_entries
from litectl.modules.catalog.infrastructure import openai_compat
from litectl.modules.catalog.infrastructure.base import model_data
from litectl.modules.catalog.infrastructure.config import PROVIDER_SPECS, AppConfig

FETCH = "litectl.modules.catalog.infrastructure.openai_compat.http_get_json"


def test_no_subprocess_during_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("discovery must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", no_run)
    monkeypatch.setattr(FETCH, lambda _url, **_kwargs: [{"id": "m"}])
    result = openai_compat.fetch_models("http://127.0.0.1:9/v1", None)
    assert isinstance(result, Reachable)


def test_no_port_probing_without_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    def no_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("discovery must not open sockets to scan ports")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    cfg = AppConfig.from_env(tmp_path)  # type: ignore[arg-type]
    result = build_registry(cfg)["ollama"][1]()
    assert isinstance(result, Unreachable)
    assert result.reason == "no api base configured"


def test_explicit_base_probed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def recorder(url: str, **_kwargs: object) -> list[dict[str, object]]:
        calls.append(url)
        return [{"id": "m"}]

    monkeypatch.setattr(FETCH, recorder)
    result = discover_openai_compatible("http://127.0.0.1:9/v1", "k")
    assert isinstance(result, Reachable)
    assert calls == ["http://127.0.0.1:9/v1/models"]


def test_auth_failure_reason_is_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(url: str, **_kwargs: object) -> list[dict[str, object]]:
        raise urllib.error.HTTPError(
            url, 401, "Unauthorized", hdrs=Message(), fp=io.BytesIO(b"{}")
        )

    monkeypatch.setattr(FETCH, denied)
    result = openai_compat.fetch_models("http://127.0.0.1:9/v1", None)
    assert isinstance(result, Unreachable)
    assert "authentication failed" in result.reason
    assert "401" in result.reason


def test_connection_refused_reason_is_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(url: str, **_kwargs: object) -> list[dict[str, object]]:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(FETCH, refused)
    result = openai_compat.fetch_models("http://127.0.0.1:9/v1", None)
    assert isinstance(result, Unreachable)
    assert result.reason == "connection refused"


def test_payload_tolerates_bare_array_and_data_wrapper() -> None:
    bare = [{"id": "a"}, {"id": "b"}]
    wrapped = {"object": "list", "data": [{"id": "a"}, {"id": "b"}]}
    assert model_data(bare) == model_data(wrapped)


def test_descriptor_ids_are_trimmed_and_deduped() -> None:
    models = openai_compat.to_descriptors(
        [{"id": " a "}, {"id": "a"}, {"id": "b"}, {"no": 1}]
    )
    assert [m.raw_id for m in models] == ["a", "b"]


@pytest.mark.parametrize("provider", ["omlx", "cerebras", "ds4"])
def test_routes_are_uniform_openai(provider: str) -> None:
    spec = ProviderSpec(provider, "http://example/v1", "X_API_KEY")
    entries = serialize_model_entries(spec, [ModelDescriptor("gpt-oss-120b")])
    assert "      model: openai/gpt-oss-120b" in entries
    assert '      model: "openai/*"' in entries


def test_registry_covers_mainstream_local_servers() -> None:
    assert set(PROVIDER_SPECS) >= {
        "omlx",
        "cerebras",
        "ollama",
        "llama-cpp",
        "lmstudio",
        "ds4",
    }


def test_shipped_resources_have_no_private_cli() -> None:
    from importlib.resources import files

    from litectl.modules.workspace.domain.settings import Settings

    config_text = (
        files("litectl.resources").joinpath("config.yaml").read_text(encoding="utf-8")
    )
    assert "OMLX_CLI" not in config_text
    assert "OMLX_CLI" not in Settings(master_key="k").as_environment()
