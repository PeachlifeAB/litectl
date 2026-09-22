"""Load and validate checked-in mutation dispositions.

The record has this shape::

    {"version": 1, "dispositions": [
        {"id": "<mutmut-name>", "category": "equivalent|suppressed",
         "reason": "<proof or cause>", "date": "YYYY-MM-DD"}
    ]}

Mutant names are the keys because task 1.1 verified their stability across
unchanged mutmut 3.8 runs.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from litectl.modules.workspace.infrastructure.process import (
    resolve_executable,
)
from litectl.modules.workspace.infrastructure.process import (
    run as run_command,
)

DEFAULT_DISPOSITIONS_PATH: Final = Path("tests/mutation-dispositions.json")
ALLOWED_CATEGORIES: Final = frozenset({"equivalent", "suppressed"})
RESULT_STATUSES: Final = frozenset(
    {
        "killed",
        "no tests",
        "segfault",
        "skipped",
        "suspicious",
        "survived",
        "timeout",
    }
)


@dataclass(frozen=True, slots=True)
class Disposition:
    mutant_id: str
    category: str
    reason: str
    date: str


def parse_results(output: str) -> dict[str, str]:
    """Parse mutmut result rows and reject unknown statuses."""
    results: dict[str, str] = {}
    for line in output.splitlines():
        if not line.startswith("    ") or ": " not in line:
            continue
        mutant_id, status = line.strip().rsplit(": ", 1)
        if status not in RESULT_STATUSES:
            raise ValueError(f"unknown mutmut status: {status}")
        if mutant_id in results:
            raise ValueError(f"duplicate mutmut result: {mutant_id}")
        results[mutant_id] = status
    if not results:
        raise ValueError("mutmut produced no result rows")
    return results


def run_mutmut_results() -> str:
    """Return the complete native mutmut result listing."""
    completed = run_command(
        resolve_executable("mutmut"),
        ["results", "--all", "true"],
    )
    if not completed.ok:
        raise RuntimeError(completed.stderr.strip() or "mutmut results failed")
    return completed.stdout


def main(
    argv: list[str] | None = None,
    result_runner: Callable[[], str] = run_mutmut_results,
) -> int:
    """Enforce zero actionable non-killed mutation results."""
    args = sys.argv[1:] if argv is None else argv
    record_path = Path(args[0]) if args else DEFAULT_DISPOSITIONS_PATH
    try:
        dispositions = load_dispositions(record_path)
        results = parse_results(result_runner())
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"BLOCKED mutation gate: {error}")
        return 2

    actionable = sorted(
        (mutant_id, status)
        for mutant_id, status in results.items()
        if status != "killed" and mutant_id not in dispositions
    )
    if actionable:
        print(f"FAIL mutation gate: {len(actionable)} actionable result(s).")
        for mutant_id, status in actionable:
            print(f"  {mutant_id}: {status}")
        return 1
    print(f"PASS mutation gate: {len(results)} result(s).")
    return 0


def load_dispositions(path: Path) -> dict[str, Disposition]:
    """Load and validate the versioned mutation disposition record."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid disposition record: {error}") from error

    if not isinstance(payload, dict):
        raise TypeError("disposition record must be an object")
    if payload.get("version") != 1:
        raise ValueError("disposition record must be version 1")

    entries = payload.get("dispositions")
    if not isinstance(entries, list):
        raise TypeError("dispositions must be a list")

    result: dict[str, Disposition] = {}
    for index, entry in enumerate(entries):
        disposition = _parse_disposition(entry, index)
        if disposition.mutant_id in result:
            raise ValueError(f"duplicate disposition id: {disposition.mutant_id}")
        result[disposition.mutant_id] = disposition
    return result


def _parse_disposition(entry: object, index: int) -> Disposition:
    if not isinstance(entry, dict):
        raise TypeError(f"disposition {index} must be an object")
    mutant_id = _required_text(entry, "id", index)
    category = _required_text(entry, "category", index)
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"disposition {index} has invalid category")
    reason = _required_text(entry, "reason", index)
    date = _required_text(entry, "date", index)
    return Disposition(mutant_id, category, reason, date)


def _required_text(entry: dict[object, object], field: str, index: int) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"disposition {index} requires non-empty {field}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
