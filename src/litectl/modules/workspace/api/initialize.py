"""Install the native user service after workspace configuration exists."""

from __future__ import annotations

import sys

from litectl.modules.workspace.infrastructure.service import (
    ServiceContext,
    install_service,
)


def initialize(context: ServiceContext, platform: str = sys.platform) -> bool:
    return install_service(context, platform)
