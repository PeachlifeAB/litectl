"""Interactive terminal prompts.

Inbound adapter: the only place that reads stdin. Callers receive a plain
choice and never touch the terminal themselves.
"""

from __future__ import annotations

import sys

from litectl.modules.catalog.domain.aliases import PRESETS as RECOVERY_PRESETS
from litectl.modules.catalog.domain.aliases import UnavailableDefaultError

ABORT_CHOICE = str(len(RECOVERY_PRESETS) + 1)
DEFAULT_CHOICE = "1"
RECOMMENDED_PRESET = "cloud"


def prompt_for_recovery(error: UnavailableDefaultError) -> str:
    """Ask which preset should replace an unavailable default.

    Raises SystemExit when there is no terminal to ask, or when the user
    chooses to abort.
    """
    if not sys.stdin.isatty():
        raise SystemExit(
            f"Active default is unavailable: {error.model}. "
            "Run `litectl update` interactively to choose a replacement."
        )

    print(f"Active default is unavailable: {error.model}\n")
    print("Choose replacement:")
    for index, preset in enumerate(RECOVERY_PRESETS, 1):
        recommendation = " (recommended)" if preset == RECOMMENDED_PRESET else ""
        print(f"  {index}. default_{preset:<7} {error.targets[preset]}{recommendation}")
    print(f"  {ABORT_CHOICE}. Abort update")

    valid = {str(index) for index in range(1, len(RECOVERY_PRESETS) + 1)}
    while True:
        choice = input(f"Selection [{DEFAULT_CHOICE}]: ").strip() or DEFAULT_CHOICE
        if choice in valid:
            return RECOVERY_PRESETS[int(choice) - 1]
        if choice == ABORT_CHOICE:
            raise SystemExit("Update aborted; working files unchanged.")
        print(f"Choose {', '.join(sorted(valid))}, or {ABORT_CHOICE}.")
