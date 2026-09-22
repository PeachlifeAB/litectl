"""The exact package resources installed as user configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    source: str
    target: str
    interpolate: bool = False


MANIFEST: tuple[Entry, ...] = (
    Entry("config.yaml", "config.yaml", interpolate=True),
    Entry("litectl_hooks.py", "litectl_hooks.py"),
    Entry(
        "providers/cerebras/models.yaml",
        "providers/cerebras/models.yaml",
    ),
    Entry(
        "providers/ds4/models.yaml",
        "providers/ds4/models.yaml",
    ),
    Entry(
        "providers/llama-cpp/models.yaml",
        "providers/llama-cpp/models.yaml",
    ),
    Entry(
        "providers/lmstudio/models.yaml",
        "providers/lmstudio/models.yaml",
    ),
    Entry(
        "providers/omlx/models.yaml",
        "providers/omlx/models.yaml",
    ),
    Entry(
        "providers/ollama/models.yaml",
        "providers/ollama/models.yaml",
    ),
)
