"""Manage native launchd and systemd user services."""

from __future__ import annotations

import html
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from litectl.modules.workspace.infrastructure.process import (
    CommandResult,
    resolve_executable,
    run,
)
from litectl.resources import SERVICE_TEMPLATES

LAUNCHD_LABEL = "dev.litectl.proxy"
SYSTEMD_UNIT = "litectl.service"
RESOURCE_PACKAGE = "litectl.resources"
LOG_NAMES = ("proxy.log", "proxy.err.log")
SUPPORTED_PLATFORMS = ("darwin", "linux")


@dataclass(frozen=True)
class ServiceContext:
    config_dir: Path
    state_dir: Path
    home_dir: Path
    uid: int
    cli_bin: str
    environment: Mapping[str, str]


def launchd_target(uid: int) -> str:
    return f"gui/{uid}/{LAUNCHD_LABEL}"


def service_file(context: ServiceContext, platform: str) -> Path:
    if platform == "darwin":
        return context.home_dir / f"Library/LaunchAgents/{LAUNCHD_LABEL}.plist"
    config_home = context.environment.get("XDG_CONFIG_HOME")
    root = Path(config_home) if config_home else context.home_dir / ".config"
    return root / "systemd/user" / SYSTEMD_UNIT


def _manager(platform: str) -> Path:
    name = "launchctl" if platform == "darwin" else "systemctl"
    return resolve_executable(name)


def _run_manager(
    platform: str, args: Sequence[str], capture: bool = True
) -> CommandResult:
    return run(_manager(platform), args, capture=capture)


def _render_template(context: ServiceContext, platform: str) -> str:
    resource = SERVICE_TEMPLATES[platform]
    text = (
        files(RESOURCE_PACKAGE)
        .joinpath(*resource.split("/"))
        .read_text(encoding="utf-8")
    )
    values = {
        "cli_bin": context.cli_bin,
        "config_dir": str(context.config_dir),
        "state_dir": str(context.state_dir),
    }
    if platform == "darwin":
        values = {name: html.escape(value) for name, value in values.items()}
    for name, value in values.items():
        text = text.replace(f"@@{name}@@", value)
    return text


def _service_file_matches(context: ServiceContext, platform: str) -> bool:
    destination = service_file(context, platform)
    return destination.is_file() and destination.read_text(  # pragma: no mutate
        encoding="utf-8"  # pragma: no mutate
    ) == _render_template(context, platform)


def _write_service_file(context: ServiceContext, platform: str) -> Path:
    context.state_dir.mkdir(parents=True, exist_ok=True)
    for name in LOG_NAMES:
        (context.state_dir / name).touch()
    destination = service_file(context, platform)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_render_template(context, platform), encoding="utf-8")
    os.chmod(destination, 0o600)
    return destination


def service_running(context: ServiceContext, platform: str = sys.platform) -> bool:
    if platform == "darwin":
        return _run_manager(platform, ("print", launchd_target(context.uid))).ok
    if platform == "linux":
        return _run_manager(
            platform, ("--user", "is-active", "--quiet", SYSTEMD_UNIT)
        ).ok
    return False


def _require(result: CommandResult, action: str) -> None:
    if not result.ok:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"{action} failed: {detail}")


def _bootstrap_launchd(context: ServiceContext, destination: Path) -> None:
    """Retry once when launchd is still completing a previous bootout."""
    args = ("bootstrap", f"gui/{context.uid}", str(destination))
    result = _run_manager("darwin", args)
    if not result.ok:
        result = _run_manager("darwin", args)
    _require(result, "launchd bootstrap")


def install_service(context: ServiceContext, platform: str = sys.platform) -> bool:
    if platform not in SUPPORTED_PLATFORMS:
        return False
    unchanged = _service_file_matches(context, platform)
    destination = _write_service_file(context, platform)
    if platform == "darwin":
        target = launchd_target(context.uid)
        if service_running(context, platform):
            if unchanged:
                _require(
                    _run_manager(platform, ("kickstart", "-k", target)),
                    "launchd restart",
                )
                return True
            _require(
                _run_manager(platform, ("bootout", target)),
                "launchd bootout",
            )
        _bootstrap_launchd(context, destination)
        return True
    _require(
        _run_manager(platform, ("--user", "daemon-reload")),
        "systemd daemon-reload",
    )
    _require(
        _run_manager(platform, ("--user", "enable", "--now", SYSTEMD_UNIT)),
        "systemd enable",
    )
    return True


def start_service(context: ServiceContext, platform: str = sys.platform) -> bool:
    if platform not in SUPPORTED_PLATFORMS:
        return False
    if service_running(context, platform):
        return True
    if platform == "darwin":
        destination = service_file(context, platform)
        _bootstrap_launchd(context, destination)
        return True
    _require(
        _run_manager(platform, ("--user", "start", SYSTEMD_UNIT)),
        "systemd start",
    )
    return True


def stop_service(context: ServiceContext, platform: str = sys.platform) -> bool:
    if platform not in SUPPORTED_PLATFORMS:
        return False
    if not service_running(context, platform):
        return True
    if platform == "darwin":
        result = _run_manager(platform, ("bootout", launchd_target(context.uid)))
    else:
        result = _run_manager(platform, ("--user", "stop", SYSTEMD_UNIT))
    _require(result, "service stop")
    return True


def remove_service(context: ServiceContext, platform: str = sys.platform) -> bool:
    if platform not in SUPPORTED_PLATFORMS:
        return False
    stop_service(context, platform)
    service_file(context, platform).unlink(missing_ok=True)
    if platform == "linux":
        _require(
            _run_manager(platform, ("--user", "daemon-reload")),
            "systemd daemon-reload",
        )
    return True


def stream_logs(context: ServiceContext) -> int:
    context.state_dir.mkdir(parents=True, exist_ok=True)
    log_path = context.state_dir / LOG_NAMES[0]
    log_path.touch()
    result = run(
        resolve_executable("tail"),
        ("-F", "-n", "50", str(log_path)),
        capture=False,
    )
    return result.returncode


def unsupported_message() -> str:
    return (
        "Native services support macOS launchd and Linux systemd user services; "
        "use `litectl serve` on this platform."
    )
