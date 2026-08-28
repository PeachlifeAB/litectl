from pathlib import Path

from litectl.app.paths import config_dir, state_dir


def test_xdg_config_home_is_used(tmp_path: Path) -> None:
    assert config_dir(environment={"XDG_CONFIG_HOME": str(tmp_path)}) == (
        tmp_path / "litectl"
    )


def test_config_falls_back_to_home(tmp_path: Path) -> None:
    assert config_dir(environment={}, home_dir=tmp_path) == (
        tmp_path / ".config/litectl"
    )


def test_explicit_config_directory_wins(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    assert (
        config_dir(
            str(explicit),
            environment={"XDG_CONFIG_HOME": str(tmp_path / "ignored")},
        )
        == explicit
    )


def test_config_file_environment_selects_its_parent(tmp_path: Path) -> None:
    config_file = tmp_path / "custom/config.yaml"
    assert config_dir(environment={"CONFIG_FILE_PATH": str(config_file)}) == (
        config_file.parent
    )


def test_xdg_state_home_is_used(tmp_path: Path) -> None:
    assert state_dir(environment={"XDG_STATE_HOME": str(tmp_path)}) == (
        tmp_path / "litectl"
    )
