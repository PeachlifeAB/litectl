from __future__ import annotations

from pathlib import Path

import pytest

from litectl.app import install
from litectl.modules.workspace.domain.settings import Settings


def test_install_never_prints_resolved_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        master_key="private-master-key",
        omlx_base="http://127.0.0.1:8008/v1",
        omlx_key="private-local-key",
        cerebras_base="https://api.cerebras.ai/v1",
    )
    monkeypatch.setattr(install, "resolve", lambda *_args: settings)
    monkeypatch.setattr("litectl.app.install.catalog.main", lambda *_args: 0)
    monkeypatch.setattr(install, "initialize", lambda _context: False)

    result = install.run(
        tmp_path / "config",
        tmp_path / "state",
        tmp_path / "home",
        interactive=False,
    )

    output = capsys.readouterr().out
    assert result == 0
    assert settings.master_key not in output
    assert settings.omlx_key not in output
    assert "litectl serve" in output
