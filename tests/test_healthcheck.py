from litectl.modules.workspace.infrastructure.healthcheck import choose_model


def test_healthcheck_prefers_local_llama_over_cloud_default() -> None:
    models = ("default", "omlx-other", "omlx-llama-3.2-3b-instruct-4bit")

    assert choose_model(models) == "omlx-llama-3.2-3b-instruct-4bit"


def test_healthcheck_never_selects_cloud_only_model() -> None:
    assert choose_model(("default", "default_cloud")) is None
