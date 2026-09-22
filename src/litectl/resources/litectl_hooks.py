"""LiteLLM custom callback, installed next to config.yaml.

LiteLLM resolves custom callbacks as files beside the config; this shim
re-exports the tested handler from the installed litectl package.
"""

from litectl.litellm_hooks import handler  # noqa: F401 — re-export
