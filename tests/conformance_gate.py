"""Validate litectl's declared artifacts against the schema the proxy enforces.

The harness `conform` runner classifies this repository from the SKILL.md files
in agent tooling (`.claude/`, `.agents/`, `.pi/`) and validates those, reporting
15 PASS rows without touching one litectl artifact -- a pass over an empty
subject, which policy rejects (`unexpected_empty_scope: fail`).

The artifacts litectl declares are the seven entries in `MANIFEST`: the packaged
config template and six provider model files. The schema is the one the product
derives from the installed LiteLLM package (`build_config_schema`), so this gate
checks what the running proxy will actually accept instead of a hand-written
copy that can drift from it.

Provider files validate against the same full schema as the config: they are
`model_list` fragments merged through `include`, and the schema accepts them
(verified against the packaged files; see
`.gdog/docs/litectl-declared-artifacts.txt`). Only the config template carries
`@@name@@` markers, matching `Settings.as_template_values()`.

Exits 0 when every artifact validates, 1 on a violation, 2 when the subject is
missing or the schema cannot be built -- an unmeasurable subject is blocked,
never a pass.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from importlib.resources import files

from ruamel.yaml.error import YAMLError

from litectl.modules.catalog.infrastructure.config_reader import (
    validate_config_text,
    validate_yaml_text,
)
from litectl.modules.catalog.infrastructure.schema import build_config_schema
from litectl.modules.workspace.domain.manifest import MANIFEST
from litectl.modules.workspace.domain.settings import Settings

RESOURCE_PACKAGE = "litectl.resources"
EXIT_VIOLATION = 1
EXIT_UNMEASURED = 2

# Structural placeholders only. The gate checks artifact shape and never reads
# credentials, an installed config, or the environment.
SAMPLE = Settings(
    master_key="sk-placeholder",
    port="4000",
    omlx_base="http://127.0.0.1:8000/v1",
    omlx_key="not-needed",
    cerebras_base="https://api.cerebras.ai/v1",
    cerebras_key="",
)


class Unmeasured(Exception):
    """The gate cannot reach a verdict."""


def interpolate(text: str, values: dict[str, str]) -> str:
    """Fill the `@@name@@` markers the installer substitutes."""
    for name, value in values.items():
        text = text.replace(f"@@{name}@@", value)
    return text


def declared_artifacts() -> Iterator[tuple[str, str, bool]]:
    """Each manifest entry as (source, text, interpolate), from the package."""
    root = files(RESOURCE_PACKAGE)
    for entry in MANIFEST:
        resource = root.joinpath(entry.source)
        if not resource.is_file():
            raise Unmeasured(f"declared artifact missing from package: {entry.source}")
        yield entry.source, resource.read_text(encoding="utf-8"), entry.interpolate


def check_artifact(text: str, needs_values: bool, schema_json: str) -> None:
    """Validate one artifact, filling template markers first when declared."""
    content = interpolate(text, SAMPLE.as_template_values()) if needs_values else text
    validate_yaml_text(content)
    validate_config_text(content, schema_json)


def main(argv: list[str] | None = None) -> int:
    _ = argv
    try:
        schema_json = build_config_schema()
        artifacts = list(declared_artifacts())
    except Unmeasured as error:
        print(f"BLOCKED  {error}", file=sys.stderr)
        return EXIT_UNMEASURED
    except ImportError as error:
        print(f"BLOCKED  cannot build config schema: {error}", file=sys.stderr)
        return EXIT_UNMEASURED

    if not artifacts:
        print("BLOCKED  manifest declares no artifacts", file=sys.stderr)
        return EXIT_UNMEASURED

    failures = 0
    for source, text, needs_values in artifacts:
        try:
            check_artifact(text, needs_values, schema_json)
        except (TypeError, ValueError, YAMLError) as error:
            failures += 1
            print(f"FAIL  {source}: {error}")
        else:
            print(f"PASS  {source}")

    print(f"\n{len(artifacts) - failures}/{len(artifacts)} declared artifacts valid")
    return EXIT_VIOLATION if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
