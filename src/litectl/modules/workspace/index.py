"""Public surface of the workspace module for global composition.

Sole entry point: `litectl.app` imports from here, never from `domain/`,
`api/`, or `infrastructure/` subpackages.
"""

from litectl.modules.workspace.api.initialize import initialize
from litectl.modules.workspace.api.resolve import read_settings, resolve
from litectl.modules.workspace.api.verify import verify
from litectl.modules.workspace.domain.settings import Settings
from litectl.modules.workspace.infrastructure.filesystem import install
from litectl.modules.workspace.infrastructure.service import (
    ServiceContext,
    remove_service,
    service_running,
    start_service,
    stop_service,
    stream_logs,
    unsupported_message,
)

__all__ = [
    "ServiceContext",
    "Settings",
    "initialize",
    "install",
    "read_settings",
    "remove_service",
    "resolve",
    "service_running",
    "start_service",
    "stop_service",
    "stream_logs",
    "unsupported_message",
    "verify",
]
