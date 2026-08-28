"""Interactive prompts for install.

Inbound adapter: the only module that reads stdin. Every prompt returns "" when
input is unavailable, so a non-interactive install proceeds with defaults.
"""

from __future__ import annotations


def ask(question: str) -> str:
    """Ask for one line of input, returning "" if the user declines or cannot.

    input() raises EOFError when stdin is piped or closed; that is a decline,
    not an error, so installs stay non-interactive-safe.
    """
    try:
        return input(question).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return ""


def ask_omlx_key(port: int) -> str:
    """Ask for a key after a local server answered with an auth challenge."""
    print(f"\n[Notice] Local inference server on port {port} requires authentication.")
    return ask(f"Enter OMLX_API_KEY for port {port} (or press Enter to skip): ")


def ask_cerebras_key() -> str:
    """Ask for a cloud key when no local server was found."""
    print("\n[Notice] No local inference server detected.")
    return ask("Enter CEREBRAS_API_KEY (or press Enter to skip): ")
