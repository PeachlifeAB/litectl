"""Run LiteLLM directly or supervise it with event-driven reload."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import signal
import sys
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Self

import uvicorn
from ruamel.yaml.error import YAMLError
from watchfiles import Change, awatch

from litectl.modules.catalog.index import (
    build_config_schema,
    read_environment_variables,
    validate_config_text,
    validate_yaml_text,
)

DEFAULT_PORT = 4000
DEFAULT_SHUTDOWN_GRACE_SECONDS = 10.0
DEFAULT_DEBOUNCE_MILLISECONDS = 500
HOST = "127.0.0.1"
CONFIG_FILE_NAME = "config.yaml"

SignalGroup = Callable[[int, signal.Signals], None]


def is_relevant_config_path(path: Path) -> bool:
    return path == Path(CONFIG_FILE_NAME) or (
        len(path.parts) >= 2 and path.parts[0] == "providers" and path.suffix == ".yaml"
    )


def relevant_change_filter(config_dir: Path) -> Callable[[Change, str], bool]:
    return lambda _change, path: is_relevant_config_path(
        Path(path).relative_to(config_dir)
    )


@lru_cache(maxsize=1)
def _config_schema() -> str:
    return build_config_schema()


def _configuration_paths(config_dir: Path) -> tuple[Path, ...]:
    config_path = config_dir / CONFIG_FILE_NAME
    providers = tuple(sorted((config_dir / "providers").rglob("*.yaml")))
    return (config_path, *providers)


def validated_fingerprint(config_dir: Path) -> str | None:
    paths = _configuration_paths(config_dir)
    if not paths[0].exists():
        return None
    digest = hashlib.sha256()
    try:
        for path in paths:
            content = path.read_text(encoding="utf-8")
            validate_yaml_text(content)
            if path == paths[0]:
                validate_config_text(content, _config_schema())
            digest.update(path.relative_to(config_dir).as_posix().encode())
            digest.update(content.encode())
    except (OSError, TypeError, ValueError, YAMLError):
        return None
    return digest.hexdigest()


def requires_reload(loaded_fingerprint: str, candidate_fingerprint: str) -> bool:
    return loaded_fingerprint != candidate_fingerprint


def _proxy_environment(config_dir: Path) -> dict[str, str]:
    """Child env: config-declared variables first, live env wins on conflict.

    LiteLLM resolves `os.environ/` references in model_list before it applies
    the config's own `environment_variables` section, so keys declared there
    must already exist in the child process environment.
    """
    config_path = str(config_dir / CONFIG_FILE_NAME)
    return {
        **read_environment_variables(config_dir / CONFIG_FILE_NAME),
        **os.environ,
        "CONFIG_FILE_PATH": config_path,
        "WORKER_CONFIG": config_path,
    }


async def start_child(config_dir: Path, port: int) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "litellm.proxy.proxy_server:app",
        "--host",
        HOST,
        "--port",
        str(port),
        "--log-level",
        "info",
        env=_proxy_environment(config_dir),
        start_new_session=True,
    )


def signal_process_group(pid: int, sent: signal.Signals) -> None:
    os.killpg(pid, sent)


async def terminate_child(
    process: asyncio.subprocess.Process,
    grace_period_seconds: float,
    signal_group: SignalGroup = signal_process_group,
) -> None:
    if process.returncode is not None:
        return
    try:
        signal_group(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        await process.wait()
        return

    wait_task = asyncio.create_task(process.wait())
    try:
        await asyncio.wait_for(asyncio.shield(wait_task), timeout=grace_period_seconds)
    except TimeoutError:
        try:
            signal_group(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await wait_task


@dataclass
class ChildState:
    config_dir: Path
    port: int
    grace_period_seconds: float
    fingerprint: str
    process: asyncio.subprocess.Process
    wait_task: asyncio.Task[int]

    @classmethod
    async def start(
        cls,
        config_dir: Path,
        port: int,
        grace_period_seconds: float,
        fingerprint: str,
    ) -> Self:
        process = await start_child(config_dir, port)
        return cls(
            config_dir,
            port,
            grace_period_seconds,
            fingerprint,
            process,
            asyncio.create_task(process.wait()),
        )

    async def replace(self, fingerprint: str) -> None:
        self.wait_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.wait_task
        await terminate_child(self.process, self.grace_period_seconds)
        self.process = await start_child(self.config_dir, self.port)
        self.fingerprint = fingerprint
        self.wait_task = asyncio.create_task(self.process.wait())

    async def close(self) -> None:
        self.wait_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.wait_task
        await terminate_child(self.process, self.grace_period_seconds)


def _watch_changes(
    config_dir: Path, debounce_milliseconds: int
) -> AsyncGenerator[set[tuple[Change, str]], None]:
    return awatch(
        config_dir,
        watch_filter=relevant_change_filter(config_dir),
        debounce=debounce_milliseconds,
        step=max(1, min(50, debounce_milliseconds // 10)),
    )


def _next_changes(
    changes: AsyncGenerator[set[tuple[Change, str]], None],
) -> asyncio.Future[set[tuple[Change, str]]]:
    return asyncio.ensure_future(anext(changes))


async def _reload_if_needed(config_dir: Path, child: ChildState) -> None:
    candidate = validated_fingerprint(config_dir)
    if candidate is None:
        print("Configuration reload skipped: validation failed.", file=sys.stderr)
    elif requires_reload(child.fingerprint, candidate):
        await child.replace(candidate)


def _install_stop_handlers(stop_event: asyncio.Event) -> None:
    if sys.platform == "win32":
        return
    loop = asyncio.get_running_loop()
    for handled_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(handled_signal, stop_event.set)


async def supervise(
    config_dir: Path,
    port: int,
    grace_period_seconds: float,
    debounce_milliseconds: int,
) -> int:
    fingerprint = validated_fingerprint(config_dir)
    if fingerprint is None:
        print("Configuration is invalid; LiteLLM was not started.", file=sys.stderr)
        return 2

    stop_event = asyncio.Event()
    _install_stop_handlers(stop_event)
    child = await ChildState.start(config_dir, port, grace_period_seconds, fingerprint)
    changes = _watch_changes(config_dir, debounce_milliseconds)
    change_task = _next_changes(changes)
    stop_task = asyncio.create_task(stop_event.wait())

    try:
        while True:
            done, _pending = await asyncio.wait(
                (change_task, child.wait_task, stop_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                return 0
            if child.wait_task in done:
                return child.wait_task.result()
            await _reload_if_needed(config_dir, child)
            change_task = _next_changes(changes)
    finally:
        for task in (change_task, stop_task):
            task.cancel()
        await asyncio.gather(change_task, return_exceptions=True)
        try:
            await changes.aclose()
        finally:
            await child.close()


def run_proxy(config_dir: Path, port: int) -> int:
    os.environ.update(_proxy_environment(config_dir))
    uvicorn.run(
        "litellm.proxy.proxy_server:app",
        host=HOST,
        port=port,
        log_level="info",
    )
    return 0


def main(
    config_dir: Path,
    port: int | None = None,
    watch: bool = False,
    shutdown_grace_period_seconds: float = DEFAULT_SHUTDOWN_GRACE_SECONDS,
    debounce_milliseconds: int = DEFAULT_DEBOUNCE_MILLISECONDS,
) -> int:
    resolved_port = port or int(os.environ.get("LITELLM_PORT", DEFAULT_PORT))
    if watch:
        return asyncio.run(
            supervise(
                config_dir,
                resolved_port,
                shutdown_grace_period_seconds,
                debounce_milliseconds,
            )
        )
    return run_proxy(config_dir, resolved_port)
