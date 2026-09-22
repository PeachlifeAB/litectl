"""Remove managed service and runtime state while preserving configuration."""

from __future__ import annotations

import shutil

from litectl.modules.workspace.index import ServiceContext, remove_service


def main(context: ServiceContext, assume_yes: bool = False) -> None:
    if not assume_yes:
        reply = input("Remove the LiteLLM service and runtime state? [y/N]: ")
        if reply.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return

    remove_service(context)
    shutil.rmtree(context.state_dir, ignore_errors=True)
    print("Removed the service and runtime state; configuration was kept.")
