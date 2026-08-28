from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404: test invokes the resolved uv executable
import zipfile
from importlib.resources import files
from pathlib import Path

import yaml

from litectl.modules.workspace.infrastructure.filesystem import install

RESOURCE_PACKAGE = "litectl.resources"
RUNTIME_FILES = {
    "config.yaml",
    "providers/cerebras/models.yaml",
    "providers/ds4/models.yaml",
    "providers/llama-cpp/models.yaml",
    "providers/lmstudio/models.yaml",
    "providers/omlx/models.yaml",
    "providers/ollama/models.yaml",
}
SERVICE_RESOURCES = {
    "litectl/resources/services/dev.litectl.proxy.plist.in",
    "litectl/resources/services/litectl.service.in",
}


def template_values() -> dict[str, str]:
    return {
        "master_key": "master-key",
        "port": "4000",
        "omlx_base": "http://127.0.0.1:8008/v1",
        "omlx_key": "local-key",
        "cerebras_base": "https://api.cerebras.ai/v1",
        "cerebras_key": "",
    }


def installed_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


def test_install_writes_only_runtime_configuration(tmp_path: Path) -> None:
    report = install(files(RESOURCE_PACKAGE), tmp_path, template_values())

    assert installed_files(tmp_path) == RUNTIME_FILES
    assert set(report.written) == RUNTIME_FILES
    config_path = tmp_path / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["environment_variables"] == {
        "LITELLM_MASTER_KEY": "master-key",
        "LITELLM_PORT": "4000",
        "OMLX_API_BASE": "http://127.0.0.1:8008/v1",
        "OMLX_API_KEY": "local-key",
        "CEREBRAS_API_BASE": "https://api.cerebras.ai/v1",
        "CEREBRAS_API_KEY": "",
    }
    assert os.stat(config_path).st_mode & 0o777 == 0o600


def test_reinstall_preserves_user_state(tmp_path: Path) -> None:
    values = template_values()
    install(files(RESOURCE_PACKAGE), tmp_path, values)
    config = tmp_path / "config.yaml"
    config.write_text("user: config\n", encoding="utf-8")

    report = install(files(RESOURCE_PACKAGE), tmp_path, values)

    assert config.read_text(encoding="utf-8") == "user: config\n"
    assert "config.yaml" in report.preserved


def test_wheel_contains_package_and_resources_only(
    tmp_path: Path, project_root: Path
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    subprocess.run(  # nosec B603: uv is resolved on PATH; arguments are literals
        [uv, "build", "--wheel", "--out-dir", str(tmp_path)],
        check=True,
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points = archive.read(
            next(name for name in names if name.endswith("entry_points.txt"))
        ).decode()

    assert "litectl/__init__.py" in names
    assert "litectl/resources/config.yaml" in names
    assert SERVICE_RESOURCES <= names
    assert "litectl/resources/mise.toml.in" not in names
    assert "litectl = litectl:main" in entry_points
    assert not any(
        name.startswith(("app/", "modules/", "tasks/", "tests/")) for name in names
    )
