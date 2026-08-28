"""Resolve which model each alias preset points at.

Pure: decides targets and warnings from plain values. Anchor identity is what
produces `*alias` output on dump, so anchoring stays in the infrastructure
layer and this module reads mappings and returns strings only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from litectl.modules.catalog.domain.models import (
    ModelDescriptor,
    rank_local_chat_models,
    select_quality_model,
    select_speed_model,
)

PRESET_KEYS = {
    "cloud": "default_cloud",
    "speed": "default_speed",
    "quality": "default_quality",
}
PRESET_ANCHORS = {"cloud": "cloud", "speed": "speed", "quality": "quality"}
PRESETS = ("cloud", "speed", "quality")
SPEED = "speed"
DEFAULT_KEY = "default"
CLOUD_KEY = PRESET_KEYS["cloud"]


class UnavailableDefaultError(ValueError):
    """The active default names a model no provider offers any more."""

    def __init__(self, model: str, targets: dict[str, str]) -> None:
        super().__init__(model)
        self.model = model
        self.targets = targets


@dataclass(frozen=True)
class Discovery:
    """What discovery found, and what the workspace already recorded."""

    models: list[ModelDescriptor]
    provider_prefix: str
    previous_discovered: list[str]
    available_aliases: set[str] = field(default_factory=set)

    def discovered_aliases(self) -> list[str]:
        """Discovered chat models as aliases, smallest first."""
        return [
            model.to_alias(self.provider_prefix)
            for model in rank_local_chat_models(self.models)
        ]

    def candidate_for(self, preset: str, fallback: str) -> str:
        """Best discovered model for a preset, or ``fallback`` if none fits."""
        chooser = select_speed_model if preset == SPEED else select_quality_model
        model = chooser(self.models)
        return model.to_alias(self.provider_prefix) if model else fallback


def selected_preset(aliases: Mapping[str, object]) -> str | None:
    """Which preset the active default currently points at, if any.

    Identity is checked first: a round-tripped config aliases the very same
    anchored scalar, and that identity is what dumps as `*alias`. Equality is
    the fallback for a config written by hand.
    """
    active = aliases.get(DEFAULT_KEY)
    for preset, key in PRESET_KEYS.items():
        if key in aliases and active is aliases[key]:
            return preset
    for preset, key in PRESET_KEYS.items():
        if key in aliases and active == aliases[key]:
            return preset
    return None


def cloud_target(aliases: Mapping[str, object]) -> str:
    """The cloud model, falling back to the active default on older configs."""
    cloud = aliases.get(CLOUD_KEY)
    if cloud is not None:
        return str(cloud)
    active = aliases.get(DEFAULT_KEY)
    if active is None:
        raise ValueError("model_group_alias.default is required")
    return str(active)


def resolve_targets(
    aliases: Mapping[str, object], discovery: Discovery
) -> tuple[dict[str, str], list[str]]:
    """Decide each preset's target, keeping any still-valid existing choice."""
    cloud = cloud_target(aliases)
    targets = {"cloud": cloud}
    warnings: list[str] = []

    for preset in ("speed", "quality"):
        current = aliases.get(PRESET_KEYS[preset])
        current_target = str(current) if current is not None else None
        target = (
            current_target
            if current_target in discovery.available_aliases
            else discovery.candidate_for(preset, cloud)
        )
        targets[preset] = target
        if current_target is not None and current_target != target:
            warnings.append(
                f"{PRESET_KEYS[preset]} target changed: {current_target} -> {target}"
            )
    return targets, warnings


def check_default_available(
    aliases: Mapping[str, object],
    targets: dict[str, str],
    preset: str | None,
    available: set[str],
) -> None:
    """Raise when a pinned default names a model that no longer exists."""
    active = aliases.get(DEFAULT_KEY)
    if preset is not None or active is None:
        return
    if str(active) not in available:
        raise UnavailableDefaultError(str(active), targets)


def preset_for(aliases: Mapping[str, object], recovery: str | None) -> str | None:
    """The preset to activate: an explicit recovery choice, or the current one."""
    preset = recovery or selected_preset(aliases)
    if preset is not None:
        return preset
    # An older config with only `default` set is implicitly tracking cloud.
    if aliases.get(CLOUD_KEY) is None and aliases.get(DEFAULT_KEY) is not None:
        return "cloud"
    return None
