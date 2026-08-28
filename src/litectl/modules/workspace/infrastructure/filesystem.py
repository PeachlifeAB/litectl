"""Install explicit package resources; never copy source into user config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib.resources.abc import Traversable
from pathlib import Path

from litectl.modules.workspace.domain.manifest import MANIFEST

PLACEHOLDER = "@@{name}@@"


@dataclass(frozen=True)
class WriteReport:
    written: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return len(self.written) + len(self.preserved)


def render(text: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        text = text.replace(PLACEHOLDER.format(name=name), value)
    return text


def install(
    resource_root: Traversable, target_dir: Path, values: dict[str, str]
) -> WriteReport:
    written: list[str] = []
    preserved: list[str] = []

    for entry in MANIFEST:
        destination = target_dir / entry.target
        if destination.exists():
            preserved.append(entry.target)
            continue

        text = resource_root.joinpath(*entry.source.split("/")).read_text(
            encoding="utf-8"
        )
        if entry.interpolate:
            text = render(text, values)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        if entry.target == "config.yaml":
            os.chmod(destination, 0o600)
        written.append(entry.target)

    return WriteReport(tuple(written), tuple(preserved))
