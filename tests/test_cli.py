from __future__ import annotations

from pathlib import Path

import pytest

from litectl.app import cli


@pytest.mark.parametrize(
    "command",
    [
        "install",
        "start",
        "stop",
        "status",
        "logs",
        "list",
        "update",
        "serve",
        "teardown",
    ],
)
def test_parser_exposes_direct_command(command: str) -> None:
    args = cli.parser().parse_args([command])

    assert args.command == command


def test_status_reports_running_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "service_running", lambda context: True)

    result = cli.main(["--config-dir", str(tmp_path), "status"])

    assert result == 0
    assert "running" in capsys.readouterr().out.lower()


def test_unsupported_start_points_to_foreground_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "start_service", lambda context: False)

    result = cli.main(["--config-dir", str(tmp_path), "start"])

    assert result == 1
    assert "litectl serve" in capsys.readouterr().err


def test_serve_watch_options_are_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[tuple[Path, int | None, bool, float, int]] = []

    def fake_serve(
        base: Path, port: int | None, watch: bool, grace: float, debounce: int
    ) -> int:
        received.append((base, port, watch, grace, debounce))
        return 0

    monkeypatch.setattr(cli, "serve", fake_serve)

    result = cli.main(
        [
            "--config-dir",
            str(tmp_path),
            "serve",
            "--watch",
            "--port",
            "4100",
            "--shutdown-grace-period-seconds",
            "7",
            "--debounce-milliseconds",
            "250",
        ]
    )

    assert result == 0
    assert received == [(tmp_path, 4100, True, 7.0, 250)]
