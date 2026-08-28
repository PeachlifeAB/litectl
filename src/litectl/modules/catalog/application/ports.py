"""Provider probe result consumed by catalog reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from litectl.modules.catalog.domain.models import ModelDescriptor


@dataclass(frozen=True)
class Reachable:
    api_base: str | None
    models: tuple[ModelDescriptor, ...]


@dataclass(frozen=True)
class Unreachable:
    reason: str


ProbeResult = Reachable | Unreachable
