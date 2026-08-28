"""Compare discovered models against what a provider file already records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDiff:
    """What changed for one provider since its models.yaml was written."""

    provider: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    unavailable_reason: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    @property
    def available(self) -> bool:
        return not self.unavailable_reason

    def summary(self) -> str:
        """One line describing this provider's result."""
        if not self.available:
            return (
                f"{self.provider}: {self.unavailable_reason} (keeping recorded models)"
            )
        if not self.changed:
            return f"{self.provider}: no changes ({len(self.unchanged)} models)"
        parts = []
        if self.added:
            parts.append(f"+{len(self.added)}")
        if self.removed:
            parts.append(f"-{len(self.removed)}")
        return f"{self.provider}: {' '.join(parts)}"


def diff_models(provider: str, discovered: list[str], recorded: list[str]) -> ModelDiff:
    """Compare two alias lists, preserving discovery order in ``added``."""
    recorded_set = set(recorded)
    discovered_set = set(discovered)
    return ModelDiff(
        provider=provider,
        added=tuple(a for a in discovered if a not in recorded_set),
        removed=tuple(a for a in recorded if a not in discovered_set),
        unchanged=tuple(a for a in discovered if a in recorded_set),
    )


def unavailable(provider: str, reason: str, recorded: list[str]) -> ModelDiff:
    """A provider that could not be asked keeps whatever it already recorded."""
    return ModelDiff(
        provider=provider, unchanged=tuple(recorded), unavailable_reason=reason
    )


def any_changed(diffs: list[ModelDiff]) -> bool:
    return any(diff.changed for diff in diffs)
