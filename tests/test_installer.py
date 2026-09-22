from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404: test invokes resolved bash
import sys
from pathlib import Path


def executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o755)  # nosec B103: test-only executable fixture


def test_installer_uses_uv_without_mise(tmp_path: Path, project_root: Path) -> None:
    bash = shutil.which("bash")
    assert bash is not None
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "args"
    executable(
        fake_bin / "uv",
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:3] == ['tool', 'install', '--force']:\n"
        "    raise SystemExit(0)\n"
        "if args == ['tool', 'dir', '--bin']:\n"
        "    print(os.environ['FAKE_BIN'])\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(2)\n",
    )
    executable(
        fake_bin / "litectl",
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "path = pathlib.Path(os.environ['CAPTURE'])\n"
        "with path.open('a', encoding='utf-8') as stream:\n"
        "    stream.write(' '.join(sys.argv[1:]) + '\\n')\n",
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "FAKE_BIN": str(fake_bin),
        "CAPTURE": str(capture),
    }

    subprocess.run(  # nosec B603: resolved bash executes repository installer
        [bash, "install.sh"],
        check=True,
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert capture.read_text(encoding="utf-8") == (
        f"install {tmp_path / 'config/litectl'}\n"
        f"--config-dir {tmp_path / 'config/litectl'} update all --yes\n"
    )
