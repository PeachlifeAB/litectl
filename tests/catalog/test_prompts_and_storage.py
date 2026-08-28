"""Prompt behaviour and atomic batch writes."""

from pathlib import Path
from typing import cast

import pytest

from litectl.modules.catalog.api.prompts import prompt_for_recovery
from litectl.modules.catalog.domain.aliases import UnavailableDefaultError
from litectl.modules.catalog.infrastructure.storage import FileStorageAdapter


def test_noninteractive_missing_default_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = UnavailableDefaultError(
        "removed-custom",
        {"cloud": "cloud-model", "speed": "fast-model", "quality": "quality-model"},
    )
    monkeypatch.setattr("litectl.modules.catalog.cli.sys.stdin.isatty", lambda: False)

    with pytest.raises(SystemExit, match="interactively"):
        prompt_for_recovery(error)


def test_batch_stages_every_file_before_replacement(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("old", encoding="utf-8")

    with pytest.raises(TypeError):
        FileStorageAdapter.write_batch({first: "new", second: cast(str, None)})

    assert first.read_text(encoding="utf-8") == "old"
    assert not second.exists()
