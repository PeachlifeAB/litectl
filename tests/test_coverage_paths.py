from __future__ import annotations

import builtins
import io
import json
import runpy
import shutil
import subprocess  # nosec B404: patches the adapter; never shells out
import sys
import time
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from litectl.app import bootstrap, cli, teardown
from litectl.modules.catalog import list_models
from litectl.modules.catalog.api import discover as discovery
from litectl.modules.catalog.domain.diff import (
    ModelDiff,
    any_changed,
    diff_models,
    unavailable,
)
from litectl.modules.workspace.api import prompts as install_prompts
from litectl.modules.workspace.api import resolve as resolve_api
from litectl.modules.workspace.api import verify as verify_api
from litectl.modules.workspace.domain.settings import Settings
from litectl.modules.workspace.domain.urls import (
    UnsupportedSchemeError,
    ensure_http_url,
)
from litectl.modules.workspace.infrastructure import healthcheck, probe, process
from litectl.modules.workspace.infrastructure.healthcheck import Attempt
from litectl.modules.workspace.infrastructure.probe import ProbeResult
from litectl.modules.workspace.infrastructure.service import ServiceContext


class Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def service_context(root: Path) -> ServiceContext:
    return ServiceContext(
        config_dir=root / "config",
        state_dir=root / "state",
        home_dir=root / "home",
        uid=501,
        cli_bin="/usr/local/bin/litectl",
        environment={},
    )


def test_verify_reports_unauthorized_and_empty_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        verify_api,
        "wait_for_models",
        lambda *_args: Attempt(unauthorized=True),
    )
    assert not verify_api.verify(tmp_path, "key", "4000")
    assert "401 Unauthorized" in capsys.readouterr().out

    monkeypatch.setattr(verify_api, "wait_for_models", lambda *_args: Attempt())
    assert not verify_api.verify(tmp_path, "key", "4000")
    assert "No concrete chat models" in capsys.readouterr().out


def test_verify_handles_no_local_model_and_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        verify_api,
        "wait_for_models",
        lambda *_args: Attempt(models=("default_cloud",)),
    )
    assert verify_api.verify(tmp_path, "key", "4000")
    assert "No local chat model" in capsys.readouterr().out

    monkeypatch.setattr(
        verify_api,
        "wait_for_models",
        lambda *_args: Attempt(models=("omlx-local",)),
    )
    monkeypatch.setattr(verify_api, "complete", lambda *_args: "local-ok")
    assert verify_api.verify(tmp_path, "key", "4000")
    assert "local-ok" in capsys.readouterr().out


def test_teardown_cancels_or_removes_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    context = service_context(tmp_path)
    context.state_dir.mkdir(parents=True)
    (context.state_dir / "proxy.log").write_text("log", encoding="utf-8")
    monkeypatch.setattr(builtins, "input", lambda _prompt: "n")
    teardown.main(context)
    assert context.state_dir.exists()
    assert "Cancelled" in capsys.readouterr().out

    calls: list[ServiceContext] = []
    monkeypatch.setattr(teardown, "remove_service", calls.append)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "yes")
    teardown.main(context)
    assert calls == [context]
    assert not context.state_dir.exists()


def test_discovery_review_reports_changes_and_confirmation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    changed = ModelDiff("omlx", added=("new",), removed=("old",))
    unchanged = ModelDiff("ollama", unchanged=("same",))
    discovery.review([changed], assume_yes=True)
    output = capsys.readouterr().out
    assert "+ new" in output
    assert "- old" in output
    assert discovery.review([unchanged], assume_yes=True) is False
    assert "No changes" in capsys.readouterr().out

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert discovery.confirm() is False
    assert "Not a terminal" in capsys.readouterr().out

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "y")
    assert discovery.confirm()
    monkeypatch.setattr(
        builtins, "input", lambda _prompt: (_ for _ in ()).throw(EOFError)
    )
    assert discovery.confirm() is False


