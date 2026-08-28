"""Read and validate LiteLLM config and provider files.

Query side of the config adapter: never mutates a document.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from litectl.modules.catalog.domain.seed import SEED_CONFIG

WILDCARD = "*"


def round_trip_yaml() -> YAML:
    """A YAML instance configured to preserve the document as written."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.explicit_start = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def read_provider_aliases(path: Path) -> list[str]:
    """Concrete model group names declared by a provider file."""
    if not path.exists():
        return []
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    return [
        str(entry["model_name"])
        for entry in data.get("model_list", [])
        if isinstance(entry, Mapping)
        and entry.get("model_name")
        and WILDCARD not in str(entry["model_name"])
    ]


def read_config_model_groups(path: Path) -> set[str]:
    """Every model group the config registers, including via `include`."""
    if not path.exists():
        return set()
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    groups = set(read_provider_aliases(path))
    for included in data.get("include", []):
        groups.update(read_provider_aliases(path.parent / str(included)))
    return groups


def read_environment_variables(path: Path) -> dict[str, str]:
    """The config's `environment_variables` block as a string map."""
    if not path.exists():
        return {}
    data = (
        YAML(typ="safe").load(path.read_text(encoding="utf-8"))  # pragma: no mutate
        or {}
    )
    variables = data.get("environment_variables")
    if not isinstance(variables, Mapping):
        return {}
    return {
        str(name): str(value) for name, value in variables.items() if value is not None
    }


def validate_yaml_text(content: str) -> None:
    if not isinstance(YAML(typ="safe").load(content), Mapping):
        raise TypeError("generated YAML must be a top-level mapping")


def validate_config_text(content: str, schema_json: str) -> None:
    config = YAML(typ="safe").load(content)
    errors = sorted(
        Draft202012Validator(json.loads(schema_json)).iter_errors(config),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise ValueError(f"config validation failed at {location}: {first.message}")


def load_config(path: Path) -> CommentedMap:
    """Load config.yaml, seeding it when absent.

    Teardown removes generated state and leaves config.yaml behind, but a
    workspace that never had one must still be usable, so a missing file is
    seeded rather than raised. This is the single read point, so every caller
    inherits the behaviour.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SEED_CONFIG, encoding="utf-8")
        print(f"seeded {path.name}")
    config = round_trip_yaml().load(path.read_text(encoding="utf-8"))
    if not isinstance(config, CommentedMap):
        raise TypeError("config.yaml must be a top-level YAML mapping")
    return config
