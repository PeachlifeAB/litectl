from __future__ import annotations

import stat
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from litectl.modules.workspace.infrastructure import service
from litectl.modules.workspace.infrastructure.process import CommandResult


def context(tmp_path: Path) -> service.ServiceContext:
    return service.ServiceContext(
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        home_dir=tmp_path / "home",
        uid=501,
        cli_bin="/usr/local/bin/litectl",
        environment={},
    )


def record_commands(
    monkeypatch: pytest.MonkeyPatch,
    results: dict[tuple[str, ...], int] | None = None,
) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []

    def fake_resolve(name: str, fallback: Path | None = None) -> Path:
        del fallback
        return Path("/usr/bin") / name

    def fake_run(
        executable: Path,
        args: Sequence[str],
        cwd: Path | None = None,
        capture: bool = True,
    ) -> CommandResult:
        del cwd, capture
        command = (executable.name, *args)
        commands.append(command)
        return CommandResult((results or {}).get(command, 0))

    monkeypatch.setattr(service, "resolve_executable", fake_resolve)
    monkeypatch.setattr(service, "run", fake_run)
    return commands


def record_manager(
    monkeypatch: pytest.MonkeyPatch,
    results: dict[tuple[str, ...], CommandResult] | None = None,
) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_run_manager(
        platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        del capture
        command = tuple(args)
        calls.append((platform, command))
        return (results or {}).get(command, CommandResult(0))

    monkeypatch.setattr(service, "_run_manager", fake_run_manager)
    return calls


def test_launchd_install_writes_native_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = record_commands(
        monkeypatch,
        {("launchctl", "print", "gui/501/dev.litectl.proxy"): 1},
    )

    assert service.install_service(context(tmp_path), platform="darwin")

    service_file = tmp_path / "home/Library/LaunchAgents/dev.litectl.proxy.plist"
    content = service_file.read_text(encoding="utf-8")
    assert "/usr/local/bin/litectl" in content
    assert "--watch" in content
    assert "<integer>15</integer>" in content
    assert "mise" not in content.lower()
    assert commands[-1] == (
        "launchctl",
        "bootstrap",
        "gui/501",
        str(service_file),
    )


def test_launchd_reinstall_restarts_unchanged_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    service._write_service_file(service_context, "darwin")
    commands = record_commands(monkeypatch)

    assert service.install_service(service_context, platform="darwin")
    assert commands == [
        ("launchctl", "print", "gui/501/dev.litectl.proxy"),
        (
            "launchctl",
            "kickstart",
            "-k",
            "gui/501/dev.litectl.proxy",
        ),
    ]


def test_service_file_matches_missing_identical_and_different(
    tmp_path: Path,
) -> None:
    service_context = context(tmp_path)
    destination = service.service_file(service_context, "darwin")

    assert not service._service_file_matches(service_context, "darwin")

    service._write_service_file(service_context, "darwin")
    assert service._service_file_matches(service_context, "darwin")

    destination.write_text("changed", encoding="utf-8")
    assert not service._service_file_matches(service_context, "darwin")


def test_launchd_install_retries_transient_bootstrap_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[tuple[str, ...]] = []
    bootstrap_attempts = 0

    def fake_run_manager(
        platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        nonlocal bootstrap_attempts
        del capture
        assert platform == "darwin"
        commands.append(tuple(args))
        if args[0] != "bootstrap":
            return CommandResult(0)
        bootstrap_attempts += 1
        return CommandResult(5 if bootstrap_attempts == 1 else 0)

    monkeypatch.setattr(service, "_run_manager", fake_run_manager)

    assert service.install_service(context(tmp_path), platform="darwin")
    service_file = str(tmp_path / "home/Library/LaunchAgents/dev.litectl.proxy.plist")
    bootstrap = ("bootstrap", "gui/501", service_file)
    assert commands == [
        ("print", "gui/501/dev.litectl.proxy"),
        ("bootout", "gui/501/dev.litectl.proxy"),
        bootstrap,
        bootstrap,
    ]


def test_launchd_install_reports_second_bootstrap_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap_attempts = 0

    def fake_run_manager(
        platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        nonlocal bootstrap_attempts
        del platform, capture
        if args[0] == "print":
            return CommandResult(1)
        bootstrap_attempts += 1
        return CommandResult(5, stderr="still unavailable")

    monkeypatch.setattr(service, "_run_manager", fake_run_manager)

    with pytest.raises(
        RuntimeError, match="launchd bootstrap failed: still unavailable"
    ):
        service.install_service(context(tmp_path), platform="darwin")
    assert bootstrap_attempts == 2


def test_systemd_install_writes_user_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = record_commands(monkeypatch)

    assert service.install_service(context(tmp_path), platform="linux")

    service_file = tmp_path / "home/.config/systemd/user/litectl.service"
    content = service_file.read_text(encoding="utf-8")
    assert "TimeoutStopSec=15s" in content
    assert "serve --watch" in content
    assert "mise" not in content.lower()
    assert commands[-2:] == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "litectl.service"),
    ]


def test_unsupported_platform_writes_no_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_commands(monkeypatch)

    assert not service.install_service(context(tmp_path), platform="win32")
    assert not any(tmp_path.rglob("*.service"))
    assert not any(tmp_path.rglob("*.plist"))


def test_stop_is_idempotent_when_launchd_service_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = record_commands(
        monkeypatch,
        {("launchctl", "print", "gui/501/dev.litectl.proxy"): 1},
    )

    assert service.stop_service(context(tmp_path), platform="darwin")
    assert commands == [("launchctl", "print", "gui/501/dev.litectl.proxy")]


def test_systemd_stop_and_remove_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = record_commands(monkeypatch)
    service_context = context(tmp_path)
    service_path = service.service_file(service_context, "linux")
    service_path.parent.mkdir(parents=True)
    service_path.write_text("unit", encoding="utf-8")

    assert service.stop_service(service_context, platform="linux")
    assert service.remove_service(service_context, platform="linux")

    assert not service_path.exists()
    assert ("systemctl", "--user", "stop", "litectl.service") in commands
    assert commands[-1] == ("systemctl", "--user", "daemon-reload")


def test_logs_stream_from_xdg_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = record_commands(monkeypatch)
    service_context = context(tmp_path)

    assert service.stream_logs(service_context) == 0

    assert commands == [
        (
            "tail",
            "-F",
            "-n",
            "50",
            str(service_context.state_dir / "proxy.log"),
        )
    ]


def test_start_service_reconciles_before_native_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    service_context = context(tmp_path)

    monkeypatch.setattr(service, "service_running", lambda *_args: False)

    def run_manager(
        _platform: str, _args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        del capture
        events.append("start")
        return CommandResult(0)

    monkeypatch.setattr(service, "_run_manager", run_manager)

    def reconcile() -> list[str]:
        events.append("reconcile")
        return ["removed omlx-old"]

    assert service.start_service(
        service_context,
        platform="linux",
        reconcile=reconcile,
    )
    assert events == ["reconcile", "start"]
    assert "removed omlx-old" in capsys.readouterr().out


def test_service_file_uses_xdg_config_home(tmp_path: Path) -> None:
    service_context = replace(
        context(tmp_path),
        environment={"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
    )

    assert service.service_file(service_context, "linux") == (
        tmp_path / "xdg/systemd/user/litectl.service"
    )


def test_run_manager_preserves_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[Path, tuple[str, ...], bool]] = []

    def fake_resolve(name: str, fallback: Path | None = None) -> Path:
        del fallback
        return Path("/usr/bin") / name

    def fake_run(
        executable: Path,
        args: Sequence[str],
        cwd: Path | None = None,
        capture: bool = True,
    ) -> CommandResult:
        del cwd
        seen.append((executable, tuple(args), capture))
        return CommandResult(0)

    monkeypatch.setattr(service, "resolve_executable", fake_resolve)
    monkeypatch.setattr(service, "run", fake_run)

    assert service._run_manager("linux", ("status",), capture=False).ok
    assert seen == [(Path("/usr/bin/systemctl"), ("status",), False)]


def test_write_service_file_creates_nested_paths_and_mode(tmp_path: Path) -> None:
    service_context = replace(
        context(tmp_path),
        state_dir=tmp_path / "nested/state",
        home_dir=tmp_path / "nested/home",
    )

    destination = service._write_service_file(service_context, "linux")

    assert destination.is_file()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert all(
        (service_context.state_dir / name).is_file() for name in service.LOG_NAMES
    )


def test_service_file_matches_reads_utf8_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    destination = service._write_service_file(service_context, "darwin")
    encodings: list[str | None] = []
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == destination:
            encodings.append(kwargs.get("encoding"))  # type: ignore[arg-type]
        return original_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", read_text)

    assert service._service_file_matches(service_context, "darwin")
    assert encodings == ["utf-8"]


def test_service_running_checks_linux_and_rejects_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def run_manager(
        platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        del capture
        calls.append((platform, tuple(args)))
        return CommandResult(0)

    monkeypatch.setattr(service, "_run_manager", run_manager)
    service_context = context(tmp_path)

    assert service.service_running(service_context, "linux")
    assert not service.service_running(service_context, "win32")
    assert calls == [("linux", ("--user", "is-active", "--quiet", "litectl.service"))]


def test_start_service_returns_when_already_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    calls: list[tuple[object, object]] = []

    def running(current: service.ServiceContext, platform: str) -> bool:
        calls.append((current, platform))
        return True

    monkeypatch.setattr(service, "service_running", running)
    monkeypatch.setattr(
        service,
        "_run_manager",
        lambda *_args: pytest.fail("running service must not start"),
    )

    assert service.start_service(service_context, platform="linux")
    assert calls == [(service_context, "linux")]


def test_start_service_bootstraps_darwin_and_rejects_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    bootstrapped: list[tuple[service.ServiceContext, Path]] = []

    monkeypatch.setattr(service, "service_running", lambda *_args: False)
    monkeypatch.setattr(
        service,
        "_bootstrap_launchd",
        lambda current, destination: bootstrapped.append((current, destination)),
    )

    assert service.start_service(service_context, platform="darwin")
    assert not service.start_service(service_context, platform="win32")
    assert bootstrapped == [
        (service_context, service.service_file(service_context, "darwin"))
    ]


def test_start_service_reports_systemd_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_manager(
        monkeypatch,
        {
            (
                "--user",
                "start",
                "litectl.service",
            ): CommandResult(5, stderr="denied")
        },
    )
    monkeypatch.setattr(service, "service_running", lambda *_args: False)

    with pytest.raises(RuntimeError, match="systemd start failed: denied"):
        service.start_service(context(tmp_path), platform="linux")
    assert calls == [("linux", ("--user", "start", "litectl.service"))]


def test_launchd_reinstall_reports_restart_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    service._write_service_file(service_context, "darwin")

    def run_manager(
        _platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        del capture
        if args[0] == "print":
            return CommandResult(0)
        return CommandResult(5, stderr="denied")

    monkeypatch.setattr(service, "_run_manager", run_manager)

    with pytest.raises(RuntimeError, match="launchd restart failed: denied"):
        service.install_service(service_context, platform="darwin")


def test_systemd_install_reports_each_manager_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_manager(
        monkeypatch,
        {
            ("--user", "daemon-reload"): CommandResult(0),
            ("--user", "enable", "--now", "litectl.service"): CommandResult(
                5, stderr="denied"
            ),
        },
    )

    with pytest.raises(RuntimeError, match="systemd enable failed: denied"):
        service.install_service(context(tmp_path), platform="linux")
    assert calls == [
        ("linux", ("--user", "daemon-reload")),
        ("linux", ("--user", "enable", "--now", "litectl.service")),
    ]


def test_stop_service_reports_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = record_manager(
        monkeypatch,
        {
            (
                "--user",
                "stop",
                "litectl.service",
            ): CommandResult(5, stderr="denied")
        },
    )
    monkeypatch.setattr(service, "service_running", lambda *_args: True)

    with pytest.raises(RuntimeError, match="service stop failed: denied"):
        service.stop_service(context(tmp_path), platform="linux")
    assert calls == [("linux", ("--user", "stop", "litectl.service"))]


def test_remove_service_allows_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    stopped: list[tuple[service.ServiceContext, str]] = []
    calls = record_manager(monkeypatch)

    def stop(current: service.ServiceContext, platform: str) -> bool:
        stopped.append((current, platform))
        return True

    paths: list[tuple[service.ServiceContext, str]] = []

    def service_path(current: service.ServiceContext, platform: str) -> Path:
        paths.append((current, platform))
        return tmp_path / "missing.service"

    monkeypatch.setattr(service, "service_file", service_path)
    monkeypatch.setattr(service, "stop_service", stop)

    assert service.remove_service(service_context, platform="linux")
    assert stopped == [(service_context, "linux")]
    assert calls == [("linux", ("--user", "daemon-reload"))]
    assert paths == [(service_context, "linux")]


def test_stream_logs_creates_nested_state_and_disables_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = replace(context(tmp_path), state_dir=tmp_path / "nested/state")
    seen: list[tuple[Path, tuple[str, ...], bool]] = []

    monkeypatch.setattr(
        service,
        "resolve_executable",
        lambda name: Path("/usr/bin") / name,
    )

    def fake_run(
        executable: Path,
        args: Sequence[str],
        cwd: Path | None = None,
        capture: bool = True,
    ) -> CommandResult:
        del cwd
        seen.append((executable, tuple(args), capture))
        return CommandResult(0)

    monkeypatch.setattr(service, "run", fake_run)

    assert service.stream_logs(service_context) == 0
    assert seen == [
        (
            Path("/usr/bin/tail"),
            ("-F", "-n", "50", str(service_context.state_dir / "proxy.log")),
            False,
        )
    ]


def test_unsupported_message_is_exact() -> None:
    assert service.unsupported_message() == (
        "Native services support macOS launchd and Linux systemd user services; "
        "use `litectl serve` on this platform."
    )


def test_service_file_defaults_to_home_config(tmp_path: Path) -> None:
    service_context = context(tmp_path)

    assert service.service_file(service_context, "linux") == (
        tmp_path / "home/.config/systemd/user/litectl.service"
    )


def test_run_manager_defaults_to_captured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captures: list[bool] = []

    monkeypatch.setattr(
        service,
        "resolve_executable",
        lambda name: Path("/usr/bin") / name,
    )

    def fake_run(
        _executable: Path,
        _args: Sequence[str],
        cwd: Path | None = None,
        capture: bool = True,
    ) -> CommandResult:
        del cwd
        captures.append(capture)
        return CommandResult(0)

    monkeypatch.setattr(service, "run", fake_run)

    assert service._run_manager("linux", ("status",)).ok
    assert captures == [True]


def test_render_template_uses_utf8_and_path_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResource:
        parts: tuple[str, ...] | None = None
        encoding: str | None = None

        def joinpath(self, *parts: str) -> FakeResource:
            self.parts = parts
            return self

        def read_text(self, *, encoding: str) -> str:
            self.encoding = encoding
            return "@@cli_bin@@|@@config_dir@@|@@state_dir@@"

    resource = FakeResource()
    monkeypatch.setattr(service, "files", lambda _package: resource)

    service_context = service.ServiceContext(
        config_dir=Path("/config"),
        state_dir=Path("/state"),
        home_dir=Path("/home"),
        uid=501,
        cli_bin="/bin/a&debug",
        environment={},
    )
    rendered = service._render_template(service_context, "linux")
    rendered_darwin = service._render_template(service_context, "darwin")

    assert resource.parts == ("services", "dev.litectl.proxy.plist.in")
    assert resource.encoding == "utf-8"
    assert rendered == "/bin/a&debug|/config|/state"
    assert rendered_darwin == "/bin/a&amp;debug|/config|/state"


def test_write_service_file_uses_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    encodings: list[object] = []
    original_write_text = Path.write_text

    def write_text(path: Path, data: str, *args: object, **kwargs: object) -> int:
        if path.name == service.SYSTEMD_UNIT:
            encodings.append(kwargs.get("encoding"))
        return original_write_text(path, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", write_text)

    service._write_service_file(service_context, "linux")
    assert encodings == ["utf-8"]


def test_install_service_passes_platform_to_running_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    service._write_service_file(service_context, "darwin")
    calls: list[tuple[service.ServiceContext, str]] = []

    def running(current: service.ServiceContext, platform: str) -> bool:
        calls.append((current, platform))
        return False

    monkeypatch.setattr(service, "service_running", running)
    monkeypatch.setattr(
        service,
        "_bootstrap_launchd",
        lambda *_args: None,
    )

    assert service.install_service(service_context, platform="darwin")
    assert calls == [(service_context, "darwin")]


def test_launchd_install_reports_bootout_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = context(tmp_path)
    service._write_service_file(original, "darwin")
    changed = replace(original, cli_bin="/different/litectl")

    def run_manager(
        _platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        del capture
        if args[0] == "print":
            return CommandResult(0)
        return CommandResult(5, stderr="denied")

    monkeypatch.setattr(service, "_run_manager", run_manager)

    with pytest.raises(RuntimeError, match="launchd bootout failed: denied"):
        service.install_service(changed, platform="darwin")


def test_systemd_install_reports_reload_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def run_manager(
        platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        del capture
        calls.append((platform, tuple(args)))
        return CommandResult(5, stderr="denied")

    monkeypatch.setattr(service, "_run_manager", run_manager)

    with pytest.raises(RuntimeError, match="systemd daemon-reload failed: denied"):
        service.install_service(context(tmp_path), platform="linux")
    assert calls == [("linux", ("--user", "daemon-reload"))]


def test_stop_service_uses_launchd_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def running(current: service.ServiceContext, platform: str) -> bool:
        assert current == context_value
        assert platform == "darwin"
        return True

    def run_manager(
        platform: str, args: Sequence[str], capture: bool = True
    ) -> CommandResult:
        del capture
        calls.append((platform, tuple(args)))
        return CommandResult(0)

    context_value = context(tmp_path)
    monkeypatch.setattr(service, "service_running", running)
    monkeypatch.setattr(service, "_run_manager", run_manager)

    assert service.stop_service(context_value, platform="darwin")
    assert calls == [("darwin", ("bootout", "gui/501/dev.litectl.proxy"))]


def test_stop_and_remove_reject_unsupported_platform(tmp_path: Path) -> None:
    service_context = context(tmp_path)

    assert not service.stop_service(service_context, platform="win32")
    assert not service.remove_service(service_context, platform="win32")


def test_remove_service_reports_reload_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = context(tmp_path)
    monkeypatch.setattr(service, "stop_service", lambda *_args: True)
    monkeypatch.setattr(
        service,
        "_run_manager",
        lambda *_args: CommandResult(5, stderr="denied"),
    )

    with pytest.raises(RuntimeError, match="systemd daemon-reload failed: denied"):
        service.remove_service(service_context, platform="linux")


def test_stream_logs_is_idempotent_for_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_context = replace(context(tmp_path), state_dir=tmp_path / "state")
    service_context.state_dir.mkdir()
    monkeypatch.setattr(
        service,
        "resolve_executable",
        lambda name: Path("/usr/bin") / name,
    )
    monkeypatch.setattr(
        service,
        "run",
        lambda *_args, **_kwargs: CommandResult(0),
    )

    assert service.stream_logs(service_context) == 0
