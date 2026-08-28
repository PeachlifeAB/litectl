"""Provider environment configuration adapter.

The registry is pure data: name -> (base env, key env, hosted default base).
A hosted default is provider-owned truth (a stable public endpoint); local
servers have none — their base is a user property, never code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROVIDER_SPECS: dict[str, tuple[str, str, str | None]] = {
    "omlx": ("OMLX_API_BASE", "OMLX_API_KEY", None),
    "cerebras": ("CEREBRAS_API_BASE", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1"),
    "ollama": ("OLLAMA_API_BASE", "OLLAMA_API_KEY", None),
    "llama-cpp": ("LLAMA_CPP_API_BASE", "LLAMA_CPP_API_KEY", None),
    "lmstudio": ("LMSTUDIO_API_BASE", "LMSTUDIO_API_KEY", None),
    "ds4": ("DS4_API_BASE", "DS4_API_KEY", None),
}


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path
    providers_dir: Path

    @classmethod
    def from_env(cls, base_dir: Path) -> AppConfig:
        return cls(base_dir=base_dir, providers_dir=base_dir / "providers")

    def api_base(self, name: str) -> str | None:
        base_env, _, default = PROVIDER_SPECS[name]
        return os.environ.get(base_env) or default

    def api_key(self, name: str) -> str | None:
        _, key_env, _ = PROVIDER_SPECS[name]
        return os.environ.get(key_env) or None
