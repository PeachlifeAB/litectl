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
