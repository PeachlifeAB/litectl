from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import AsyncGenerator, Callable
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

        result = await asyncio.wait_for(
            serve.supervise(tmp_path, 4000, 0.1, 10),
            timeout=0.1,
        )
        return result, child

    result, child = asyncio.run(exercise())

    assert result == 0
    assert child.closed


def test_direct_serve_reconciles_before_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[tuple[str, object]] = []

    def run_proxy(config_dir: Path, port: int) -> int:
        events.append(("proxy", (config_dir, port)))
        return 0

    monkeypatch.setattr(serve, "run_proxy", run_proxy)

    def reconcile() -> list[str]:
        events.append(("reconcile", None))
        return ["removed omlx-old"]

    result = serve.main(
        tmp_path,
        port=4100,
        reconcile=reconcile,
    )

    assert result == 0
    assert events == [("reconcile", None), ("proxy", (tmp_path, 4100))]
    assert "removed omlx-old" in capsys.readouterr().out


def test_ensure_callback_shim_writes_once_and_preserves(tmp_path: Path) -> None:
    """Startup repair is idempotent and never clobbers user content."""
    serve.ensure_callback_shim(tmp_path)

    shim = tmp_path / "litectl_hooks.py"
    assert "handler" in shim.read_text(encoding="utf-8")

    shim.write_text("# custom\n", encoding="utf-8")
    serve.ensure_callback_shim(tmp_path)
    assert shim.read_text(encoding="utf-8") == "# custom\n"


