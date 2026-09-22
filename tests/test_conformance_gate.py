from __future__ import annotations

import pytest
from conformance_gate import (
    SAMPLE,
    check_artifact,
    declared_artifacts,
    interpolate,
    main,
)

from litectl.modules.catalog.infrastructure.schema import build_config_schema
from litectl.modules.workspace.domain.manifest import MANIFEST


@pytest.fixture(scope="module")
def schema_json() -> str:
    return build_config_schema()


def test_every_manifest_entry_is_reachable_in_the_package() -> None:
    sources = [source for source, _text, _fill in declared_artifacts()]
    yaml_entries = [e.source for e in MANIFEST if not e.source.endswith(".py")]

    assert sources == yaml_entries
    assert sources, "manifest must declare at least one artifact"


def test_shipped_artifacts_all_validate() -> None:
    assert main([]) == 0


def test_unknown_top_level_key_is_rejected(schema_json: str) -> None:
    fragment = (
        "model_list:\n  - model_name: a\n    litellm_params:\n"
        "      model: openai/a\nbogus: true\n"
    )

    with pytest.raises(ValueError, match="Additional properties"):
        check_artifact(fragment, False, schema_json)


def test_malformed_yaml_is_rejected(schema_json: str) -> None:
    with pytest.raises(Exception, match="flow sequence"):
        check_artifact("model_list: [unclosed\n", False, schema_json)


def test_non_mapping_document_is_rejected(schema_json: str) -> None:
    with pytest.raises(TypeError, match="top-level mapping"):
        check_artifact("- just\n- a\n- list\n", False, schema_json)


def test_interpolate_fills_every_declared_placeholder() -> None:
    values = SAMPLE.as_template_values()
    template = " ".join(f"@@{name}@@" for name in values)

    filled = interpolate(template, values)

    assert "@@" not in filled


def test_config_template_markers_match_settings_keys() -> None:
    """A renamed Settings field must not silently leave @@markers@@ unfilled."""
    source, text, needs_values = next(
        item for item in declared_artifacts() if item[0] == "config.yaml"
    )

    assert needs_values, f"{source} must be declared as interpolated"
    assert "@@" not in interpolate(text, SAMPLE.as_template_values())