def test_list_models_reports_empty_and_recorded_providers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    list_models.main(tmp_path)
    assert "No providers recorded" in capsys.readouterr().out

    provider = tmp_path / "providers/omlx/models.yaml"
    provider.parent.mkdir(parents=True)
    provider.write_text("model_list:\n  - model_name: omlx-local\n", encoding="utf-8")
    list_models.main(tmp_path)
    output = capsys.readouterr().out
    assert "omlx (1 models)" in output
    assert "1 model group(s)" in output


def test_install_prompts_accept_input_and_decline_interrupts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(builtins, "input", lambda _prompt: " key ")
    assert install_prompts.ask("key?") == "key"
    monkeypatch.setattr(
        builtins, "input", lambda _prompt: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    assert install_prompts.ask("key?") == ""
    assert install_prompts.ask_omlx_key(8008) == ""
    assert install_prompts.ask_cerebras_key() == ""
    assert "Notice" in capsys.readouterr().out


def test_healthcheck_lists_models_and_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        healthcheck,
        "_get_json",
        lambda *_args: {"data": [{"id": "omlx-a"}, {"id": "omlx-a/*"}, "bad"]},
    )
    assert healthcheck.list_models("http://proxy", "key").models == ("omlx-a",)

    attempts = iter((Attempt(), Attempt(models=("omlx-a",))))
    monkeypatch.setattr(
        healthcheck,
        "list_models",
        lambda *_args: next(attempts),
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert healthcheck.wait_for_models("http://proxy", "key").models == ("omlx-a",)
    assert healthcheck.choose_model(("other", "omlx-fallback")) == "omlx-fallback"


def test_healthcheck_handles_http_and_completion_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unauthorized = urllib.error.HTTPError(
        "http://proxy/models", 401, "no", Message(), io.BytesIO(b"")
    )
    monkeypatch.setattr(
        healthcheck, "_get_json", lambda *_args: (_ for _ in ()).throw(unauthorized)
    )
    assert healthcheck.list_models("http://proxy", "key").unauthorized

    monkeypatch.setattr(
        healthcheck,
        "_get_json",
        lambda *_args: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    assert healthcheck.list_models("http://proxy", "key").note == "waiting for proxy"

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(
            {"choices": [{"message": {"content": " hello "}}]}
        ),
    )
    assert healthcheck.complete("http://proxy", "key", "omlx-a") == "hello"

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("down")),
    )
    assert "test call notice" in healthcheck.complete("http://proxy", "key", "omlx-a")


def test_resolve_settings_and_provider_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(master_key="master")
    monkeypatch.setattr(resolve_api, "find_local_server", lambda _key: ProbeResult())
    assert resolve_api.ensure_provider(settings, interactive=False) == settings

    monkeypatch.setattr(
        resolve_api,
        "find_local_server",
        lambda _key: ProbeResult(reachable=True, port=8008, needs_auth=True),
    )
    monkeypatch.setattr(resolve_api, "ask_omlx_key", lambda _port: "local-key")
    assert resolve_api.ensure_provider(settings).omlx_key == "local-key"

    monkeypatch.setattr(
        resolve_api,
        "find_local_server",
        lambda _key: ProbeResult(),
    )
    monkeypatch.setattr(resolve_api, "ask_cerebras_key", lambda: "cloud-key")
    assert resolve_api.ensure_provider(settings).cerebras_key == "cloud-key"
    assert resolve_api.mint_master_key().startswith("sk-local-")
    assert resolve_api.read_settings(tmp_path, tmp_path).master_key


def test_url_and_local_probe_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ensure_http_url("https://example.test/v1") == "https://example.test/v1"
    with pytest.raises(UnsupportedSchemeError):
        ensure_http_url("file:///tmp/config")

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: Response({"data": []}),
    )
    assert probe.probe_port(8008).reachable
    unauthorized = urllib.error.HTTPError(
        "http://127.0.0.1:8008/v1/models", 401, "no", Message(), io.BytesIO(b"")
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(unauthorized),
    )
    assert probe.probe_port(8008).needs_auth