def test_main_materializes_callback_shim_into_empty_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The serve entry point repairs a missing shim before any proxy start."""
    monkeypatch.setattr(serve, "run_proxy", lambda _dir, _port: 0)  # never bind a port

    code = serve.main(tmp_path)

    assert code == 0
    assert (tmp_path / "litectl_hooks.py").exists()


def test_relevant_change_filter_accepts_only_config_paths(tmp_path: Path) -> None:
    predicate = serve.relevant_change_filter(tmp_path)

    assert predicate(Change.added, str(tmp_path / "config.yaml")) is True
    assert predicate(Change.added, str(tmp_path / "providers/local.yaml")) is True
    assert predicate(Change.added, str(tmp_path / "state/proxy.log")) is False


def test_configuration_paths_lists_config_then_sorted_providers(tmp_path: Path) -> None:
    (tmp_path / "providers").mkdir()
    (tmp_path / "providers/zeta.yaml").write_text("model_list: []\n", encoding="utf-8")
    (tmp_path / "providers/alpha.yaml").write_text("model_list: []\n", encoding="utf-8")

    paths = serve._configuration_paths(tmp_path)

    assert paths == (
        tmp_path / "config.yaml",
        tmp_path / "providers/alpha.yaml",
        tmp_path / "providers/zeta.yaml",
    )


def test_signal_process_group_kills_the_whole_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(serve.os, "killpg", lambda pid, sent: calls.append((pid, sent)))

    serve.signal_process_group(4242, signal.SIGTERM)

    assert calls == [(4242, signal.SIGTERM)]


def test_start_child_launches_uvicorn_with_proxy_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []

    async def fake_exec(*command: str, **kwargs: object) -> asyncio.subprocess.Process:
        commands.append(command)
        environments.append(cast(dict[str, str], kwargs["env"]))
        return cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    monkeypatch.setattr(serve.asyncio, "create_subprocess_exec", fake_exec)

    process = asyncio.run(serve.start_child(tmp_path, 4100))

    assert isinstance(process, FakeProcess)
    assert commands == [
        (
            sys.executable,
            "-m",
            "uvicorn",
            "litellm.proxy.proxy_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            "4100",
            "--log-level",
            "info",
        )
    ]
    assert environments[0]["CONFIG_FILE_PATH"] == str(tmp_path / "config.yaml")


def test_watch_changes_builds_awatch_with_derived_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_awatch(
        *paths: Path, **kwargs: object
    ) -> AsyncGenerator[set[tuple[Change, str]], None]:
        captured["paths"] = paths
        captured.update(kwargs)

        async def generator() -> AsyncGenerator[set[tuple[Change, str]], None]:
            yield set()

        return generator()

    monkeypatch.setattr(serve, "awatch", fake_awatch)

    serve._watch_changes(tmp_path, 500)

    assert captured["paths"] == (tmp_path,)
    assert captured["debounce"] == 500
    assert captured["step"] == 50
    assert callable(captured["watch_filter"])


def test_watch_changes_clamps_step_for_small_debounce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        serve,
        "awatch",
        lambda *_paths, **kwargs: captured.update(kwargs) or _empty_changes(),
    )

    serve._watch_changes(tmp_path, 5)

    assert captured["step"] == 1


def _empty_changes() -> AsyncGenerator[set[tuple[Change, str]], None]:
    async def generator() -> AsyncGenerator[set[tuple[Change, str]], None]:
        yield set()

    return generator()


def test_reload_if_needed_reports_invalid_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_valid_config(tmp_path)
    fingerprint = serve.validated_fingerprint(tmp_path)
    assert fingerprint is not None
    child = cast(serve.ChildState, PendingChild(fingerprint))
    (tmp_path / "config.yaml").write_text("model_list: [\n", encoding="utf-8")

    asyncio.run(serve._reload_if_needed(tmp_path, child))

    assert cast(PendingChild, child).replacements == []
    assert (
        capsys.readouterr().err == "Configuration reload skipped: validation failed.\n"
    )


def test_supervise_refuses_invalid_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert asyncio.run(_supervise_for_test(tmp_path, 4000, 0.1, 10)) == 2

    assert (
        capsys.readouterr().err
        == "Configuration is invalid; LiteLLM was not started.\n"
    )


def test_supervise_uses_resolved_port_and_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_valid_config(tmp_path)
    starts: list[tuple[Path, int, float, str]] = []

    async def fake_start(
        config_dir: Path, port: int, grace: float, fingerprint: str
    ) -> serve.ChildState:
        starts.append((config_dir, port, grace, fingerprint))
        return cast(serve.ChildState, FakeSupervisedChild())

    monkeypatch.setattr(serve, "validated_fingerprint", lambda _path: "fingerprint")
    monkeypatch.setattr(serve, "_install_stop_handlers", lambda event: event.set())
    monkeypatch.setattr(serve.ChildState, "start", staticmethod(fake_start))
    monkeypatch.setattr(serve, "_watch_changes", lambda *_args: _empty_changes())

    assert asyncio.run(_supervise_for_test(tmp_path, 4100, 7.5, 10)) == 0

    assert starts == [(tmp_path, 4100, 7.5, "fingerprint")]


def test_child_state_start_captures_launched_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched: list[tuple[Path, int]] = []

    async def fake_start_child(
        config_dir: Path, port: int
    ) -> asyncio.subprocess.Process:
        launched.append((config_dir, port))
        return cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    monkeypatch.setattr(serve, "start_child", fake_start_child)

    async def exercise() -> serve.ChildState:
        state = await serve.ChildState.start(tmp_path, 4100, 2.5, "fingerprint")
        state.wait_task.cancel()
        await asyncio.gather(state.wait_task, return_exceptions=True)
        return state

    state = asyncio.run(exercise())

    assert launched == [(tmp_path, 4100)]
    assert state.config_dir == tmp_path
    assert state.port == 4100
    assert state.grace_period_seconds == 2.5
    assert state.fingerprint == "fingerprint"
    assert state.process.pid == 123


def test_child_state_replace_swaps_process_and_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminations: list[float] = []
    launches: list[tuple[Path, int]] = []

    async def fake_terminate(
        process: asyncio.subprocess.Process, grace: float, **_kwargs: object
    ) -> None:
        terminations.append(grace)

    async def fake_start_child(
        config_dir: Path, port: int
    ) -> asyncio.subprocess.Process:
        launches.append((config_dir, port))
        return cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    monkeypatch.setattr(serve, "terminate_child", fake_terminate)
    monkeypatch.setattr(serve, "start_child", fake_start_child)

    async def exercise() -> serve.ChildState:
        state = serve.ChildState(
            tmp_path,
            4100,
            3.0,
            "old",
            cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event())),
            asyncio.create_task(_never_exits()),
        )
        await state.replace("new")
        state.wait_task.cancel()
        await asyncio.gather(state.wait_task, return_exceptions=True)
        return state

    state = asyncio.run(exercise())

    assert terminations == [3.0]
    assert launches == [(tmp_path, 4100)]
    assert state.fingerprint == "new"


async def _never_exits() -> int:
    await asyncio.Event().wait()
    return 0


def test_child_state_close_stops_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminations: list[float] = []

    async def fake_terminate(
        process: asyncio.subprocess.Process, grace: float, **_kwargs: object
    ) -> None:
        terminations.append(grace)

    monkeypatch.setattr(serve, "terminate_child", fake_terminate)

    async def exercise() -> None:
        state = serve.ChildState(
            tmp_path,
            4100,
            4.0,
            "fingerprint",
            cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event())),
            asyncio.create_task(_never_exits()),
        )
        await state.close()

    asyncio.run(exercise())

    assert terminations == [4.0]


def test_install_stop_handlers_registers_interrupt_and_terminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[tuple[signal.Signals, object]] = []
    monkeypatch.setattr(serve.sys, "platform", "linux")
    monkeypatch.setattr(
        serve.asyncio,
        "get_running_loop",
        lambda: cast(
            asyncio.AbstractEventLoop,
            _RecordingLoop(
                lambda handled, callback: registered.append((handled, callback))
            ),
        ),
    )
    stop_event = asyncio.Event()

    asyncio.run(_run_install_handlers(stop_event))

    assert [handled for handled, _ in registered] == [signal.SIGINT, signal.SIGTERM]
    for _handled, callback in registered:
        callback()
    assert stop_event.is_set()


async def _run_install_handlers(stop_event: asyncio.Event) -> None:
    serve._install_stop_handlers(stop_event)


def test_install_stop_handlers_is_noop_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(serve.sys, "platform", "win32")
    monkeypatch.setattr(
        serve.asyncio,
        "get_running_loop",
        lambda: pytest.fail("signal handlers must not be installed on win32"),
    )

    asyncio.run(_run_install_handlers(asyncio.Event()))


class _RecordingLoop:
    def __init__(self, recorder: Callable[[signal.Signals, object], None]) -> None:
        self._recorder = recorder

    def add_signal_handler(self, handled: signal.Signals, callback: object) -> None:
        self._recorder(handled, callback)


def test_main_resolves_port_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ports: list[int] = []
    monkeypatch.setenv("LITELLM_PORT", "4321")
    monkeypatch.setattr(serve, "run_proxy", lambda _dir, port: ports.append(port) or 0)
    monkeypatch.setattr(serve, "ensure_callback_shim", lambda _dir: None)

    assert serve.main(tmp_path) == 0

    assert ports == [4321]


def test_main_defaults_port_when_environment_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ports: list[int] = []
    monkeypatch.delenv("LITELLM_PORT", raising=False)
    monkeypatch.setattr(serve, "run_proxy", lambda _dir, port: ports.append(port) or 0)
    monkeypatch.setattr(serve, "ensure_callback_shim", lambda _dir: None)

    assert serve.main(tmp_path) == 0

    assert ports == [serve.DEFAULT_PORT]


def test_main_watch_mode_runs_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervised: list[tuple[Path, int, float, int]] = []

    async def fake_supervise(
        config_dir: Path, port: int, grace: float, debounce: int
    ) -> int:
        supervised.append((config_dir, port, grace, debounce))
        return 7

    monkeypatch.setattr(serve, "supervise", fake_supervise)
    monkeypatch.setattr(serve, "ensure_callback_shim", lambda _dir: None)

    assert serve.main(tmp_path, port=4100, watch=True) == 7

    assert supervised == [
        (
            tmp_path,
            4100,
            serve.DEFAULT_SHUTDOWN_GRACE_SECONDS,
            serve.DEFAULT_DEBOUNCE_MILLISECONDS,
        )
    ]


def test_supervise_returns_child_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_valid_config(tmp_path)
    exit_event = asyncio.Event()

    class ExitingChild(FakeSupervisedChild):
        fingerprint = "fingerprint"
        wait_task = None  # replaced per-run below

    monkeypatch.setattr(serve, "validated_fingerprint", lambda _path: "fingerprint")
    monkeypatch.setattr(serve, "_install_stop_handlers", lambda _event: None)
    monkeypatch.setattr(serve, "_watch_changes", lambda *_args: _empty_changes())

    async def fake_start(
        config_dir: Path, port: int, grace: float, fingerprint: str
    ) -> serve.ChildState:
        child = cast(serve.ChildState, ExitingChild())
        child.wait_task = asyncio.create_task(_exit_with(exit_event, 5))
        return child

    monkeypatch.setattr(serve.ChildState, "start", staticmethod(fake_start))

    assert asyncio.run(_supervise_for_test(tmp_path, 4000, 0.1, 10)) == 5


async def _exit_with(event: asyncio.Event, code: int) -> int:
    event.set()
    return code


async def _record_and_stop(
    config_dir: Path, reloads: list[Path], stop_event: asyncio.Event
) -> None:
    reloads.append(config_dir)
    stop_event.set()


def test_reload_if_needed_replaces_child_on_fingerprint_change(
    tmp_path: Path,
) -> None:
    write_valid_config(tmp_path)
    child = cast(serve.ChildState, PendingChild("stale-fingerprint"))

    asyncio.run(serve._reload_if_needed(tmp_path, child))

    assert len(cast(PendingChild, child).replacements) == 1
    assert cast(PendingChild, child).fingerprint == serve.validated_fingerprint(
        tmp_path
    )


def test_reload_if_needed_skips_unchanged_fingerprint(tmp_path: Path) -> None:
    write_valid_config(tmp_path)
    fingerprint = serve.validated_fingerprint(tmp_path)
    assert fingerprint is not None
    child = cast(serve.ChildState, PendingChild(fingerprint))

    asyncio.run(serve._reload_if_needed(tmp_path, child))

    assert cast(PendingChild, child).replacements == []


def test_supervise_reloads_with_first_completed_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_valid_config(tmp_path)
    reloads: list[tuple[Path, object]] = []
    wait_calls = 0

    monkeypatch.setattr(serve, "validated_fingerprint", lambda _path: "fingerprint")
    monkeypatch.setattr(serve, "_install_stop_handlers", lambda _event: None)
    monkeypatch.setattr(
        serve.ChildState, "start", staticmethod(_start_supervised_child)
    )

    async def changes() -> AsyncGenerator[set[tuple[Change, str]], None]:
        yield set()
        await asyncio.Event().wait()

    async def fake_reload(config_dir: Path, child: serve.ChildState) -> None:
        reloads.append((config_dir, child))

    async def fake_wait(
        awaitables: object, *, return_when: object
    ) -> tuple[set[object], set[object]]:
        nonlocal wait_calls
        wait_calls += 1
        tasks = tuple(cast(tuple[object, ...], awaitables))
        assert return_when is asyncio.FIRST_COMPLETED
        if wait_calls == 1:
            return {tasks[0]}, set(tasks[1:])
        return {tasks[2]}, {tasks[0], tasks[1]}

    monkeypatch.setattr(serve, "_watch_changes", lambda *_args: changes())
    monkeypatch.setattr(serve, "_reload_if_needed", fake_reload)
    monkeypatch.setattr(serve.asyncio, "wait", fake_wait)

    assert asyncio.run(_supervise_for_test(tmp_path, 4000, 0.1, 10)) == 0

    assert wait_calls == 2
    assert len(reloads) == 1
    assert reloads[0][0] == tmp_path
    assert isinstance(reloads[0][1], FakeSupervisedChild)


def test_terminate_child_signals_recorded_process_pid() -> None:
    exit_event = asyncio.Event()
    exit_event.set()
    process = cast(asyncio.subprocess.Process, FakeProcess(exit_event))
    signals: list[tuple[int, signal.Signals]] = []

    asyncio.run(
        serve.terminate_child(
            process,
            grace_period_seconds=0.1,
            signal_group=lambda pid, sent: signals.append((pid, sent)),
        )
    )

    assert signals == [(123, signal.SIGTERM)]


def test_terminate_child_kills_recorded_process_pid() -> None:
    exit_event = asyncio.Event()
    process = cast(asyncio.subprocess.Process, FakeProcess(exit_event))
    signals: list[tuple[int, signal.Signals]] = []

    def signal_group(pid: int, sent: signal.Signals) -> None:
        signals.append((pid, sent))
        if sent is signal.SIGKILL:
            exit_event.set()
        elif sent is not signal.SIGTERM:
            raise AssertionError(f"unexpected signal: {sent!r}")

    asyncio.run(
        serve.terminate_child(
            process,
            grace_period_seconds=0.001,
            signal_group=signal_group,
        )
    )

    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]


def test_terminate_child_uses_the_grace_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exit_event = asyncio.Event()
    process = cast(asyncio.subprocess.Process, FakeProcess(exit_event))
    timeouts: list[float | None] = []
    real_wait_for = asyncio.wait_for

    async def recording_wait_for(awaitable: object, *, timeout: float | None) -> object:
        timeouts.append(timeout)
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(serve.asyncio, "wait_for", recording_wait_for)

    asyncio.run(
        serve.terminate_child(
            process,
            grace_period_seconds=0.25,
            signal_group=lambda _pid, _sent: exit_event.set(),
        )
    )

    assert timeouts == [0.25]


def test_start_child_detaches_the_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions: list[object] = []

    async def fake_exec(*_command: str, **kwargs: object) -> asyncio.subprocess.Process:
        sessions.append(kwargs["start_new_session"])
        return cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    monkeypatch.setattr(serve.asyncio, "create_subprocess_exec", fake_exec)

    asyncio.run(serve.start_child(tmp_path, 4100))

    assert sessions == [True]


def test_start_child_passes_config_dir_to_proxy_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directories: list[Path] = []

    def fake_environment(config_dir: Path) -> dict[str, str]:
        directories.append(config_dir)
        return {"CONFIG_FILE_PATH": "sentinel"}

    async def fake_exec(
        *_command: str, **_kwargs: object
    ) -> asyncio.subprocess.Process:
        return cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    monkeypatch.setattr(serve, "_proxy_environment", fake_environment)
    monkeypatch.setattr(serve.asyncio, "create_subprocess_exec", fake_exec)

    asyncio.run(serve.start_child(tmp_path, 4100))

    assert directories == [tmp_path]


def test_watch_changes_filters_through_the_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        serve,
        "awatch",
        lambda *_paths, **kwargs: captured.update(kwargs) or _empty_changes(),
    )

    serve._watch_changes(tmp_path, 500)

    watch_filter = cast(Callable[[Change, str], bool], captured["watch_filter"])
    assert watch_filter(Change.added, str(tmp_path / "config.yaml")) is True
    assert watch_filter(Change.added, str(tmp_path / "state/proxy.log")) is False


def test_child_state_replace_terminates_the_previous_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminated: list[object] = []

    async def fake_terminate(process: object, grace: float, **_kwargs: object) -> None:
        terminated.append(process)

    async def fake_start_child(
        _config_dir: Path, _port: int
    ) -> asyncio.subprocess.Process:
        return cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    monkeypatch.setattr(serve, "terminate_child", fake_terminate)
    monkeypatch.setattr(serve, "start_child", fake_start_child)
    process = cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    async def exercise() -> None:
        state = serve.ChildState(
            tmp_path, 4100, 3.0, "old", process, asyncio.create_task(_never_exits())
        )
        await state.replace("new")

    asyncio.run(exercise())

    assert terminated == [process]


def test_child_state_close_terminates_the_current_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminated: list[object] = []

    async def fake_terminate(process: object, grace: float, **_kwargs: object) -> None:
        terminated.append(process)

    monkeypatch.setattr(serve, "terminate_child", fake_terminate)
    process = cast(asyncio.subprocess.Process, FakeProcess(asyncio.Event()))

    async def exercise() -> None:
        state = serve.ChildState(
            tmp_path,
            4100,
            4.0,
            "fingerprint",
            process,
            asyncio.create_task(_never_exits()),
        )
        await state.close()

    asyncio.run(exercise())

    assert terminated == [process]


def test_supervise_passes_config_dir_and_debounce_to_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_valid_config(tmp_path)
    watched: list[tuple[Path, int]] = []

    monkeypatch.setattr(serve, "validated_fingerprint", lambda _path: "fingerprint")
    monkeypatch.setattr(serve, "_install_stop_handlers", lambda event: event.set())
    monkeypatch.setattr(
        serve.ChildState, "start", staticmethod(_start_supervised_child)
    )

    def fake_watch(
        config_dir: Path, debounce: int
    ) -> AsyncGenerator[set[tuple[Change, str]], None]:
        watched.append((config_dir, debounce))
        return _empty_changes()

    monkeypatch.setattr(serve, "_watch_changes", fake_watch)

    assert asyncio.run(_supervise_for_test(tmp_path, 4100, 0.1, 10)) == 0

    assert watched == [(tmp_path, 10)]


def test_supervise_waits_for_first_completed_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_valid_config(tmp_path)
    return_whens: list[object] = []

    monkeypatch.setattr(serve, "validated_fingerprint", lambda _path: "fingerprint")
    monkeypatch.setattr(serve, "_install_stop_handlers", lambda event: event.set())
    monkeypatch.setattr(
        serve.ChildState, "start", staticmethod(_start_supervised_child)
    )
    monkeypatch.setattr(serve, "_watch_changes", lambda *_args: _empty_changes())

    async def recording_wait(
        futures: object, *, return_when: object
    ) -> tuple[set[object], set[object]]:
        return_whens.append(return_when)
        return await real_wait(futures, return_when=return_when)

    real_wait = asyncio.wait
    monkeypatch.setattr(serve.asyncio, "wait", recording_wait)

    assert asyncio.run(_supervise_for_test(tmp_path, 4100, 0.1, 10)) == 0

    assert return_whens == [asyncio.FIRST_COMPLETED]


async def _start_supervised_child(
    config_dir: Path, port: int, grace: float, fingerprint: str
) -> serve.ChildState:
    return cast(serve.ChildState, FakeSupervisedChild())


async def _supervise_for_test(
    config_dir: Path, port: int, grace_period_seconds: float, debounce_milliseconds: int
) -> int:
    return await asyncio.wait_for(
        serve.supervise(config_dir, port, grace_period_seconds, debounce_milliseconds),
        timeout=0.1,
    )


def test_watch_changes_caps_step_at_fifty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        serve,
        "awatch",
        lambda *_paths, **kwargs: captured.update(kwargs) or _empty_changes(),
    )

    serve._watch_changes(tmp_path, 1000)

    assert captured["step"] == 50


def test_watch_changes_uses_integer_division_for_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        serve,
        "awatch",
        lambda *_paths, **kwargs: captured.update(kwargs) or _empty_changes(),
    )

    serve._watch_changes(tmp_path, 10)

    assert captured["step"] == 1
    assert type(captured["step"]) is int
