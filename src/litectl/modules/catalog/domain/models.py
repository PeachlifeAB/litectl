"""Pure model classification, ranking, and discovery reconciliation."""

from __future__ import annotations

import re
from dataclasses import dataclass

SPEED_MIN_BILLIONS = 2.0
SPEED_MAX_BILLIONS = 9.0
PARAMETER_BILLIONS_PATTERN = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)b(?=$|[-_.])", re.IGNORECASE
)
EXCLUDED_SUBSTRINGS = (
    "-tts",
    "tts",
    "whisper",
    "asr",
    "embed",
    "embedding",
    "rerank",
    "reranker",
    "parakeet",
    "fish-audio",
    "markitdown",
    "bge-",
    "nomic",
    "gte-",
    "e5-",
    "minilm",
    "sam3",
    "sam2",
    "segment-anything",
    "stable-diffusion",
    "flux",
    "sdxl",
)


@dataclass(frozen=True)
class ModelDescriptor:
    raw_id: str
    max_model_len: int | None = None

    def is_chat_model(self) -> bool:
        lower = self.raw_id.lower()
        return not any(pattern in lower for pattern in EXCLUDED_SUBSTRINGS)

    def parameter_billions(self) -> float | None:
        match = PARAMETER_BILLIONS_PATTERN.search(self.raw_id)
        return float(match.group(1)) if match else None

    def to_alias(self, prefix: str) -> str:
        clean = self.raw_id.lower()
        clean = clean.removeprefix("meta-")
        clean = clean.removesuffix("-mlx")
        clean = clean.removesuffix("-instruct")
        return f"{prefix}-{clean}"


def rank_local_chat_models(models: list[ModelDescriptor]) -> list[ModelDescriptor]:
    """Prefer balanced local models, then larger models, then tiny/unknown ones."""
    chat_models = [model for model in models if model.is_chat_model()]

    def rank(item: tuple[int, ModelDescriptor]) -> tuple[int, float, int]:
        index, model = item
        size = model.parameter_billions()
        if size is None:
            return 3, float("inf"), index
        if SPEED_MIN_BILLIONS <= size <= SPEED_MAX_BILLIONS:
            return 0, size, index
        if size > SPEED_MAX_BILLIONS:
            return 1, size, index
        return 2, size, index

    return [model for _, model in sorted(enumerate(chat_models), key=rank)]


def select_speed_model(models: list[ModelDescriptor]) -> ModelDescriptor | None:
    ranked = rank_local_chat_models(models)
    return ranked[0] if ranked else None


def select_quality_model(models: list[ModelDescriptor]) -> ModelDescriptor | None:
    chat_models = [model for model in models if model.is_chat_model()]
    sized = [model for model in chat_models if model.parameter_billions() is not None]
    if sized:
        return max(sized, key=lambda model: model.parameter_billions() or 0.0)
    return chat_models[0] if chat_models else None


def reconcile_fallback_aliases(
    discovered: list[str],
    previous_chain: list[str] | None,
    previous_discovered: list[str],
) -> tuple[list[str], list[str]]:
    """Reconcile recorded aliases with what discovery just returned.

    Preserves user order and exclusions, dropping aliases that have vanished
    and appending newly discovered ones.
    """
    if previous_chain is None:
        return list(discovered), []

    previous_set = set(previous_discovered)
    discovered_set = set(discovered)
    removed = [
        alias
        for alias in previous_chain
        if alias in previous_set and alias not in discovered_set
    ]
    if previous_chain == previous_discovered:
        return list(discovered), removed

    kept = [
        alias
        for alias in previous_chain
        if alias not in previous_set or alias in discovered_set
    ]
    kept.extend(
        alias for alias in discovered if alias not in previous_set and alias not in kept
    )
    return kept, removed


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    api_base: str | None
    api_key_env_var: str
