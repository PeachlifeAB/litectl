from __future__ import annotations

from collections.abc import Sequence
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
