"""Install the minimal LiteLLM configuration from package resources."""

from __future__ import annotations

import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path

from litectl.app.paths import config_dir, state_dir
from litectl.modules.catalog.index import main as catalog_main
from litectl.modules.workspace.index import (
    ServiceContext,
    Settings,
    initialize,
    install,
    resolve,
    unsupported_message,
    verify,
)

RESOURCE_PACKAGE = "litectl.resources"


def cli_binary() -> str:
    return shutil.which("litectl") or str(Path(sys.argv[0]).resolve())


def apply_environment(settings: Settings) -> None:
    for name, value in settings.as_environment().items():
        os.environ.setdefault(name, value)


def service_context(
    base_dir: Path, runtime_state_dir: Path, home_dir: Path
) -> ServiceContext:
    return ServiceContext(
        config_dir=base_dir,
        state_dir=runtime_state_dir,
        home_dir=home_dir,
        uid=os.getuid(),
        cli_bin=cli_binary(),
        environment=os.environ,
    )


def run(
    base_dir: Path, runtime_state_dir: Path, home_dir: Path, interactive: bool = True
) -> int:
    print(f"Setting up LiteLLM in {base_dir} ...\n")
    runtime_state_dir.mkdir(parents=True, exist_ok=True)

    settings = resolve(base_dir, home_dir, interactive)
    apply_environment(settings)
    report = install(files(RESOURCE_PACKAGE), base_dir, settings.as_template_values())

    for path in report.written:
        print(f"  ✓ {path}")
    for path in report.preserved:
        print(f"  = {path} (kept)")

    print(f"\nCreated/Updated {report.total} files in {base_dir}.")
    catalog_main(base_dir, ["all", "--yes"])
    if initialize(service_context(base_dir, runtime_state_dir, home_dir)):
        verify(runtime_state_dir, settings.master_key, settings.port)
    else:
        print(unsupported_message())
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    home_dir = Path.home()
    return run(
        config_dir(args[0] if args else None, home_dir=home_dir),
        state_dir(home_dir=home_dir),
        home_dir,
        interactive=sys.stdin.isatty(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
