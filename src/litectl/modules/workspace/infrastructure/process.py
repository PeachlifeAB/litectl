"""Run external commands by absolute path.

Outbound adapter. Executables are resolved on PATH once and invoked by their
resolved absolute path: the Python docs recommend a fully qualified path for
reliability, and it removes the PATH-substitution surface bandit flags as B607.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404: this module is the subprocess boundary
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class ExecutableNotFoundError(RuntimeError):
    """Raised when a required executable is absent from PATH."""

    def __init__(self, name: str) -> None:
        super().__init__(f"required executable not found on PATH: {name}")
        self.name = name


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def resolve_executable(name: str, fallback: Path | None = None) -> Path:
    """Return the absolute path of ``name``, falling back if it is missing."""
    found = shutil.which(name)
    if found:
        return Path(found).resolve()
    if fallback is not None and fallback.exists():
        return fallback.resolve()
    raise ExecutableNotFoundError(name)


def run(
    executable: Path,
    args: Sequence[str],
    cwd: Path | None = None,
    capture: bool = True,
) -> CommandResult:
    """Run a resolved absolute executable with literal arguments.

    No shell is involved, so arguments need no quoting or escaping.
    """
    if not executable.is_absolute():
        raise ValueError(f"executable must be an absolute path: {executable}")
    completed = subprocess.run(  # nosec B603: absolute executable, no shell
        [str(executable), *args],
        capture_output=capture,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
