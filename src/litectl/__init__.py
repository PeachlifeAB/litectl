"""Bootstrap LiteLLM command-line package."""

__all__ = ["main"]


def main() -> int:
    """Load global composition only when the console entry point runs."""
    from litectl.app.cli import main as app_main

    return app_main()
