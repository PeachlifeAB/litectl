from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
import uvicorn
from watchfiles import Change

from litectl import serve


def write_valid_config(root: Path) -> None:
    (root / "providers").mkdir(parents=True)
    (root / "config.yaml").write_text("model_list: []\n", encoding="utf-8")
    (root / "providers/local.yaml").write_text("model_list: []\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("config.yaml", True),
        ("providers/omlx.yaml", True),
        ("providers/nested/models.yaml", True),
        ("providers/readme.txt", False),
        ("state/proxy.log", False),
    ],
)
def test_relevant_config_paths(relative_path: str, expected: bool) -> None:
    assert serve.is_relevant_config_path(Path(relative_path)) is expected


def test_validated_fingerprint_rejects_invalid_intermediate_config(
    tmp_path: Path,
) -> None:
    write_valid_config(tmp_path)
    original = serve.validated_fingerprint(tmp_path)
    (tmp_path / "config.yaml").write_text("model_list: [\n", encoding="utf-8")

    assert original is not None
    assert serve.validated_fingerprint(tmp_path) is None


def test_same_configuration_does_not_restart_again(tmp_path: Path) -> None:
    write_valid_config(tmp_path)
    loaded = serve.validated_fingerprint(tmp_path)

    assert loaded is not None
    assert not serve.requires_reload(loaded, loaded)


class PendingChild:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint
        self.replacements: list[str] = []

    async def replace(self, fingerprint: str) -> None:
        self.replacements.append(fingerprint)
        self.fingerprint = fingerprint


def test_pending_reload_revalidates_and_skips_redundant_restart(
    tmp_path: Path,
) -> None:
    write_valid_config(tmp_path)
    fingerprint = serve.validated_fingerprint(tmp_path)
    assert fingerprint is not None
    child = cast(serve.ChildState, PendingChild(fingerprint))

    asyncio.run(serve._reload_if_needed(tmp_path, child))

    assert cast(PendingChild, child).replacements == []

    (tmp_path / "providers/local.yaml").write_text(
        "model_list:\n  - model_name: changed\n", encoding="utf-8"
    )
    asyncio.run(serve._reload_if_needed(tmp_path, child))

    assert len(cast(PendingChild, child).replacements) == 1


class FakeProcess:
    pid = 123
    returncode: int | None = None

    def __init__(self, exit_event: asyncio.Event) -> None:
        self.exit_event = exit_event

    async def wait(self) -> int:
        await self.exit_event.wait()
        self.returncode = 0
        return 0


def test_child_exit_within_grace_never_uses_sigkill() -> None:
    exit_event = asyncio.Event()
    exit_event.set()
    process = cast(asyncio.subprocess.Process, FakeProcess(exit_event))
    signals: list[signal.Signals] = []

    asyncio.run(
        serve.terminate_child(
            process,
            grace_period_seconds=0.1,
            signal_group=lambda _pid, sent: signals.append(sent),
        )
    )

    assert signals == [signal.SIGTERM]


def test_child_exceeding_grace_is_killed_and_reaped() -> None:
    exit_event = asyncio.Event()
    process = cast(asyncio.subprocess.Process, FakeProcess(exit_event))
    signals: list[signal.Signals] = []

    def signal_group(_pid: int, sent: signal.Signals) -> None:
        signals.append(sent)
        if sent == signal.SIGKILL:
            exit_event.set()

    asyncio.run(
        serve.terminate_child(
            process,
            grace_period_seconds=0.001,
            signal_group=signal_group,
        )
    )

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert process.returncode == 0


def test_proxy_environment_seeds_config_environment_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.yaml").write_text(
        "environment_variables:\n"
        "  OMLX_API_KEY: from-config\n"
        "  LITELLM_PORT: '4100'\n"
        "  CEREBRAS_API_KEY: from-config\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OMLX_API_KEY", "from-shell")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_PORT", raising=False)

    env = serve._proxy_environment(tmp_path)

    assert env["OMLX_API_KEY"] == "from-shell"
    assert env["CEREBRAS_API_KEY"] == "from-config"
    assert env["LITELLM_PORT"] == "4100"


def test_proxy_environment_without_config_file(tmp_path: Path) -> None:
    env = serve._proxy_environment(tmp_path)

    assert env["CONFIG_FILE_PATH"] == str(tmp_path / "config.yaml")
    assert env["WORKER_CONFIG"] == str(tmp_path / "config.yaml")


def test_run_proxy_applies_environment_and_starts_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, int, str]] = []
    environment_calls: list[Path] = []

    def fake_proxy_environment(config_dir: Path) -> dict[str, str]:
        environment_calls.append(config_dir)
        return {"TEST_PROXY_ENV": "set"}

    monkeypatch.delenv("TEST_PROXY_ENV", raising=False)
    monkeypatch.setattr(serve, "_proxy_environment", fake_proxy_environment)
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, *, host, port, log_level: calls.append(
            (app, host, port, log_level)
        ),
    )

    assert serve.run_proxy(tmp_path, 4100) == 0
    assert environment_calls == [tmp_path]
    assert os.environ["TEST_PROXY_ENV"] == "set"
    assert calls == [("litellm.proxy.proxy_server:app", "127.0.0.1", 4100, "info")]


class FakeSupervisedChild:
    fingerprint = "fingerprint"

    def __init__(self) -> None:
        self.closed = False
        self.wait_task = asyncio.create_task(self._wait())

    async def _wait(self) -> int:
        await asyncio.Event().wait()
        return 0

    async def close(self) -> None:
        self.closed = True
        self.wait_task.cancel()
        await asyncio.gather(self.wait_task, return_exceptions=True)


def test_supervisor_closes_pending_watcher_before_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> tuple[int, FakeSupervisedChild]:
        child = FakeSupervisedChild()

        async def fake_start(*_args: object) -> serve.ChildState:
            return cast(serve.ChildState, child)

        async def pending_changes() -> AsyncGenerator[set[tuple[Change, str]], None]:
            await asyncio.Event().wait()
            yield set()

        monkeypatch.setattr(serve, "validated_fingerprint", lambda _path: "fingerprint")
        monkeypatch.setattr(serve, "_install_stop_handlers", lambda event: event.set())
        monkeypatch.setattr(serve.ChildState, "start", staticmethod(fake_start))
        monkeypatch.setattr(serve, "_watch_changes", lambda *_args: pending_changes())

        result = await serve.supervise(tmp_path, 4000, 0.1, 10)
        return result, child

    result, child = asyncio.run(exercise())

    assert result == 0
    assert child.closed
