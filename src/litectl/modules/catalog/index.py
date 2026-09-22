"""Public surface of the catalog module for global composition.

Sole entry point: `litectl.app` and `serve.py` import from here, never from
`domain/`, `application/`, `api/`, or `infrastructure/` subpackages.
"""

from .cli import main, reconcile_local_models
from .infrastructure.config import PROVIDER_SPECS
from .infrastructure.config_reader import (
    read_environment_variables,
    validate_config_text,
    validate_yaml_text,
)
from .infrastructure.schema import build_config_schema
from .list_models import main as list_models_main

__all__ = [
    "PROVIDER_SPECS",
    "build_config_schema",
    "list_models_main",
    "main",
    "read_environment_variables",
    "reconcile_local_models",
    "validate_config_text",
    "validate_yaml_text",
]
