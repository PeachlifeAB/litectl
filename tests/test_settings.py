from __future__ import annotations

from pathlib import Path

from litectl.modules.workspace.infrastructure.keys import resolve_setting


def write_config(path: Path, value: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.yaml").write_text(
        f'environment_variables:\n  OMLX_API_KEY: "{value}"\n',
        encoding="utf-8",
    )


def test_setting_reads_config_environment_variables(tmp_path: Path) -> None:
    write_config(tmp_path, "saved-key")

    assert resolve_setting(tmp_path, "OMLX_API_KEY", environment={}) == "saved-key"


def test_process_environment_overrides_saved_setting(tmp_path: Path) -> None:
    write_config(tmp_path, "saved-key")

    assert (
        resolve_setting(
            tmp_path,
            "OMLX_API_KEY",
            environment={"OMLX_API_KEY": "runtime-key"},
        )
        == "runtime-key"
    )
