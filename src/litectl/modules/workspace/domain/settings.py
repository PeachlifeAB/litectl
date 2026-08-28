"""Workspace settings and the template values they produce."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PORT = "4000"
PLACEHOLDER_KEY = "not-needed"


@dataclass(frozen=True)
class Settings:
    """Everything the template needs substituted, resolved once at the edge."""

    master_key: str
    port: str = DEFAULT_PORT
    omlx_base: str = ""
    omlx_key: str = PLACEHOLDER_KEY
    cerebras_base: str = ""
    cerebras_key: str = ""

    def with_omlx_key(self, key: str) -> Settings:
        """Copy with a different oMLX key."""
        return Settings(
            master_key=self.master_key,
            port=self.port,
            omlx_base=self.omlx_base,
            omlx_key=key,
            cerebras_base=self.cerebras_base,
            cerebras_key=self.cerebras_key,
        )

    def with_cerebras_key(self, key: str) -> Settings:
        """Copy with a different Cerebras key."""
        return Settings(
            master_key=self.master_key,
            port=self.port,
            omlx_base=self.omlx_base,
            omlx_key=self.omlx_key,
            cerebras_base=self.cerebras_base,
            cerebras_key=key,
        )

    def as_environment(self) -> dict[str, str]:
        """Return the strict environment shape consumed by LiteLLM and catalog."""
        return {
            "LITELLM_MASTER_KEY": self.master_key,
            "LITELLM_PORT": self.port,
            "OMLX_API_BASE": self.omlx_base,
            "OMLX_API_KEY": self.omlx_key,
            "CEREBRAS_API_BASE": self.cerebras_base,
            "CEREBRAS_API_KEY": self.cerebras_key,
        }

    def as_template_values(self) -> dict[str, str]:
        """Render values used by the initial config resource."""
        return {
            "master_key": self.master_key,
            "port": self.port,
            "omlx_base": self.omlx_base,
            "omlx_key": self.omlx_key,
            "cerebras_base": self.cerebras_base,
            "cerebras_key": self.cerebras_key,
        }