def test_process_adapter_resolves_and_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/tool")
    assert process.resolve_executable("tool") == Path("/usr/bin/tool")
    fallback = tmp_path / "tool"
    fallback.touch()
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert process.resolve_executable("tool", fallback) == fallback
    with pytest.raises(process.ExecutableNotFoundError):
        process.resolve_executable("missing")
    with pytest.raises(ValueError):
        process.run(Path("relative"), ())

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="out", stderr=""
        ),
    )
    result = process.run(Path("/usr/bin/tool"), ("--version",))
    assert result.ok and result.stdout == "out"


def test_model_diffs_cover_available_and_unavailable_paths() -> None:
    changed = diff_models("omlx", ["new", "same"], ["old", "same"])
    assert changed.changed and changed.available
    assert "+1 -1" in changed.summary()
    unchanged = diff_models("omlx", ["same"], ["same"])
    assert unchanged.summary() == "omlx: no changes (1 models)"
    offline = unavailable("omlx", "down", ["old"])
    assert not offline.available and "keeping recorded models" in offline.summary()
    assert any_changed([changed]) and not any_changed([unchanged])


def test_bootstrap_and_module_entrypoints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bootstrap.main()
    assert "Application initialized" in capsys.readouterr().out
    monkeypatch.setattr(cli, "main", lambda: 0)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("litectl.__main__", run_name="__main__")
    assert raised.value.code == 0


def test_catalog_recovery_prompt_covers_interactive_choices(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from litectl.modules.catalog.api.prompts import (
        ABORT_CHOICE,
        prompt_for_recovery,
    )
    from litectl.modules.catalog.domain.aliases import (
        PRESETS,
        UnavailableDefaultError,
    )

    targets = {preset: f"target-{preset}" for preset in PRESETS}
    error = UnavailableDefaultError("old-model", targets)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit, match="Active default is unavailable"):
        prompt_for_recovery(error)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    choices = iter(("invalid", ""))
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(choices))
    assert prompt_for_recovery(error) == PRESETS[0]
    assert "recommended" in capsys.readouterr().out

    monkeypatch.setattr(builtins, "input", lambda _prompt: ABORT_CHOICE)
    with pytest.raises(SystemExit, match="Update aborted"):
        prompt_for_recovery(error)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("forbidden", "authentication failed (HTTP 403)"),
        ("payment", "payment or quota"),
        ("server", "HTTP 500"),
        ("timed_out", "connection timed out"),
        ("down", "endpoint unreachable"),
        ("bad_json", "invalid payload"),
        ("key", "invalid payload"),
        ("scheme", "refusing to open"),
    ],
)
def test_openai_adapter_describes_provider_failures(
    monkeypatch: pytest.MonkeyPatch, failure: str, expected: str
) -> None:
    from litectl.modules.catalog.application.ports import Unreachable
    from litectl.modules.catalog.infrastructure import openai_compat

    def fail(*_args: object, **_kwargs: object) -> object:
        if failure in {"forbidden", "payment", "server"}:
            code = {"forbidden": 403, "payment": 402, "server": 500}[failure]
            raise urllib.error.HTTPError(
                "http://provider/models",
                code,
                "failure",
                hdrs=Message(),
                fp=io.BytesIO(b"{}"),
            )
        if failure == "timed_out":
            raise urllib.error.URLError("request timed out")
        if failure == "down":
            raise urllib.error.URLError("host down")
        if failure == "bad_json":
            raise json.JSONDecodeError("bad", "", 0)
        raise KeyError("data")

    monkeypatch.setattr(openai_compat, "http_get_json", fail)
    base = "ftp://provider" if failure == "scheme" else "http://provider/v1"
    result = openai_compat.fetch_models(base)
    assert isinstance(result, Unreachable)
    assert expected in result.reason


def test_probe_handles_non_auth_http_and_refused_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_error = urllib.error.HTTPError(
        "http://127.0.0.1:8008/v1/models",
        500,
        "server",
        hdrs=Message(),
        fp=io.BytesIO(b""),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error),
    )
    assert not probe.probe_port(8008).reachable

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    assert not probe.probe_port(8008).reachable


