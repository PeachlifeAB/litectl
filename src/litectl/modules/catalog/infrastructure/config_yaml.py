"""Apply discovery results to config.yaml, preserving anchors.

Command side of the config adapter. Anchors are set here because anchor
identity is what dumps as `*alias`; which model an alias names is decided in
litectl.modules.catalog.domain.aliases.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import cast

from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import PlainScalarString

from litectl.modules.catalog.domain.aliases import (
    DEFAULT_KEY,
    PRESET_ANCHORS,
    PRESET_KEYS,
    PRESETS,
    Discovery,
    check_default_available,
    preset_for,
    resolve_targets,
)
from litectl.modules.catalog.domain.models import reconcile_fallback_aliases
from litectl.modules.catalog.infrastructure.config_reader import (
    load_config,
    round_trip_yaml,
)

CALLBACK_NAME = "litectl_hooks.handler"
BROKEN_CALLBACK_NAME = "litectl.litellm_hooks.handler"


def _apply_callbacks(config: CommentedMap) -> None:
    """Own the hook entry: fix the broken name, keep every other callback."""
    settings = config.setdefault("litellm_settings", CommentedMap())
    if not isinstance(settings, CommentedMap):
        return
    callbacks = settings.get("callbacks")
    if not isinstance(callbacks, CommentedSeq):
        callbacks = (
            CommentedSeq(
                item for item in callbacks if str(item) != BROKEN_CALLBACK_NAME
            )
            if isinstance(callbacks, list)
            else CommentedSeq()
        )
        settings["callbacks"] = callbacks
    else:
        replaced = [
            CALLBACK_NAME if str(item) == BROKEN_CALLBACK_NAME else item
            for item in callbacks
        ]
        callbacks.clear()
        callbacks.extend(replaced)
    if CALLBACK_NAME not in [str(item) for item in callbacks]:
        callbacks.insert(0, CALLBACK_NAME)


@dataclass(frozen=True)
class ConfigUpdate:
    content: str
    warnings: tuple[str, ...]


def _anchored(value: str, anchor: str) -> PlainScalarString:
    scalar = cast(PlainScalarString, PlainScalarString(value))
    scalar.yaml_set_anchor(anchor, always_dump=True)
    return scalar


def _set_before_default(aliases: CommentedMap, key: str, value: object) -> None:
    if key in aliases:
        aliases[key] = value
        return
    keys = list(aliases)
    index = keys.index(DEFAULT_KEY) if DEFAULT_KEY in keys else len(keys)
    aliases.insert(index, key, value)


def _existing_chain(
    router: Mapping[str, object], cloud_targets: set[str]
) -> list[str] | None:
    fallbacks = router.get("fallbacks", [])
    if not isinstance(fallbacks, list):
        return None
    for item in fallbacks:
        if not isinstance(item, Mapping) or len(item) != 1:
            continue
        key, value = next(iter(item.items()))
        if str(key) in cloud_targets and isinstance(value, list):
            return [str(alias) for alias in value]
    return None


def _alias_map(config: CommentedMap) -> tuple[CommentedMap, CommentedMap]:
    router = config.setdefault("router_settings", CommentedMap())
    aliases = router.setdefault("model_group_alias", CommentedMap())
    if not isinstance(router, CommentedMap) or not isinstance(aliases, CommentedMap):
        raise TypeError("router_settings.model_group_alias must be a mapping")
    return router, aliases


def _apply_aliases(
    aliases: CommentedMap, targets: dict[str, str], preset: str | None
) -> dict[str, PlainScalarString]:
    """Write each preset as an anchored scalar, aliasing the active one."""
    values = {
        name: _anchored(target, PRESET_ANCHORS[name])
        for name, target in targets.items()
    }
    for name in PRESETS:
        _set_before_default(aliases, PRESET_KEYS[name], values[name])
    if preset is not None:
        # Assigning the same object makes ruamel emit `*anchor` on dump.
        aliases[DEFAULT_KEY] = values[preset]
    return values


def _apply_fallbacks(
    router: CommentedMap,
    discovery: Discovery,
    targets: dict[str, str],
    values: Mapping[str, PlainScalarString],
    active_before: object,
) -> list[str]:
    """Rebuild the fallback chain, reusing anchors for preset members."""
    previous = _existing_chain(
        router, {DEFAULT_KEY, targets["cloud"], str(active_before or "")}
    )
    chain, removed = reconcile_fallback_aliases(
        discovery.discovered_aliases(), previous, discovery.previous_discovered
    )
    anchored = CommentedSeq(
        values["speed"]
        if alias == targets["speed"]
        else values["quality"]
        if alias == targets["quality"]
        else alias
        for alias in chain
    )
    router["fallbacks"] = CommentedSeq([CommentedMap([(DEFAULT_KEY, anchored)])])
    return [f"unavailable fallback removed: {alias}" for alias in removed]


def update_config(
    path: Path, discovery: Discovery, recovery_preset: str | None = None
) -> ConfigUpdate:
    """Reconcile config.yaml with what discovery found."""
    config = load_config(path)
    router, aliases = _alias_map(config)
    active_before = aliases.get(DEFAULT_KEY)

    targets, warnings = resolve_targets(aliases, discovery)
    preset = preset_for(aliases, recovery_preset)
    check_default_available(aliases, targets, preset, discovery.available_aliases)

    _apply_callbacks(config)
    values = _apply_aliases(aliases, targets, preset)
    warnings.extend(_apply_fallbacks(router, discovery, targets, values, active_before))
    config.setdefault("model_list", CommentedSeq())

    stream = StringIO()
    round_trip_yaml().dump(config, stream)
    return ConfigUpdate(stream.getvalue(), tuple(warnings))
