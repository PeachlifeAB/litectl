"""Atomic filesystem output adapter."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class FileStorageAdapter:
    @staticmethod
    def write(destination: Path, content: str) -> None:
        FileStorageAdapter.write_batch({destination: content})

    @staticmethod
    def write_batch(outputs: dict[Path, str]) -> None:
        staged: dict[Path, Path] = {}
        try:
            for destination, content in outputs.items():
                destination.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary_name = tempfile.mkstemp(
                    dir=destination.parent, prefix=f".{destination.name}.", text=True
                )
                temporary = Path(temporary_name)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(content)
                staged[destination] = temporary

            for destination, temporary in staged.items():
                os.replace(temporary, destination)
        finally:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)
