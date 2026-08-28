"""Report what discovery found and ask before writing.

Inbound adapter: prints the per-provider diff, then confirms. Never blocks
without a terminal, so `--yes` or a pipe both behave predictably.
"""

from __future__ import annotations

import sys

from litectl.modules.catalog.domain.diff import ModelDiff, any_changed

AFFIRMATIVE = ("", "y", "yes")
ADDED_MARK = "+"
REMOVED_MARK = "-"


def print_report(diffs: list[ModelDiff]) -> None:
    """Show each provider's result, listing the models that moved."""
    for diff in diffs:
        print(f"  {diff.summary()}")
        for alias in diff.added:
            print(f"      {ADDED_MARK} {alias}")
        for alias in diff.removed:
            print(f"      {REMOVED_MARK} {alias}")


def confirm(assume_yes: bool = False) -> bool:
    """Ask whether to save. True without asking when ``assume_yes``."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Not a terminal; nothing written. Re-run with --yes to save.")
        return False
    try:
        return input("\nSave these models? [Y/n]: ").strip().lower() in AFFIRMATIVE
    except (KeyboardInterrupt, EOFError):
        print()
        return False


def review(diffs: list[ModelDiff], assume_yes: bool = False) -> bool:
    """Print the diff and decide whether to write. False means write nothing."""
    print("\nDiscovered models:")
    print_report(diffs)

    if not any_changed(diffs):
        print("\nNo changes.")
        return False
    return confirm(assume_yes)