def test_healthcheck_exhausts_readiness_and_handles_bad_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_error = urllib.error.HTTPError(
        "http://proxy/models",
        500,
        "server",
        hdrs=Message(),
        fp=io.BytesIO(b""),
    )
    monkeypatch.setattr(
        healthcheck,
        "_get_json",
        lambda *_args: (_ for _ in ()).throw(server_error),
    )
    assert healthcheck.list_models("http://proxy", "key").note == "HTTP 500: server"

    monkeypatch.setattr(
        healthcheck,
        "_get_json",
        lambda *_args: (_ for _ in ()).throw(json.JSONDecodeError("bad", "", 0)),
    )
    assert healthcheck.list_models("http://proxy", "key").note == "waiting for proxy"

    monkeypatch.setattr(healthcheck, "_get_json", lambda *_args: {"data": "bad"})
    assert (
        healthcheck.list_models("http://proxy", "key").note == "awaiting model registry"
    )

    monkeypatch.setattr(healthcheck, "list_models", lambda *_args: Attempt())
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    exhausted = healthcheck.wait_for_models("http://proxy", "key")
    assert exhausted.note == ""


def test_healthcheck_completion_failure_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed: tuple[dict[str, object], ...] = (
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 1}}]},
    )
    for payload in malformed:
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda *_args, payload=payload, **_kwargs: Response(payload),
        )
        assert "test call notice" in healthcheck.complete(
            "http://proxy", "key", "omlx-model"
        )

    error = urllib.error.HTTPError(
        "http://proxy/v1/chat/completions",
        500,
        "server",
        hdrs=Message(),
        fp=io.BytesIO(b"bad response"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    assert healthcheck.complete("http://proxy", "key", "omlx-model").startswith(
        "HTTP 500"
    )


def test_catalog_cli_recovery_and_no_change_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from litectl.modules.catalog import cli as catalog_cli
    from litectl.modules.catalog.domain.aliases import (
        Discovery,
        UnavailableDefaultError,
    )
    from litectl.modules.catalog.infrastructure.config import AppConfig
    from litectl.modules.catalog.infrastructure.config_yaml import ConfigUpdate
    from litectl.modules.catalog.pipeline import Rendered

    cfg = AppConfig.from_env(tmp_path)
    discovery_value = Discovery([], "omlx", [], set())
    calls = 0

    def update(
        _path: Path, _discovery: Discovery, recovery_preset: str | None = None
    ) -> ConfigUpdate:
        nonlocal calls
        calls += 1
        if recovery_preset is None:
            raise UnavailableDefaultError(
                "old", {"cloud": "c", "speed": "s", "quality": "q"}
            )
        return ConfigUpdate("model_list: []\n", ())

    monkeypatch.setattr(catalog_cli, "update_config", update)
    monkeypatch.setattr(catalog_cli, "prompt_for_recovery", lambda _error: "speed")
    assert (
        catalog_cli.build_config_update(cfg, discovery_value).content
        == "model_list: []\n"
    )
    assert calls == 2

    assert catalog_cli.main(tmp_path, ["unknown"]) == 1
    assert catalog_cli.main(tmp_path, ["omlx", "--yes"]) == 0
    assert "No changes" in capsys.readouterr().out

    rendered = Rendered(reports=["report"], entries=["- model_name: x\n"])
    catalog_cli.report_results(
        rendered, ("warning",), Discovery([], "omlx", [], {"omlx-x"})
    )
    output = capsys.readouterr().out
    assert (
        "report" in output and "WARN  warning" in output and "1 model routes" in output
    )


def test_bootstrap_config_and_service_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from litectl import serve
    from litectl.app import paths
    from litectl.modules.catalog.domain.urls import ensure_http_url as catalog_url
    from litectl.modules.workspace.infrastructure import service

    assert (
        paths.config_dir("~/cfg", home_dir=tmp_path) == (Path.home() / "cfg").resolve()
    )
    assert (
        paths.config_dir(
            environment={"CONFIG_FILE_PATH": "~/x/config.yaml"}, home_dir=tmp_path
        ).name
        == "x"
    )
    assert (
        paths.state_dir(
            environment={"XDG_STATE_HOME": "~/state"}, home_dir=tmp_path
        ).name
        == "litectl"
    )
    assert catalog_url("HTTP://example.test") == "HTTP://example.test"

    assert serve.validated_fingerprint(tmp_path) is None
    monkeypatch.setattr(serve, "_config_schema", lambda: "{}")
    (tmp_path / "config.yaml").write_text("model_list: []\n", encoding="utf-8")
    assert serve.validated_fingerprint(tmp_path) is not None

    context = service_context(tmp_path)
    monkeypatch.setattr(service, "service_running", lambda *_args: False)
    monkeypatch.setattr(
        service, "_write_service_file", lambda *_args: tmp_path / "service"
    )
    assert service.install_service(context, platform="unsupported") is False


def test_catalog_config_readers_cover_missing_and_included_shapes(
    tmp_path: Path,
) -> None:
    from litectl.modules.catalog.infrastructure import config_reader

    missing = tmp_path / "missing.yaml"
    assert config_reader.read_provider_aliases(missing) == []
    assert config_reader.read_provider_base(missing) is None
    assert config_reader.read_config_model_groups(missing) == set()
    assert config_reader.read_environment_variables(missing) == {}

    provider = tmp_path / "provider.yaml"
    provider.write_text(
        "model_list:\n"
        "  - model_name: good\n"
        "  - model_name: 'wild/*'\n"
        "  - ignored: true\n"
        "  - model_name: null\n"
        "  - model_name: plain\n"
        "    litellm_params: {}\n"
        "  - model_name: base\n"
        "    litellm_params:\n"
        "      api_base: http://127.0.0.1:8008/v1\n",
        encoding="utf-8",
    )
    assert config_reader.read_provider_aliases(provider) == ["good", "plain", "base"]
    assert config_reader.read_provider_base(provider) == "http://127.0.0.1:8008/v1"

    config = tmp_path / "config.yaml"
    config.write_text(
        "include:\n  - provider.yaml\n  - absent.yaml\nmodel_list: []\n",
        encoding="utf-8",
    )
    assert config_reader.read_config_model_groups(config) == {"good", "plain", "base"}

    env = tmp_path / "env.yaml"
    env.write_text(
        "environment_variables:\n  KEY: ' value '\n  EMPTY: null\n",
        encoding="utf-8",
    )
    assert config_reader.read_environment_variables(env) == {"KEY": " value "}
    env.write_text("environment_variables: []\n", encoding="utf-8")
    assert config_reader.read_environment_variables(env) == {}


def test_keys_read_all_config_value_shapes(tmp_path: Path) -> None:
    from litectl.modules.workspace.infrastructure.keys import config_environment_value

    missing = tmp_path / "missing.yaml"
    assert config_environment_value(missing, "KEY") == ""
    missing.write_text("environment_variables: [\n", encoding="utf-8")
    assert config_environment_value(missing, "KEY") == ""
    missing.write_text("[]\n", encoding="utf-8")
    assert config_environment_value(missing, "KEY") == ""
    missing.write_text("environment_variables: []\n", encoding="utf-8")
    assert config_environment_value(missing, "KEY") == ""
    missing.write_text(
        "environment_variables:\n  KEY: ' value '\n  EMPTY: null\n",
        encoding="utf-8",
    )
    assert config_environment_value(missing, "KEY") == "value"
    assert config_environment_value(missing, "MISSING") == ""
    assert config_environment_value(missing, "EMPTY") == ""


def test_probe_builds_auth_requests_and_scans_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    def response(request: object, **_kwargs: object) -> Response:
        seen.append(request)
        return Response({"data": []})

    monkeypatch.setattr(urllib.request, "urlopen", response)
    assert probe.probe_port(8008, "real-key").reachable
    request = seen[0]
    assert isinstance(request, urllib.request.Request)
    assert request.get_header("Authorization") == "Bearer real-key"
    outcomes = iter((ProbeResult(), ProbeResult(reachable=True, port=8080)))
    monkeypatch.setattr(probe, "probe_port", lambda *_args: next(outcomes))
    assert probe.find_local_server("key") == ProbeResult(reachable=True, port=8080)
    monkeypatch.setattr(probe, "probe_port", lambda *_args: ProbeResult())
    assert not probe.find_local_server().reachable


def test_app_handlers_cover_success_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from argparse import Namespace

    from litectl.app import install as installer_module
    from litectl.app import teardown as teardown_module

    runtime = cli.RuntimeContext(
        base_dir=tmp_path,
        state_dir=tmp_path / "state",
        home_dir=tmp_path / "home",
        service=service_context(tmp_path),
    )
    monkeypatch.setattr(installer_module, "run", lambda *_args: 0)
    assert cli._install(Namespace(target=None, config_dir=None), runtime) == 0

    listed: list[Path] = []

    def record_list(path: Path) -> None:
        listed.append(path)

    monkeypatch.setattr(cli, "list_models_main", record_list)
    assert cli._list(Namespace(), runtime) == 0
    assert listed == [tmp_path]

    monkeypatch.setattr(cli, "read_settings", lambda *_args: Settings(master_key="key"))
    monkeypatch.setattr(installer_module, "apply_environment", lambda _settings: None)
    updates: list[list[str]] = []

    def record_update(_base: Path, args: list[str]) -> int:
        updates.append(args)
        return 0

    monkeypatch.setattr(cli, "catalog_main", record_update)
    assert cli._update(Namespace(provider="omlx", yes=True), runtime) == 0
    assert updates == [["omlx", "--yes"]]

    monkeypatch.setattr(cli, "start_service", lambda *_args, **_kwargs: True)
    assert cli._start(Namespace(), runtime) == 0
    monkeypatch.setattr(cli, "stop_service", lambda _service: True)
    assert cli._stop(Namespace(), runtime) == 0
    monkeypatch.setattr(cli, "service_running", lambda _service: False)
    assert cli._status(Namespace(), runtime) == 1
    monkeypatch.setattr(cli, "stream_logs", lambda _service: 7)
    assert cli._logs(Namespace(), runtime) == 7
    monkeypatch.setattr(teardown_module, "main", lambda *_args: None)
    assert cli._teardown(Namespace(yes=True), runtime) == 0
    assert "started" in capsys.readouterr().out.lower()


def test_config_reader_seeds_and_rejects_non_mapping(tmp_path: Path) -> None:
    from litectl.modules.catalog.infrastructure import config_reader

    seeded = tmp_path / "seeded.yaml"
    config = config_reader.load_config(seeded)
    assert "router_settings" in config
    seeded.write_text("[]\n", encoding="utf-8")
    with pytest.raises(TypeError, match="top-level YAML mapping"):
        config_reader.load_config(seeded)

    no_base = tmp_path / "no-base.yaml"
    no_base.write_text("model_list:\n  - ignored\n", encoding="utf-8")
    assert config_reader.read_provider_base(no_base) is None


def test_client_saved_master_key_handles_missing_and_malformed_files(
    tmp_path: Path,
) -> None:
    from litectl.modules.workspace.infrastructure.keys import client_saved_master_key

    assert client_saved_master_key(tmp_path) == ""
    fabric_env = tmp_path / ".config/fabric/.env"
    fabric_env.parent.mkdir(parents=True)
    fabric_env.write_text("DEFAULT_MODEL=default\n", encoding="utf-8")
    assert client_saved_master_key(tmp_path) == ""
    fabric_env.write_text("LITELLM_API_KEY=sk-local-test123\n", encoding="utf-8")
    assert client_saved_master_key(tmp_path) == "sk-local-test123"
