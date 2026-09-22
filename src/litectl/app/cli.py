"""Command-line adapter for the packaged application."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from litectl.app import install as installer
from litectl.app import teardown
from litectl.app.paths import config_dir, state_dir
from litectl.modules.catalog.index import (
    PROVIDER_SPECS as CATALOG_PROVIDER_SPECS,
)
from litectl.modules.catalog.index import (
    list_models_main,
    reconcile_local_models,
)
from litectl.modules.catalog.index import (
    main as catalog_main,
)
from litectl.modules.workspace.index import (
    ServiceContext,
    read_settings,
    service_running,
    start_service,
    stop_service,
    stream_logs,
    unsupported_message,
)
from litectl.serve import main as serve

PROVIDERS = ("all", *CATALOG_PROVIDER_SPECS)
DEFAULT_SHUTDOWN_GRACE_SECONDS = 10.0
DEFAULT_DEBOUNCE_MILLISECONDS = 500


@dataclass(frozen=True)
class RuntimeContext:
    base_dir: Path
    state_dir: Path
    home_dir: Path
    service: ServiceContext


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="litectl")
    root.add_argument("--config-dir")
    commands = root.add_subparsers(dest="command", required=True)

    install_command = commands.add_parser("install")
    install_command.add_argument("target", nargs="?")
    for name in ("start", "stop", "status", "logs", "list"):
        commands.add_parser(name)

    update_command = commands.add_parser("update")
    update_command.add_argument("provider", nargs="?", choices=PROVIDERS, default="all")
    update_command.add_argument("-y", "--yes", action="store_true")

    serve_command = commands.add_parser("serve")
    serve_command.add_argument("--port", type=int)
    serve_command.add_argument("--watch", action="store_true")
    serve_command.add_argument(
        "--shutdown-grace-period-seconds",
        type=float,
        default=DEFAULT_SHUTDOWN_GRACE_SECONDS,
    )
    serve_command.add_argument(
        "--debounce-milliseconds",
        type=int,
        default=DEFAULT_DEBOUNCE_MILLISECONDS,
    )

    teardown_command = commands.add_parser("teardown")
    teardown_command.add_argument("-y", "--yes", action="store_true")
    return root


def _runtime(args: argparse.Namespace) -> RuntimeContext:
    home_dir = Path.home()
    base_dir = config_dir(args.config_dir, home_dir=home_dir)
    runtime_state_dir = state_dir(home_dir=home_dir)
    return RuntimeContext(
        base_dir=base_dir,
        state_dir=runtime_state_dir,
        home_dir=home_dir,
        service=installer.service_context(base_dir, runtime_state_dir, home_dir),
    )


def _install(args: argparse.Namespace, context: RuntimeContext) -> int:
    target = config_dir(args.target or args.config_dir, home_dir=context.home_dir)
    return installer.run(
        target, context.state_dir, context.home_dir, sys.stdin.isatty()
    )


def _list(_args: argparse.Namespace, context: RuntimeContext) -> int:
    list_models_main(context.base_dir)
    return 0


def _update(args: argparse.Namespace, context: RuntimeContext) -> int:
    installer.apply_environment(read_settings(context.base_dir, context.home_dir))
    update_args = [args.provider, *(["--yes"] if args.yes else [])]
    return catalog_main(context.base_dir, update_args)


def _serve(args: argparse.Namespace, context: RuntimeContext) -> int:
    return serve(
        context.base_dir,
        args.port,
        args.watch,
        args.shutdown_grace_period_seconds,
        args.debounce_milliseconds,
        reconcile=lambda: reconcile_local_models(context.base_dir),
    )


def _unsupported() -> int:
    print(unsupported_message(), file=sys.stderr)
    return 1


def _start(_args: argparse.Namespace, context: RuntimeContext) -> int:
    if not start_service(
        context.service,
        reconcile=lambda: reconcile_local_models(context.base_dir),
    ):
        return _unsupported()
    print("LiteLLM service started.")
    return 0


def _stop(_args: argparse.Namespace, context: RuntimeContext) -> int:
    if not stop_service(context.service):
        return _unsupported()
    print("LiteLLM service stopped.")
    return 0


def _status(_args: argparse.Namespace, context: RuntimeContext) -> int:
    if service_running(context.service):
        print("LiteLLM service is running.")
        return 0
    print("LiteLLM service is stopped.")
    return 1


def _logs(_args: argparse.Namespace, context: RuntimeContext) -> int:
    return stream_logs(context.service)


def _teardown(args: argparse.Namespace, context: RuntimeContext) -> int:
    teardown.main(context.service, args.yes)
    return 0


Handler = Callable[[argparse.Namespace, RuntimeContext], int]
HANDLERS: dict[str, Handler] = {
    "install": _install,
    "start": _start,
    "stop": _stop,
    "status": _status,
    "logs": _logs,
    "list": _list,
    "update": _update,
    "serve": _serve,
    "teardown": _teardown,
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(sys.argv[1:] if argv is None else argv)
    return HANDLERS[args.command](args, _runtime(args))
